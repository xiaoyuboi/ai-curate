import requests
import logging
from datetime import datetime
from typing import List, Optional, Dict
from sqlalchemy.orm import Session

from backend.config import TWITTER_API_KEY
from backend.database import Tweet, TwitterAccount

logger = logging.getLogger(__name__)


def fetch_user_tweets(username: str, limit: int = 20) -> List[Dict]:
    """
    获取用户的推文

    Args:
        username: Twitter用户名
        limit: 获取数量

    Returns:
        推文列表
    """
    if not TWITTER_API_KEY:
        logger.warning("Twitter API key not configured, using mock data")
        return get_mock_tweets(username, limit)

    url = f"https://api.twitterapi.io/twitter/user/last_tweets"
    params = {
        "userName": username,
        "count": limit
    }
    headers = {
        "x-api-key": TWITTER_API_KEY
    }

    try:
        response = requests.get(url, params=params, headers=headers, timeout=30)
        if response.status_code == 200:
            data = response.json()
            return parse_twitter_response(data)
        else:
            logger.error(f"Twitter API error: {response.status_code}")
            return get_mock_tweets(username, limit)
    except Exception as e:
        logger.error(f"Fetch tweets error: {e}")
        return get_mock_tweets(username, limit)


def parse_twitter_response(data: dict) -> List[Dict]:
    """解析Twitter API响应"""
    tweets = []

    # 新端点返回格式: data.tweets[]
    tweet_list = data.get("data", {}).get("tweets", [])
    for tweet in tweet_list:
        tweets.append({
            "id": str(tweet.get("id", "")),
            "content": tweet.get("text", ""),
            "posted_at": parse_twitter_date(tweet.get("createdAt")),
            "url": tweet.get("url", "")
        })

    return tweets


def parse_twitter_date(date_str: str) -> Optional[datetime]:
    """解析Twitter日期格式"""
    if not date_str:
        return None
    try:
        # Twitter API返回的日期格式: "2024-01-01T00:00:00.000Z"
        return datetime.fromisoformat(date_str.replace("Z", "+00:00"))
    except:
        return None


def get_mock_tweets(username: str, limit: int) -> List[Dict]:
    """获取模拟推文数据（用于测试）"""
    return [
        {
            "id": f"mock_{username}_{i}",
            "content": f"这是 {username} 的模拟推文 {i+1}。这是一条关于AI的新闻或动态。",
            "posted_at": datetime.utcnow(),
            "url": f"https://twitter.com/{username}/status/{i}"
        }
        for i in range(limit)
    ]


def save_tweets(db: Session, account_id: int, tweets: List[Dict]) -> List[Tweet]:
    """保存推文到数据库"""
    saved_tweets = []
    for tweet_data in tweets:
        # 检查是否已存在
        existing = db.query(Tweet).filter(
            Tweet.tweet_id == tweet_data["id"]
        ).first()

        if not existing:
            tweet = Tweet(
                tweet_id=tweet_data["id"],
                account_id=account_id,
                content=tweet_data["content"],
                url=tweet_data.get("url"),
                posted_at=tweet_data.get("posted_at")
            )
            db.add(tweet)
            saved_tweets.append(tweet)

    db.commit()
    return saved_tweets


def fetch_and_save_tweets(db: Session, username: str) -> List[Tweet]:
    """
    获取并保存指定用户的推文

    Args:
        db: 数据库会话
        username: Twitter用户名

    Returns:
        新保存的推文列表
    """
    # 获取或创建账号
    account = db.query(TwitterAccount).filter(
        TwitterAccount.username == username
    ).first()

    if not account:
        account = TwitterAccount(username=username)
        db.add(account)
        db.commit()
        db.refresh(account)

    # 获取推文
    tweets = fetch_user_tweets(username)

    # 保存推文
    saved_tweets = save_tweets(db, account.id, tweets)

    logger.info(f"Fetched {len(tweets)} tweets for {username}, saved {len(saved_tweets)} new tweets")
    return saved_tweets


def get_unpushed_tweets(db: Session) -> List[Tweet]:
    """获取未推送的推文"""
    return db.query(Tweet).filter(
        Tweet.is_pushed == False
    ).order_by(Tweet.posted_at.desc()).all()
