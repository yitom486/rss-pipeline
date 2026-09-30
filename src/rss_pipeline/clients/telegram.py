"""Telegram controls and native rich presentation; no ordinary message fallback."""
import html
from .. import config, db
from . import native_rich, http
import httpx


def export_report(chat_id, report_id):
    report = db.report(chat_id, report_id)
    if report is None:
        raise ValueError('报告不存在')
    content = ('# ' + report['title'] + '\n\n' + report['content'] + '\n').encode('utf-8')
    try:
        response = http.post(f'https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}/sendDocument',
                             data={'chat_id': str(chat_id)},
                             files={'document': (f'news-report-{report_id}.md', content, 'text/markdown; charset=utf-8')}, timeout=45)
        data = response.json()
    except (httpx.HTTPError, ValueError):
        raise native_rich.NativeRichError('报告文件发送未确认，请检查聊天后再决定是否重试。', unconfirmed=True) from None
    if not data.get('ok'):
        raise native_rich.NativeRichError('Telegram 未接受报告文件。')
    return data['result']


def send_message(text, reply_markup=None, chat_id=None, disable_preview=True,
                 markdown=True, parse_mode=None):
    if parse_mode == "HTML":
        return native_rich.send_message(text, format="html", chat_id=chat_id, reply_markup=reply_markup)
    if not markdown:
        return native_rich.send_message("<p>" + html.escape(text).replace("\n", "<br/>") + "</p>",
                                        format="html", chat_id=chat_id, reply_markup=reply_markup)
    return native_rich.send_message(text, chat_id=chat_id, reply_markup=reply_markup)


def send_html(md_text, **kwargs):
    return native_rich.send_message(md_text, **kwargs)


def edit_message(chat_id, message_id, text, reply_markup=None, parse_mode=None):
    return native_rich._call("editMessageText", chat_id=chat_id, message_id=message_id,
                            rich_message={"markdown": text}, reply_markup=reply_markup)


def send_rich_message_draft(draft_id, markdown, chat_id=None, **kwargs):
    return native_rich.send_draft(draft_id, markdown, chat_id=chat_id, **kwargs)


def send_rich_message(markdown, chat_id=None, **kwargs):
    return native_rich.send_message(markdown, chat_id=chat_id, **kwargs)


def stream_to_message(chunks, header="", min_interval=1.1, chat_id=None, rich=None, **kwargs):
    if rich is False:
        raise ValueError("Plain streaming is disabled; use native rich messages")
    return native_rich.stream(chunks, header=header, min_interval=min_interval, chat_id=chat_id, **kwargs)


def answer_callback(callback_id, text=""):
    try:
        return native_rich._call("answerCallbackQuery", callback_query_id=callback_id, text=text)
    except native_rich.NativeRichError:
        return None


def get_updates(offset=None, timeout=20):
    return native_rich._call("getUpdates", offset=offset, timeout=timeout, _timeout=timeout+10,
                            allowed_updates=["message", "callback_query", "stopped_message_generation"])


def review_buttons(item_id, url=None):
    rows = [
        [{"text": "速读", "callback_data": f"brief:{item_id}"},
         {"text": "深入解读", "callback_data": f"detail:{item_id}"},
         {"text": "技术视角", "callback_data": f"technical:{item_id}"}],
        [{"text": "继续追问", "callback_data": f"ask:{item_id}"},
         {"text": "收藏 / 取消", "callback_data": f"save:{item_id}"}],
        [{"text": "感兴趣", "callback_data": f"more:{item_id}"},
         {"text": "暂不感兴趣", "callback_data": f"less:{item_id}"}],
    ]
    if url:
        rows.append([{"text": "查看原文", "url": url}])
    return {"inline_keyboard": rows}
