import httpx
import pytest

from rss_pipeline import codex_agent, config, feeds


def feed_response(monkeypatch, body, requests):
    def get(url, **kwargs):
        requests.append(url)
        return httpx.Response(200, content=body.encode(), request=httpx.Request('GET', url))
    monkeypatch.setattr(feeds.http, 'get', get)


def test_rss_direct_url_skips_invalid_rows_and_deduplicates_sections(monkeypatch):
    requests = []
    feed_response(monkeypatch, '''<rss version="2.0"><channel>
      <item><title>Missing link</title></item>
      <item><title>First &amp; useful</title><link>https://example.com/post#one</link>
        <description>&lt;p&gt;Original content&lt;/p&gt;</description></item>
      <item><title>Same article</title><link>https://example.com/post#two</link></item>
      <item><title>Unsafe link</title><link>javascript:alert(1)</link></item>
      <item><title>Second</title><link>/second</link></item>
      <item><title>Third</title><link>/third</link></item>
    </channel></rss>''', requests)
    assert feeds.fetch('https://example.com/feed', 2) == [
        ('First & useful', 'https://example.com/post', 'Original content'),
        ('Second', 'https://example.com/second', ''),
    ]
    assert requests == ['https://example.com/feed']


def test_atom_chooses_article_link_and_handles_html_and_xhtml(monkeypatch):
    requests = []
    feed_response(monkeypatch, '''<feed xmlns="http://www.w3.org/2005/Atom">
      <entry><title type="html">AI &amp; tools</title>
        <link rel="self" type="application/atom+xml" href="/entry.atom"/>
        <link rel="alternate" type="text/html" href="/post"/>
        <summary type="html">&lt;p&gt;Real experiment&lt;/p&gt;</summary></entry>
      <entry><title>Second</title><link href="https://other.example/post"/>
        <content type="xhtml"><div xmlns="http://www.w3.org/1999/xhtml"><p>Full text</p></div></content></entry>
      <entry><title>Only self link</title><link rel="self" href="/entry.atom"/></entry>
    </feed>''', requests)
    assert feeds.fetch('https://example.com/atom/', 6) == [
        ('AI & tools', 'https://example.com/post', 'Real experiment'),
        ('Second', 'https://other.example/post', 'Full text'),
    ]


def test_rsshub_routes_still_use_local_base(monkeypatch):
    requests = []
    monkeypatch.setattr(config, 'RSSHUB_BASE', 'http://rsshub.example')
    feed_response(monkeypatch, '<rss><channel/></rss>', requests)
    assert feeds.fetch('/hackernews/best', 6) == []
    assert requests == ['http://rsshub.example/hackernews/best']


def test_unrecognized_xml_is_reported_as_failure(monkeypatch):
    feed_response(monkeypatch, '<html><body>Unavailable</body></html>', [])
    with pytest.raises(ValueError, match='Unsupported feed'):
        feeds.fetch('https://example.com/feed', 6)


@pytest.mark.parametrize('selected,expected', [
    ('lobsters', 'Lobsters'), ('simonwillison', 'Simon Willison'), ('infoq', 'InfoQ'),
    ('openai', 'OpenAI'), ('anthropic', 'Anthropic'), ('deepseek', 'DeepSeek'),
])
def test_new_sources_can_be_refreshed_individually(monkeypatch, selected, expected):
    monkeypatch.setitem(codex_agent._bindings, 'reader', {'chat_id': '123', 'session_id': 1})
    requests = []
    monkeypatch.setattr(feeds, 'fetch', lambda route, limit: requests.append(route) or [])
    result = codex_agent._tool('reader', 'news_refresh', {'source': selected})
    assert [r['source'] for r in result] == [expected]
    assert len(requests) == 1


def test_collector_deduplicates_across_sources_and_continues_after_failure(database, monkeypatch):
    binding = {'chat_id': '123', 'session_id': None, 'collector': True,
               'candidates': {}, 'read_urls': {}, 'queued': []}
    monkeypatch.setitem(codex_agent._bindings, 'collector', binding)
    monkeypatch.setattr(config, 'SOURCES', [
        ('Hacker News', '/hackernews/best', 6), ('Lobsters', 'https://lobste.rs/rss', 6),
        ('InfoQ', 'https://www.infoq.com/feed/', 6),
        ('Simon Willison', 'https://simonwillison.net/atom/everything/', 6),
    ])
    with database.conn() as c:
        database.insert_item(c, 'Hacker News', 'Old', 'https://example.com/old', '', '', '')
    def fetch(route, limit):
        if 'infoq' in route:
            raise httpx.ConnectError('source unavailable')
        if 'hackernews' in route:
            return [('Shared', 'https://example.com/shared', 'HN'), ('Old', 'https://example.com/old', '')]
        if 'lobste.rs' in route:
            return [('Shared again', 'https://example.com/shared', 'Lobsters')]
        return [('New', 'https://example.com/new', 'Simon')]
    monkeypatch.setattr(feeds, 'fetch', fetch)
    result = codex_agent._tool('collector', 'news_refresh', {'source': 'all'})
    assert [len(r.get('items', [])) for r in result] == [1, 0, 0, 1]
    assert 'error' in result[2]
    assert binding['candidates'] == {
        'https://example.com/shared': ('Hacker News', 'Shared', 'HN'),
        'https://example.com/new': ('Simon Willison', 'New', 'Simon'),
    }


def test_collection_budget_is_six_articles_across_all_sources(database, monkeypatch):
    binding = {'chat_id': '123', 'session_id': None, 'collector': True,
               'candidates': {}, 'read_urls': {}, 'queued': []}
    monkeypatch.setitem(codex_agent._bindings, 'collector', binding)
    for i in range(7):
        url = f'https://example.com/{i}'
        binding['candidates'][url] = (['Lobsters', 'Simon Willison', 'InfoQ'][i % 3], 'Title', 'Intro')
        binding['read_urls'][url] = 'Actual article'
        args = {'url': url, 'title': '标题', 'summary': '有来源的解读'}
        if i < 6:
            assert codex_agent._tool('collector', 'news_queue_digest', args)['queued']
        else:
            with pytest.raises(ValueError, match='Collection budget reached'):
                codex_agent._tool('collector', 'news_queue_digest', args)
    with database.conn() as c:
        assert len(database.delivery_queue(c)) == 6
