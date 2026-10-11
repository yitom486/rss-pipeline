"""Telegram Bot API 10.3 native rich transport. Never downgrade message format.

Reference: https://core.telegram.org/bots/api#sendrichmessagedraft
Drafts are private-chat previews; only sendRichMessage persists the result.
"""
import random
import html
import threading
import time
import json

import httpx

from .. import config
from . import http

_draft_lock = threading.Lock()
_last_draft = {}
DRAFT_INTERVAL = 1.1  # < 40 requests / 30 seconds per chat, in this process


class NativeRichError(RuntimeError):
    """Safe to display: transport exceptions must never expose the bot URL/token."""
    def __init__(self, message, *, unconfirmed=False):
        super().__init__(message)
        self.unconfirmed = unconfirmed


def _pace_draft(chat_id):
    with _draft_lock:
        delay = _last_draft.get(str(chat_id), -DRAFT_INTERVAL) + DRAFT_INTERVAL - time.monotonic()
        if delay > 0:
            time.sleep(delay)
        _last_draft[str(chat_id)] = time.monotonic()


def _call(method, **params):
    if not config.TELEGRAM_BOT_TOKEN or not config.TELEGRAM_CHAT_ID and not params.get('chat_id'):
        raise NativeRichError('Telegram bot token or destination is not configured')
    timeout = params.pop("_timeout", 30)
    api = f'https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}'
    params = {k: v for k, v in params.items() if v is not None}
    files = {}
    if params.get('rich_message'):
        from .. import diagrams
        rich_body = dict(params['rich_message'])
        media, files = diagrams.attachments(json.dumps(rich_body, ensure_ascii=False), chat_id=params.get('chat_id'))
        if media:
            rich_body['media'] = media
            params['rich_message'] = rich_body
    for attempt in range(3):
        if method == 'sendRichMessageDraft':
            _pace_draft(params['chat_id'])
        try:
            if files:
                fields = {key: json.dumps(value, ensure_ascii=False) if isinstance(value, (dict, list, bool))
                          else str(value) for key, value in params.items()}
                response = http.post(f'{api}/{method}', data=fields, files=files, timeout=timeout)
            else:
                response = http.post(f'{api}/{method}', json=params, timeout=timeout)
        except httpx.HTTPError:
            # Final delivery may have succeeded before a timeout: do not duplicate it.
            raise NativeRichError(f'Telegram {method}: network failure; delivery is unconfirmed', unconfirmed=True) from None
        try:
            data = response.json()
        except ValueError:
            raise NativeRichError(f'Telegram {method}: non-JSON response ({response.status_code})', unconfirmed=True) from None
        if data.get('ok'):
            return data['result']
        retry_after = data.get('parameters', {}).get('retry_after')
        if data.get('error_code') == 429 and isinstance(retry_after, (int, float)) and 0 <= retry_after <= 30 and attempt < 2:
            time.sleep(retry_after + 0.1)
            continue
        description = str(data.get('description', 'request rejected')).replace(config.TELEGRAM_BOT_TOKEN, '[REDACTED]')
        raise NativeRichError(f'Telegram {method} [{data.get("error_code", response.status_code)}]: {description}')


def _content(content, format):
    if format not in ('markdown', 'html', 'blocks'):
        raise ValueError('Native rich format must be markdown, html, or blocks')
    if format == 'blocks' and not isinstance(content, list):
        raise TypeError('blocks must be a list')
    if format != 'blocks' and not isinstance(content, str):
        raise TypeError('markdown/html must be a string')
    return {format: content}


def send_draft(draft_id, content, *, chat_id=None, format='markdown', message_thread_id=None,
               can_stop=False, keep_on_stop=False):
    if not isinstance(draft_id, int) or draft_id == 0:
        raise ValueError('draft_id must be a non-zero integer')
    return _call('sendRichMessageDraft', chat_id=chat_id or config.TELEGRAM_CHAT_ID,
                 draft_id=draft_id, rich_message=_content(content, format),
                 message_thread_id=message_thread_id, can_stop=can_stop, keep_on_stop=keep_on_stop)


def send_message(content, *, chat_id=None, format='markdown', message_thread_id=None,
                 reply_markup=None, reply_parameters=None):
    result = _call('sendRichMessage', chat_id=chat_id or config.TELEGRAM_CHAT_ID,
                   rich_message=_content(content, format), message_thread_id=message_thread_id,
                   reply_markup=reply_markup, reply_parameters=reply_parameters)
    if not isinstance(result, dict) or not result.get('rich_message'):
        raise NativeRichError('Telegram response did not confirm a native rich message')
    return result


def stream(chunks, *, header='', min_interval=DRAFT_INTERVAL, chat_id=None,
           message_thread_id=None, on_event=None, stop_event=None, reply_markup=None):
    """Consume model deltas; send accumulated native drafts and one native final.

    A stop_event enables the stop UI; the bot loop must consume stopped_message_generation.
    Empty chunks allow the bot producer queue to heartbeat while fetching sources.
    """
    draft_id = random.getrandbits(31) or 1
    interval = max(DRAFT_INTERVAL, min_interval)
    kwargs = {'chat_id': chat_id, 'message_thread_id': message_thread_id}
    draft_kwargs = {**kwargs, 'can_stop': stop_event is not None, 'keep_on_stop': True}

    def emit(kind, **fields):
        if on_event:
            on_event({'event': kind, 'draft_id': draft_id, **fields})

    emit('started')
    status = '正在建立 Codex 会话…'
    send_draft(draft_id, '<tg-thinking>' + status + '</tg-thinking>', **draft_kwargs)
    emit('thinking')
    last_push = time.monotonic()
    buf = []
    last_body = None
    stopped = False
    for chunk in chunks:
        if stop_event is not None and stop_event.is_set():
            stopped = True
            break
        if isinstance(chunk, dict) and chunk.get('kind') == 'activity':
            status = chunk['message']
            emit('activity', activity=chunk)
            chunk = ''
        if not isinstance(chunk, str):
            raise TypeError('stream chunks must be strings')
        if chunk:
            buf.append(chunk)
        if time.monotonic() - last_push >= interval:
            body = header + ''.join(buf) + '\n\n<tg-thinking>' + html.escape(status) + '</tg-thinking>'
            if body != last_body or time.monotonic() - last_push >= 8:
                send_draft(draft_id, body, **draft_kwargs)
                emit('draft', characters=len(body))
                last_body = body
                last_push = time.monotonic()
    final = ''.join(buf)
    if stop_event is not None and stop_event.is_set():
        stopped = True
    if stopped:
        final += '\n\n*已停止生成。*'
        emit('stopped')
    if not final.strip():
        raise NativeRichError('Empty generation; no final message was sent')
    body = header + final
    if body != last_body:
        send_draft(draft_id, body, **draft_kwargs)
        emit('draft', characters=len(body))
    controls = reply_markup() if callable(reply_markup) else reply_markup
    result = send_message(body, reply_markup=controls, **kwargs)
    emit('final', message_id=result['message_id'], block_types=[b.get('type') for b in result['rich_message']['blocks']])
    return final
