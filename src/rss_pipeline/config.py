"""共享配置：读取 .env、常量定义。"""
import os

# 本文件位于 src/rss_pipeline/；项目根（存放 .env / rss.db）在其上两级。
PACKAGE_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(os.path.dirname(PACKAGE_DIR))
ENV_PATH = os.environ.get("RSS_ENV_PATH", os.path.join(PROJECT_ROOT, ".env"))
DB_PATH = os.environ.get("RSS_DB_PATH", os.path.join(PROJECT_ROOT, "rss.db"))


def _load_env():
    """极简 .env 解析，写入 os.environ（不覆盖已存在的）。"""
    if not os.path.exists(ENV_PATH):
        return
    with open(ENV_PATH, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            os.environ.setdefault(k.strip(), v.strip())


_load_env()

# --- Telegram ---
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")

# --- 翻译厂商（可换）---
# provider: codex（默认）| deepseek（显式选择的旧后端）
TRANSLATE_PROVIDER = os.environ.get("NEWS_PROVIDER", "codex")
DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY", "")
DEEPSEEK_MODEL = os.environ.get("DEEPSEEK_MODEL", "deepseek-chat")
DEEPSEEK_BASE = "https://api.deepseek.com"

# 原生富文本为唯一流式路径，不提供普通消息降级。
RICH_STREAMING = True

# --- RSSHub 数据源（本地直连，不走 Caddy）---
RSSHUB_BASE = os.environ.get("RSSHUB_BASE", "http://127.0.0.1:1200")
# 要采集的源：(名称, RSSHub 路由或公开 feed URL, 每次取条数)
SOURCES = [
    ("GitHub Trending", "/github/trending/daily/any", 8),
    ("Hacker News", "https://news.ycombinator.com/rss", 6),
    ("Lobsters", "https://lobste.rs/rss", 6),
    ("Simon Willison", "https://simonwillison.net/atom/everything/", 6),
    ("InfoQ", "https://www.infoq.com/feed/", 6),
    ("OpenAI", "https://openai.com/news/rss.xml", 24),
    ("Anthropic", "https://www.anthropic.com/research", 12),
    ("DeepSeek", "https://www.deepseek.com/en/news/", 10),
    ("Linux DO", os.environ.get('LINUXDO_FEED_URL', 'https://linux.do/latest.rss'), 8),
    ("Reddit Technology", "https://www.reddit.com/r/technology/.rss", 8),
]
SOURCE_KEYS = {
    "GitHub Trending": "github", "Hacker News": "hackernews",
    "Lobsters": "lobsters", "Simon Willison": "simonwillison", "InfoQ": "infoq",
    "OpenAI": "openai", "Anthropic": "anthropic", "DeepSeek": "deepseek",
    "Linux DO": "linuxdo", "Reddit Technology": "reddit",
}

DIAGRAM_SKILL_PATH = os.path.join(os.environ.get('CODEX_HOME', os.path.expanduser('~/.codex')), 'skills', 'diagram-design')
# First-use style confirmation is required by the installed skill.
DIAGRAM_STYLE = os.environ.get('NEWS_DIAGRAM_STYLE', '')

# Codex runtime uses saved CLI authentication, not a copied API key.
CODEX_BIN = os.environ.get('CODEX_BIN', 'codex')
CODEX_MODEL = os.environ.get('CODEX_MODEL') or None
CODEX_CWD = os.environ.get('CODEX_CWD', PROJECT_ROOT)
