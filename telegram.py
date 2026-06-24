"""Telegram Bot API 薄封装（原生 HTTP，无第三方 SDK）。"""
import re
import requests
import config


def md_to_tg_html(text):
    """把标准 Markdown（LLM 输出）转成 Telegram 支持的 HTML。
    Telegram HTML 只认 <b><i><u><s><code><pre><a>，不支持标题/列表标签，
    所以标题降级为 <b>，列表项降级为 • 项目符号。"""
    if not text:
        return ""
    holds = []

    def _hold(html):
        holds.append(html)
        return f"\x00{len(holds) - 1}\x00"

    def _esc(s):
        return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    # 1) 先抽出代码，避免里面的字符被后续规则误伤
    text = re.sub(r"```[^\n]*\n?(.*?)```",
                  lambda m: _hold(f"<pre>{_esc(m.group(1).rstrip())}</pre>"),
                  text, flags=re.S)
    text = re.sub(r"`([^`\n]+)`",
                  lambda m: _hold(f"<code>{_esc(m.group(1))}</code>"), text)

    # 2) 转义正文里的 HTML 特殊字符
    text = _esc(text)

    # 3) 逐行处理标题 / 列表
    lines = []
    for ln in text.split("\n"):
        h = re.match(r"\s*#{1,6}\s+(.*)", ln)
        if h:
            lines.append(f"<b>{h.group(1).strip()}</b>")
            continue
        b = re.match(r"\s*[-*+]\s+(.*)", ln)
        if b:
            lines.append(f"• {b.group(1)}")
            continue
        lines.append(ln)
    text = "\n".join(lines)

    # 4) 内联：链接 → 加粗 → 斜体
    text = re.sub(r"\[([^\]]+)\]\((https?://[^\s)]+)\)", r'<a href="\2">\1</a>', text)
    text = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", text)
    text = re.sub(r"__(.+?)__", r"<b>\1</b>", text)
    text = re.sub(r"(?<!\w)[*_]([^*_\n]+)[*_](?!\w)", r"<i>\1</i>", text)

    # 5) 还原代码占位
    for i, html in enumerate(holds):
        text = text.replace(f"\x00{i}\x00", html)
    return text

API = f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}"
TIMEOUT = 30


def _call(method, **params):
    timeout = params.pop("_timeout", TIMEOUT)
    # 剔除值为 None 的参数：Telegram 对「不传」正常，对传 null（如 parse_mode=null）会 400
    params = {k: v for k, v in params.items() if v is not None}
    r = requests.post(f"{API}/{method}", json=params, timeout=timeout)
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


def send_rich_message_draft(draft_id, markdown, chat_id=None):
    """富文本流式草稿（Bot API 10.1）：rich_message.markdown 服务端原生渲染，
    且容忍流式中途未闭合的代码块/表格，不会 400。"""
    return _call(
        "sendRichMessageDraft",
        chat_id=chat_id or config.TELEGRAM_CHAT_ID,
        draft_id=draft_id, rich_message={"markdown": markdown},
    )


def send_rich_message(markdown, chat_id=None):
    """发送原生富文本消息（Bot API 10.1）：标题/表格/代码块由服务端渲染。"""
    return _call(
        "sendRichMessage",
        chat_id=chat_id or config.TELEGRAM_CHAT_ID,
        rich_message={"markdown": markdown},
    )


def stream_to_message(chunks, header="", min_interval=0.4, chat_id=None):
    """原生富文本流式：sendRichMessageDraft 高频推草稿（无闪烁、原生渲染、容忍半截 markdown），
    结束后 sendRichMessage 定稿落地。富文本不可用时逐级降级到纯文本草稿 / HTML。
    chunks 产出增量 Markdown，返回完整文本。"""
    import time, random
    chat_id = chat_id or config.TELEGRAM_CHAT_ID
    draft_id = random.getrandbits(31) or 1  # 非零唯一 ID
    buf = []
    last_push = 0.0
    mode = "rich"  # rich -> plain（草稿降级）

    def _push():
        nonlocal last_push, mode
        body = "".join(buf)
        if not body:
            return
        md = header + body
        try:
            if mode == "rich":
                send_rich_message_draft(draft_id, md, chat_id=chat_id)
            else:
                send_message_draft(draft_id, md, chat_id=chat_id)  # 纯文本，免半截标签报错
        except RuntimeError:
            if mode == "rich":   # 富文本草稿不支持 → 降级纯文本草稿
                mode = "plain"
        last_push = time.time()

    for ch in chunks:
        buf.append(ch)
        if time.time() - last_push >= min_interval:
            _push()

    # 定稿：优先原生富文本，失败再退 HTML
    final = "".join(buf)
    md = header + final
    try:
        send_rich_message(md, chat_id=chat_id)
    except RuntimeError:
        send_message(md_to_tg_html(md), parse_mode="HTML", chat_id=chat_id)
    return final


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
