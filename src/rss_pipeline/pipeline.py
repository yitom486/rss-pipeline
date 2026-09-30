"""Hourly source collection and native-rich delivery with durable retry state."""
import fcntl
import json
from pathlib import Path
import sys
from . import config, db, feeds, translate, material
from .clients import telegram, native_rich


def format_card(source, zh_title, zh_summary, url):
    # A native heading, natural paragraphs and a source link; no HTML conversion.
    title = zh_title.replace("\n", " ")
    return f"# {title}\n\n{zh_summary}\n\n---\n\n来源：{source} · [阅读原文]({url})"


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
                format_card(item['source'], item['zh_title'], item['zh_summary'], item['url']),
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
        _deliver()
        new_count = 0
        for source, route, limit in config.SOURCES:
            try:
                rows = feeds.fetch(route, limit)
            except Exception:
                print(f"拉取 {source} 失败，将在下一次采集重试", file=sys.stderr)
                continue
            for title, url, desc in rows:
                with db.conn() as c:
                    if db.url_exists(c, url):
                        continue
                source_text = material.fetch_material(url)
                try:
                    zh_title, zh_summary = translate.translate_summarize(title, desc, source_text)
                except Exception:
                    print(f"总结失败：{title[:100]}；等待重试", file=sys.stderr)
                    continue
                with db.conn() as c:
                    item_id = db.insert_item(c, source, title, url, desc, zh_title, zh_summary)
                    if not source_text.startswith('（'):
                        db.save_material(c, item_id, source_text)
                new_count += 1
        _deliver()
        result = {'new_items': new_count}
        print(json.dumps(result, ensure_ascii=False), flush=True)
        return result


def main():
    run()


if __name__ == '__main__':
    main()
