"""LLM 客户端：DeepSeek 调用收口（chat / 流式 / function-calling 传输）。

统一了原先散落在 translate.py / agent.py 的 4 处重复调用与那段重复的 SSE 解析。
将来加 anthropic 或换 httpx/异步，只动这一文件。
"""
import json
from .. import config
from . import http

TIMEOUT = 90


def _headers():
    return {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {config.DEEPSEEK_API_KEY}",
    }


def chat(messages, *, tools=None, max_tokens=None, temperature=0.3, timeout=TIMEOUT):
    """非流式补全。返回 message dict（含 content，可能含 tool_calls）。
    tools 为空/None 时不传，强制模型直接出文字。"""
    body = {"model": config.DEEPSEEK_MODEL, "messages": messages, "temperature": temperature}
    if max_tokens is not None:
        body["max_tokens"] = max_tokens
    if tools:
        body["tools"] = tools
    r = http.post(f"{config.DEEPSEEK_BASE}/chat/completions",
                  headers=_headers(), json=body, timeout=timeout)
    r.raise_for_status()
    return r.json()["choices"][0]["message"]


def chat_stream(messages, *, max_tokens=None, temperature=0.3, timeout=TIMEOUT):
    """流式补全：逐段 yield 文本增量（解析 SSE 的 choices[0].delta.content）。"""
    body = {"model": config.DEEPSEEK_MODEL, "messages": messages,
            "temperature": temperature, "stream": True}
    if max_tokens is not None:
        body["max_tokens"] = max_tokens
    with http.stream_post(f"{config.DEEPSEEK_BASE}/chat/completions",
                          headers=_headers(), json=body, timeout=timeout) as r:
        r.raise_for_status()
        for line in r.iter_lines(decode_unicode=True):
            if not line or not line.startswith("data:"):
                continue
            payload = line[5:].strip()
            if payload == "[DONE]":
                break
            try:
                delta = json.loads(payload)["choices"][0]["delta"].get("content")
            except (json.JSONDecodeError, KeyError, IndexError):
                continue
            if delta:
                yield delta
