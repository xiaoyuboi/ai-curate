import logging
import json
from typing import List, Dict, Any, Optional
from sqlalchemy.orm import Session
import anthropic

from backend.config import MINIMAX_API_KEY, MINIMAX_MODEL
from backend.database import Tweet, Article, ContentItem, PushHistory
from backend import feishu

logger = logging.getLogger(__name__)


def analyze_with_minimax(content_items: List[Dict]) -> List[Dict]:
    """
    使用MiniMax Coding Plan API分析内容，判断是否值得推送
    使用Anthropic SDK兼容接口
    """
    if not MINIMAX_API_KEY:
        logger.warning("MiniMax API key not configured, skipping AI filter")
        return content_items

    if not content_items:
        return []

    # 构建提示词
    prompt = build_filter_prompt(content_items)

    try:
        # 使用Anthropic SDK（Coding Plan兼容）
        client = anthropic.Anthropic(
            api_key=MINIMAX_API_KEY,
            base_url="https://api.minimaxi.com/anthropic"
        )

        message = client.messages.create(
            model=MINIMAX_MODEL,
            max_tokens=4000,
            system="你是一个AI资讯筛选助手，负责从大量内容中筛选出最有价值、最值得关注的AI相关新闻和资讯。请根据内容的相关性、时效性、重要性进行筛选。只返回JSON数组。",
            messages=[
                {
                    "role": "user",
                    "content": prompt
                }
            ]
        )

        # 解析响应 - 需要处理可能包含的thinking block
        result = ""
        for block in message.content:
            # 跳过思考块，获取实际的文本内容
            if hasattr(block, 'thinking'):
                continue
            # 处理文本块
            if hasattr(block, 'text') and block.text:
                result = block.text
                break

        if not result:
            logger.error("No text content in API response")
            return content_items

        filtered = parse_minimax_response(result)

        logger.info(f"AI filtered {len(content_items)} items to {len(filtered)} items")
        return filtered

    except Exception as e:
        logger.error(f"MiniMax API error: {e}")
        # 如果API失败，返回原始内容
        return content_items


def build_filter_prompt(content_items: List[Dict]) -> str:
    """构建筛选提示词"""
    items_text = []
    for i, item in enumerate(content_items, 1):
        title = item.get("title", "")
        content = item.get("content", "")[:300]
        url = item.get("url", "")
        source = item.get("source", "unknown")

        items_text.append(f"""
{i}. 来源: {source}
   标题: {title}
   内容: {content}
   链接: {url}
""")

    prompt = f"""请分析以下AI相关资讯，筛选出最值得推送的内容（最多10条）。

筛选标准：
1. 内容必须与AI相关（人工智能、机器学习、大模型等）
2. 内容要有价值（新闻、重大更新、技术突破等）
3. 避免重复或相似内容

以下是待筛选的内容：
{''.join(items_text)}

请以JSON数组格式返回筛选结果，格式如下：
[
  {{"title": "标题", "content": "摘要", "url": "链接", "source": "来源", "reason": "筛选理由"}}
]

只返回JSON数组，不要其他内容。"""

    return prompt


def parse_minimax_response(response: str) -> List[Dict]:
    """解析MiniMax响应"""
    try:
        start = response.find("[")
        end = response.rfind("]") + 1

        if start != -1 and end != 0:
            json_str = response[start:end]
            items = json.loads(json_str)
            return items
    except json.JSONDecodeError as e:
        logger.error(f"Parse MiniMax response error: {e}")

    return []


# 每次推送的配置
MAX_CONTENT_PER_PUSH = 50  # 每批最多处理的内容数
TARGET_ITEM_COUNT = 10      # 目标筛选出多少条优质内容
MAX_BATCHES = 3             # 最多筛选多少批


def filter_and_push(db: Session, webhook_url: str, push_type: str = "manual") -> bool:
    """执行AI筛选并推送 - 循环筛选直到找到足够数量的优质内容"""

    all_filtered_items = []  # 收集所有筛选出的优质内容
    processed_tweet_ids = []  # 记录已处理的推文ID
    processed_article_ids = []  # 记录已处理的文章ID
    batch_count = 0

    while batch_count < MAX_BATCHES and len(all_filtered_items) < TARGET_ITEM_COUNT:
        batch_count += 1

        # 获取未推送的内容（排除已处理的）
        query_tweets = db.query(Tweet).filter(Tweet.is_pushed == False)
        if processed_tweet_ids:
            query_tweets = query_tweets.filter(~Tweet.id.in_(processed_tweet_ids))

        query_articles = db.query(Article).filter(Article.is_pushed == False)
        if processed_article_ids:
            query_articles = query_articles.filter(~Article.id.in_(processed_article_ids))

        unpushed_tweets = query_tweets.limit(MAX_CONTENT_PER_PUSH).all()
        unpushed_articles = query_articles.limit(10).all()

        # 记录本次处理的ID
        processed_tweet_ids.extend([t.id for t in unpushed_tweets])
        processed_article_ids.extend([a.id for a in unpushed_articles])

        content_items = []

        for tweet in unpushed_tweets:
            content_items.append({
                "title": tweet.content[:50],
                "content": tweet.content,
                "url": tweet.url,
                "source": "twitter"
            })

        for article in unpushed_articles:
            content_items.append({
                "title": article.title,
                "content": article.content or article.title,
                "url": article.url,
                "source": "website"
            })

        if not content_items:
            logger.info("No more content to process")
            break

        # AI筛选
        if MINIMAX_API_KEY:
            filtered_items = analyze_with_minimax(content_items)
        else:
            filtered_items = content_items[:10]

        if filtered_items:
            all_filtered_items.extend(filtered_items)
            logger.info(f"Batch {batch_count}: found {len(filtered_items)} items, total: {len(all_filtered_items)}")
        else:
            logger.info(f"Batch {batch_count}: no items passed filter")

    if not all_filtered_items:
        logger.info("No content passed AI filter after all batches")
        # 将已处理的内容标记为已推送，避免重复处理
        for tweet_id in processed_tweet_ids:
            db.query(Tweet).filter(Tweet.id == tweet_id).update({"is_pushed": True})
        for article_id in processed_article_ids:
            db.query(Article).filter(Article.id == article_id).update({"is_pushed": True})
        db.commit()
        return True

    # 只取目标数量的优质内容
    push_items = []
    for item in all_filtered_items[:TARGET_ITEM_COUNT]:
        push_items.append({
            "title": item.get("title", "")[:50],
            "summary": item.get("content", "")[:150],
            "url": item.get("url", "")
        })

    success = feishu.send_feishu_message(
        webhook_url=webhook_url,
        content="AI资讯每日推送",
        items=push_items
    )

    push_history = PushHistory(
        content=f"推送{len(push_items)}条内容",
        push_type=push_type,
        item_count=len(push_items),
        status="success" if success else "failed"
    )
    db.add(push_history)

    if success:
        # 将所有已处理的内容标记为已推送
        for tweet_id in processed_tweet_ids:
            db.query(Tweet).filter(Tweet.id == tweet_id).update({"is_pushed": True})
        for article_id in processed_article_ids:
            db.query(Article).filter(Article.id == article_id).update({"is_pushed": True})

    db.commit()
    return success


def get_filtered_content_summary(content_items: List[Dict]) -> str:
    """生成内容摘要"""
    if not content_items:
        return "暂无新内容"

    summary_parts = []
    for item in content_items[:5]:
        title = item.get("title", "")[:30]
        summary_parts.append(f"- {title}")

    return "\n".join(summary_parts)
