"""Read-only runtime handshake plus optional isolated model/memory validation."""
import argparse
import json
from pathlib import Path
import tempfile

from rss_pipeline import config, db, codex_agent
from rss_pipeline.clients.codex import CodexError


def emit(**fields):
    print(json.dumps(fields, ensure_ascii=False), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--inference', action='store_true', help='Run synthetic turns using saved Codex authentication')
    parser.add_argument('--summary', action='store_true', help='Validate source-grounded JSON summary with synthetic material')
    args = parser.parse_args()
    try:
        api = codex_agent.server()
        account = api.request('account/read', {'refreshToken': False})
        emit(event='account', auth_type=(account.get('account') or {}).get('type'),
             requires_auth=account.get('requiresOpenaiAuth'))
        models = codex_agent.models()
        emit(event='models', count=len(models), default=next((r['model'] for r in models if r.get('isDefault')), None))
        started = api.create_thread(codex_agent.TOOLS, ephemeral=True)
        sources = started.get('instructionSources', [])
        emit(event='instructions', paths=sources, project_agents_loaded=any(str(p).endswith('/rss-native-preview/AGENTS.md') for p in sources))
        if args.summary:
            from rss_pipeline import prompts
            title, summary = codex_agent.structured_summary(
                '演示项目：Local Reader', '一份用于测试的虚构项目简介。',
                '这是虚构测试资料，不是真实新闻。Local Reader 在用户本机读取 RSS，将条目存入 SQLite；'
                '用户可以按来源查询历史条目。资料未提供性能、许可证、部署步骤或安全性结论。', prompts.SUMMARY)
            emit(event='structured_summary', title=title, summary=summary)
            if not title or not summary:
                raise CodexError('结构化摘要为空')
        if args.inference:
            with tempfile.TemporaryDirectory(prefix='news-codex-e2e-') as folder:
                db.DB_PATH = str(Path(folder) / 'isolated.db')
                db.init()
                chat = 'e2e-isolated-owner'
                first = ''.join(codex_agent.reply('这是隔离测试。记住本会话的代号是“蓝鲸731”。请只回复“收到蓝鲸731”。', chat))
                session = db.active_session(chat)
                emit(event='first_turn', thread_id=session['thread_id'], answer=first)
                api.close()
                codex_agent._server = None
                second = ''.join(codex_agent.reply('刚才本会话的代号是什么？只回复代号。', chat))
                emit(event='resumed_turn', same_thread=db.active_session(chat)['thread_id'] == session['thread_id'], answer=second)
                if '蓝鲸731' not in second:
                    raise CodexError('同一 thread 恢复后未通过上下文测试')
                preference = ''.join(codex_agent.reply('测试：请调用 news_remember_preference 保存 key="e2e阅读方式"、value="先解释原理"，然后简短确认。', chat))
                emit(event='preference_tool', stored=db.preferences(chat), answer=preference)
                if db.preferences(chat).get('e2e阅读方式') != '先解释原理':
                    raise CodexError('偏好工具未写入隔离数据库')
                report = ''.join(codex_agent.reply('测试：调用 news_save_report，title="隔离测试报告"，content="这是一份验证持久化的测试报告，没有真实新闻结论。"，然后简短确认。', chat))
                emit(event='report_tool', report_count=len(db.list_reports(chat)), answer=report)
                if len(db.list_reports(chat)) != 1:
                    raise CodexError('报告工具未通过持久化测试')
                db.new_session(chat, '另一个测试会话')
                fresh = ''.join(codex_agent.reply('只根据本轮应用上下文，回复我保存的 e2e阅读方式 是什么。', chat))
                emit(event='new_session', different_thread=db.active_session(chat)['thread_id'] != session['thread_id'], answer=fresh)
                if '先解释原理' not in fresh:
                    raise CodexError('新会话未正确加载长期偏好')
                db.switch_session(chat, session['id'])
                emit(event='switch_back', same_thread=db.active_session(chat)['thread_id'] == session['thread_id'])
        emit(event='passed', inference=args.inference or args.summary)
        return 0
    except (CodexError, OSError) as exc:
        emit(event='failed', reason=str(exc))
        return 1
    finally:
        if codex_agent._server is not None:
            codex_agent._server.close()


if __name__ == '__main__':
    raise SystemExit(main())
