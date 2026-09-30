"""Real Codex collection tools with isolated fixture sources; never send messages."""
import json
from pathlib import Path
import tempfile

from rss_pipeline import codex_agent, config, db, feeds, material, prompts


def main():
    with tempfile.TemporaryDirectory(prefix='news-collector-probe-') as folder:
        db.DB_PATH = str(Path(folder) / 'probe.db')
        db.init()
        config.SOURCES = [('Hacker News', '/hackernews/best', 2), ('GitHub Trending', '/github/trending/daily/any', 1)]
        def fetch(route, limit):
            if 'github' in route:
                raise RuntimeError('fixture source failure')
            return [('虚构演练项目 Alpha', 'https://example.com/alpha', '用于测试的虚构 RSS 阅读器。'),
                    ('虚构演练项目 Beta', 'https://example.com/beta', '用于测试的虚构备份工具。')]
        feeds.fetch = fetch
        material.fetch_material = lambda url: ('这是虚构流程演练资料，没有真实新闻结论。Alpha 在本机读取 RSS 并用 SQLite 保存文章；'
                                                'Beta 使用 SQLite backup API 保存副本。未提供性能测试、许可证或维护情况。')
        prompts.COLLECTOR = ('这是隔离工具链演练。两个条目明确为虚构资料，只在临时数据库中处理；'
                             '回调只记录顺序，不向 Telegram 发消息。请处理两篇，摘要保留虚构说明。\n' + prompts.COLLECTOR)
        delivered = []
        def on_queued():
            with db.conn() as c:
                delivered.append([r['id'] for r in db.delivery_queue(c)])
        try:
            result = codex_agent.collect_news('isolated-collector-probe', on_queued=on_queued)
            events = db.trace('isolated-collector-probe', result['task_id'])
            assert result['new_items'] == 2
            assert [len(items) for items in delivered] == [1, 2]
            assert any('GitHub Trending 获取失败' in e['message'] for e in events)
            print(json.dumps({'passed': True, 'queued_articles': result['new_items'],
                              'per_article_callbacks': delivered,
                              'tools': [e['tool'] for e in events if e['event'] == 'tool_started']}, ensure_ascii=False))
        finally:
            if codex_agent._server:
                codex_agent._server.close()


if __name__ == '__main__':
    main()
