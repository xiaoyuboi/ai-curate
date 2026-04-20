# ai-curate

AI 日报系统，基于 GitHub Actions + GitHub Models 每天自动生成一份中文 AI 资讯日报。

## 功能

- 每天自动抓取 AI 资讯
  - Hacker News AI 相关高分帖子
  - arXiv 最新 AI / LLM 论文
  - GitHub 重点项目 Release 动态
- 自动拉取 GitHub 热门 AI 仓库 TOP5
- 使用 GitHub Models 把英文内容处理成中文
  - 中文标题
  - 中文摘要
  - 3 条重点
  - 为什么值得关注
- 自动输出日报文件：
  - `reports/daily/YYYY-MM-DD.md`
  - `reports/daily/YYYY-MM-DD.json`
  - `latest.md`

## 工作流

- 手动触发：GitHub Actions → `Daily AI Brief`
- 定时触发：每天北京时间 08:00（cron `0 0 * * *`，按 UTC 配置）

## 技术方案

- 抓取层：GitHub API / HN Algolia / arXiv API
- 智能处理层：GitHub Models
- 承载层：GitHub Actions + 仓库内 Markdown 报告

## GitHub Models 说明

工作流使用 `secrets.GITHUB_TOKEN` 调用 GitHub Models，workflow 已包含：

```yaml
permissions:
  contents: write
  models: read
```

默认模型：`openai/gpt-4o-mini`

如果后面想换模型，可以修改 `.github/workflows/daily-ai-brief.yml` 中的 `GITHUB_MODELS_MODEL`。

## 邮箱推送（Gmail SMTP）

现在工作流已支持生成日报后自动发邮件。

需要在仓库 `Settings -> Secrets and variables -> Actions` 里配置这些 secrets：

- `SMTP_USER`：你的 Gmail 地址
- `SMTP_PASS`：Gmail 16 位应用专用密码
- `MAIL_TO`：收件邮箱
- `SMTP_HOST`：可选，默认 `smtp.gmail.com`
- `SMTP_PORT`：可选，默认 `587`

注意：
- `SMTP_PASS` 必须是 Gmail 应用专用密码，不是 Gmail 登录密码
- 这些值不要写进代码，也不要提交到仓库
- 如果 `SMTP_USER / SMTP_PASS / MAIL_TO` 没配，workflow 会跳过邮件步骤，不影响日报生成

## 本地运行

```bash
pip install -r requirements.txt
export GITHUB_TOKEN=你的 GitHub Token
python scripts/generate_daily_report.py
```

## 目录

```text
.
├── .github/workflows/daily-ai-brief.yml
├── scripts/generate_daily_report.py
├── reports/daily/
└── latest.md
```

## 注意

- GitHub Models 免费额度适合日报试运行，但不是无限免费。
- 如果后面加入 X / 网页抓取，维护成本会明显增加。
- 当前第一版优先保证：稳定、低成本、日报可读。
