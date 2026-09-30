"""Explicit live E2E: real source tools -> bot queue -> native activity drafts."""
import argparse
import json

from rss_pipeline import bot, codex_agent, config, db


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--send', action='store_true', help='Send one real native-stream reading example to the configured Telegram chat')
    args = parser.parse_args()
    if not args.send:
        parser.error('Live Telegram delivery requires --send')
    db.init()
    api = codex_agent.server()
    thread_id = None
    try:
        account = api.request('account/read', {'refreshToken': False})
        if (account.get('account') or {}).get('type') != 'chatgpt':
            raise RuntimeError('Expected ChatGPT authentication')
        tools = [s for s in codex_agent.TOOLS if s['name'] in ('news_refresh', 'news_read_url')]
        thread_id = api.create_thread(tools, ephemeral=True)['thread']['id']
        session = db.active_session(config.TELEGRAM_CHAT_ID)
        codex_agent._bindings[thread_id] = {'chat_id': str(config.TELEGRAM_CHAT_ID), 'session_id': session['id']}
        prompt = ('这是执行状态与逐篇阅读的真实验收。调用 news_refresh，source=hackernews。'
                  '从实际结果中选择一篇资讯，调用 news_read_url 读取来源。只讲这一篇，约 250—400 字，'
                  '解释发生了什么、机制或影响、资料限制，附真实来源链接，不能编造全文。'
                  '若来源获取失败就如实说明，不能捏造新闻。不要保存报告或偏好。')
        job = bot.Job(str(config.TELEGRAM_CHAT_ID))
        bot._run(job, lambda stop: api.turn(thread_id, prompt, cancel_event=stop, emit_activity=True), None)
        record = next(r for r in db.tasks(config.TELEGRAM_CHAT_ID) if r['id'] == job.task_id)
        events = db.trace(config.TELEGRAM_CHAT_ID, job.task_id)
        print(json.dumps({'task_id': job.task_id, 'status': record['status'], 'message_id': record['message_id'],
                          'events': [{'event': e['event'], 'message': e['message']} for e in events]}, ensure_ascii=False))
        assert record['status'] == 'completed' and record['message_id']
        assert any(e['tool'] == 'news_refresh' and e['event'] == 'tool_started' for e in events)
        return 0
    finally:
        if thread_id:
            codex_agent._bindings.pop(thread_id, None)
        api.close()


if __name__ == '__main__':
    raise SystemExit(main())
