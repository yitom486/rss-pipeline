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


def test_article_images_preserve_resolved_sources_and_captions_without_chrome():
    parser = material.ArticleText('https://publisher.example/posts/news/')
    parser.feed('<nav><img src="/logo.png"></nav><img src="/sidebar.png">'
                '<main><p>' + '正文事实。' * 40 + '</p>'
                '<figure><img src="placeholder.gif" data-src="../../media/diagram.png" '
                'alt="调用关系图"><figcaption>图一：请求进入处理器。</figcaption></figure>'
                '<img src="../../media/diagram.png"><img src="pixel.gif" width="1">'
                '<img src="data:image/png;base64,abc"><img src="http://127.0.0.1/a.png">'
                '<img src="javascript:alert(1)"></main>')
    body = parser.text()
    images = json.loads(body.split('按相关性选择）：\n', 1)[1])
    assert len(images) == 1
    assert images[0]['url'] == 'https://publisher.example/media/diagram.png'
    assert images[0]['alt'] == '调用关系图'
    assert '正文事实' in images[0]['preceding_text']
    assert '图一：请求进入处理器。' in body
    assert 'logo.png' not in body
    assert 'sidebar.png' not in body


def test_image_metadata_stays_within_material_budget_and_does_not_fake_body():
    parser = material.ArticleText('https://publisher.example/news')
    parser.feed('<main><p>' + '正文' * material.MAX_TEXT + '</p>' + ''.join(
        f'<img src="https://cdn.example/{index}/' + 'x' * 1800 + '.png" alt="图示">'
        for index in range(10)) + '</main>')
    body = parser.text()
    assert len(body) <= material.MAX_TEXT
    images = json.loads(body.split('按相关性选择）：\n', 1)[1])
    assert images
    assert body.startswith('正文')
    empty = material.ArticleText('https://publisher.example/news')
    empty.feed('<img src="/cover.png">')
    assert empty.text() == ''


def test_page_image_budget_does_not_hide_later_article_images():
    parser = material.ArticleText('https://publisher.example/news')
    parser.feed(''.join(f'<img src="/decoration-{index}.png">' for index in range(30))
                + '<main><p>' + '正文事实。' * 40 + '</p><img src="/diagram.png"></main>')
    images = json.loads(parser.text().split('按相关性选择）：\n', 1)[1])
    assert [image['url'] for image in images] == ['https://publisher.example/diagram.png']


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
