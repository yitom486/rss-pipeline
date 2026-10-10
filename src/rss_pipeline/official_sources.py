"""Read official publication indexes without a third-party feed dependency."""
from html.parser import HTMLParser
from datetime import datetime
import re
from urllib.parse import urljoin, urlsplit, urlunsplit

from .clients import http

INDEXES = {
    'https://www.anthropic.com/research': (
        'https://www.anthropic.com/research',
        'https://www.anthropic.com/engineering',
        'https://www.anthropic.com/news',
    ),
    'https://www.deepseek.com/en/news/': ('https://www.deepseek.com/en/news/',),
}
VOID_TAGS = {'img', 'br', 'hr', 'meta', 'link', 'input', 'source', 'wbr', 'area', 'base', 'embed', 'param', 'track', 'col'}


class PublicationIndex(HTMLParser):
    """Only take article cards with explicit title markup, excluding navigation."""
    def __init__(self, base):
        super().__init__()
        self.base = base
        self.anchor = None
        self.stack = []
        self.rows = {}

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'a':
            self.anchor = {'href': attrs.get('href', ''), 'class': attrs.get('class', ''),
                           'title': [], 'text': [], 'date': []}
            self.stack = []
        if self.anchor is not None and tag not in VOID_TAGS:
            classes = attrs.get('class', '')
            role = 'title' if tag in ('h2', 'h3') or '__title' in classes or 'ds-research-title' in classes else None
            if tag == 'time' or 'ds-research-date' in classes:
                role = 'date'
            self.stack.append((tag, role))

    def handle_data(self, data):
        if self.anchor is None:
            return
        if any(tag in ('script', 'style') for tag, _ in self.stack):
            return
        self.anchor['text'].append(data)
        role = next((role for _, role in reversed(self.stack) if role), None)
        if role:
            self.anchor[role].append(data)

    def handle_endtag(self, tag):
        if self.anchor is None:
            return
        if tag == 'a':
            self._finish()
            self.anchor = None
            self.stack = []
        else:
            for i in range(len(self.stack) - 1, -1, -1):
                if self.stack[i][0] == tag:
                    del self.stack[i:]
                    break

    def _finish(self):
        title = ' '.join(''.join(self.anchor['title']).split())
        parsed = urlsplit(urljoin(self.base, self.anchor['href']))
        origin = urlsplit(self.base)
        internal = parsed.netloc == origin.netloc and (
            parsed.path.startswith(('/news/', '/research/', '/engineering/', '/en/news/'))
            and '/team/' not in parsed.path
            and parsed.path.rstrip('/') != origin.path.rstrip('/')
        )
        # External papers are accepted only from DeepSeek's official research list.
        research = origin.hostname == 'www.deepseek.com' and 'ds-research-item' in self.anchor['class'].split() and (
            parsed.hostname == 'arxiv.org' and parsed.path.startswith('/abs/')
            or parsed.hostname == 'github.com' and parsed.path.startswith('/deepseek-ai/')
        )
        if not title or parsed.scheme not in ('http', 'https') or not (internal or research):
            return
        url = urlunsplit(parsed._replace(fragment=''))
        desc = ' '.join(' '.join(self.anchor['text']).split())
        row = (title, url, f'官方索引：{self.base}\n{desc}')
        if url not in self.rows or len(row[2]) > len(self.rows[url][2]):
            self.rows[url] = row


def parse_index(text, url):
    parser = PublicationIndex(url)
    parser.feed(text)
    rows = list(parser.rows.values())
    if not rows:
        raise ValueError('Official publication index contains no article cards')
    # Featured cards can precede newer list entries. Keep undated featured cards
    # visible, but sort all dated publications by their actual publication date.
    def date(row):
        match = re.search(r'\b([A-Z][a-z]+ \d{1,2}, \d{4})\b', row[2])
        if match:
            for fmt in ('%b %d, %Y', '%B %d, %Y'):
                try:
                    return datetime.strptime(match[1], fmt)
                except ValueError:
                    pass
        return datetime.max
    return sorted(rows, key=date, reverse=True)


def fetch(route, limit):
    indexes = INDEXES[route]
    # Preserve space for each Anthropic section rather than filling with news alone.
    per_index = max(1, limit // len(indexes))
    rows, seen = [], set()
    for url in indexes:
        response = http.get(url, timeout=30)
        response.raise_for_status()
        for row in parse_index(response.text, url)[:per_index]:
            if row[1] not in seen:
                rows.append(row)
                seen.add(row[1])
    return rows[:limit]
