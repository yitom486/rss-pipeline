"""Hourly source collection and native-rich delivery with durable retry state."""
import fcntl
import json
from pathlib import Path
import sys
from . import config, db, codex_agent
from .clients import telegram, native_rich


def format_card(source, zh_title, zh_summary, url, task_id=None):
    # A native heading, natural paragraphs and a source link; no HTML conversion.
    title = zh_title.replace("\n", " ")
    trace = f'\n\n取材与执行记录：/trace {task_id}' if task_id else ''
    return f"# {title}\n\n{zh_summary}\n\n---\n\n来源：{source} · [阅读原文]({url})" + trace


def _deliver():
    with db.conn() as c:
        # A previous process crash after send cannot safely be retried blindly.
        c.execute("UPDATE items SET delivery_status='unknown',delivery_error='进程中断，需确认是否已送达' WHERE delivery_status='sending'")
        rows = db.delivery_queue(c)
    for item in rows:
        with db.conn() as c:
            db.set_delivery(c, item['id'], 'sending')
        try:
            msg = telegram.send_rich_message(
                format_card(item['source'], item['zh_title'], item['zh_summary'], item['url'], item['collection_task_id']),
                reply_markup=telegram.review_buttons(item['id'], item['url']))
        except native_rich.NativeRichError as exc:
            with db.conn() as c:
                db.set_delivery(c, item['id'], 'unknown' if exc.unconfirmed else 'failed', str(exc))
            print(f"推送未完成 #{item['id']}: {exc}", file=sys.stderr)
        else:
            with db.conn() as c:
                db.set_tg_message_id(c, item['id'], msg['message_id'])


def run():
    db.init()
    lock_path = Path(config.DB_PATH).with_suffix('.run.lock')
    with lock_path.open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return {'new_items': 0, 'busy': True}
        db.recover_tasks('定时资讯采集')
        _deliver()
        try:
            result = codex_agent.collect_news(config.TELEGRAM_CHAT_ID, on_queued=_deliver)
        finally:
            _deliver()
        print(json.dumps(result, ensure_ascii=False), flush=True)
        return result


def main():
    run()


if __name__ == '__main__':
    main()
