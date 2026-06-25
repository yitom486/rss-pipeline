"""共享配置：读取 .env、常量定义。"""
import os

# 本文件位于 src/rss_pipeline/；项目根（存放 .env / rss.db）在其上两级。
PACKAGE_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(os.path.dirname(PACKAGE_DIR))
ENV_PATH = os.path.join(PROJECT_ROOT, ".env")
DB_PATH = os.path.join(PROJECT_ROOT, "rss.db")


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
# provider: deepseek | (将来可加 anthropic)
TRANSLATE_PROVIDER = os.environ.get("TRANSLATE_PROVIDER", "deepseek")
DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY", "")
DEEPSEEK_MODEL = os.environ.get("DEEPSEEK_MODEL", "deepseek-chat")
DEEPSEEK_BASE = "https://api.deepseek.com"

# --- 流式渲染方式 ---
# False(默认): 成熟方案——纯文本草稿(Bot API 9.5)流式 + HTML 定稿，全端(含手机)兼容
# True: 原生富文本(Bot API 10.1)流式 + rich 定稿，渲染更精致但需新版客户端，移动端支持尚不稳
RICH_STREAMING = os.environ.get("RICH_STREAMING", "").lower() in ("1", "true", "yes")

# --- RSSHub 数据源（本地直连，不走 Caddy）---
RSSHUB_BASE = os.environ.get("RSSHUB_BASE", "http://127.0.0.1:1200")
# 要采集的源：(名称, 路由路径, 每次取条数)
SOURCES = [
    ("GitHub Trending", "/github/trending/daily/any", 8),
    ("Hacker News", "/hackernews/best", 6),
]
