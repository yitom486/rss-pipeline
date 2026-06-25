"""纯文本渲染：把 LLM 输出的 Markdown 转成 Telegram 支持的 HTML（无 I/O，可单测）。"""
import re


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
