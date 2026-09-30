"""Public execution events; never expose raw reasoning or tool arguments."""
import re

LABELS = {
    'news_refresh': '获取最新资讯', 'news_search': '查询已采集资讯',
    'news_article': '读取文章原文', 'news_read_url': '读取公开资料',
    'news_preferences': '读取阅读偏好', 'news_remember_preference': '保存阅读偏好',
    'news_save_report': '保存详细报告', 'news_get_report': '读取历史报告',
    'news_rich_layout': '准备阅读操作', 'news_queue_digest': '保存这篇资讯的解读',
    'news_export_report': '生成可下载报告',
}


def public_text(value, limit=400):
    text = str(value or '')
    text = re.sub(r'https?://\S+', '[来源链接]', text)
    text = re.sub(r'\b(?:sk-[\w-]+|\d{6,}:[\w-]{20,})\b', '[已隐藏凭据]', text)
    return text[:limit]


def event(kind, message, *, tool=None, status=None):
    return {'kind': 'activity', 'event': kind, 'message': public_text(message),
            **({'tool': tool} if tool in LABELS else {}),
            **({'status': status} if status else {})}


def tool_event(name, started, success=True):
    label = LABELS.get(name, '执行应用工具')
    state = 'running' if started else 'completed' if success else 'failed'
    return event('tool_started' if started else 'tool_completed',
                 ('正在' if started else '已完成：' if success else '未完成：') + label,
                 tool=name, status=state)


def summarize_result(result):
    if isinstance(result, list):
        sources = [r for r in result if isinstance(r, dict) and 'source' in r]
        if sources:
            return '；'.join(f"{public_text(r['source'], 60)}：" +
                            ('获取失败' if r.get('error') else f"取得 {len(r.get('items', []))} 条") for r in sources)
    if isinstance(result, dict):
        if result.get('error'):
            return '工具返回错误，未取得完整结果'
        if 'report_id' in result:
            return f"报告 #{int(result['report_id'])}"
        if 'item_id' in result:
            return f"资讯 #{int(result['item_id'])}"
    return ''
