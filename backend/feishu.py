import requests
from typing import List, Dict, Any
import logging

logger = logging.getLogger(__name__)


def send_feishu_message(webhook_url: str, content: str, items: List[Dict[str, Any]] = None,
                       hot_topics: Dict[str, List[Dict]] = None, normal_items: List[Dict] = None) -> bool:
    """
    发送飞书消息 - 支持两层推送：热点主题 + 普通资讯

    Args:
        webhook_url: 飞书机器人webhook地址
        content: 消息标题/摘要
        items: 内容项列表，每项包含 title, url, summary, topic
        hot_topics: 热点主题字典 {topic: [items]}
        normal_items: 普通资讯列表

    Returns:
        是否发送成功
    """
    if not webhook_url:
        logger.warning("Feishu webhook URL not configured")
        return False

    if not items:
        # 发送空消息
        message = {
            "msg_type": "interactive",
            "card": {
                "config": {"wide_screen_mode": True},
                "elements": [{
                    "tag": "div",
                    "text": {
                        "tag": "lark_md",
                        "content": "**暂无新内容**"
                    }
                }]
            }
        }
    else:
        # 构建消息结构
        message = {
            "msg_type": "interactive",
            "card": {
                "config": {
                    "wide_screen_mode": True
                },
                "elements": []
            }
        }

        # 标题
        message["card"]["elements"].append({
            "tag": "div",
            "text": {
                "tag": "lark_md",
                "content": f"**{content}**\n共 {len(items)} 条内容"
            }
        })
        message["card"]["elements"].append({"tag": "div", "text": {"tag": "lark_md", "content": "---"}})

        # 热点主题（优先展示）
        if hot_topics:
            message["card"]["elements"].append({
                "tag": "div",
                "text": {
                    "tag": "lark_md",
                    "content": "**📌 热点聚焦**"
                }
            })
            for topic, topic_items in hot_topics.items():
                topic_title = f"🔹 {topic} ({len(topic_items)}条)"
                message["card"]["elements"].append({
                    "tag": "div",
                    "text": {
                        "tag": "lark_md",
                        "content": topic_title
                    }
                })
                for item in topic_items:
                    title = item.get("title", "无标题")[:50]
                    summary = item.get("summary", "")[:150]
                    url = item.get("url", "")
                    item_content = f"  • {title}\n    {summary}"
                    if url:
                        item_content += f" [原文]({url})"
                    message["card"]["elements"].append({
                        "tag": "div",
                        "text": {
                            "tag": "lark_md",
                            "content": item_content
                        }
                    })

        # 普通资讯
        if normal_items:
            if hot_topics:
                message["card"]["elements"].append({
                    "tag": "div",
                    "text": {"tag": "lark_md", "content": "---"}
                })
                message["card"]["elements"].append({
                    "tag": "div",
                    "text": {
                        "tag": "lark_md",
                        "content": "**📰 其他重要资讯**"
                    }
                })
            else:
                message["card"]["elements"].append({
                    "tag": "div",
                    "text": {
                        "tag": "lark_md",
                        "content": "**📰 资讯速递**"
                    }
                })

            for item in normal_items:
                title = item.get("title", "无标题")[:50]
                summary = item.get("summary", "")[:150]
                url = item.get("url", "")
                topic = item.get("topic", "")

                topic_tag = f"[{topic}] " if topic else ""
                item_content = f"**{topic_tag}{title}**\n{summary}"
                if url:
                    item_content += f"\n[查看原文]({url})"

                message["card"]["elements"].append({
                    "tag": "div",
                    "text": {
                        "tag": "lark_md",
                        "content": item_content
                    }
                })

    try:
        response = requests.post(webhook_url, json=message, timeout=30)
        if response.status_code == 200:
            result = response.json()
            if result.get("code") == 0:
                logger.info(f"Feishu message sent successfully: {len(items)} items")
                return True
            else:
                logger.error(f"Feishu API error: {result}")
                return False
        else:
            logger.error(f"Feishu request failed: {response.status_code}")
            return False
    except Exception as e:
        logger.error(f"Feishu push error: {e}")
        return False


def send_simple_text(webhook_url: str, text: str) -> bool:
    """发送简单文本消息"""
    if not webhook_url:
        return False

    message = {
        "msg_type": "text",
        "content": {
            "text": text
        }
    }

    try:
        response = requests.post(webhook_url, json=message, timeout=30)
        return response.status_code == 200
    except Exception as e:
        logger.error(f"Feishu text push error: {e}")
        return False
