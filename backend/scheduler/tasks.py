import logging
import threading
import time
from datetime import datetime
from typing import Optional, Callable
import schedule
from sqlalchemy.orm import Session

from backend.database import SessionLocal, PushConfig
from backend.fetcher import twitter, website
from backend.filter import ai_filter

logger = logging.getLogger(__name__)


class Scheduler:
    """定时任务调度器"""

    def __init__(self):
        self.running = False
        self.thread = None
        self.stop_event = threading.Event()

    def start(self):
        """启动调度器"""
        if self.running:
            logger.warning("Scheduler already running")
            return

        self.running = True
        self.stop_event.clear()
        self.thread = threading.Thread(target=self._run_schedule, daemon=True)
        self.thread.start()
        logger.info("Scheduler started")

    def stop(self):
        """停止调度器"""
        self.running = False
        self.stop_event.set()
        if self.thread:
            self.thread.join(timeout=5)
        logger.info("Scheduler stopped")

    def _run_schedule(self):
        """运行调度循环"""
        while not self.stop_event.is_set():
            schedule.run_pending()
            time.sleep(60)  # 每分钟检查一次

    def add_daily_task(self, time_str: str, task_func: Callable):
        """
        添加每日任务

        Args:
            time_str: 时间字符串，格式 "HH:MM"
            task_func: 任务函数
        """
        schedule.clear()
        schedule.every().day.at(time_str).do(task_func)
        logger.info(f"Daily task scheduled at {time_str}")

    def add_hourly_task(self, task_func: Callable):
        """添加每小时任务"""
        schedule.clear()
        schedule.every().hour.do(task_func)
        logger.info("Hourly task scheduled")


# 全局调度器实例
scheduler = Scheduler()


def run_fetch_task():
    """执行抓取任务"""
    db = SessionLocal()
    try:
        # 获取所有启用的Twitter账号
        from backend.database import TwitterAccount
        accounts = db.query(TwitterAccount).filter(TwitterAccount.enabled == True).all()

        for account in accounts:
            try:
                twitter.fetch_and_save_tweets(db, account.username)
            except Exception as e:
                logger.error(f"Fetch tweets for {account.username} error: {e}")

        # 获取所有启用的网站
        website.fetch_all_websites(db)

        logger.info("Fetch task completed")
    finally:
        db.close()


def run_push_task(push_type: str = "scheduled"):
    """执行推送任务"""
    db = SessionLocal()
    try:
        # 获取推送配置
        config = db.query(PushConfig).first()
        if not config:
            config = PushConfig()
            db.add(config)
            db.commit()

        webhook_url = config.feishu_webhook
        if not webhook_url:
            logger.warning("Feishu webhook not configured")
            return

        # 执行筛选和推送
        ai_filter.filter_and_push(db, webhook_url, push_type)

        logger.info(f"Push task ({push_type}) completed")
    finally:
        db.close()


def run_full_pipeline():
    """运行完整流程：抓取+推送"""
    from datetime import datetime

    # 检查是否在禁止推送时间段（凌晨0点到早上7点）
    current_hour = datetime.now().hour
    if 0 <= current_hour < 7:
        logger.info(f"Skipping push - currently in quiet hours ({current_hour}:00)")
        return

    logger.info("Starting full pipeline: fetch + push")
    run_fetch_task()
    run_push_task("scheduled")


def update_schedule_time(time_str: str, frequency: str = "daily"):
    """更新定时推送时间"""
    if frequency == "hourly":
        scheduler.add_hourly_task(run_full_pipeline)
    else:
        scheduler.add_daily_task(time_str, run_full_pipeline)


def init_scheduler():
    """初始化调度器"""
    db = SessionLocal()
    try:
        config = db.query(PushConfig).first()
        if config and config.schedule_enabled:
            scheduler.start()
            frequency = getattr(config, 'schedule_frequency', 'daily')
            update_schedule_time(config.schedule_time or "09:00", frequency)
            logger.info(f"Scheduler initialized: {frequency} at {config.schedule_time}")
    finally:
        db.close()
