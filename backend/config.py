import os
from typing import Optional

# 数据库配置
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./data/database.db")

# 飞书机器人配置
FEISHU_WEBHOOK_URL = os.getenv("FEISHU_WEBHOOK_URL", "")

# MiniMax API配置 (AI筛选)
MINIMAX_API_KEY = os.getenv("MINIMAX_API_KEY", "")
MINIMAX_MODEL = os.getenv("MINIMAX_MODEL", "MiniMax-M2.5")

# Twitter API配置 (twitterapi.io)
TWITTER_API_KEY = os.getenv("TWITTER_API_KEY", "")

# Playwright配置
BROWSER_HEADLESS = os.getenv("BROWSER_HEADLESS", "true").lower() == "true"

# 定时任务配置
DEFAULT_SCHEDULE_TIME = "09:00"
DEFAULT_SCHEDULE_ENABLED = False

# AI筛选配置
AI_FILTER_ENABLED = True
DUPLICATE_SIMILARITY_THRESHOLD = 0.85
