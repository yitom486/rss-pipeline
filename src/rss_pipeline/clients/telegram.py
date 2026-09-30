"""Telegram Bot API 薄封装（原生 HTTP，无第三方 SDK）。

原生富文本与流式预览使用 Bot API 10.3 协议，见 native_rich。
"""
import time
import random
from .. import config
from . import http
from ..rendering import md_to_tg_html

API = f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}"
TIMEOUT = 30


def _call(method, **params):
    timeout = params.pop("_timeout", TIMEOUT)
    # 剔除值为 None 的参数：Telegram 对「不传」正常，对传 null（如 parse_mode=null）会 400
    params = {k: v for k, v in params.items() if v is not None}
    r = http.post(f"{API}/{method}", json=params, timeout=timeout)
    data = r.json()
    if not data.get("ok"):
        raise RuntimeError(f"Telegram {method} 失败 [{r.status_code}]: {data.get('description')}")
    return data["result"]


def send_message(text, reply_markup=None, chat_id=None, disable_preview=True,
                 markdown=True, parse_mode=None):
    # parse_mode 显式传入时优先；否则按 markdown 开关用旧版 Markdown
    pm = parse_mode if parse_mode is not None else ("Markdown" if markdown else None)
    return _call(
        "sendMessage",
        chat_id=chat_id or config.TELEGRAM_CHAT_ID,
        text=text,
        parse_mode=pm,
        disable_web_page_preview=disable_preview,
        reply_markup=reply_markup,
    )


def send_html(md_text, **kwargs):
    """把 Markdown 文本转成 Telegram HTML 后发送（加粗/标题/代码块可正常渲染）。"""
    kwargs.pop("markdown", None)
    return send_message(md_to_tg_html(md_text), parse_mode="HTML", **kwargs)


def edit_message(chat_id, message_id, text, reply_markup=None, parse_mode="Markdown"):
    return _call(
        "editMessageText",
        chat_id=chat_id,
        message_id=message_id,
        text=text,
        parse_mode=parse_mode,
        disable_web_page_preview=True,
        reply_markup=reply_markup,
    )


def send_message_draft(draft_id, text, chat_id=None, parse_mode=None):
    """纯文本流式草稿（Bot API 9.5）：同一 draft_id 持续推入，客户端平滑打字。"""
    return _call(
        "sendMessageDraft",
        chat_id=chat_id or config.TELEGRAM_CHAT_ID,
        draft_id=draft_id, text=text, parse_mode=parse_mode,
    )


def send_rich_message_draft(draft_id, markdown, chat_id=None, **kwargs):
    from . import native_rich
    return native_rich.send_draft(draft_id, markdown, chat_id=chat_id, **kwargs)


def send_rich_message(markdown, chat_id=None, **kwargs):
    from . import native_rich
    return native_rich.send_message(markdown, chat_id=chat_id, **kwargs)


def stream_to_message(chunks, header="", min_interval=1.1, chat_id=None, rich=None):
    """Native rich drafts and native final only. Errors remain visible."""
    if rich is False:
        raise ValueError("Plain streaming is disabled; use native rich messages")
    from . import native_rich
    return native_rich.stream(chunks, header=header, min_interval=min_interval, chat_id=chat_id)


def answer_callback(callback_id, text=""):
    # 过期 callback（机器人重启后积压）会 400，属正常，吞掉不影响主动作
    try:
        return _call("answerCallbackQuery", callback_query_id=callback_id, text=text)
    except Exception:
        return None


def get_updates(offset=None, timeout=50):
    # 长轮询：HTTP 超时要比 telegram timeout 稍长
    return _call("getUpdates", offset=offset, timeout=timeout, _timeout=timeout + 10)


def review_buttons(item_id):
    """审核按钮：通过发布 / 丢弃 / 深入了解。"""
    return {
        "inline_keyboard": [[
            {"text": "✅ 通过发布", "callback_data": f"approve:{item_id}"},
            {"text": "❌ 丢弃", "callback_data": f"discard:{item_id}"},
            {"text": "🔍 深入了解", "callback_data": f"dive:{item_id}"},
        ]]
    }
