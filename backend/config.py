import os
from typing import Optional

# 数据库配置
DATABASE_URL = "sqlite:///./data/database.db"

# 飞书机器人配置
FEISHU_WEBHOOK_URL = "https://open.feishu.cn/open-apis/bot/v2/hook/f19887ac-ee8d-411f-82de-9fe192d06a53"

# MiniMax API配置 (AI筛选)
MINIMAX_API_KEY = "sk-cp-_eIzhQFmTJjoTnSGu67dwDmnjx_9Ln5XBrG8WAhP9HUb4Hj6-im5YZiGW7QmUcySgJ0ax3VvbRZ9x7wgMcWotmdn0jNWYHBxamZ7DJ8xRDH15hxhvG2Ng_A"
MINIMAX_MODEL = os.getenv("MINIMAX_MODEL", "MiniMax-M2.5")

# Twitter API配置 (twitterapi.io)
TWITTER_API_KEY = "new1_0587a9742edc4d12902dc7a40dc9433e"

# Playwright配置
BROWSER_HEADLESS = os.getenv("BROWSER_HEADLESS", "true").lower() == "true"

# 定时任务配置
DEFAULT_SCHEDULE_TIME = "09:00"
DEFAULT_SCHEDULE_ENABLED = False

# AI筛选配置
AI_FILTER_ENABLED = True
DUPLICATE_SIMILARITY_THRESHOLD = 0.85
