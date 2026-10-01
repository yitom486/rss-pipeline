"""读取 RSSHub 路由或公开 RSS / Atom，统一返回文章链接与简介。"""
import re
import html
import xml.etree.ElementTree as ET
from urllib.parse import urljoin, urlsplit, urlunsplit
from . import config
from .clients import http

TIMEOUT = 30
ATOM = '{http://www.w3.org/2005/Atom}'


def _strip_html(s):
    return re.sub(r"<[^>]+>", "", html.unescape(s or "")).strip()


def _text(element):
    return _strip_html(''.join(element.itertext())) if element is not None else ''


def _article_url(base, value):
    if not value or not value.strip():
        return ''
    parsed = urlsplit(urljoin(base, value.strip()))
    if parsed.scheme not in ('http', 'https') or not parsed.netloc:
        return ''
    # Fragments select sections of the same article and must not cause duplicates.
    return urlunsplit(parsed._replace(fragment=''))


def fetch(route, limit):
    """返回 [(title, url, desc), ...]"""
    url = route if route.startswith(('https://', 'http://')) else f"{config.RSSHUB_BASE}{route}"
    r = http.get(url, timeout=TIMEOUT)
    r.raise_for_status()
    root = ET.fromstring(r.content)
    if root.tag == f'{ATOM}feed':
        items = root.findall(f'{ATOM}entry')
    elif root.tag == 'rss':
        items = root.findall('./channel/item')
    else:
        raise ValueError('Unsupported feed format')
    out = []
    seen = set()
    for it in items:
        if root.tag == f'{ATOM}feed':
            title = _text(it.find(f'{ATOM}title'))
            link = next((link for link in it.findall(f'{ATOM}link')
                         if link.get('rel', 'alternate') == 'alternate'
                         and link.get('type', 'text/html') in ('text/html', 'application/xhtml+xml')
                         and link.get('href')), None)
            article_url = _article_url(url, link.get('href') if link is not None else '')
            desc = _text(it.find(f'{ATOM}summary')) or _text(it.find(f'{ATOM}content'))
        else:
            title = _text(it.find('title'))
            article_url = _article_url(url, it.findtext('link'))
            desc = _text(it.find('description'))
        if title and article_url and article_url not in seen:
            out.append((title, article_url, desc))
            seen.add(article_url)
            if len(out) >= limit:
                break
    return out
