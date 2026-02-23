from datetime import datetime
from typing import Optional, List
from sqlalchemy import create_engine, Column, Integer, String, Boolean, DateTime, Text, ForeignKey
from sqlalchemy.orm import declarative_base, relationship, sessionmaker
from backend.config import DATABASE_URL

Base = declarative_base()


class TwitterAccount(Base):
    """X(Twitter)账号"""
    __tablename__ = "twitter_accounts"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, nullable=False)
    name = Column(String, nullable=True)
    enabled = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # 关联
    tweets = relationship("Tweet", back_populates="account")


class Website(Base):
    """要抓取的网站"""
    __tablename__ = "websites"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    url = Column(String, nullable=False)
    selector = Column(String, nullable=True)  # CSS选择器，用于内容提取
    last_fetched = Column(DateTime, nullable=True)  # 上次抓取时间
    enabled = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # 关联
    articles = relationship("Article", back_populates="website")


class Tweet(Base):
    """推文记录"""
    __tablename__ = "tweets"

    id = Column(Integer, primary_key=True, index=True)
    tweet_id = Column(String, unique=True, nullable=False)  # Twitter原始ID
    account_id = Column(Integer, ForeignKey("twitter_accounts.id"))
    content = Column(Text, nullable=False)
    url = Column(String, nullable=True)
    posted_at = Column(DateTime, nullable=True)
    fetched_at = Column(DateTime, default=datetime.utcnow)
    is_pushed = Column(Boolean, default=False)

    # 关联
    account = relationship("TwitterAccount", back_populates="tweets")


class Article(Base):
    """网站文章记录"""
    __tablename__ = "articles"

    id = Column(Integer, primary_key=True, index=True)
    website_id = Column(Integer, ForeignKey("websites.id"))
    title = Column(String, nullable=False)
    url = Column(String, unique=True, nullable=False)
    content = Column(Text, nullable=True)
    published_at = Column(DateTime, nullable=True)
    fetched_at = Column(DateTime, default=datetime.utcnow)
    is_pushed = Column(Boolean, default=False)

    # 关联
    website = relationship("Website", back_populates="articles")


class PushConfig(Base):
    """推送配置"""
    __tablename__ = "push_config"

    id = Column(Integer, primary_key=True, index=True)
    schedule_time = Column(String, default="09:00")  # 每日推送时间
    schedule_frequency = Column(String, default="daily")  # daily, hourly
    schedule_enabled = Column(Boolean, default=False)
    feishu_webhook = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class PushHistory(Base):
    """推送历史"""
    __tablename__ = "push_history"

    id = Column(Integer, primary_key=True, index=True)
    content = Column(Text, nullable=False)
    push_type = Column(String, nullable=False)  # manual, scheduled
    item_count = Column(Integer, default=0)
    pushed_at = Column(DateTime, default=datetime.utcnow)
    status = Column(String, default="success")  # success, failed


class ContentItem(Base):
    """待推送内容（AI筛选后）"""
    __tablename__ = "content_items"

    id = Column(Integer, primary_key=True, index=True)
    source_type = Column(String, nullable=False)  # twitter, website
    source_id = Column(Integer, nullable=False)  # tweet_id or article_id
    title = Column(String, nullable=True)
    content = Column(Text, nullable=False)
    url = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    is_pushed = Column(Boolean, default=False)


# 数据库初始化
engine = create_engine(DATABASE_URL.replace("sqlite:///", "sqlite:////Users/zish/Coding/ai-curate/"))
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def init_db():
    """初始化数据库表"""
    Base.metadata.create_all(bind=engine)


def get_db():
    """获取数据库会话"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
