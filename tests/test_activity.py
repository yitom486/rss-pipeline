import json
from unittest.mock import Mock
import pytest

from rss_pipeline import activity, codex_agent, config, pipeline
from rss_pipeline.clients import native_rich, telegram
from rss_pipeline.clients.codex import AppServer
from test_codex_protocol import Peer


def test_real_tool_events_are_routed_without_argument_or_secret_leaks():
    class ToolPeer(Peer):
        def write(self, line):
            msg = json.loads(line)
            if msg.get('method') == 'turn/start':
                self.calls.append(msg)
                self.lines.put(json.dumps({'id': msg['id'], 'result': {'turn': {'id': 'turn-1'}}}))
                self.lines.put(json.dumps({'id': 'tool-1', 'method': 'item/tool/call', 'params': {
                    'threadId': 'thread-1', 'turnId': 'turn-1', 'tool': 'news_read_url',
                    'arguments': {'url': 'https://private.example/?token=secret'}}}))
            elif msg.get('id') == 'tool-1':
                self.calls.append(msg)
                self.event('item/agentMessage/delta', {'threadId': 'thread-1', 'turnId': 'turn-1', 'delta': '结果正文'})
                self.event('turn/completed', {'threadId': 'thread-1', 'turn': {'id': 'turn-1', 'status': 'completed'}})
            else:
                super().write(line)
    peer = ToolPeer()
    api = AppServer(process=peer, tool_handler=lambda *args: {'material': 'source'})
    try:
        values = list(api.turn('thread-1', 'test', use_skill=False, emit_activity=True))
        events = [v for v in values if isinstance(v, dict)]
        assert [e['event'] for e in events] == ['turn_started', 'tool_started', 'tool_completed', 'writing']
        assert 'secret' not in json.dumps(events)
        assert ''.join(v for v in values if isinstance(v, str)) == '结果正文'
    finally:
        api.close()


def test_real_status_changes_in_draft_and_is_absent_from_final(monkeypatch):
    ticks = iter(range(100))
    monkeypatch.setattr(native_rich.time, 'monotonic', lambda: next(ticks) * 2)
    drafts, finals = [], []
    monkeypatch.setattr(native_rich, 'send_draft', lambda _, body, **kw: drafts.append(body))
    monkeypatch.setattr(native_rich, 'send_message', lambda body, **kw: finals.append(body) or
                        {'message_id': 1, 'rich_message': {'blocks': [{'type': 'paragraph'}]}})
    values = [activity.event('tool_progress', '正在获取 Hacker News'),
              activity.event('tool_completed', 'Hacker News 返回 3 条'), '正文']
    native_rich.stream(values)
    assert any('正在获取 Hacker News' in d for d in drafts)
    assert any('Hacker News 返回 3 条' in d for d in drafts)
    assert finals == ['正文']


def test_trace_owner_isolation_and_terminal_status(database):
    task = database.start_task(123, 'reading')
    database.task_event(task, activity.tool_event('news_article', True))
    database.finish_task(task, 'completed', 5)
    assert database.tasks(123)[0]['message_id'] == 5
    assert database.trace(123, task)[0]['tool'] == 'news_article'
    assert database.tasks(456) == []
    with pytest.raises(ValueError):
        database.trace(456, task)


def test_collector_queues_only_refreshed_and_read_urls_one_at_a_time(database, monkeypatch):
    binding = {'chat_id': '123', 'session_id': None, 'collector': True, 'candidates': {}, 'read_urls': {}, 'queued': []}
    monkeypatch.setitem(codex_agent._bindings, 'collector', binding)
    monkeypatch.setattr(config, 'SOURCES', [('Hacker News', '/hackernews/best', 2)])
    monkeypatch.setattr(codex_agent.feeds, 'fetch', lambda *args: [('first', 'https://example.com/1', 'intro'), ('second', 'https://example.com/2', 'intro')])
    monkeypatch.setattr(codex_agent.material, 'fetch_material', lambda url: '真实原文')
    delivered = []
    binding['on_queued'] = lambda: delivered.append(list(binding['queued']))
    def queue(url):
        return codex_agent._tool('collector', 'news_queue_digest', {'url': url, 'title': '自然中文标题', 'summary': '自然解读'})
    with pytest.raises(ValueError):
        queue('https://example.com/1')
    codex_agent._tool('collector', 'news_refresh', {})
    with pytest.raises(ValueError):
        queue('https://example.com/1')
    with pytest.raises(ValueError, match='Read a collection article'):
        codex_agent._tool('collector', 'news_read_url', {'url': 'https://docs.example/guide'})
    for url in ['https://example.com/1', 'https://example.com/2']:
        codex_agent._tool('collector', 'news_read_url', {'url': url})
        queue(url)
    assert [len(ids) for ids in delivered] == [1, 2]
    assert queue('https://example.com/1')['already_exists']
    supplement = codex_agent._tool('collector', 'news_read_url', {'url': 'https://docs.example/guide'})
    assert supplement['material'] == '真实原文'
    with pytest.raises(ValueError, match='Read a real source'):
        queue('https://docs.example/guide')
    assert [len(ids) for ids in delivered] == [1, 2]


def test_digest_length_is_not_an_editorial_tool_limit(database, monkeypatch):
    url = 'https://example.com/long-article'
    binding = {'chat_id': '123', 'session_id': None, 'collector': True,
               'candidates': {url: ('Hacker News', 'Long article', 'intro')},
               'read_urls': {url: '原文资料'}, 'queued': []}
    monkeypatch.setitem(codex_agent._bindings, 'collector', binding)
    body = '一段必要的解释。\n\n' * 1500
    assert len(body) > 10000
    result = codex_agent._tool('collector', 'news_queue_digest', {'url': url, 'title': '复杂内容', 'summary': body})
    with database.conn() as c:
        assert database.get_item(c, result['item_id'])['zh_summary'] == body


def test_pipeline_delegates_to_agent_and_delivers_each_queue_callback(database, monkeypatch, tmp_path):
    monkeypatch.setattr(config, 'DB_PATH', str(tmp_path/'lock-db'))
    delivery = Mock()
    monkeypatch.setattr(pipeline, '_deliver', delivery)
    def collect(owner, on_queued):
        on_queued()
        on_queued()
        return {'new_items': 2, 'task_id': 10}
    collect_mock = Mock(side_effect=collect)
    monkeypatch.setattr(pipeline.codex_agent, 'collect_news', collect_mock)
    assert pipeline.run()['new_items'] == 2
    assert delivery.call_count == 4  # pending, first article, second article, final reconciliation


def test_report_download_is_owned_and_preserves_utf8_markdown(database, monkeypatch):
    session = database.active_session(123)
    report = database.save_report(123, session['id'], '中文标题', '## 来源\n\n[文章](https://example.com)\n正文')
    sent = Mock(return_value=Mock(json=lambda: {'ok': True, 'result': {'message_id': 9}}))
    monkeypatch.setattr(telegram.http, 'post', sent)
    assert telegram.export_report(123, report)['message_id'] == 9
    assert '中文标题' in sent.call_args.kwargs['files']['document'][1].decode('utf-8')
    with pytest.raises(ValueError):
        telegram.export_report(456, report)
    assert sent.call_count == 1


def test_report_send_unknown_is_not_repeated_by_agent(database, monkeypatch):
    binding = {'chat_id': '123', 'session_id': 1}
    monkeypatch.setitem(codex_agent._bindings, 'export', binding)
    send = Mock(side_effect=native_rich.NativeRichError('unconfirmed', unconfirmed=True))
    monkeypatch.setattr(telegram, 'export_report', send)
    with pytest.raises(native_rich.NativeRichError):
        codex_agent._tool('export', 'news_export_report', {'report_id': 1})
    assert codex_agent._tool('export', 'news_export_report', {'report_id': 1}).get('error')
    assert send.call_count == 1


def test_bot_queue_preserves_activity_and_records_final_message(database, monkeypatch):
    from rss_pipeline import bot
    monkeypatch.setattr(native_rich, 'send_draft', Mock())
    monkeypatch.setattr(native_rich, 'send_message', lambda *args, **kwargs:
                        {'message_id': 42, 'rich_message': {'blocks': [{'type': 'paragraph'}]}})
    event = activity.tool_event('news_article', True)
    job = bot.Job('123')
    bot._run(job, lambda stop: iter([event, '完整正文']), None)
    assert database.tasks(123)[0]['status'] == 'completed'
    assert database.tasks(123)[0]['message_id'] == 42
    assert database.trace(123, job.task_id)[0]['tool'] == 'news_article'


def test_restart_marks_only_its_own_task_kind_unknown(database):
    a = database.start_task(123, '资讯对话')
    b = database.start_task(123, '定时资讯采集')
    database.recover_tasks('资讯对话')
    rows = {r['id']: r for r in database.tasks(123)}
    assert rows[a]['status'] == 'unknown'
    assert rows[b]['status'] == 'running'


def test_collector_connection_failure_is_visible_in_trace(database, monkeypatch):
    monkeypatch.setattr(codex_agent, 'server', Mock(side_effect=RuntimeError('connection failed')))
    with pytest.raises(RuntimeError):
        codex_agent.collect_news('123')
    task = database.tasks(123)[0]
    assert task['status'] == 'failed'
    assert database.trace(123, task['id'])[-1]['status'] == 'failed'


def test_media_input_is_not_silently_treated_as_a_text_question(database, monkeypatch):
    from rss_pipeline import bot
    send = Mock()
    reply = Mock()
    monkeypatch.setattr(bot.telegram, 'send_message', send)
    monkeypatch.setattr(bot, '_start_reply', reply)
    bot.handle_message({'chat': {'id': 123}, 'photo': [{'file_id': 'fixture'}], 'caption': '看一下截图'})
    assert '还没有接入' in send.call_args.args[0]
    assert not reply.called


def test_parallel_deliveries_do_not_send_one_article_twice(database, article, monkeypatch):
    import threading
    from concurrent.futures import ThreadPoolExecutor
    entered, release = threading.Event(), threading.Event()
    calls = []
    def send(*args, **kwargs):
        calls.append(True)
        entered.set()
        assert release.wait(3)
        return {'message_id': 11}
    monkeypatch.setattr(pipeline.telegram, 'send_rich_message', send)
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(pipeline._deliver)
        assert entered.wait(3)
        second = pool.submit(pipeline._deliver)
        release.set()
        first.result()
        second.result()
    assert len(calls) == 1
