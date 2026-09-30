"""Persistent JSON-RPC stdio client for Codex App Server 0.159.2.

Authentication belongs to Codex. Never inspect/copy auth tokens. One server serves
many isolated threads; requests, events and client-side tools are routed by ID.
"""
from concurrent.futures import Future, ThreadPoolExecutor
import json
import os
from pathlib import Path
import queue
import subprocess
import threading
import time

from .. import config, prompts


class CodexError(RuntimeError):
    pass


class AppServer:
    def __init__(self, *, tool_handler=None, process=None):
        self.tool_handler = tool_handler
        self._write_lock = threading.Lock()
        self._state_lock = threading.RLock()
        self._next_id = 1
        self._pending = {}
        self._events = {}
        self._tool_workers = ThreadPoolExecutor(max_workers=4)
        self._closed = False
        # Disable inherited connector/shell capabilities: app tools are explicit.
        command = [config.CODEX_BIN, 'app-server', '--listen', 'stdio://',
                   '-c', 'features.shell_tool=false', '-c', 'features.apps=false',
                   '-c', 'features.plugins=false', '-c', 'features.multi_agent=false',
                   '-c', 'features.browser_use=false', '-c', 'features.computer_use=false']
        env = {k: v for k, v in os.environ.items()
               if k not in ('TELEGRAM_BOT_TOKEN', 'DEEPSEEK_API_KEY', 'GITHUB_ACCESS_TOKEN')}
        self.process = process or subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                                   stderr=subprocess.DEVNULL, text=True, bufsize=1,
                                                   cwd=config.CODEX_CWD, env=env)
        self._reader = threading.Thread(target=self._read, daemon=True)
        self._reader.start()
        try:
            self.request('initialize', {'clientInfo': {'name': 'personal_news_assistant',
                         'title': 'Personal News Assistant', 'version': '0.2.0'},
                         'capabilities': {'experimentalApi': True}})
            self._write({'method': 'initialized'})
        except Exception:
            self.close()
            raise

    def _write(self, message):
        with self._write_lock:
            if self._closed or self.process.poll() is not None:
                raise CodexError('Codex App Server 已停止，请重试恢复会话')
            try:
                self.process.stdin.write(json.dumps(message, ensure_ascii=False) + '\n')
                self.process.stdin.flush()
            except (OSError, ValueError):
                raise CodexError('Codex App Server 连接已断开') from None

    def request(self, method, params=None, timeout=45):
        future = Future()
        with self._state_lock:
            request_id = self._next_id
            self._next_id += 1
            self._pending[request_id] = future
        try:
            self._write({'id': request_id, 'method': method, 'params': params or {}})
            return future.result(timeout=timeout)
        except TimeoutError:
            raise CodexError(f'Codex {method} 超时；未自动新建会话') from None
        finally:
            with self._state_lock:
                self._pending.pop(request_id, None)

    def _fail_pending(self):
        with self._state_lock:
            for future in self._pending.values():
                if not future.done():
                    future.set_exception(CodexError('Codex App Server 连接已断开'))
            for events in self._events.values():
                events.put({'method': 'client/disconnected', 'params': {}})

    def _read(self):
        try:
            for line in self.process.stdout:
                try:
                    message = json.loads(line)
                except ValueError:
                    continue
                if 'id' in message and 'method' not in message:
                    with self._state_lock:
                        future = self._pending.get(message['id'])
                        if future is not None and not future.done():
                            if 'error' in message:
                                # Raw errors may contain local URLs; expose only method-independent safe metadata.
                                future.set_exception(CodexError(f"Codex 协议请求失败（code={message['error'].get('code')}）"))
                            else:
                                future.set_result(message.get('result', {}))
                elif 'id' in message:
                    self._tool_workers.submit(self._server_request, message)
                else:
                    thread_id = message.get('params', {}).get('threadId')
                    with self._state_lock:
                        events = self._events.get(thread_id)
                    if events:
                        events.put(message)
        finally:
            self._fail_pending()

    def _server_request(self, request):
        method, params = request['method'], request.get('params', {})
        if method == 'item/tool/call':
            try:
                if self.tool_handler is None:
                    raise ValueError('Tool handler unavailable')
                result = self.tool_handler(params['threadId'], params['tool'], params['arguments'])
                reply = {'success': True, 'contentItems': [{'type': 'inputText', 'text': json.dumps(result, ensure_ascii=False)}]}
            except Exception:
                reply = {'success': False, 'contentItems': [{'type': 'inputText', 'text': '工具执行失败，请检查参数或稍后重试。'}]}
            self._write({'id': request['id'], 'result': reply})
        elif method in ('item/commandExecution/requestApproval', 'item/fileChange/requestApproval'):
            self._write({'id': request['id'], 'result': {'decision': 'decline'}})
        elif method == 'item/permissions/requestApproval':
            self._write({'id': request['id'], 'result': {'permissions': {}, 'scope': 'turn'}})
        else:
            self._write({'id': request['id'], 'error': {'code': -32601, 'message': 'Unsupported client request'}})

    def create_thread(self, tools=None, ephemeral=False, model=None):
        params = {'cwd': config.CODEX_CWD, 'sandbox': 'read-only', 'approvalPolicy': 'never',
                  'developerInstructions': prompts.ASSISTANT,
                  'serviceName': 'personal_news_assistant', 'ephemeral': ephemeral}
        if tools:
            params['dynamicTools'] = tools
        if model or config.CODEX_MODEL:
            params['model'] = model or config.CODEX_MODEL
        return self.request('thread/start', params)

    def resume_thread(self, thread_id, model=None):
        # Dynamic tools persist in the rollout. Never replace a failed resume with a new thread.
        return self.request('thread/resume', {'threadId': thread_id, 'cwd': config.CODEX_CWD,
                            'sandbox': 'read-only', 'approvalPolicy': 'never',
                            'developerInstructions': prompts.ASSISTANT, **({'model': model} if model else {})})

    def turn(self, thread_id, text, *, cancel_event=None, output_schema=None, use_skill=True, timeout=600):
        events = queue.Queue()
        with self._state_lock:
            if thread_id in self._events:
                raise CodexError('该会话正在生成，请先停止或等待完成')
            self._events[thread_id] = events
        turn_id = None
        completed = False
        interrupted_at = None
        try:
            inputs = [{'type': 'text', 'text': text}]
            skill_path = Path(config.CODEX_CWD) / '.agents/skills/news-assistant/SKILL.md'
            if use_skill and skill_path.is_file():
                inputs.append({'type': 'skill', 'name': 'news-assistant', 'path': str(skill_path)})
            params = {'threadId': thread_id, 'input': inputs}
            if output_schema:
                params['outputSchema'] = output_schema
            started = self.request('turn/start', params)
            turn_id = started['turn']['id']
            deadline = time.monotonic() + timeout
            authoritative = []
            streamed = False
            message_phases = {}
            while time.monotonic() < deadline:
                if cancel_event is not None and cancel_event.is_set() and interrupted_at is None:
                    self.request('turn/interrupt', {'threadId': thread_id, 'turnId': turn_id})
                    interrupted_at = time.monotonic()
                if interrupted_at and time.monotonic() - interrupted_at > 30:
                    raise CodexError('停止请求已发送，但尚未确认终止')
                try:
                    event = events.get(timeout=1)
                except queue.Empty:
                    yield ''
                    continue
                method, data = event['method'], event.get('params', {})
                if data.get('turnId') and data['turnId'] != turn_id:
                    continue
                if method == 'client/disconnected':
                    raise CodexError('Codex 连接中断；原会话 ID 已保留，重连后可继续')
                if method == 'item/started' and data.get('item', {}).get('type') == 'agentMessage':
                    item = data['item']
                    message_phases[item['id']] = item.get('phase')
                elif method == 'item/agentMessage/delta':
                    if interrupted_at is None and message_phases.get(data.get('itemId')) != 'commentary':
                        streamed = True
                        yield data.get('delta', '')
                elif method == 'item/completed' and data.get('item', {}).get('type') == 'agentMessage':
                    if data['item'].get('phase') != 'commentary':
                        authoritative.append(data['item'].get('text', ''))
                elif method == 'turn/completed':
                    if data['turn']['id'] != turn_id:
                        continue
                    status = data['turn']['status']
                    completed = True
                    if status == 'interrupted' and interrupted_at is not None:
                        return
                    if status != 'completed':
                        info = (data['turn'].get('error') or {}).get('codexErrorInfo')
                        category = info if isinstance(info, str) else next(iter(info), 'unknown') if isinstance(info, dict) else 'unknown'
                        labels = {'usageLimitExceeded': 'Codex 额度已用尽', 'UsageLimitExceeded': 'Codex 额度已用尽',
                                  'unauthorized': 'Codex 登录或模型权限不可用', 'Unauthorized': 'Codex 登录或模型权限不可用',
                                  'contextWindowExceeded': '当前上下文超出模型限制', 'ContextWindowExceeded': '当前上下文超出模型限制'}
                        raise CodexError(labels.get(category, 'Codex 本轮未完成') + '，原会话已保留。')
                    if not streamed:
                        yield '\n\n'.join(authoritative)
                    return
            raise CodexError('Codex 分析超时，原会话保留')
        finally:
            if turn_id and not completed:
                try:
                    self.request('turn/interrupt', {'threadId': thread_id, 'turnId': turn_id}, timeout=10)
                except CodexError:
                    pass
            with self._state_lock:
                self._events.pop(thread_id, None)

    def close(self):
        if self._closed:
            return
        self._closed = True
        self._fail_pending()
        self._tool_workers.shutdown(wait=False, cancel_futures=True)
        if self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()
