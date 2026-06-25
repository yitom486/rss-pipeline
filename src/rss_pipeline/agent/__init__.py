"""自然语言指令层（只读 + 取材）：function calling 选白名单工具 → 执行 → 回结果。

- runner: 编排（工具循环 + 跨消息上下文）
- tools:  白名单工具实现 + schema（加新工具只动这里）
"""
from .runner import handle, handle_stream, reset_history

__all__ = ["handle", "handle_stream", "reset_history"]
