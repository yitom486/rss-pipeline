"""从 RSSHub 拉取并解析 RSS。"""
import re
import html
import xml.etree.ElementTree as ET
import requests
import config

TIMEOUT = 30


def _strip_html(s):
    return re.sub(r"<[^>]+>", "", html.unescape(s or "")).strip()


def fetch(route, limit):
    """返回 [(title, url, desc), ...]"""
    r = requests.get(f"{config.RSSHUB_BASE}{route}", timeout=TIMEOUT)
    r.raise_for_status()
    root = ET.fromstring(r.content)
    items = root.findall(".//item")[:limit]
    out = []
    for it in items:
        title = _strip_html(it.findtext("title"))
        url = (it.findtext("link") or "").strip()
        desc = _strip_html(it.findtext("description"))
        if title and url:
            out.append((title, url, desc))
    return out
