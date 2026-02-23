import requests
from typing import List, Dict, Any
import logging

logger = logging.getLogger(__name__)


def send_feishu_message(webhook_url: str, content: str, items: List[Dict[str, Any]] = None) -> bool:
    """
    发送飞书消息

    Args:
        webhook_url: 飞书机器人webhook地址
        content: 消息标题/摘要
        items: 内容项列表，每项包含 title, url, summary

    Returns:
        是否发送成功
    """
    if not webhook_url:
        logger.warning("Feishu webhook URL not configured")
        return False

    # 构建卡片消息
    cards = []

    # 标题卡片
    header_card = {
        "header": {
            "title": {
                "tag": "plain_text",
                "content": content,
                "template": "blue"
            }
        }
    }
    cards.append(header_card)

    # 内容卡片
    if items:
        for item in items:
            item_card = {
                "header": {
                    "title": {
                        "tag": "plain_text",
                        "content": item.get("title", "无标题")[:50]
                    }
                },
                "elements": [
                    {
                        "tag": "div",
                        "text": {
                            "tag": "lark_md",
                            "content": item.get("summary", "")[:200]
                        }
                    }
                ]
            }
            if item.get("url"):
                item_card["elements"].append({
                    "tag": "action",
                    "actions": [
                        {
                            "tag": "button",
                            "text": {
                                "tag": "plain_text",
                                "content": "查看原文"
                            },
                            "url": item["url"],
                            "type": "primary"
                        }
                    ]
                })
            cards.append(item_card)

    # 如果没有内容项，只发送标题
    if not items:
        message = {
            "msg_type": "interactive",
            "card": header_card
        }
    else:
        # 使用container类型发送多条消息
        message = {
            "msg_type": "interactive",
            "card": {
                "config": {
                    "wide_screen_mode": True
                },
                "elements": [
                    {
                        "tag": "div",
                        "text": {
                            "tag": "lark_md",
                            "content": f"**{content}**\n共 {len(items)} 条内容",
                            "template": "blue"
                        }
                    },
                    {
                        "tag": "div",
                        "text": {
                            "tag": "lark_md",
                            "content": "---"
                        }
                    }
                ]
            }
        }

        # 添加每个内容项
        for item in items:
            title = item.get("title", "无标题")[:50]
            summary = item.get("summary", "")[:200]
            url = item.get("url", "")

            item_content = f"**{title}**\n{summary}"
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
