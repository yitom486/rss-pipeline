"""白名单工具实现 + schema。

安全：只暴露下面这组只读 / 取材工具，绝不开放裸 bash / 任意写。
加新工具 = 在此写实现并登记到 TOOLS_IMPL / TOOLS_SCHEMA，无需改 runner。
"""
import json
from .. import db, feeds, material, translate, pipeline


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
