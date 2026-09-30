import pytest
from rss_pipeline import bot, codex_agent


def test_session_switch_preserves_thread_model_and_article(database, article):
    first = database.active_session(123)
    database.bind_thread(123, first['id'], 'thread-one')
    database.set_model(123, first['id'], 'model-one')
    database.set_current(123, article)
    second = database.new_session(123, '另一个话题')
    assert database.current(123) is None
    database.switch_session(123, first['id'])
    resumed = database.active_session(123)
    assert resumed['thread_id'] == 'thread-one'
    assert resumed['model'] == 'model-one'
    assert database.current(123)['id'] == article
    assert second['id'] != first['id']


def test_user_cannot_switch_or_read_other_users_session_report(database):
    session = database.new_session(123, '私人会话')
    report_id = database.save_report(123, session['id'], '报告', '事实与来源')
    with pytest.raises(ValueError):
        database.switch_session(456, session['id'])
    with pytest.raises(ValueError):
        database.bind_thread(456, session['id'], 'foreign')
    assert database.report(456, report_id) is None


def test_preferences_survive_new_session_and_can_be_deleted(database):
    database.set_preference(123, '阅读方式', '先解释机制')
    database.new_session(123, '新话题')
    database.init()  # simulate restart/migration
    assert database.preferences(123) == {'阅读方式': '先解释机制'}
    assert database.preferences(456) == {}
    database.set_preference(123, '阅读方式', '')
    assert database.preferences(123) == {}


def test_model_selection_changes_model_without_replacing_thread(database, monkeypatch):
    session = database.active_session(123)
    database.bind_thread(123, session['id'], 'keep-me')
    monkeypatch.setattr(codex_agent, 'models', lambda: [{'id': 'model-2', 'model': 'model-2'}])
    assert codex_agent.choose_model(123, 'model-2') == 'model-2'
    assert database.active_session(123)['thread_id'] == 'keep-me'
    with pytest.raises(ValueError):
        codex_agent.choose_model(123, 'invented-model')


def test_tool_arguments_cannot_supply_a_different_owner(database):
    session = database.active_session(123)
    codex_agent._bindings['owned'] = {'chat_id': '123', 'session_id': session['id'], 'reports': []}
    try:
        with pytest.raises(ValueError):
            codex_agent._tool('owned', 'news_remember_preference', {'key': 'test', 'value': 'yes', 'chat_id': 456})
        codex_agent._tool('owned', 'news_remember_preference', {'key': 'test', 'value': 'yes'})
        assert database.preferences(123)['test'] == 'yes'
        assert database.preferences(456) == {}
    finally:
        codex_agent._bindings.pop('owned', None)


def test_stop_events_are_owned_and_match_active_draft(monkeypatch):
    monkeypatch.setattr(bot.config, 'TELEGRAM_CHAT_ID', '123')
    assert not bot.authorized({'stopped_message_generation': {'chat': {'id': 456}, 'draft_id': 8}})
    assert bot.authorized({'stopped_message_generation': {'chat': {'id': 123}, 'draft_id': 8}})
    job = bot.Job('123', draft_id=8)
    monkeypatch.setattr(bot, '_jobs', {'123': job})
    assert not bot.stop_job(123, 9)
    assert not job.stop.is_set()
    assert bot.stop_job(123, 8)
    assert job.stop.is_set()


def test_refresh_reports_source_failure_without_inventing_results(database, monkeypatch):
    session = database.active_session(123)
    codex_agent._bindings['refresh-owned'] = {'chat_id': '123', 'session_id': session['id'], 'reports': []}
    monkeypatch.setattr(codex_agent.config, 'SOURCES', [('GitHub Trending', '/github', 3)])
    monkeypatch.setattr(codex_agent.feeds, 'fetch', lambda *args: (_ for _ in ()).throw(RuntimeError('503')))
    try:
        result = codex_agent._tool('refresh-owned', 'news_refresh', {})
        assert result[0]['source'] == 'GitHub Trending'
        assert 'error' in result[0]
        assert 'items' not in result[0]
    finally:
        codex_agent._bindings.pop('refresh-owned', None)
