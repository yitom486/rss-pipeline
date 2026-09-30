import json
import pytest
from rss_pipeline import material, translate


def test_article_extraction_omits_navigation_and_preserves_paragraphs():
    parser = material.ArticleText()
    parser.feed('<nav>irrelevant</nav><main><p>' + '正文事实。'*40 + '</p><p>第二段说明。</p></main><script>fake</script>')
    body = parser.text()
    assert 'irrelevant' not in body
    assert 'fake' not in body
    assert '第二段说明。' in body
    assert '\n' in body


def test_invalid_model_json_does_not_become_a_fake_summary(monkeypatch):
    monkeypatch.setattr(translate.config, 'TRANSLATE_PROVIDER', 'deepseek')
    monkeypatch.setattr(translate, '_chat', lambda *args: 'not JSON')
    with pytest.raises(ValueError):
        translate.translate_summarize('title', 'preview')


def test_raw_source_is_sent_to_model_as_data(monkeypatch):
    monkeypatch.setattr(translate.config, 'TRANSLATE_PROVIDER', 'deepseek')
    seen = []

    def chat(system, payload):
        seen.append(json.loads(payload))
        return json.dumps({'title': '标题', 'summary': '第一段。\n\n第二段。'}, ensure_ascii=False)

    monkeypatch.setattr(translate, '_chat', chat)
    title, summary = translate.translate_summarize('Original', 'preview', '原文材料')
    assert seen[0]['source_material'] == '原文材料'
    assert '\n\n' in summary


def test_local_source_is_rejected_before_http_request(monkeypatch):
    monkeypatch.setattr(material.http, 'get', lambda *args, **kwargs: pytest.fail('must not access local host'))
    assert '资料不可用' in material.fetch_material('http://127.0.0.1/secrets')
    assert '资料不可用' in material.fetch_material('file:///root/.env')


def test_private_redirect_is_not_followed(monkeypatch):
    import httpx
    from contextlib import contextmanager
    requests = []
    original = material._public_url

    def public(url):
        if url.startswith('https://public.example/'):
            from urllib.parse import urlsplit
            return urlsplit(url)
        return original(url)

    @contextmanager
    def get(url, **kwargs):
        requests.append(url)
        yield httpx.Response(302, headers={'location': 'http://127.0.0.1/secrets'}, request=httpx.Request('GET', url))

    monkeypatch.setattr(material, '_public_url', public)
    monkeypatch.setattr(material.http, 'get', get)
    assert '未能取得原文' in material.fetch_material('https://public.example/article')
    assert requests == ['https://public.example/article']
