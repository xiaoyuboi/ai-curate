#!/usr/bin/env python3
import os
import smtplib
from email.message import EmailMessage
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LATEST_MD = ROOT / "latest.md"


def required_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


def main() -> None:
    smtp_host = (os.getenv("SMTP_HOST") or "smtp.gmail.com").strip() or "smtp.gmail.com"
    smtp_port = int((os.getenv("SMTP_PORT") or "587").strip() or "587")
    smtp_user = required_env("SMTP_USER")
    smtp_pass = required_env("SMTP_PASS")
    mail_to = required_env("MAIL_TO")
    subject = (os.getenv("MAIL_SUBJECT") or "AI 日报").strip() or "AI 日报"

    if not LATEST_MD.exists():
        raise RuntimeError(f"latest.md not found: {LATEST_MD}")

    report_markdown = LATEST_MD.read_text(encoding="utf-8")
    body = (
        "这是今天自动生成的 AI 日报。\n\n"
        f"仓库：{os.getenv('GITHUB_REPOSITORY', 'unknown')}\n"
        f"工作流：{os.getenv('GITHUB_WORKFLOW', 'Daily AI Brief')}\n\n"
        f"{report_markdown}\n"
    )

    msg = EmailMessage()
    msg["From"] = smtp_user
    msg["To"] = mail_to
    msg["Subject"] = subject
    msg.set_content(body)

    with smtplib.SMTP(smtp_host, smtp_port, timeout=60) as server:
        server.ehlo()
        server.starttls()
        server.ehlo()
        server.login(smtp_user, smtp_pass)
        server.send_message(msg)

    print(f"Email sent to {mail_to}")


if __name__ == "__main__":
    main()
