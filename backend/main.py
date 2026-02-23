import logging
from contextlib import asynccontextmanager
from typing import List, Optional
from fastapi import FastAPI, Depends, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session
from sqlalchemy import func

from backend.database import (
    init_db, get_db, TwitterAccount, Website, PushConfig, PushHistory,
    Tweet, Article, ContentItem
)
from backend.fetcher import twitter as twitter_fetcher
from backend.fetcher import website as website_fetcher
from backend.filter import ai_filter
from backend.scheduler import tasks
from backend import feishu

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    # 启动时初始化
    init_db()
    tasks.init_scheduler()
    yield
    # 关闭时停止
    tasks.scheduler.stop()


app = FastAPI(title="AI资讯推送系统", lifespan=lifespan)

# 挂载静态文件
import os
frontend_path = os.path.join(os.path.dirname(__file__), "..", "frontend")
if os.path.exists(frontend_path):
    app.mount("/static", StaticFiles(directory=frontend_path), name="static")


# ==================== 数据模型 ====================

class TwitterAccountCreate(BaseModel):
    username: str
    name: Optional[str] = None


class TwitterAccountResponse(BaseModel):
    id: int
    username: str
    name: Optional[str]
    enabled: bool

    class Config:
        from_attributes = True


class WebsiteCreate(BaseModel):
    name: str
    url: str
    selector: Optional[str] = None


class WebsiteResponse(BaseModel):
    id: int
    name: str
    url: str
    selector: Optional[str]
    enabled: bool

    class Config:
        from_attributes = True


class PushConfigUpdate(BaseModel):
    schedule_time: Optional[str] = None
    schedule_frequency: Optional[str] = None
    schedule_enabled: Optional[bool] = None
    feishu_webhook: Optional[str] = None


class PushConfigResponse(BaseModel):
    schedule_time: str
    schedule_frequency: str
    schedule_enabled: bool
    feishu_webhook: Optional[str]

    class Config:
        from_attributes = True


class PushHistoryResponse(BaseModel):
    id: int
    content: str
    push_type: str
    item_count: int
    pushed_at: str
    status: str

    class Config:
        from_attributes = True


class StatsResponse(BaseModel):
    twitter_accounts: int
    websites: int
    unpushed_tweets: int
    unpushed_articles: int
    total_pushed: int


# ==================== 前端路由 ====================

@app.get("/", response_class=HTMLResponse)
async def root():
    """返回管理页面"""
    index_path = os.path.join(os.path.dirname(__file__), "..", "frontend", "index.html")
    if os.path.exists(index_path):
        with open(index_path, "r", encoding="utf-8") as f:
            return f.read()
    return """
    <html><head><title>AI资讯推送系统</title></head>
    <body><h1>AI资讯推送系统</h1><p>请创建 frontend/index.html 文件</p></body></html>
    """


# ==================== Twitter账号管理 ====================

@app.get("/api/twitter-accounts", response_model=List[TwitterAccountResponse])
async def get_twitter_accounts(db: Session = Depends(get_db)):
    """获取所有Twitter账号"""
    accounts = db.query(TwitterAccount).all()
    return accounts


@app.post("/api/twitter-accounts", response_model=TwitterAccountResponse)
async def create_twitter_account(
    account: TwitterAccountCreate,
    db: Session = Depends(get_db)
):
    """添加Twitter账号"""
    # 检查是否已存在
    existing = db.query(TwitterAccount).filter(
        TwitterAccount.username == account.username
    ).first()
    if existing:
        raise HTTPException(status_code=400, detail="账号已存在")

    db_account = TwitterAccount(
        username=account.username,
        name=account.name
    )
    db.add(db_account)
    db.commit()
    db.refresh(db_account)
    return db_account


@app.delete("/api/twitter-accounts/{account_id}")
async def delete_twitter_account(account_id: int, db: Session = Depends(get_db)):
    """删除Twitter账号"""
    account = db.query(TwitterAccount).filter(TwitterAccount.id == account_id).first()
    if not account:
        raise HTTPException(status_code=404, detail="账号不存在")

    db.delete(account)
    db.commit()
    return {"status": "deleted"}


@app.patch("/api/twitter-accounts/{account_id}/toggle")
async def toggle_twitter_account(account_id: int, db: Session = Depends(get_db)):
    """启用/禁用Twitter账号"""
    account = db.query(TwitterAccount).filter(TwitterAccount.id == account_id).first()
    if not account:
        raise HTTPException(status_code=404, detail="账号不存在")

    account.enabled = not account.enabled
    db.commit()
    return {"enabled": account.enabled}


# ==================== 网站管理 ====================

@app.get("/api/websites", response_model=List[WebsiteResponse])
async def get_websites(db: Session = Depends(get_db)):
    """获取所有网站"""
    websites = db.query(Website).all()
    return websites


@app.post("/api/websites", response_model=WebsiteResponse)
async def create_website(website: WebsiteCreate, db: Session = Depends(get_db)):
    """添加网站"""
    db_website = Website(
        name=website.name,
        url=website.url,
        selector=website.selector
    )
    db.add(db_website)
    db.commit()
    db.refresh(db_website)
    return db_website


@app.delete("/api/websites/{website_id}")
async def delete_website(website_id: int, db: Session = Depends(get_db)):
    """删除网站"""
    website = db.query(Website).filter(Website.id == website_id).first()
    if not website:
        raise HTTPException(status_code=404, detail="网站不存在")

    db.delete(website)
    db.commit()
    return {"status": "deleted"}


@app.patch("/api/websites/{website_id}/toggle")
async def toggle_website(website_id: int, db: Session = Depends(get_db)):
    """启用/禁用网站"""
    website = db.query(Website).filter(Website.id == website_id).first()
    if not website:
        raise HTTPException(status_code=404, detail="网站不存在")

    website.enabled = not website.enabled
    db.commit()
    return {"enabled": website.enabled}


# ==================== 推送配置 ====================

@app.get("/api/push-config", response_model=PushConfigResponse)
async def get_push_config(db: Session = Depends(get_db)):
    """获取推送配置"""
    config = db.query(PushConfig).first()
    if not config:
        config = PushConfig()
        db.add(config)
        db.commit()
        db.refresh(config)
    return config


@app.put("/api/push-config", response_model=PushConfigResponse)
async def update_push_config(
    config_update: PushConfigUpdate,
    db: Session = Depends(get_db)
):
    """更新推送配置"""
    config = db.query(PushConfig).first()
    if not config:
        config = PushConfig()
        db.add(config)

    if config_update.schedule_time is not None:
        config.schedule_time = config_update.schedule_time
    if config_update.schedule_frequency is not None:
        config.schedule_frequency = config_update.schedule_frequency
    if config_update.schedule_enabled is not None:
        config.schedule_enabled = config_update.schedule_enabled
        if config_update.schedule_enabled:
            tasks.scheduler.start()
            tasks.update_schedule_time(
                config.schedule_time or "09:00",
                getattr(config, 'schedule_frequency', 'daily')
            )
    if config_update.feishu_webhook is not None:
        config.feishu_webhook = config_update.feishu_webhook

    db.commit()
    db.refresh(config)
    return config


# ==================== 手动触发 ====================

@app.post("/api/fetch")
async def trigger_fetch(db: Session = Depends(get_db)):
    """手动触发抓取"""
    try:
        # 抓取Twitter
        accounts = db.query(TwitterAccount).filter(TwitterAccount.enabled == True).all()
        tweet_count = 0
        for account in accounts:
            tweets = twitter_fetcher.fetch_and_save_tweets(db, account.username)
            tweet_count += len(tweets)

        # 抓取网站
        articles = website_fetcher.fetch_all_websites(db)

        return {
            "status": "success",
            "tweets_fetched": tweet_count,
            "articles_fetched": len(articles)
        }
    except Exception as e:
        logger.error(f"Fetch error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/push")
async def trigger_push(db: Session = Depends(get_db)):
    """手动触发推送"""
    try:
        config = db.query(PushConfig).first()
        if not config or not config.feishu_webhook:
            raise HTTPException(status_code=400, detail="请先配置飞书Webhook")

        success = ai_filter.filter_and_push(db, config.feishu_webhook, "manual")

        return {
            "status": "success" if success else "failed",
            "message": "推送完成" if success else "推送失败"
        }
    except Exception as e:
        logger.error(f"Push error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/fetch-and-push")
async def fetch_and_push(db: Session = Depends(get_db)):
    """手动触发抓取+推送"""
    try:
        config = db.query(PushConfig).first()
        if not config or not config.feishu_webhook:
            raise HTTPException(status_code=400, detail="请先配置飞书Webhook")

        # 抓取
        accounts = db.query(TwitterAccount).filter(TwitterAccount.enabled == True).all()
        tweet_count = 0
        for account in accounts:
            tweets = twitter_fetcher.fetch_and_save_tweets(db, account.username)
            tweet_count += len(tweets)

        articles = website_fetcher.fetch_all_websites(db)

        # 推送
        success = ai_filter.filter_and_push(db, config.feishu_webhook, "manual")

        return {
            "status": "success" if success else "failed",
            "tweets_fetched": tweet_count,
            "articles_fetched": len(articles),
            "message": "抓取并推送完成" if success else "抓取完成，推送失败"
        }
    except Exception as e:
        logger.error(f"Fetch and push error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ==================== 历史记录 ====================

@app.get("/api/push-history", response_model=List[PushHistoryResponse])
async def get_push_history(
    limit: int = 20,
    db: Session = Depends(get_db)
):
    """获取推送历史"""
    history = db.query(PushHistory).order_by(
        PushHistory.pushed_at.desc()
    ).limit(limit).all()

    return [
        PushHistoryResponse(
            id=h.id,
            content=h.content,
            push_type=h.push_type,
            item_count=h.item_count,
            pushed_at=h.pushed_at.isoformat(),
            status=h.status
        )
        for h in history
    ]


# ==================== 资讯列表 ====================

class ContentItemResponse(BaseModel):
    id: int
    source_type: str
    title: Optional[str] = None
    content: str
    url: Optional[str] = None
    topic: Optional[str] = None
    fetched_at: str
    is_pushed: bool


@app.get("/api/content", response_model=List[ContentItemResponse])
async def get_content(
    topic: Optional[str] = None,
    source: Optional[str] = None,  # twitter, website
    is_pushed: Optional[bool] = None,
    limit: int = 50,
    db: Session = Depends(get_db)
):
    """获取资讯列表"""
    # 查询推文
    tweets_query = db.query(Tweet)
    if topic:
        tweets_query = tweets_query.filter(Tweet.topic == topic)
    if is_pushed is not None:
        tweets_query = tweets_query.filter(Tweet.is_pushed == is_pushed)
    tweets = tweets_query.order_by(Tweet.fetched_at.desc()).limit(limit).all()

    # 查询文章
    articles_query = db.query(Article)
    if topic:
        articles_query = articles_query.filter(Article.topic == topic)
    if is_pushed is not None:
        articles_query = articles_query.filter(Article.is_pushed == is_pushed)
    articles = articles_query.order_by(Article.fetched_at.desc()).limit(limit).all()

    # 合并结果
    results = []

    for t in tweets:
        results.append(ContentItemResponse(
            id=t.id,
            source_type="twitter",
            title=t.content[:50],
            content=t.content,
            url=t.url,
            topic=t.topic,
            fetched_at=t.fetched_at.isoformat(),
            is_pushed=t.is_pushed
        ))

    for a in articles:
        results.append(ContentItemResponse(
            id=a.id,
            source_type="website",
            title=a.title,
            content=a.content or a.title,
            url=a.url,
            topic=a.topic,
            fetched_at=a.fetched_at.isoformat(),
            is_pushed=a.is_pushed
        ))

    # 按时间排序
    results.sort(key=lambda x: x.fetched_at, reverse=True)

    # 过滤来源
    if source:
        results = [r for r in results if r.source_type == source]

    return results[:limit]


@app.get("/api/topics")
async def get_topics(db: Session = Depends(get_db)):
    """获取所有主题及其数量"""
    # 从推文中获取主题
    tweet_topics = db.query(
        Tweet.topic,
        func.count(Tweet.id).label("count")
    ).filter(Tweet.topic != None).group_by(Tweet.topic).all()

    # 从文章中获取主题
    article_topics = db.query(
        Article.topic,
        func.count(Article.id).label("count")
    ).filter(Article.topic != None).group_by(Article.topic).all()

    # 合并统计
    topic_counts = {}
    for topic, count in tweet_topics:
        topic_counts[topic] = topic_counts.get(topic, 0) + count
    for topic, count in article_topics:
        topic_counts[topic] = topic_counts.get(topic, 0) + count

    # 转换为列表
    topics = [{"name": k, "count": v} for k, v in topic_counts.items()]
    topics.sort(key=lambda x: x["count"], reverse=True)

    return topics


# ==================== 统计 ====================

@app.get("/api/stats", response_model=StatsResponse)
async def get_stats(db: Session = Depends(get_db)):
    """获取统计信息"""
    twitter_accounts = db.query(TwitterAccount).count()
    websites = db.query(Website).count()
    unpushed_tweets = db.query(Tweet).filter(Tweet.is_pushed == False).count()
    unpushed_articles = db.query(Article).filter(Article.is_pushed == False).count()
    total_pushed = db.query(PushHistory).count()

    return StatsResponse(
        twitter_accounts=twitter_accounts,
        websites=websites,
        unpushed_tweets=unpushed_tweets,
        unpushed_articles=unpushed_articles,
        total_pushed=total_pushed
    )


# ==================== 健康检查 ====================

@app.get("/api/health")
async def health_check():
    """健康检查"""
    return {"status": "ok"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
