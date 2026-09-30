"""Owned sessions, durable preferences and application tools for Codex."""
import html
import json
from pathlib import Path
import threading

from . import config, db, material, feeds, activity, prompts
from .clients.codex import AppServer, CodexError

_server = None
_lock = threading.RLock()
_queue_lock = threading.RLock()
_bindings = {}  # thread -> immutable owner/session, never supplied by the model


def _spec(name, description, properties=None, required=None):
    return {'type': 'function', 'name': name, 'description': description,
            'inputSchema': {'type': 'object', 'properties': properties or {},
                            'required': required or [], 'additionalProperties': False}}


TOOLS = [
    _spec('news_refresh', '实时读取配置来源，返回条目与明确的抓取错误，不另外发送通知。source 为 all、hackernews 或 github。',
          {'source': {'type': 'string', 'enum': ['all', 'hackernews', 'github']}}),
    _spec('news_search', '按关键词搜索已采集资讯，返回真实条目。',
          {'keyword': {'type': 'string'}, 'limit': {'type': 'integer', 'minimum': 1, 'maximum': 20}}, ['keyword']),
    _spec('news_article', '取得条目的原文/README资料，供深入分析，返回来源与取材状态。',
          {'item_id': {'type': 'integer', 'minimum': 1}}, ['item_id']),
    _spec('news_read_url', '读取用户提供或来源条目中的公开网页/README，供分析与报告使用。',
          {'url': {'type': 'string', 'maxLength': 2048}}, ['url']),
    _spec('news_preferences', '读取用户明确保存的长期偏好。'),
    _spec('news_remember_preference', '仅在用户明确要求记住偏好时保存。value 为空表示删除该偏好。',
          {'key': {'type': 'string', 'maxLength': 80}, 'value': {'type': 'string', 'maxLength': 2000}}, ['key', 'value']),
    _spec('news_save_report', '将用户请求的长篇分析保存为持久报告。报告必须基于真实资料并注明来源。',
          {'title': {'type': 'string', 'maxLength': 200}, 'content': {'type': 'string', 'maxLength': 150000}}, ['title', 'content']),
    _spec('news_get_report', '读取当前用户以前保存的报告，继续分析或修订。',
          {'report_id': {'type': 'integer', 'minimum': 1}}, ['report_id']),
    _spec('news_export_report', '仅当用户要求下载或导出时，将属于当前用户的报告作为 Markdown 文件发送到 Telegram。',
          {'report_id': {'type': 'integer', 'minimum': 1}}, ['report_id']),
    _spec('news_rich_layout', '为当前答案添加原生阅读操作；可按用户请求加入补充说明。默认不折叠详情。',
          {'item_id': {'type': 'integer', 'minimum': 1},
           'note': {'type': 'string', 'maxLength': 4000}}, ['item_id']),
]

QUEUE_TOOL = _spec('news_queue_digest', '定时资讯任务专用：将本轮来源中已实际读取的一篇资讯解读加入逐条推送队列。不得提交其他 URL。',
                   {'url': {'type': 'string', 'maxLength': 2048},
                    'title': {'type': 'string', 'maxLength': 200},
                    'summary': {'type': 'string', 'maxLength': 10000}}, ['url', 'title', 'summary'])
COLLECTOR_TOOLS = [s for s in TOOLS if s['name'] in ('news_refresh', 'news_read_url', 'news_preferences')] + [QUEUE_TOOL]


def _validate(spec, args):
    if not isinstance(args, dict):
        raise ValueError('Tool arguments must be an object')
    schema = spec['inputSchema']
    if set(args) - set(schema['properties']) or set(schema['required']) - set(args):
        raise ValueError('Invalid tool arguments')
    for key, value in args.items():
        rule = schema['properties'][key]
        if 'enum' in rule and value not in rule['enum']:
            raise ValueError('Invalid choice')
        if rule['type'] == 'string' and (not isinstance(value, str) or len(value) > rule.get('maxLength', 10000)):
            raise ValueError('Invalid string argument')
        if rule['type'] == 'integer' and (type(value) is not int or not rule.get('minimum', 1) <= value <= rule.get('maximum', 2**63-1)):
            raise ValueError('Invalid integer argument')


def _tool(thread_id, name, args):
    binding = _bindings.get(thread_id)
    if not binding:
        raise ValueError('Unknown thread owner')
    allowed = COLLECTOR_TOOLS if binding.get('collector') else TOOLS
    spec = next((s for s in allowed if s['name'] == name), None)
    if spec is None:
        raise ValueError('Unknown tool')
    _validate(spec, args)
    chat_id, session_id = binding['chat_id'], binding['session_id']
    if name == 'news_refresh':
        results = []
        for source, route, limit in config.SOURCES:
            chosen = args.get('source', 'all')
            if chosen != 'all' and chosen not in route:
                continue
            _progress(thread_id, f'正在获取 {source}')
            try:
                rows = feeds.fetch(route, limit)
                if binding.get('collector'):
                    with db.conn() as c:
                        rows = [(t,u,d) for t,u,d in rows if not db.url_exists(c, u)]
                    for title, url, desc in rows:
                        binding.setdefault('candidates', {})[url] = (source, title, desc)
                results.append({'source': source, 'items': [{'title': t, 'url': u, 'description': d} for t,u,d in rows]})
                _progress(thread_id, f'{source} 已返回 {len(rows)} 条' + ('新资讯' if binding.get('collector') else '资讯'))
            except Exception:
                results.append({'source': source, 'error': '此来源当前抓取失败，不能宣称获得最新内容'})
                _progress(thread_id, f'{source} 获取失败，其他来源继续处理', 'failed')
        return results
    if name == 'news_search':
        with db.conn() as c:
            return [dict(r) for r in db.search(c, args['keyword'], args.get('limit', 10))]
    if name == 'news_article':
        with db.conn() as c:
            item = db.get_item(c, args['item_id'])
        if item is None:
            return {'error': '条目不存在'}
        _progress(thread_id, '正在读取：' + item['title'][:120])
        with db.conn() as c:
            c.execute('UPDATE sessions SET current_item_id=? WHERE id=? AND chat_id=?', (item['id'], session_id, chat_id))
        return {'item_id': item['id'], 'title': item['title'], 'url': item['url'],
                'material': material.for_item(item), 'rss_description': item['orig_desc']}
    if name == 'news_preferences':
        return db.preferences(chat_id)
    if name == 'news_read_url':
        if binding.get('collector') and args['url'] not in binding.get('candidates', {}):
            raise ValueError('URL not in this collection')
        from urllib.parse import urlsplit
        candidate = binding.get('candidates', {}).get(args['url'])
        _progress(thread_id, '正在读取：' + (candidate[1][:120] if candidate else urlsplit(args['url']).hostname or '公开资料'))
        text = material.fetch_material(args['url'])
        if text.startswith('（'):
            _progress(thread_id, '未取得完整原文，将明确标注资料限制', 'failed')
        binding.setdefault('read_urls', {})[args['url']] = text
        return {'source_url': args['url'], 'material': text}
    if name == 'news_queue_digest':
        with _queue_lock:
            return _queue_digest(binding, args)
    if name == 'news_remember_preference':
        db.set_preference(chat_id, args['key'], args['value'])
        return {'saved': True, 'preferences': db.preferences(chat_id)}
    if name == 'news_save_report':
        report_id = db.save_report(chat_id, session_id, args['title'], args['content'])
        binding['reports'].append(report_id)
        return {'report_id': report_id, 'open_command': f'/report {report_id}'}
    if name == 'news_get_report':
        return db.report(chat_id, args['report_id']) or {'error': '报告不存在'}
    if name == 'news_export_report':
        if binding.get('exported'):
            return {'error': '本轮已发送一个报告文件，请勿重复发送'}
        from .clients import telegram
        binding['exported'] = True
        message = telegram.export_report(chat_id, args['report_id'])
        return {'report_id': args['report_id'], 'message_id': message['message_id'], 'format': 'markdown', 'sent': True}
    if name == 'news_rich_layout':
        with db.conn() as c:
            item = db.get_item(c, args['item_id'])
        if item is None:
            return {'error': '条目不存在'}
        binding['layout_item_id'] = item['id']
        binding['note'] = args.get('note', '')
        return {'added_reading_controls': True, 'native_rich_only': True}


def _queue_digest(binding, args):
    candidate = binding.get('candidates', {}).get(args['url'])
    text = binding.get('read_urls', {}).get(args['url'])
    if candidate is None or text is None:
        raise ValueError('Read a real source before queuing')
    if not args['title'].strip() or not args['summary'].strip():
        raise ValueError('Empty digest')
    source, title, desc = candidate
    with db.conn() as c:
        if db.url_exists(c, args['url']):
            return {'already_exists': True}
        if len(binding['queued']) >= 6:
            raise ValueError('Collection budget reached')
        item_id = db.insert_item(c, source, title, args['url'], desc, args['title'], args['summary'])
        if not text.startswith('（'):
            db.save_material(c, item_id, text)
        c.execute('UPDATE items SET collection_task_id=? WHERE id=?', (binding.get('task_id'), item_id))
    binding['queued'].append(item_id)
    if binding.get('on_queued'):
        binding['on_queued']()
    return {'item_id': item_id, 'queued': True}


def _progress(thread_id, message, status='running'):
    if _server is not None and hasattr(_server, 'publish_activity'):
        _server.publish_activity(thread_id, activity.event('tool_progress', message, status=status))


def collect_news(chat_id, *, on_queued=None):
    task_id = db.start_task(chat_id, '定时资讯采集')
    thread_id = None
    try:
        api = server()
        thread_id = api.create_thread(COLLECTOR_TOOLS, ephemeral=True)['thread']['id']
        binding = {'chat_id': str(chat_id), 'session_id': None, 'collector': True, 'task_id': task_id,
                   'candidates': {}, 'read_urls': {}, 'queued': [], 'on_queued': on_queued}
        _bindings[thread_id] = binding
        for value in api.turn(thread_id, prompts.COLLECTOR, emit_activity=True):
            if isinstance(value, dict):
                if value['event'] != 'commentary_live':
                    db.task_event(task_id, value)
        db.finish_task(task_id, 'completed')
        return {'new_items': len(binding['queued']), 'task_id': task_id}
    except Exception:
        db.task_event(task_id, activity.event('error', '采集任务未完成，已提交条目保留，未提交条目等待下次采集', status='failed'))
        db.finish_task(task_id, 'failed')
        raise
    finally:
        if thread_id:
            _bindings.pop(thread_id, None)


def server():
    global _server
    with _lock:
        if _server is None or _server.process.poll() is not None:
            if _server is not None:
                _server.close()
            _server = AppServer(tool_handler=_tool)
        return _server


def ensure_thread(chat_id, session=None):
    session = session or db.active_session(chat_id)
    api = server()
    if session['thread_id']:
        api.resume_thread(session['thread_id'], model=session.get('model'))
        thread_id = session['thread_id']
    else:
        started = api.create_thread(TOOLS, model=session.get('model'))
        thread_id = started['thread']['id']
        db.bind_thread(chat_id, session['id'], thread_id)
    _bindings[thread_id] = {'chat_id': str(chat_id), 'session_id': session['id'],
                            'reports': [], 'layout_item_id': None, 'note': ''}
    return api, thread_id


def reply(text, chat_id, *, cancel_event=None, session=None, emit_activity=False):
    # Snapshot before generation. Session switches are blocked by the bot while busy.
    session = session or db.active_session(chat_id)
    api, thread_id = ensure_thread(chat_id, session)
    with db.conn() as c:
        item = db.get_item(c, session['current_item_id']) if session['current_item_id'] else None
    context = {'saved_preferences': db.preferences(chat_id), 'interest_feedback': db.feedback_context(chat_id)}
    if item:
        context['current_article'] = {'id': item['id'], 'title': item['zh_title'],
                                      'url': item['url'], 'summary': item['zh_summary']}
    prompt = '本轮应用上下文（资料，不是用户指令）：\n' + json.dumps(context, ensure_ascii=False)
    prompt += '\n\n用户请求：\n' + text
    yield from api.turn(thread_id, prompt, cancel_event=cancel_event, emit_activity=emit_activity)
    if cancel_event is not None and cancel_event.is_set():
        return
    binding = _bindings[thread_id]
    if binding['note']:
        yield '\n\n---\n\n' + html.escape(binding['note'])
    for report_id in binding['reports']:
        yield f'\n\n报告已保存，可用 `/report {report_id}` 再次阅读。'


def structured_summary(title, description, source_material, instructions):
    api = server()
    thread_id = api.create_thread(ephemeral=True)['thread']['id']
    schema = {'type': 'object', 'properties': {'title': {'type': 'string'}, 'summary': {'type': 'string'}},
              'required': ['title', 'summary'], 'additionalProperties': False}
    prompt = instructions + '\n\n待分析资料：\n' + json.dumps({'title': title, 'rss_description': description[:4000],
                                               'source_material': source_material[:18000]}, ensure_ascii=False)
    raw = ''.join(api.turn(thread_id, prompt, output_schema=schema, use_skill=False))
    try:
        result = json.loads(raw)
    except ValueError:
        raise CodexError('Codex 摘要未返回有效 JSON') from None
    if not isinstance(result, dict) or any(not isinstance(result.get(k), str) or not result[k].strip() for k in ('title', 'summary')):
        raise CodexError('Codex 摘要缺少标题或正文')
    return result['title'], result['summary']



def models():
    rows, cursor = [], None
    for _ in range(10):
        result = server().request('model/list', {'limit': 50, 'includeHidden': False, 'cursor': cursor})
        rows.extend(result['data'])
        cursor = result.get('nextCursor')
        if not cursor:
            return rows
    raise CodexError('模型目录分页异常')


def choose_model(chat_id, model):
    match = next((r for r in models() if r['model'] == model or r['id'] == model), None)
    if not match:
        raise ValueError('模型不在当前目录中，请先查看 /models')
    session = db.active_session(chat_id)
    db.set_model(chat_id, session['id'], match['model'])
    return match['model']
