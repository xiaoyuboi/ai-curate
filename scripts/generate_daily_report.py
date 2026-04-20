#!/usr/bin/env python3
import json
import math
import os
import re
import textwrap
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import quote

import requests
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
REPORT_DIR = ROOT / "reports" / "daily"
REPORT_DIR.mkdir(parents=True, exist_ok=True)

GH_API = "https://api.github.com"
MODELS_API = "https://models.github.ai/inference/chat/completions"
SH_TZ = timezone(timedelta(hours=8))
TODAY = datetime.now(SH_TZ)
TODAY_STR = TODAY.strftime("%Y-%m-%d")
UTC_24H = (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%SZ")

GITHUB_TOKEN = os.getenv("GITHUB_TOKEN") or os.getenv("GH_TOKEN")
GITHUB_REPOSITORY = os.getenv("GITHUB_REPOSITORY", "xiaoyuboi/ai-curate")
GITHUB_MODELS_MODEL = os.getenv("GITHUB_MODELS_MODEL", "openai/gpt-4o-mini")
NEWS_LIMIT = int(os.getenv("NEWS_LIMIT", "8"))
REPO_LIMIT = int(os.getenv("REPO_LIMIT", "5"))

SESSION = requests.Session()
SESSION.headers.update({
    "User-Agent": f"{GITHUB_REPOSITORY}-daily-ai-brief",
    "Accept": "application/json",
})
if GITHUB_TOKEN:
    SESSION.headers["Authorization"] = f"Bearer {GITHUB_TOKEN}"

AI_KEYWORDS = [
    "AI", "artificial intelligence", "LLM", "model", "agent", "OpenAI", "Claude",
    "Gemini", "DeepSeek", "Anthropic", "copilot", "RAG", "multimodal",
]
REPO_TOPICS = [
    "artificial-intelligence", "machine-learning", "llm", "ai-agent", "generative-ai",
]
EXCLUDE_NEWS_TERMS = [
    "molotov", "cocktail", "typewriter", "typewriters", "murder", "police", "crime",
]


def strip_html(text: str) -> str:
    text = re.sub(r"<[^>]+>", " ", text or "")
    return re.sub(r"\s+", " ", text).strip()


def truncate(text: str, limit: int = 240) -> str:
    text = re.sub(r"\s+", " ", (text or "").strip())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def github_api(path: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    resp = SESSION.get(f"{GH_API}{path}", params=params, timeout=60)
    resp.raise_for_status()
    return resp.json()


def safe_get_json(url: str, params: Optional[Dict[str, Any]] = None) -> Any:
    resp = SESSION.get(url, params=params, timeout=60)
    resp.raise_for_status()
    return resp.json()


def safe_get_text(url: str, params: Optional[Dict[str, Any]] = None) -> str:
    resp = SESSION.get(url, params=params, timeout=60)
    resp.raise_for_status()
    return resp.text


def score_repo(item: Dict[str, Any]) -> float:
    stars = item.get("stargazers_count", 0)
    forks = item.get("forks_count", 0)
    updated_at = item.get("pushed_at") or item.get("updated_at")
    freshness = 0.0
    if updated_at:
        dt = datetime.fromisoformat(updated_at.replace("Z", "+00:00"))
        hours = max((datetime.now(timezone.utc) - dt).total_seconds() / 3600.0, 1)
        freshness = 96 / hours
    return round(math.log1p(stars) * 15 + math.log1p(forks) * 4 + freshness, 2)


def fetch_hn_news() -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []
    seen = set()
    for keyword in ["AI", "LLM", "agent", "OpenAI", "Claude", "Gemini", "DeepSeek"]:
        data = safe_get_json(
            "https://hn.algolia.com/api/v1/search_by_date",
            params={"query": keyword, "tags": "story", "numericFilters": "points>20", "hitsPerPage": 20},
        )
        for hit in data.get("hits", []):
            title = hit.get("title") or hit.get("story_title") or ""
            url = hit.get("url") or hit.get("story_url") or f"https://news.ycombinator.com/item?id={hit.get('objectID')}"
            if not title or not url or url in seen:
                continue
            seen.add(url)
            items.append({
                "id": f"hn-{hit.get('objectID')}",
                "source": "Hacker News",
                "title": title,
                "summary": truncate(hit.get("story_text") or title, 220),
                "url": url,
                "published_at": hit.get("created_at") or UTC_24H,
                "score": (hit.get("points") or 0) + (hit.get("num_comments") or 0) * 2,
            })
    items.sort(key=lambda x: x["score"], reverse=True)
    return items


def fetch_arxiv_news() -> List[Dict[str, Any]]:
    xml_text = safe_get_text(
        "http://export.arxiv.org/api/query",
        params={
            "search_query": "cat:cs.AI+OR+cat:cs.CL+OR+cat:cs.LG",
            "sortBy": "submittedDate",
            "sortOrder": "descending",
            "start": 0,
            "max_results": 12,
        },
    )
    root = ET.fromstring(xml_text)
    ns = {"a": "http://www.w3.org/2005/Atom"}
    items = []
    for entry in root.findall("a:entry", ns):
        title = truncate((entry.findtext("a:title", default="", namespaces=ns) or "").replace("\n", " "), 160)
        summary = truncate((entry.findtext("a:summary", default="", namespaces=ns) or "").replace("\n", " "), 240)
        url = entry.findtext("a:id", default="", namespaces=ns)
        published = entry.findtext("a:published", default=UTC_24H, namespaces=ns)
        items.append({
            "id": f"arxiv-{url.rsplit('/', 1)[-1]}",
            "source": "arXiv",
            "title": title,
            "summary": summary,
            "url": url,
            "published_at": published,
            "score": 50,
        })
    return items


def fetch_github_releases() -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []
    for repo in [
        "microsoft/markitdown", "langchain-ai/langgraph", "huggingface/transformers",
        "anthropics/anthropic-cookbook", "openai/openai-python",
    ]:
        try:
            releases = github_api(f"/repos/{repo}/releases", params={"per_page": 2})
        except Exception:
            continue
        for rel in releases[:1]:
            published = rel.get("published_at") or rel.get("created_at")
            if not published:
                continue
            if datetime.fromisoformat(published.replace("Z", "+00:00")) < datetime.now(timezone.utc) - timedelta(days=14):
                continue
            items.append({
                "id": f"release-{repo}-{rel.get('id')}",
                "source": "GitHub Release",
                "title": f"{repo} 发布 {rel.get('tag_name')}",
                "summary": truncate(strip_html(rel.get("body") or rel.get("name") or ""), 240),
                "url": rel.get("html_url"),
                "published_at": published,
                "score": 65,
            })
    return items


def dedupe_news(items: List[Dict[str, Any]], limit: int) -> List[Dict[str, Any]]:
    seen_urls = set()
    deduped = []
    for item in sorted(items, key=lambda x: (x.get("score", 0), x.get("published_at", "")), reverse=True):
        url = item.get("url")
        title = (item.get("title") or "").lower()
        summary = (item.get("summary") or "").lower()
        if any(term in title or term in summary for term in EXCLUDE_NEWS_TERMS):
            continue
        if not url or url in seen_urls:
            continue
        seen_urls.add(url)
        deduped.append(item)
        if len(deduped) >= limit:
            break
    return deduped


def fetch_top_repos(limit: int) -> List[Dict[str, Any]]:
    repos: Dict[str, Dict[str, Any]] = {}
    pushed_since = (datetime.now(timezone.utc) - timedelta(days=14)).strftime("%Y-%m-%d")
    created_since = (datetime.now(timezone.utc) - timedelta(days=120)).strftime("%Y-%m-%d")
    for topic in REPO_TOPICS:
        data = github_api(
            "/search/repositories",
            params={
                "q": f"topic:{topic} pushed:>={pushed_since} created:>={created_since} stars:>30 archived:false",
                "sort": "stars",
                "order": "desc",
                "per_page": 20,
            },
        )
        for item in data.get("items", []):
            repos[item["full_name"]] = {
                "name": item["full_name"],
                "url": item["html_url"],
                "description": truncate(item.get("description") or "", 220),
                "language": item.get("language") or "Unknown",
                "stars": item.get("stargazers_count", 0),
                "forks": item.get("forks_count", 0),
                "updated_at": item.get("pushed_at"),
                "topics": item.get("topics") or [],
                "score": score_repo(item),
            }
    ranked = sorted(repos.values(), key=lambda x: (x["score"], x["stars"]), reverse=True)
    return ranked[:limit]


def call_github_models(system_prompt: str, user_prompt: str, max_tokens: int = 3000) -> str:
    if not GITHUB_TOKEN:
        raise RuntimeError("GITHUB_TOKEN is required for GitHub Models")
    payload = {
        "model": GITHUB_MODELS_MODEL,
        "temperature": 0.2,
        "max_tokens": max_tokens,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
    }
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {GITHUB_TOKEN}",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    resp = requests.post(MODELS_API, headers=headers, json=payload, timeout=120)
    resp.raise_for_status()
    data = resp.json()
    return data["choices"][0]["message"]["content"]


def parse_json_from_text(text: str) -> Any:
    match = re.search(r"```json\s*(.*?)```", text, re.S)
    if match:
        text = match.group(1)
    decoder = json.JSONDecoder()
    for token in ["[", "{"]:
        start = text.find(token)
        if start != -1:
            try:
                obj, _ = decoder.raw_decode(text[start:])
                return obj
            except Exception:
                pass
    raise ValueError("No JSON found in model response")


def enrich_news_with_ai(news_items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    if not news_items:
        return []
    system_prompt = "你是AI日报编辑。把英文资讯翻译成简洁中文，并提炼重点。只输出合法JSON。"
    user_prompt = {
        "task": "请把下面资讯整理成中文日报条目。每条输出字段：id, title_cn, summary_cn, highlights(长度3), why_it_matters。不要省略任何id。summary_cn控制在90字内，why_it_matters控制在50字内。",
        "items": [
            {
                "id": item["id"],
                "source": item["source"],
                "title": item["title"],
                "summary": item["summary"],
                "url": item["url"],
            }
            for item in news_items
        ],
    }
    try:
        result = call_github_models(system_prompt, json.dumps(user_prompt, ensure_ascii=False), max_tokens=3600)
        parsed = parse_json_from_text(result)
        mapping = {x["id"]: x for x in parsed}
        for item in news_items:
            extra = mapping.get(item["id"], {})
            item["title_cn"] = extra.get("title_cn") or item["title"]
            item["summary_cn"] = extra.get("summary_cn") or item["summary"]
            item["highlights"] = extra.get("highlights") or [item["summary"]]
            item["why_it_matters"] = extra.get("why_it_matters") or "值得继续跟踪。"
    except Exception as e:
        for item in news_items:
            item["title_cn"] = item["title"]
            item["summary_cn"] = item["summary"]
            item["highlights"] = ["GitHub Models 调用失败，回退原文摘要。"]
            item["why_it_matters"] = f"模型处理失败：{truncate(str(e), 80)}"
    return news_items


def enrich_repos_with_ai(repos: List[Dict[str, Any]]) -> Tuple[List[Dict[str, Any]], str]:
    if not repos:
        return [], "今天没有足够的新仓库数据。"
    takeaway = "今天仓库趋势偏向通用AI工具。"
    for repo in repos:
        system_prompt = "你是AI情报分析师。把英文仓库简介翻译成自然中文，并输出关注理由与3条重点。只输出合法JSON对象。"
        user_prompt = {
            "task": "处理单个GitHub仓库，输出字段：name, desc_cn, highlights(长度3), why_watch。",
            "repo": repo,
        }
        try:
            result = call_github_models(system_prompt, json.dumps(user_prompt, ensure_ascii=False), max_tokens=800)
            parsed = parse_json_from_text(result)
            if isinstance(parsed, list):
                parsed = parsed[0] if parsed else {}
            if isinstance(parsed, str):
                parsed = {"desc_cn": parsed, "highlights": [], "why_watch": "适合继续跟踪。"}
            if not isinstance(parsed, dict):
                parsed = {}
            repo["desc_cn"] = parsed.get("desc_cn") or repo["description"]
            repo["highlights"] = parsed.get("highlights") or [repo["description"] or "仓库简介缺失"]
            repo["why_watch"] = parsed.get("why_watch") or "适合继续跟踪。"
        except Exception as e:
            repo["desc_cn"] = repo["description"]
            repo["highlights"] = ["GitHub Models 调用失败，回退原始简介。"]
            repo["why_watch"] = f"建议手动复核：{truncate(str(e), 70)}"
    try:
        summary_prompt = {
            "task": "根据这些热门AI仓库，输出一个 today_takeaway 字段，总结今天的仓库趋势，控制在60字内。",
            "repos": [
                {
                    "name": repo["name"],
                    "desc_cn": repo.get("desc_cn") or repo.get("description"),
                    "stars": repo["stars"],
                    "language": repo["language"],
                }
                for repo in repos
            ],
        }
        result = call_github_models(
            "你是AI日报主编。根据仓库列表总结今天最值得关注的开源趋势。只输出合法JSON对象。",
            json.dumps(summary_prompt, ensure_ascii=False),
            max_tokens=500,
        )
        parsed = parse_json_from_text(result)
        if isinstance(parsed, str):
            takeaway = parsed
        elif isinstance(parsed, dict):
            takeaway = parsed.get("today_takeaway") or takeaway
    except Exception as e:
        takeaway = f"仓库趋势总结生成失败：{truncate(str(e), 90)}"
    return repos, takeaway


def build_markdown(news: List[Dict[str, Any]], repos: List[Dict[str, Any]], takeaway: str) -> str:
    lines = [
        f"# AI 日报 - {TODAY_STR}",
        "",
        f"> 生成时间：{TODAY.strftime('%Y-%m-%d %H:%M:%S %Z')}",
        f"> 模型：{GITHUB_MODELS_MODEL}",
        "",
        "## 今日 AI 资讯",
        "",
    ]
    for idx, item in enumerate(news, 1):
        lines.extend([
            f"### {idx}. {item['title_cn']}",
            f"- 来源：{item['source']}",
            f"- 原标题：{item['title']}",
            f"- 摘要：{item['summary_cn']}",
            f"- 为什么值得看：{item['why_it_matters']}",
            f"- 链接：{item['url']}",
            "- 重点：",
        ])
        for h in item.get("highlights", [])[:3]:
            lines.append(f"  - {h}")
        lines.append("")
    lines.extend(["## GitHub 热门 AI 仓库 TOP5", ""])
    for idx, repo in enumerate(repos, 1):
        lines.extend([
            f"### TOP {idx}. {repo['name']}",
            f"- Stars：{repo['stars']} | Forks：{repo['forks']} | 语言：{repo['language']}",
            f"- 中文解读：{repo['desc_cn']}",
            f"- 为什么值得关注：{repo['why_watch']}",
            f"- 链接：{repo['url']}",
            "- 重点：",
        ])
        for h in repo.get("highlights", [])[:3]:
            lines.append(f"  - {h}")
        lines.append("")
    lines.extend(["## 今日结论", "", takeaway, ""])
    return "\n".join(lines)


def main() -> None:
    raw_news = dedupe_news(fetch_hn_news() + fetch_arxiv_news() + fetch_github_releases(), NEWS_LIMIT)
    news = enrich_news_with_ai(raw_news)
    repos, takeaway = enrich_repos_with_ai(fetch_top_repos(REPO_LIMIT))

    payload = {
        "generated_at": TODAY.isoformat(),
        "repository": GITHUB_REPOSITORY,
        "news": news,
        "repos": repos,
        "takeaway": takeaway,
    }
    json_path = REPORT_DIR / f"{TODAY_STR}.json"
    md_path = REPORT_DIR / f"{TODAY_STR}.md"
    latest_path = ROOT / "latest.md"
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    markdown = build_markdown(news, repos, takeaway)
    md_path.write_text(markdown, encoding="utf-8")
    latest_path.write_text(markdown, encoding="utf-8")
    print(f"Wrote {json_path}")
    print(f"Wrote {md_path}")
    print(f"Wrote {latest_path}")


if __name__ == "__main__":
    main()
