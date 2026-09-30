from unittest.mock import Mock
import pytest

from rss_pipeline import bot
from rss_pipeline.clients import native_rich


def test_read_button_reuses_current_session_and_does_not_edit_rendered_message(database, article, monkeypatch):
    session = database.active_session(123)
    database.bind_thread(123, session['id'], 'persistent-thread')
    start = Mock(return_value=True)
    monkeypatch.setattr(bot, '_start_reply', start)
    monkeypatch.setattr(bot.telegram, 'answer_callback', Mock())
    monkeypatch.setattr(bot.telegram, 'edit_message', Mock(side_effect=AssertionError('must not rewrite rich text')))
    monkeypatch.setattr(bot, '_jobs', {})
    bot.handle_callback({'id': 'callback', 'data': f'detail:{article}', 'message': {'chat': {'id': 123}, 'message_id': 1}})
    assert database.active_session(123)['thread_id'] == 'persistent-thread'
    assert database.current(123)['id'] == article
    assert '深入解读' in start.call_args.args[1]


def test_generating_session_cannot_be_switched(database, monkeypatch):
    first = database.active_session(123)
    second = database.new_session(123, '另一个')
    database.switch_session(123, first['id'])
    monkeypatch.setattr(bot, '_jobs', {'123': bot.Job('123')})
    with pytest.raises(ValueError):
        bot._switch(123, second['id'])
    assert database.active_session(123)['id'] == first['id']


def test_saved_report_pages_preserve_every_character_and_escape_html(database, monkeypatch):
    session = database.active_session(123)
    content = '<script>source text</script>\n' + '资料。'*5000
    report_id = database.save_report(123, session['id'], '标题', content)
    sent = []
    monkeypatch.setattr(bot.native_rich, 'send_message', lambda body, **kwargs: sent.append((body, kwargs)))
    pages = (len(content)+5999)//6000
    for page in range(pages):
        bot._report_page(123, report_id, page)
    import html
    restored = ''.join(html.unescape(body.split('<p>', 1)[1].split('</p>', 1)[0].replace('<br/>', '\n')) for body,_ in sent)
    assert restored == content
    assert all(kwargs['format'] == 'html' for _,kwargs in sent)
    assert all('<script>' not in body for body,_ in sent)


def test_native_stop_persists_partial_answer_without_plain_fallback(monkeypatch):
    import threading
    stop = threading.Event()
    calls = []
    monkeypatch.setattr(native_rich, 'send_draft', lambda draft, text, **kwargs: calls.append(('draft', text, kwargs)))
    monkeypatch.setattr(native_rich, 'send_message', lambda text, **kwargs: calls.append(('final', text, kwargs)) or
                        {'message_id': 12, 'rich_message': {'blocks': [{'type': 'paragraph'}]}})

    def deltas():
        yield '已生成内容'
        stop.set()
        yield '不应发送的内容'

    native_rich.stream(deltas(), stop_event=stop)
    final = next(text for kind,text,_ in calls if kind == 'final')
    assert '已生成内容' in final
    assert '不应发送的内容' not in final
    assert '已停止生成' in final
    assert calls[0][2]['can_stop'] is True
