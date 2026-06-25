"""agent 编排：function calling 工具循环 + 跨消息上下文（内存态，按 chat_id）。"""
import json
from ..clients import llm
from . import tools

SYSTEM = (
    "你是 RSS 资讯流水线的助手，通过 Telegram 和用户中文对话。"
    "你有一组工具用于操作流水线（查库、搜索、统计、触发采集、深入了解）。"
    "判断原则：涉及本地条目/库数据/采集操作时调用工具，不要编造库里的数据；"
    "若是通用知识或闲聊问题（与本地库无关），直接用简洁中文回答，无需调用任何工具。"
)

# --- 跨消息上下文（内存态，按 chat_id；保留最近 N 轮 user+assistant）---
MAX_TURNS = 10
_HISTORY = {}


def _remember(chat_id, user_text, assistant_text):
    if not chat_id or not assistant_text.strip():
        return
    h = _HISTORY.setdefault(chat_id, [])
    h.append({"role": "user", "content": user_text})
    h.append({"role": "assistant", "content": assistant_text})
    del h[: -2 * MAX_TURNS]  # 仅保留最近 MAX_TURNS 轮


def reset_history(chat_id):
    """清空某会话的上下文。"""
    _HISTORY.pop(chat_id, None)


def _run_tool_calls(tool_calls, messages):
    """执行一批 tool_calls，把结果回填进 messages。"""
    for tc in tool_calls:
        name = tc["function"]["name"]
        try:
            args = json.loads(tc["function"]["arguments"] or "{}")
        except json.JSONDecodeError:
            args = {}
        fn = tools.TOOLS_IMPL.get(name)
        try:
            result = fn(**args) if fn else f"未知工具 {name}"
        except Exception as e:
            result = f"工具 {name} 执行出错: {e}"
        messages.append({"role": "tool", "tool_call_id": tc["id"], "content": str(result)})


def handle_stream(user_text, chat_id=None, max_steps=4):
    """流式版：带最近若干轮上下文，先用（非流式）工具循环解析数据，最终回答流式 yield。"""
    history = _HISTORY.get(chat_id, []) if chat_id else []
    messages = [
        {"role": "system", "content": SYSTEM},
        *history,
        {"role": "user", "content": user_text},
    ]
    for _ in range(max_steps):
        msg = llm.chat(messages, tools=tools.TOOLS_SCHEMA, temperature=0.2)
        tool_calls = msg.get("tool_calls")
        if not tool_calls:
            break  # 到达最终回答阶段
        messages.append(msg)
        _run_tool_calls(tool_calls, messages)
    # 最终回答：流式（不带工具）逐段吐字，并记入上下文（只存 user + 最终文字）
    collected = []
    for delta in llm.chat_stream(messages, temperature=0.2):
        collected.append(delta)
        yield delta
    _remember(chat_id, user_text, "".join(collected))


def handle(user_text, max_steps=4):
    """处理一条自然语言指令，返回要发回用户的文本。"""
    messages = [
        {"role": "system", "content": SYSTEM},
        {"role": "user", "content": user_text},
    ]
    for _ in range(max_steps):
        msg = llm.chat(messages, tools=tools.TOOLS_SCHEMA, temperature=0.2)
        tool_calls = msg.get("tool_calls")
        if not tool_calls:
            return msg.get("content") or "（无回复）"
        messages.append(msg)  # 带 tool_calls 的 assistant 消息
        _run_tool_calls(tool_calls, messages)
    # 步数用尽：不带工具再问一次，强制基于已有上下文给出文字答案
    try:
        final = llm.chat(messages, tools=None, temperature=0.2)
        return final.get("content") or "（无回复）"
    except Exception:
        return "处理步骤过多，已中止。请把指令说得更具体些。"
