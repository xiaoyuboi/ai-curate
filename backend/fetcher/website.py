import requests
import logging
from datetime import datetime
from typing import List, Optional, Dict
from bs4 import BeautifulSoup
from sqlalchemy.orm import Session
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urljoin

from backend.database import Website, Article

logger = logging.getLogger(__name__)

# Playwright 线程池
_executor = ThreadPoolExecutor(max_workers=2)


def _fetch_with_playwright_sync(url: str) -> List[Dict]:
    """在独立线程中运行Playwright抓取"""
    try:
        from playwright.sync_api import sync_playwright
        playwright = sync_playwright().start()
        browser = playwright.chromium.launch(headless=True)

        page = browser.new_page()
        page.goto(url, wait_until="networkidle", timeout=30000)
        page.wait_for_timeout(2000)
        content = page.content()
        browser.close()
        playwright.stop()

        soup = BeautifulSoup(content, "html.parser")
        articles = []

        # 查找列表项
        items = soup.select("li, .item, .list-item, .card, .post-item, .news-item")

        for item in items[:50]:
            title_elem = item.select_one("h1, h2, h3, h4, .title, .name, a")
            link_elem = item.select_one("a")
            if title_elem and link_elem:
                href = link_elem.get("href", "")
                if href and not href.startswith("#"):
                    articles.append({
                        "title": title_elem.get_text(strip=True)[:100],
                        "url": href if href.startswith("http") else url,
                        "content": item.get_text(strip=True)[:300]
                    })

        # 备选：查找所有链接
        if not articles:
            links = soup.select("a")[:10]
            for link in links:
                href = link.get("href", "")
                text = link.get_text(strip=True)
                if href and text and len(text) > 5:
                    articles.append({
                        "title": text[:100],
                        "url": href if href.startswith("http") else url,
                        "content": text
                    })

        return articles
    except Exception as e:
        logger.error(f"Playwright fetch error: {e}")
        return []


def fetch_website_with_playwright(url: str) -> List[Dict]:
    """使用Playwright抓取动态网页内容"""
    try:
        future = _executor.submit(_fetch_with_playwright_sync, url)
        return future.result(timeout=60)
    except Exception as e:
        logger.error(f"Playwright fetch error: {e}")
        return []


def parse_rss_date(date_str: str) -> Optional[datetime]:
    """解析RSS日期格式"""
    if not date_str:
        return None

    # 常见日期格式
    formats = [
        "%a, %d %b %Y %H:%M:%S %z",  # RFC 822
        "%Y-%m-%dT%H:%M:%S%z",       # ISO 8601
        "%Y-%m-%dT%H:%M:%S",         # ISO 8601 without timezone
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d",
    ]

    for fmt in formats:
        try:
            return datetime.strptime(date_str.strip(), fmt)
        except:
            continue
    return None


def try_parse_rss(soup: BeautifulSoup, base_url: str) -> List[Dict]:
    """尝试解析RSS/Atom"""
    articles = []

    # 查找item/channel项
    items = soup.select("item, entry")
    for item in items[:20]:
        title_elem = item.select_one("title")
        link_elem = item.select_one("link")
        desc_elem = item.select_one("description, summary, content")
        pubdate_elem = item.select_one("pubDate, published, updated, dc\\:date")

        if title_elem:
            url = ""
            if link_elem:
                url = link_elem.get("text", "") or link_elem.get("href", "")

            # 解析发布日期
            published_at = None
            if pubdate_elem:
                pubdate_str = pubdate_elem.get_text(strip=True)
                published_at = parse_rss_date(pubdate_str)

            articles.append({
                "title": title_elem.get_text(strip=True),
                "url": url,
                "content": desc_elem.get_text(strip=True)[:500] if desc_elem else "",
                "published_at": published_at
            })

    return articles


def fetch_website_content(url: str, selector: str = None) -> List[Dict]:
    """
    抓取网站内容

    Args:
        url: 网站URL
        selector: CSS选择器

    Returns:
        文章列表
    """
    try:
        response = requests.get(url, timeout=30, headers={
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
        })
        response.raise_for_status()

        soup = BeautifulSoup(response.content, "html.parser")

        # 尝试提取文章
        articles = []

        # 首先尝试RSS
        rss_articles = try_parse_rss(soup, url)
        if rss_articles:
            return rss_articles

        # 然后尝试常见的选择器
        selectors = [
            "article",
            ".post",
            ".entry",
            ".article-content",
            "main article",
            selector
        ]

        for sel in selectors:
            if not sel:
                continue
            elements = soup.select(sel)
            if elements:
                for elem in elements[:10]:  # 最多取10条
                    title_elem = elem.select_one("h1, h2, h3, .title, .entry-title")
                    link_elem = elem.select_one("a")
                    if title_elem and link_elem:
                        articles.append({
                            "title": title_elem.get_text(strip=True),
                            "url": link_elem.get("href", ""),
                            "content": elem.get_text(strip=True)[:500]
                        })
                if articles:
                    break

        # 如果HTTP请求没有获取到有效内容，使用Playwright
        if not articles or (len(articles) == 1 and articles[0].get("content") == "页面内容未能解析"):
            logger.info(f"Falling back to Playwright for {url}")
            articles = fetch_website_with_playwright(url)

        # 如果都没找到，返回页面标题作为备选
        if not articles:
            title = soup.title.string if soup.title else "无标题"
            articles.append({
                "title": title,
                "url": url,
                "content": "页面内容未能解析"
            })

        return articles

    except Exception as e:
        logger.error(f"Fetch website error: {e}")
        # 尝试Playwright作为备选
        return fetch_website_with_playwright(url)


def save_articles(db: Session, website_id: int, articles: List[Dict]) -> List[Article]:
    """保存文章到数据库（增量：只保存新URL的文章）"""
    saved_articles = []

    # 获取网站信息
    website = db.query(Website).filter(Website.id == website_id).first()
    if not website:
        return []

    for article_data in articles:
        url = article_data.get("url", "")
        if not url:
            continue

        # 跳过网站主URL
        if url == website.url or url.rstrip('/') == website.url.rstrip('/'):
            continue

        # 完整URL
        if url.startswith("/"):
            url = urljoin(website.url, url)

        # 检查是否已存在（URL去重）
        existing = db.query(Article).filter(
            Article.url == url
        ).first()

        if not existing:
            article = Article(
                website_id=website_id,
                title=article_data.get("title", "无标题"),
                url=url,
                content=article_data.get("content", ""),
                published_at=article_data.get("published_at")
            )
            db.add(article)
            saved_articles.append(article)

    db.commit()
    return saved_articles


def fetch_and_save_website(db: Session, website_id: int) -> List[Article]:
    """
    获取并保存网站内容（增量抓取）

    Args:
        db: 数据库会话
        website_id: 网站ID

    Returns:
        新保存的文章列表
    """
    website = db.query(Website).filter(Website.id == website_id).first()
    if not website or not website.enabled:
        return []

    # 抓取内容
    articles = fetch_website_content(website.url, website.selector)

    # 保存文章（自动去重）
    saved_articles = save_articles(db, website_id, articles)

    # 更新最后抓取时间
    website.last_fetched = datetime.utcnow()
    db.commit()

    logger.info(f"Fetched {len(articles)} articles from {website.name}, saved {len(saved_articles)} new articles")
    return saved_articles


def fetch_all_websites(db: Session) -> List[Article]:
    """获取所有启用的网站内容"""
    websites = db.query(Website).filter(Website.enabled == True).all()
    all_articles = []

    for website in websites:
        articles = fetch_and_save_website(db, website.id)
        all_articles.extend(articles)

    return all_articles


def get_unpushed_articles(db: Session) -> List[Article]:
    """获取未推送的文章"""
    return db.query(Article).filter(
        Article.is_pushed == False
    ).order_by(Article.published_at.desc()).all()
