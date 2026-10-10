"""Inspect official company sources; send selected news only with --send."""
import argparse
import fcntl
import json
from pathlib import Path

from rss_pipeline import codex_agent, config, db, feeds, pipeline

COMPANIES = ('openai', 'anthropic', 'deepseek')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--send', action='store_true', help='Run the real editor and deliver up to two articles per company')
    args = parser.parse_args()
    if not args.send:
        for name, route, limit in config.SOURCES:
            if config.SOURCE_KEYS.get(name) in COMPANIES:
                rows = feeds.fetch(route, limit)
                print(json.dumps({'source': name, 'articles': [{'title': t, 'url': u, 'description': d} for t, u, d in rows]}, ensure_ascii=False), flush=True)
        return
    db.init()
    with Path(config.DB_PATH).with_suffix('.run.lock').open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise SystemExit('Collection already running; no additional messages sent')
        try:
            result = codex_agent.collect_news(config.TELEGRAM_CHAT_ID, source_keys=COMPANIES,
                                              per_source_limit=2, on_queued=pipeline._deliver)
            with db.conn() as c:
                rows = c.execute('SELECT id,source,zh_title,url,delivery_status,tg_message_id FROM items WHERE collection_task_id=? ORDER BY id', (result['task_id'],)).fetchall()
            result['articles'] = [dict(row) for row in rows]
            print(json.dumps(result, ensure_ascii=False), flush=True)
        finally:
            if codex_agent._server:
                codex_agent._server.close()


if __name__ == '__main__':
    main()
