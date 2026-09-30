"""Source-grounded editorial generation; prompts live in prompts.py."""
import json
from . import config, prompts
from .clients import llm


def _check_provider():
    if config.TRANSLATE_PROVIDER not in ("deepseek", "codex"):
        raise ValueError(f"尚未配置模型后端: {config.TRANSLATE_PROVIDER}")


def _chat(system, user, max_tokens=4000):
    _check_provider()
    msg = llm.chat([{"role": "system", "content": system}, {"role": "user", "content": user}],
                   max_tokens=max_tokens, temperature=0.4)
    return (msg.get("content") or "").strip()


def translate_summarize(title, desc, material=""):
    if config.TRANSLATE_PROVIDER == "codex":
        from .codex_agent import structured_summary
        return structured_summary(title, desc, material, prompts.SUMMARY)
    payload = json.dumps({"title": title, "rss_description": desc[:4000],
                          "source_material": material[:18000] or "未取得全文，仅有 RSS 简介"}, ensure_ascii=False)
    raw = _chat(prompts.SUMMARY, payload)
    raw = raw.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        raise ValueError("模型未返回有效摘要 JSON；该条目将等待下次采集重试") from None
    if not isinstance(data, dict) or not isinstance(data.get("title"), str) or not isinstance(data.get("summary"), str):
        raise ValueError("摘要必须包含字符串 title 和 summary")
    if not data['title'].strip() or not data['summary'].strip():
        raise ValueError("模型摘要为空")
    return data['title'].strip(), data['summary'].strip()


def _messages(title, url, material, mode):
    if mode not in prompts.MODES:
        raise ValueError("未知阅读模式")
    return [{"role": "system", "content": prompts.EDITOR + "\n" + prompts.MODES[mode]},
            {"role": "user", "content": json.dumps({"title": title, "source_url": url,
             "source_material": material[:18000]}, ensure_ascii=False)}]


def deep_dive(title, url, material, mode="detail"):
    _check_provider()
    if config.TRANSLATE_PROVIDER == "codex":
        return ''.join(deep_dive_stream(title, url, material, mode=mode))
    msg = llm.chat(_messages(title, url, material, mode), max_tokens=5000, temperature=0.4)
    return (msg.get('content') or '').strip()


def deep_dive_stream(title, url, material, max_tokens=5000, mode="detail", cancel_event=None):
    _check_provider()
    if config.TRANSLATE_PROVIDER == "codex":
        from .codex_agent import server
        api = server()
        thread_id = api.create_thread(ephemeral=True)['thread']['id']
        messages = _messages(title, url, material, mode)
        text = messages[0]['content'] + '\n\n待分析资料：\n' + messages[1]['content']
        yield from api.turn(thread_id, text, cancel_event=cancel_event, use_skill=False)
        return
    yield from llm.chat_stream(_messages(title, url, material, mode), max_tokens=max_tokens, temperature=0.4, cancel_event=cancel_event)
