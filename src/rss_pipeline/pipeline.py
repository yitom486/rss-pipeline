"""采集流水线（cron 定时跑）：拉源 → 去重 → DeepSeek 翻译摘要 → 存库 → 推 Telegram 待审。

入口：`rss-pipeline`（见 pyproject [project.scripts]）→ main()。
"""
import sys
import traceback
from . import config, db, feeds, translate
from .clients import telegram


def format_card(source, zh_title, zh_summary, url):
    return (
        f"📰 *{telegram_escape(zh_title)}*\n"
        f"_{source}_\n\n"
        f"{telegram_escape(zh_summary)}\n\n"
        f"[原文链接]({url})"
    )


def telegram_escape(s):
    # Markdown(v1) 下只需避免标题里的下划线/星号破坏格式
    return (s or "").replace("*", "").replace("_", "")


def run():
    db.init()
    new_count = 0
    with db.conn() as c:
        for source, route, limit in config.SOURCES:
            try:
                rows = feeds.fetch(route, limit)
            except Exception as e:
                print(f"[警告] 拉取 {source} 失败: {e}", file=sys.stderr)
                continue
            for title, url, desc in rows:
                if db.url_exists(c, url):
                    continue
                try:
                    zh_title, zh_summary = translate.translate_summarize(title, desc)
                except Exception as e:
                    print(f"[警告] 翻译失败 {url}: {e}", file=sys.stderr)
                    continue
                item_id = db.insert_item(c, source, title, url, desc, zh_title, zh_summary)
                c.commit()
                # 推送待审卡片
                try:
                    msg = telegram.send_message(
                        format_card(source, zh_title, zh_summary, url),
                        reply_markup=telegram.review_buttons(item_id),
                    )
                    db.set_tg_message_id(c, item_id, msg["message_id"])
                    c.commit()
                except Exception as e:
                    print(f"[警告] 推送失败 item {item_id}: {e}", file=sys.stderr)
                new_count += 1
    print(f"完成，新增 {new_count} 条待审。")


def main():
    try:
        run()
    except Exception:
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
