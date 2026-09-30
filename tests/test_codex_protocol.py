"""Exercise real client routing against an in-process JSON-RPC peer."""
import json
import queue
import threading
import pytest

from rss_pipeline.clients.codex import AppServer, CodexError


class Peer:
    def __init__(self, failed=False):
        self.stdout = self
        self.stdin = self
        self.lines = queue.Queue()
        self.calls = []
        self.failed = failed
        self.exit_code = None

    def __iter__(self):
        while True:
            line = self.lines.get()
            if line is None:
                return
            yield line

    def event(self, method, params):
        self.lines.put(json.dumps({'method': method, 'params': params}) + '\n')

    def write(self, line):
        msg = json.loads(line)
        self.calls.append(msg)
        if 'id' not in msg or 'method' not in msg:
            return
        method = msg['method']
        result = {}
        if method == 'thread/start':
            result = {'thread': {'id': 'thread-1'}}
        if method == 'thread/resume':
            self.lines.put(json.dumps({'id': msg['id'], 'error': {'code': -32000, 'message': 'test'}}))
            return
        if method == 'turn/start':
            result = {'turn': {'id': 'turn-1'}}
        self.lines.put(json.dumps({'id': msg['id'], 'result': result}))
        if method == 'turn/start':
            self.event('item/agentMessage/delta', {'threadId': 'different-thread', 'turnId': 'turn-1', 'delta': 'wrong'})
            self.event('item/agentMessage/delta', {'threadId': 'thread-1', 'turnId': 'turn-1', 'delta': '你好'})
            self.event('turn/completed', {'threadId': 'thread-1', 'turn': {'id': 'turn-1', 'status': 'failed' if self.failed else 'completed'}})

    def flush(self):
        pass

    def poll(self):
        return self.exit_code

    def terminate(self):
        self.exit_code = 0
        self.lines.put(None)

    def wait(self, timeout=None):
        return self.exit_code


def test_rpc_handshake_and_thread_routing():
    peer = Peer()
    api = AppServer(process=peer)
    try:
        text = ''.join(api.turn('thread-1', 'hi', use_skill=False))
        assert text == '你好'
        assert peer.calls[0]['method'] == 'initialize'
        assert peer.calls[0]['params']['capabilities']['experimentalApi']
        assert peer.calls[1]['method'] == 'initialized'
    finally:
        api.close()


def test_failed_turn_is_not_treated_as_a_complete_answer():
    peer = Peer(failed=True)
    api = AppServer(process=peer)
    try:
        with pytest.raises(CodexError):
            list(api.turn('thread-1', 'hi', use_skill=False))
    finally:
        api.close()


def test_resume_failure_never_creates_replacement_thread():
    peer = Peer()
    api = AppServer(process=peer)
    try:
        with pytest.raises(CodexError):
            api.resume_thread('existing-thread')
        assert not any(c.get('method') == 'thread/start' for c in peer.calls)
    finally:
        api.close()


def test_dynamic_tool_request_returns_correct_protocol_shape():
    peer = Peer()
    api = AppServer(process=peer, tool_handler=lambda thread, tool, args: {'saved': True})
    try:
        api._server_request({'id': 'tool-request', 'method': 'item/tool/call',
                             'params': {'threadId': 'thread-1', 'tool': 'news_preferences', 'arguments': {}}})
        reply = peer.calls[-1]
        assert reply['id'] == 'tool-request'
        assert reply['result']['success'] is True
        assert reply['result']['contentItems'][0]['type'] == 'inputText'
        assert json.loads(reply['result']['contentItems'][0]['text']) == {'saved': True}
    finally:
        api.close()


def test_cancel_calls_turn_interrupt_and_waits_for_completion():
    class InterruptPeer(Peer):
        def write(self, line):
            msg = json.loads(line)
            if msg.get('method') == 'turn/start':
                self.calls.append(msg)
                self.lines.put(json.dumps({'id': msg['id'], 'result': {'turn': {'id': 'turn-1'}}}))
            elif msg.get('method') == 'turn/interrupt':
                super().write(line)
                self.event('turn/completed', {'threadId': 'thread-1', 'turn': {'id': 'turn-1', 'status': 'interrupted'}})
            else:
                super().write(line)

    peer = InterruptPeer()
    api = AppServer(process=peer)
    stop = threading.Event()
    stop.set()
    try:
        assert list(api.turn('thread-1', 'hi', use_skill=False, cancel_event=stop)) == []
        interrupts = [c for c in peer.calls if c.get('method') == 'turn/interrupt']
        assert len(interrupts) == 1
        assert interrupts[0]['params'] == {'threadId': 'thread-1', 'turnId': 'turn-1'}
    finally:
        api.close()
