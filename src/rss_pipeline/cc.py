"""Claude Code headless 调用（/cc 路径，A 档：限工具 + 限目录）。
每条 /cc 消息 = 一次性 `claude -p`，跑完即退，符合「单元式」。"""
import subprocess

CLAUDE_BIN = "/root/.local/bin/claude"
WORKSPACE = "/root/agent-workspace"
TIMEOUT = 600  # 秒

# A 档白名单：可读写工作区文件、搜索、联网取信息、跑命令。
# 注意：含 Bash（以便真正干活），但 cwd 限定在 WORKSPACE。
# 想更严可改 disallowedTools，或升 B 档（非 root 用户隔离）。
ALLOWED_TOOLS = ["Read", "Write", "Edit", "Grep", "Glob", "WebFetch", "WebSearch", "Bash"]


def run(task):
    """跑一次 Claude Code，返回最终文本。"""
    cmd = [
        CLAUDE_BIN, "-p", task,
        "--allowedTools", *ALLOWED_TOOLS,
        "--add-dir", WORKSPACE,
        "--permission-mode", "default",
    ]
    try:
        r = subprocess.run(
            cmd, cwd=WORKSPACE, capture_output=True, text=True, timeout=TIMEOUT,
        )
    except subprocess.TimeoutExpired:
        return f"⏱ 任务超时（>{TIMEOUT}s），已中止。"
    out = (r.stdout or "").strip()
    err = (r.stderr or "").strip()
    if r.returncode != 0 and not out:
        return f"❌ 执行失败：{err[:500] or '未知错误'}"
    return out or "（无输出）"
