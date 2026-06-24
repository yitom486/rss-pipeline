"""自然语言指令层（只读 + 取材）。
你发文字 → DeepSeek function calling 选白名单工具 → 执行 → 回结果。
安全：只暴露下面这组工具，绝不开放裸 bash / 任意写。"""
import json
import requests
import config
import db
import feeds
import material
import translate
import pipeline

TIMEOUT = 90

SYSTEM = (
    "你是 RSS 资讯流水线的助手，通过 Telegram 和用户中文对话。"
    "你有一组工具用于操作流水线（查库、搜索、统计、触发采集、深入了解）。"
    "判断原则：涉及本地条目/库数据/采集操作时调用工具，不要编造库里的数据；"
    "若是通用知识或闲聊问题（与本地库无关），直接用简洁中文回答，无需调用任何工具。"
)

# --- 白名单工具实现 ---

def _t_run_pipeline():
    pipeline.run()  # 采集→翻译→推送（推送本身会发到 Telegram）
    with db.conn() as c:
        s = db.stats(c)
    return f"采集完成。当前统计：{s}"


def _t_list_pending(limit=10):
    with db.conn() as c:
        rows = db.list_by_status(c, "pending", limit)
    if not rows:
        return "没有待审条目。"
    return "\n".join(f"#{r['id']} [{r['source']}] {r['zh_title']}" for r in rows)


def _t_search(keyword, limit=10):
    with db.conn() as c:
        rows = db.search(c, keyword, limit)
    if not rows:
        return f"没找到与「{keyword}」相关的条目。"
    return "\n".join(f"#{r['id']} [{r['status']}] {r['zh_title']} ({r['url']})" for r in rows)


def _t_stats():
    with db.conn() as c:
        return json.dumps(db.stats(c), ensure_ascii=False)


def _t_trending_by_lang(language="", limit=8):
    """实时拉取 GitHub 当日趋势（可按语言筛选），不依赖本地库。"""
    lang = (language or "").strip().lower()
    route = f"/github/trending/daily/{lang}" if lang else "/github/trending/daily/any"
    try:
        rows = feeds.fetch(route, limit)
    except Exception as e:
        return f"拉取趋势失败（语言={lang or 'any'}）：{e}"
    if not rows:
        return f"GitHub 当日 {lang or '全部'} 趋势暂时没有结果。"
    label = f"{language} " if lang else ""
    return f"GitHub 当日 {label}热门项目：\n" + "\n".join(
        f"- {t}（{u}）" for t, u, _ in rows
    )


def _t_deep_dive(item_id=None, url=None):
    title, link = None, url
    if item_id is not None:
        with db.conn() as c:
            it = db.get_item(c, int(item_id))
        if not it:
            return f"条目 #{item_id} 不存在。"
        title, link = it["title"], it["url"]
    if not link:
        return "需要提供 item_id 或 url。"
    mat = material.fetch_material(link)
    return translate.deep_dive(title or link, link, mat)


TOOLS_IMPL = {
    "run_pipeline": _t_run_pipeline,
    "list_pending": _t_list_pending,
    "search": _t_search,
    "stats": _t_stats,
    "trending_by_lang": _t_trending_by_lang,
    "deep_dive": _t_deep_dive,
}

TOOLS_SCHEMA = [
    {"type": "function", "function": {
        "name": "run_pipeline", "description": "立即触发一次采集：拉取RSSHub→翻译摘要→推送待审到Telegram",
        "parameters": {"type": "object", "properties": {}}}},
    {"type": "function", "function": {
        "name": "list_pending", "description": "列出待审核(pending)的条目",
        "parameters": {"type": "object", "properties": {"limit": {"type": "integer", "description": "最多几条,默认10"}}}}},
    {"type": "function", "function": {
        "name": "search", "description": "在已采集的库里按关键词搜索条目",
        "parameters": {"type": "object", "properties": {"keyword": {"type": "string"}, "limit": {"type": "integer"}}, "required": ["keyword"]}}},
    {"type": "function", "function": {
        "name": "stats", "description": "返回各状态(pending/published/discarded)的数量统计",
        "parameters": {"type": "object", "properties": {}}}},
    {"type": "function", "function": {
        "name": "trending_by_lang", "description": "实时查询GitHub当日趋势热门项目，可按编程语言筛选(如rust/python/go/typescript)。用户想看某语言/某主题的最新热点项目时用这个，不依赖本地库",
        "parameters": {"type": "object", "properties": {"language": {"type": "string", "description": "编程语言,如 rust。留空则查全部语言"}, "limit": {"type": "integer", "description": "返回条数,默认8"}}}}},
    {"type": "function", "function": {
        "name": "deep_dive", "description": "对某个项目/链接深入了解：抓README或正文并生成中文汇总。可传库里的item_id或直接传url",
        "parameters": {"type": "object", "properties": {"item_id": {"type": "integer"}, "url": {"type": "string"}}}}},
]


def _deepseek(messages, tools):
    body = {"model": config.DEEPSEEK_MODEL, "messages": messages, "temperature": 0.2}
    if tools:  # 不传或传 None 时省略，强制模型直接出文字
        body["tools"] = tools
    r = requests.post(
        f"{config.DEEPSEEK_BASE}/chat/completions",
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {config.DEEPSEEK_API_KEY}"},
        json=body,
        timeout=TIMEOUT,
    )
    r.raise_for_status()
    return r.json()["choices"][0]["message"]


def handle(user_text, max_steps=4):
    """处理一条自然语言指令，返回要发回用户的文本。"""
    messages = [
        {"role": "system", "content": SYSTEM},
        {"role": "user", "content": user_text},
    ]
    for _ in range(max_steps):
        msg = _deepseek(messages, TOOLS_SCHEMA)
        tool_calls = msg.get("tool_calls")
        if not tool_calls:
            return msg.get("content") or "（无回复）"
        messages.append(msg)  # 带 tool_calls 的 assistant 消息
        for tc in tool_calls:
            name = tc["function"]["name"]
            try:
                args = json.loads(tc["function"]["arguments"] or "{}")
            except json.JSONDecodeError:
                args = {}
            fn = TOOLS_IMPL.get(name)
            try:
                result = fn(**args) if fn else f"未知工具 {name}"
            except Exception as e:
                result = f"工具 {name} 执行出错: {e}"
            messages.append({"role": "tool", "tool_call_id": tc["id"], "content": str(result)})
    # 步数用尽：不带工具再问一次，强制基于已有上下文给出文字答案
    try:
        final = _deepseek(messages, tools=None)
        return final.get("content") or "（无回复）"
    except Exception:
        return "处理步骤过多，已中止。请把指令说得更具体些。"
