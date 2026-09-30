"""Telegram personal news reader: native rich UI and persistent Codex sessions."""
from dataclasses import dataclass, field
import html
import json
import queue
import sys
import threading
import time

from . import config, db, codex_agent
from .clients import telegram, native_rich

_jobs = {}
_lock = threading.Lock()


@dataclass
class Job:
    chat_id: str
    stop: threading.Event = field(default_factory=threading.Event)
    draft_id: int | None = None
    task_id: int | None = None


def busy(chat_id):
    with _lock:
        return str(chat_id) in _jobs


def _run(job, factory, markup):
    output = queue.Queue(maxsize=32)
    job.task_id = db.start_task(job.chat_id, '资讯对话')
    outcome, message_id = 'failed', None

    def put(value):
        while not job.stop.is_set():
            try:
                output.put(value, timeout=0.5)
                return
            except queue.Full:
                continue

    producer_done = threading.Event()

    def produce():
        try:
            for delta in factory(job.stop):
                # On cancel keep consuming until Codex confirms turn/interrupt.
                if not job.stop.is_set():
                    put(('text', delta))
        except Exception as exc:
            safe = str(exc) if isinstance(exc, (codex_agent.CodexError, ValueError)) else '取材或模型生成失败，请稍后重试。'
            put(('error', safe))
        finally:
            put(('done', None))
            producer_done.set()

    def chunks():
        while not job.stop.is_set():
            try:
                kind, value = output.get(timeout=1)
            except queue.Empty:
                yield ''
                continue
            if kind == 'done':
                return
            if kind == 'error':
                raise codex_agent.CodexError(value)
            yield value
        yield ''

    def event(data):
        nonlocal message_id
        if data['event'] == 'started':
            job.draft_id = data['draft_id']
        elif data['event'] == 'activity':
            if data['activity']['event'] != 'commentary_live':
                db.task_event(job.task_id, data['activity'])
        elif data['event'] == 'final':
            message_id = data['message_id']

    threading.Thread(target=produce, daemon=True).start()
    try:
        native_rich.stream(chunks(), chat_id=job.chat_id, stop_event=job.stop,
                           reply_markup=markup, on_event=event)
        outcome = 'interrupted' if job.stop.is_set() else 'completed'
    except Exception as exc:
        safe = str(exc) if isinstance(exc, (codex_agent.CodexError, native_rich.NativeRichError)) else '这次解读未完成，请稍后重试。'
        db.task_event(job.task_id, {'event': 'error', 'message': safe, 'status': 'failed'})
        try:
            telegram.send_message(safe, chat_id=job.chat_id, markdown=False)
        except Exception:
            print('原生回复发送失败；没有回退发送普通消息', file=sys.stderr, flush=True)
    finally:
        job.stop.set()
        # Keep the session busy until its producer has actually stopped.
        if not producer_done.wait(timeout=35):
            print('Codex 尚未确认停止，保留忙碌状态防止会话交叉', file=sys.stderr, flush=True)
            producer_done.wait()
        db.finish_task(job.task_id, outcome, message_id)
        with _lock:
            if _jobs.get(job.chat_id) is job:
                _jobs.pop(job.chat_id)


def start_job(chat_id, factory, markup=None):
    key = str(chat_id)
    with _lock:
        if key in _jobs:
            return False
        job = Job(key)
        _jobs[key] = job
    threading.Thread(target=_run, args=(job, factory, markup), daemon=True).start()
    return True


def stop_job(chat_id, draft_id=None):
    with _lock:
        job = _jobs.get(str(chat_id))
        if not job or draft_id is not None and job.draft_id != draft_id:
            return False
        job.stop.set()
        return True


def _start_reply(chat_id, text, markup=None):
    session = db.active_session(chat_id)
    def controls():
        item = db.current(chat_id)
        return telegram.review_buttons(item['id'], item['url']) if item else markup
    return start_job(chat_id, lambda stop: codex_agent.reply(text, chat_id, cancel_event=stop, session=session, emit_activity=True), controls)


def _switch(chat_id, session_id):
    if busy(chat_id):
        raise ValueError('请先停止当前生成，再切换会话。')
    session = db.switch_session(chat_id, session_id)
    telegram.send_message(f"已切换到会话 #{session['id']}：{session['name']}。", chat_id=chat_id, markdown=False)


def _choose_model(chat_id, model):
    if busy(chat_id):
        raise ValueError('请先停止当前生成，再切换模型。')
    chosen = codex_agent.choose_model(chat_id, model)
    telegram.send_message(f'后续回复使用 {chosen}，当前会话和上下文保留。', chat_id=chat_id, markdown=False)


def handle_callback(cb):
    data = cb.get('data', '')
    chat_id = cb.get('message', {}).get('chat', {}).get('id')
    action, sep, sid = data.partition(':')
    if not sep or chat_id is None:
        telegram.answer_callback(cb['id'], '这个操作暂不可用')
        return
    if action == 'session' and sid.isdigit():
        telegram.answer_callback(cb['id'])
        _switch(chat_id, int(sid))
        return
    if action == 'model':
        telegram.answer_callback(cb['id'])
        _choose_model(chat_id, sid)
        return
    if not sid.isdigit():
        telegram.answer_callback(cb['id'], '这个操作暂不可用')
        return
    item_id = int(sid)
    with db.conn() as c:
        item = db.get_item(c, item_id)
    if item is None:
        telegram.answer_callback(cb['id'], '条目不存在')
        return
    if action in ('brief', 'detail', 'technical', 'dive'):
        if busy(chat_id):
            telegram.answer_callback(cb['id'], '请先停止当前生成')
            return
        db.set_current(chat_id, item_id)
        modes = {'brief': '速读', 'detail': '深入解读', 'technical': '技术视角', 'dive': '深入解读'}
        request = f"请以{modes[action]}方式解读资讯 #{item_id}：{item['zh_title']}。先读取原文或 README，按内容自然组织，不使用固定模板。"
        ok = _start_reply(chat_id, request, telegram.review_buttons(item_id, item['url']))
        telegram.answer_callback(cb['id'], '正在阅读原文…' if ok else '正在处理上一条')
    elif action == 'ask':
        if busy(chat_id):
            telegram.answer_callback(cb['id'], '请先停止当前生成')
            return
        db.set_current(chat_id, item_id)
        telegram.answer_callback(cb['id'], '直接发送你想问的问题')
        telegram.send_message(f"可以继续问这篇：{item['zh_title']}\n例如：它有什么局限？适合我的场景吗？",
                              chat_id=chat_id, markdown=False)
    elif action == 'save':
        saved = db.toggle_saved(chat_id, item_id)
        telegram.answer_callback(cb['id'], '已收藏，可用 /saved 查看' if saved else '已取消收藏')
    elif action in ('more', 'less'):
        db.feedback(chat_id, item_id, action)
        telegram.answer_callback(cb['id'], '已记录，作为后续分析的兴趣参考')
    elif action in ('approve', 'discard'):
        with db.conn() as c:
            db.set_status(c, item_id, 'published' if action == 'approve' else 'discarded')
        telegram.answer_callback(cb['id'], '已标记通过' if action == 'approve' else '已丢弃')
    else:
        telegram.answer_callback(cb['id'], '未知操作')


def _report_page(chat_id, report_id, page=0):
    report = db.report(chat_id, report_id)
    if not report:
        raise ValueError('报告不存在')
    # Plain text blocks keep pagination lossless; native HTML escapes each page.
    content = report['content']
    pages = [content[i:i+6000] for i in range(0, len(content), 6000)]
    if not 0 <= page < len(pages):
        raise ValueError('报告页码不存在')
    controls = []
    if page > 0:
        controls.append({'text': '上一页', 'callback_data': f'report:{report_id}:{page-1}'})
    if page+1 < len(pages):
        controls.append({'text': '下一页', 'callback_data': f'report:{report_id}:{page+1}'})
    title = html.escape(report['title'])
    body = html.escape(pages[page]).replace('\n', '<br/>')
    native_rich.send_message(f'<h1>{title}</h1><p>{body}</p><footer>第 {page+1} / {len(pages)} 页</footer>',
                             format='html', chat_id=chat_id,
                             reply_markup={'inline_keyboard': [controls]} if controls else None)


def handle_message(msg):
    chat_id = msg['chat']['id']
    text = (msg.get('text') or '').strip()
    if any(key in msg for key in ('photo', 'document', 'voice', 'audio', 'video')):
        telegram.send_message('目前还没有接入图片、音视频或 PDF 文件的内容识别。请发送文字或公开来源链接；已保存的报告可以用 /export 编号 下载 Markdown 文件。',
                              chat_id=chat_id, markdown=False)
        return
    if not text:
        return
    command, _, argument = text.partition(' ')
    if command == '/stop':
        ok = stop_job(chat_id)
        telegram.send_message('正在停止生成。' if ok else '没有正在生成的任务。', chat_id=chat_id, markdown=False)
    elif command in ('/new', '/reset'):
        if busy(chat_id):
            raise ValueError('请先停止当前生成，再新建会话。')
        session = db.new_session(chat_id, argument.strip() or '新会话')
        telegram.send_message(f"已建立会话 #{session['id']}：{session['name']}。旧会话和长期偏好保留。",
                              chat_id=chat_id, markdown=False)
    elif command == '/sessions':
        current = db.active_session(chat_id)
        rows = db.sessions(chat_id)
        buttons = [[{'text': ('✓ ' if row['id'] == current['id'] else '') + f"#{row['id']} {row['name']}",
                     'callback_data': f"session:{row['id']}"}] for row in rows]
        telegram.send_message('# 你的会话\n\n点击切换，会保留各自的上下文。', chat_id=chat_id,
                              reply_markup={'inline_keyboard': buttons})
    elif command == '/switch':
        if not argument.isdigit():
            raise ValueError('用法：/switch 会话编号')
        _switch(chat_id, int(argument))
    elif command == '/models':
        rows = codex_agent.models()
        current = db.active_session(chat_id).get('model')
        buttons = [[{'text': ('✓ ' if row['model'] == current else '') + row['displayName'],
                     'callback_data': 'model:' + row['model']}] for row in rows
                   if len(('model:' + row['model']).encode()) <= 64]
        telegram.send_message('# 选择模型\n\n切换后保留当前会话。模型目录来自 Codex，实际可用性以生成结果为准。',
                              chat_id=chat_id, reply_markup={'inline_keyboard': buttons})
    elif command == '/model':
        _choose_model(chat_id, argument.strip())
    elif command == '/preferences':
        preferences = db.preferences(chat_id)
        body = '\n'.join(f'{k}：{v}' for k,v in preferences.items()) or '还没有保存偏好。'
        telegram.send_message(body + '\n\n用 /prefer 名称=内容 修改；空内容删除。', chat_id=chat_id, markdown=False)
    elif command == '/prefer':
        key, sep, value = argument.partition('=')
        if not sep:
            raise ValueError('用法：/prefer 阅读风格=多解释机制，少用固定编号')
        db.set_preference(chat_id, key, value)
        telegram.send_message('偏好已保存。' if value.strip() else '偏好已删除。', chat_id=chat_id, markdown=False)
    elif command in ('/start', '/help'):
        telegram.send_message('# 你的资讯助手\n\n直接发问题，或在新闻下选择速读、深入解读和技术视角。'
                              '\n\n`/new 名称` 新会话 · `/sessions` 切换会话 · `/models` 选择模型'
                              '\n\n`/preferences` 偏好 · `/saved` 收藏 · `/latest` 最近资讯'
                              '\n\n`/reports` 报告 · `/delivery` 推送状态 · `/stop` 停止生成'
                              '\n\n`/status` 执行状态 · `/trace 编号` 执行记录 · `/export 编号` 下载报告'
                              '\n\n也可以直接问：你有哪些功能？帮我把这篇生成一份详细报告。', chat_id=chat_id)
    elif command in ('/saved', '/latest'):
        if command == '/saved':
            rows = db.saved(chat_id)
        else:
            with db.conn() as c:
                rows = c.execute('SELECT * FROM items ORDER BY id DESC LIMIT 5').fetchall()
        if not rows:
            telegram.send_message('暂时没有记录。', chat_id=chat_id, markdown=False)
        else:
            for item in rows:
                telegram.send_message(f"# {item['zh_title']}\n\n{item['zh_summary']}", chat_id=chat_id,
                                      reply_markup=telegram.review_buttons(item['id'], item['url']))
    elif command == '/reports':
        rows = db.list_reports(chat_id)
        telegram.send_message('\n'.join(f"#{r['id']} {r['title']} · /report {r['id']}" for r in rows)
                              or '暂无报告。可以直接请求：帮我生成并保存详细报告。', chat_id=chat_id, markdown=False)
    elif command == '/export':
        if not argument.isdigit():
            raise ValueError('用法：/export 报告编号')
        telegram.export_report(chat_id, int(argument))
    elif command == '/report':
        if not argument.isdigit():
            raise ValueError('用法：/report 报告编号')
        _report_page(chat_id, int(argument))
    elif command == '/status':
        labels = {'running': '运行中', 'completed': '已完成', 'failed': '未完成', 'interrupted': '已停止', 'unknown': '进程中断，待确认'}
        rows = db.tasks(chat_id)
        body = '\n\n'.join(f"任务 #{r['id']} · {r['kind']} · {labels.get(r['status'], r['status'])} · /trace {r['id']}\n{r['latest_event'] or '等待执行事件'}" for r in rows)
        telegram.send_message(body or '暂无任务。', chat_id=chat_id, markdown=False)
    elif command == '/trace':
        if not argument.isdigit():
            raise ValueError('用法：/trace 任务编号')
        rows = db.trace(chat_id, int(argument))
        body = '\n'.join(r['message'] for r in rows[-30:])
        telegram.send_message(body or '该任务尚无执行事件。', chat_id=chat_id, markdown=False)
    elif command == '/delivery':
        with db.conn() as c:
            rows = c.execute('SELECT delivery_status,COUNT(*) AS count FROM items GROUP BY delivery_status').fetchall()
        telegram.send_message('\n'.join(f"{r['delivery_status']}：{r['count']}" for r in rows) or '暂无推送记录',
                              chat_id=chat_id, markdown=False)
    else:
        if busy(chat_id):
            raise ValueError('正在处理上一条，可以先停止，再发送新的问题。')
        replied = msg.get('reply_to_message', {}).get('message_id')
        if replied:
            with db.conn() as c:
                item = c.execute('SELECT id FROM items WHERE tg_message_id=?', (replied,)).fetchone()
            if item:
                db.set_current(chat_id, item['id'])
        current = db.current(chat_id)
        markup = telegram.review_buttons(current['id'], current['url']) if current else None
        _start_reply(chat_id, text, markup)


def authorized(update):
    if not config.TELEGRAM_CHAT_ID:
        return False
    if 'message' in update:
        key = update['message'].get('chat', {}).get('id')
    elif 'callback_query' in update:
        cb = update['callback_query']
        key = cb.get('message', {}).get('chat', {}).get('id')
        if str(cb.get('from', {}).get('id')) != str(config.TELEGRAM_CHAT_ID):
            return False
    elif 'stopped_message_generation' in update:
        key = update['stopped_message_generation'].get('chat', {}).get('id')
    else:
        return False
    return str(key) == str(config.TELEGRAM_CHAT_ID)


def main():
    db.init()
    db.recover_tasks('资讯对话')
    print('原生富文本 Codex 资讯助手启动', flush=True)
    offset = None
    while True:
        try:
            updates = telegram.get_updates(offset=offset)
        except Exception:
            print('获取 Telegram 更新失败，5 秒后重试', file=sys.stderr, flush=True)
            time.sleep(5)
            continue
        for update in updates:
            offset = update['update_id'] + 1
            if not authorized(update):
                continue
            owner = config.TELEGRAM_CHAT_ID
            try:
                if 'stopped_message_generation' in update:
                    stop = update['stopped_message_generation']
                    stop_job(stop['chat']['id'], stop['draft_id'])
                elif 'callback_query' in update:
                    callback = update['callback_query']
                    if callback.get('data', '').startswith('report:'):
                        telegram.answer_callback(callback['id'])
                        _, report_id, page = callback['data'].split(':')
                        _report_page(owner, int(report_id), int(page))
                    else:
                        handle_callback(callback)
                elif 'message' in update:
                    handle_message(update['message'])
            except Exception as exc:
                safe = str(exc) if isinstance(exc, (ValueError, codex_agent.CodexError, native_rich.NativeRichError)) else '操作未完成，请稍后重试。'
                try:
                    telegram.send_message(safe, chat_id=owner, markdown=False)
                except Exception:
                    print('无法发送原生错误提示', file=sys.stderr, flush=True)


if __name__ == '__main__':
    main()
