import httpx
import pytest

from rss_pipeline import codex_agent, config, feeds, official_sources


def test_official_cards_use_titles_dates_and_canonical_links():
    rows = official_sources.parse_index('''
      <a href="/research/team/alignment">Alignment</a>
      <a href="/research/older"><h3>Older featured article</h3><time>Sep 1, 2026</time><p>Background</p></a>
      <a href="/research/new#section"><time>Oct 9, 2026</time><span class="PublicationList__title">New <em>research</em></span></a>
      <a href="/research/new#other"><time>Oct 9, 2026</time><span class="PublicationList__title">New research</span></a>
      <a href="https://fake.example/research/post"><h3>External fake</h3></a>
      <a href="javascript:alert(1)"><h3>Unsafe</h3></a>
    ''', 'https://www.anthropic.com/research')
    assert [row[0] for row in rows] == ['New research', 'Older featured article']
    assert rows[0][1] == 'https://www.anthropic.com/research/new'
    assert 'Oct 9, 2026' in rows[0][2]


def test_deepseek_papers_require_official_research_card_and_allowed_destination():
    rows = official_sources.parse_index('''
      <a href="/en/news/model/"><h2>Model release</h2><span>September 10, 2026</span><p>Native vision</p></a>
      <a class="ds-research-item" href="https://arxiv.org/abs/2606.12345"><span class="ds-research-date">June 24, 2026</span><span class="ds-research-title">Technical report</span></a>
      <a class="ds-research-item" href="https://fake.example/paper"><span class="ds-research-title">Fake paper</span></a>
      <a href="/en/news/model/">Footer duplicate</a>
    ''', 'https://www.deepseek.com/en/news/')
    assert [row[0] for row in rows] == ['Model release', 'Technical report']
    assert 'Native vision' in rows[0][2]
    assert rows[1][1] == 'https://arxiv.org/abs/2606.12345'


def test_anthropic_fetch_includes_each_section_without_xml_or_rsshub(monkeypatch):
    requests = []
    def get(url, **kwargs):
        requests.append(url)
        section = url.rsplit('/', 1)[-1]
        body = ''.join(f'<a href="/{section}/{i}"><h3>{section} {i}</h3></a>' for i in range(8))
        return httpx.Response(200, text=body, request=httpx.Request('GET', url))
    monkeypatch.setattr(official_sources.http, 'get', get)
    rows = feeds.fetch('https://www.anthropic.com/research', 12)
    assert len(rows) == 12
    assert {row[0].split()[0] for row in rows} == {'research', 'engineering', 'news'}
    assert requests == list(official_sources.INDEXES['https://www.anthropic.com/research'])


def test_index_markup_change_is_an_explicit_failure():
    with pytest.raises(ValueError, match='no article cards'):
        official_sources.parse_index('<html><a href="/research/post">Navigation</a></html>', 'https://www.anthropic.com/research')


def test_rss_publication_date_and_category_are_available_to_editor(monkeypatch):
    body = '<rss><channel><item><title>Research</title><link>https://openai.com/index/example</link><pubDate>Fri, 09 Oct 2026 00:00:00 GMT</pubDate><category>Research</category><description>Evidence</description></item></channel></rss>'
    monkeypatch.setattr(feeds.http, 'get', lambda url, **kwargs: httpx.Response(200, text=body, request=httpx.Request('GET', url)))
    row = feeds.fetch('https://openai.com/news/rss.xml', 1)[0]
    assert '09 Oct 2026' in row[2] and 'Research' in row[2] and 'Evidence' in row[2]


def test_targeted_collection_cannot_refresh_unrelated_sources(database, monkeypatch):
    binding = {'chat_id': '123', 'session_id': None, 'collector': True,
               'source_keys': {'openai', 'anthropic', 'deepseek'},
               'candidates': {}, 'read_urls': {}, 'queued': []}
    monkeypatch.setitem(codex_agent._bindings, 'target', binding)
    requests = []
    monkeypatch.setattr(feeds, 'fetch', lambda route, limit: requests.append(route) or [])
    result = codex_agent._tool('target', 'news_refresh', {'source': 'all'})
    assert {row['source'] for row in result} == {'OpenAI', 'Anthropic', 'DeepSeek'}
    assert len(requests) == 3
    assert codex_agent._tool('target', 'news_refresh', {'source': 'hackernews'}) == []


def test_targeted_collection_enforces_company_cap_before_insert(database, monkeypatch):
    binding = {'chat_id': '123', 'session_id': None, 'collector': True,
               'candidates': {}, 'read_urls': {}, 'queued': [], 'per_source_limit': 2}
    monkeypatch.setitem(codex_agent._bindings, 'target', binding)
    for i in range(3):
        url = f'https://openai.com/index/{i}'
        binding['candidates'][url] = ('OpenAI', 'Title', 'Description')
        binding['read_urls'][url] = 'Actual article'
        args = {'url': url, 'title': '标题', 'summary': '基于原文的分析'}
        if i < 2:
            codex_agent._tool('target', 'news_queue_digest', args)
        else:
            with pytest.raises(ValueError, match='Per-source'):
                codex_agent._tool('target', 'news_queue_digest', args)
    with database.conn() as c:
        assert len(database.delivery_queue(c)) == 2
