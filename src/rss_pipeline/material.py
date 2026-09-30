"""为「深入了解」抓取素材：GitHub 项目抓 README+元信息；其他网页抓正文。"""
import re
import html
import ipaddress
import socket
from urllib.parse import urljoin
from urllib.parse import urlsplit
from html.parser import HTMLParser
from .clients import http

TIMEOUT = (8, 15)
MAX_TEXT = 18000
MAX_BYTES = 1500000
UA = {"User-Agent": "Mozilla/5.0 (rss-pipeline deep-dive)"}

GH_RE = re.compile(r"github\.com/([^/]+)/([^/?#]+)")


def _strip_html(s):
    s = re.sub(r"(?is)<(script|style).*?</\1>", " ", s)
    s = re.sub(r"<[^>]+>", " ", s)
    s = html.unescape(s)
    return re.sub(r"\s+", " ", s).strip()


def _public_url(url):
    parsed = urlsplit(url)
    if parsed.scheme not in ('http', 'https') or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError('Only public HTTP/HTTPS sources are supported')
    host = parsed.hostname.lower()
    if host == 'localhost' or host.endswith(('.local', '.internal')):
        raise ValueError('Not a public source')
    try:
        addresses = [ipaddress.ip_address(host)]
    except ValueError:
        addresses = [ipaddress.ip_address(row[4][0]) for row in socket.getaddrinfo(host, parsed.port or 443, type=socket.SOCK_STREAM)]
    if not addresses or any(not address.is_global for address in addresses):
        raise ValueError('Not a public source')
    return parsed


def fetch_material(url):
    """Fetch public source material; failures are explicit data, not invented content."""
    try:
        parsed = _public_url(url)
    except (ValueError, OSError):
        return '（资料不可用：来源必须是可访问的公开 HTTP/HTTPS 网站）'
    m = GH_RE.fullmatch(parsed.hostname + parsed.path)
    if m:
        return _github_material(m.group(1), m.group(2))
    return _web_material(url)


def _github_material(owner, repo):
    repo = repo.removesuffix(".git")
    parts = []
    try:
        meta = http.get(f"https://api.github.com/repos/{owner}/{repo}",
                        headers=UA, timeout=TIMEOUT)
        meta.raise_for_status()
        meta = meta.json()
        if isinstance(meta, dict):
            parts.append(f"描述: {meta.get('description') or '无'}")
            parts.append(f"语言: {meta.get('language') or '未知'}  Stars: {meta.get('stargazers_count', '?')}")
            if meta.get("topics"):
                parts.append("标签: " + ", ".join(meta["topics"]))
    except Exception:
        pass
    try:
        readme = http.get(
            f"https://api.github.com/repos/{owner}/{repo}/readme",
            headers={**UA, "Accept": "application/vnd.github.raw"},
            timeout=TIMEOUT,
        )
        if readme.status_code == 200:
            parts.append("\nREADME:\n" + readme.text[:MAX_TEXT])
    except Exception:
        pass
    return "\n".join(parts) if parts else "（未能抓到项目资料）"


class ArticleText(HTMLParser):
    """Prefer article/main content; preserve paragraph breaks, exclude chrome."""
    def __init__(self):
        super().__init__()
        self.parts = []
        self.article = []
        self.skip = 0
        self.depth = 0

    def handle_starttag(self, tag, attrs):
        if tag in ('script', 'style', 'nav', 'header', 'footer', 'noscript'):
            self.skip += 1
        if tag in ('article', 'main'):
            self.depth += 1
        if tag in ('p', 'br', 'div', 'h1', 'h2', 'h3', 'li'):
            self.handle_data('\n')

    def handle_endtag(self, tag):
        if tag in ('script', 'style', 'nav', 'header', 'footer', 'noscript') and self.skip:
            self.skip -= 1
        if tag in ('article', 'main') and self.depth:
            self.depth -= 1
        if tag in ('p', 'div', 'li'):
            self.handle_data('\n')

    def handle_data(self, data):
        if not self.skip:
            self.parts.append(data)
            if self.depth:
                self.article.append(data)

    def text(self):
        parts = self.article if len(''.join(self.article).strip()) >= 100 else self.parts
        return re.sub(r'\n\s*\n+', '\n\n', ''.join(parts)).strip()[:MAX_TEXT]


def _web_material(url):
    try:
        # Check each redirect before following it; never fetch a local redirect target.
        for _ in range(6):
            _public_url(url)
            with http.get(url, headers=UA, timeout=TIMEOUT, stream=True, follow_redirects=False) as r:
                if r.is_redirect:
                    location = r.headers.get('location')
                    if not location:
                        break
                    url = urljoin(url, location)
                    continue
                r.raise_for_status()
                data = bytearray()
                for chunk in r.iter_bytes(16384):
                    data.extend(chunk)
                    if len(data) >= MAX_BYTES:
                        break
                text = bytes(data[:MAX_BYTES]).decode(r.encoding or 'utf-8', errors='replace')
                parser = ArticleText()
                parser.feed(text)
                return parser.text() or '（未能取得正文）'
    except Exception:
        pass
    return '（未能取得原文正文；不能视为已阅读全文）'


def for_item(item, refresh=False):
    from . import db
    import time
    if not refresh and item['material'] and time.time() - item['material_updated_at'] < 86400:
        return item['material']
    text = fetch_material(item['url'])
    if text.startswith('（'):
        return text + '\nRSS 简介：\n' + (item['orig_desc'] or '')[:4000]
    with db.conn() as c:
        db.save_material(c, item['id'], text)
    return text
