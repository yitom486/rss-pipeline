import json
import pytest

from rss_pipeline import config, codex_agent, diagrams
from rss_pipeline.clients import native_rich


def test_foreign_diagram_is_not_attached_or_queued(database, monkeypatch):
    monkeypatch.setattr(diagrams, 'render', lambda document: b'png-test')
    binding = {'chat_id': '123', 'session_id': 1}
    result = diagrams.save(binding, '流程', 'HTML')
    with pytest.raises(ValueError, match='this user'):
        diagrams.attachments(result['markdown'], chat_id='456')
    with pytest.raises(ValueError, match='this task'):
        diagrams.attachments(result['markdown'], chat_id='123', allowed=[])


def test_native_media_upload_keeps_picture_in_same_message_and_retries(database, monkeypatch):
    monkeypatch.setattr(diagrams, 'render', lambda document: b'png-test')
    result = diagrams.save({'chat_id': '123'}, '请求流程', 'HTML')
    calls = []
    monkeypatch.setattr(config, 'TELEGRAM_BOT_TOKEN', 'test-secret')
    monkeypatch.setattr(native_rich.time, 'sleep', lambda seconds: None)

    def post(url, **kwargs):
        calls.append((url.rsplit('/', 1)[1], kwargs))
        class Response:
            status_code = 200
            def json(self):
                if len(calls) == 1:
                    return {'ok': False, 'error_code': 429, 'parameters': {'retry_after': 1}}
                return {'ok': True, 'result': {'message_id': 1, 'rich_message': {'blocks': []}}}
        return Response()

    monkeypatch.setattr(native_rich.http, 'post', post)
    native_rich.send_message(result['markdown'], chat_id='123')
    assert [method for method, _ in calls] == ['sendRichMessage', 'sendRichMessage']
    assert calls[0] == calls[1]
    payload = json.loads(calls[-1][1]['data']['rich_message'])
    assert payload['markdown'] == result['markdown']
    assert payload['media'][0]['id'] == result['asset_id']
    assert payload['media'][0]['media']['media'] == 'attach://' + result['asset_id']
    assert calls[-1][1]['files'][result['asset_id']][1] == b'png-test'


@pytest.mark.parametrize('document', [
    '<svg viewBox="0 0 600 400"><script>alert(1)</script></svg>',
    '<svg viewBox="0 0 600 400" onload="alert(1)"></svg>',
    '<svg viewBox="0 0 10000 10000"></svg>',
    '<!DOCTYPE svg><svg/>',
])
def test_invalid_diagram_is_rejected_before_browser_launch(document):
    with pytest.raises(ValueError):
        diagrams.render(document)


def test_drawing_requires_guide_and_source_evidence(database, monkeypatch):
    binding = {'chat_id': '123', 'session_id': None, 'collector': True}
    monkeypatch.setitem(codex_agent._bindings, 'drawing', binding)
    args = {'title': '流程', 'html': 'HTML'}
    with pytest.raises(ValueError, match='guidance'):
        codex_agent._tool('drawing', 'news_draw_diagram', args)
    binding['diagram_guide_read'] = True
    with pytest.raises(ValueError, match='evidence'):
        codex_agent._tool('drawing', 'news_draw_diagram', args)


def test_default_style_is_not_silently_selected(monkeypatch):
    monkeypatch.setattr(config, 'DIAGRAM_STYLE', '')
    assert diagrams.guide('flowchart')['ready'] is False
