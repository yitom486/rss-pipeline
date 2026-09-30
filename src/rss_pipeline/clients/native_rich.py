"""Telegram Bot API 10.3 native rich transport. Never downgrade message format.

Reference: https://core.telegram.org/bots/api#sendrichmessagedraft
Drafts are private-chat previews; only sendRichMessage persists the result.
"""
import random
import threading
import time

import requests

from .. import config
from . import http

_draft_lock = threading.Lock()
_last_draft = {}
DRAFT_INTERVAL = 1.1  # < 40 requests / 30 seconds per chat, in this process


class NativeRichError(RuntimeError):
    """Safe to display: transport exceptions must never expose the bot URL/token."""


def _pace_draft(chat_id):
    with _draft_lock:
        delay = _last_draft.get(str(chat_id), -DRAFT_INTERVAL) + DRAFT_INTERVAL - time.monotonic()
        if delay > 0:
            time.sleep(delay)
        _last_draft[str(chat_id)] = time.monotonic()


def _call(method, **params):
    if not config.TELEGRAM_BOT_TOKEN or not config.TELEGRAM_CHAT_ID and not params.get('chat_id'):
        raise NativeRichError('Telegram bot token or destination is not configured')
    api = f'https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}'
    params = {k: v for k, v in params.items() if v is not None}
    for attempt in range(3):
        if method == 'sendRichMessageDraft':
            _pace_draft(params['chat_id'])
        try:
            response = http.post(f'{api}/{method}', json=params, timeout=30)
        except requests.RequestException:
            # Final delivery may have succeeded before a timeout: do not duplicate it.
            raise NativeRichError(f'Telegram {method}: network failure; delivery is unconfirmed') from None
        try:
            data = response.json()
        except ValueError:
            raise NativeRichError(f'Telegram {method}: non-JSON response ({response.status_code})') from None
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
           message_thread_id=None, on_event=None):
    """Consume model deltas; send accumulated native drafts and one native final.

    Stop UI is intentionally disabled until the bot update loop can cancel the producer.
    The demo exercises transport with fixture deltas, not model generation.
    """
    draft_id = random.getrandbits(31) or 1
    interval = max(DRAFT_INTERVAL, min_interval)
    kwargs = {'chat_id': chat_id, 'message_thread_id': message_thread_id}

    def emit(kind, **fields):
        if on_event:
            on_event({'event': kind, 'draft_id': draft_id, **fields})

    send_draft(draft_id, '<tg-thinking>正在整理内容…</tg-thinking>', **kwargs)
    emit('thinking')
    last_push = time.monotonic()
    buf = []
    last_body = None
    for chunk in chunks:
        if not isinstance(chunk, str):
            raise TypeError('stream chunks must be strings')
        buf.append(chunk)
        if time.monotonic() - last_push >= interval:
            body = header + ''.join(buf)
            if body != last_body and body.strip():
                send_draft(draft_id, body, **kwargs)
                emit('draft', characters=len(body))
                last_body = body
                last_push = time.monotonic()
    final = ''.join(buf)
    if not final.strip():
        raise NativeRichError('Empty generation; no final message was sent')
    body = header + final
    if body != last_body:
        send_draft(draft_id, body, **kwargs)
        emit('draft', characters=len(body))
    result = send_message(body, **kwargs)
    emit('final', message_id=result['message_id'], block_types=[b.get('type') for b in result['rich_message']['blocks']])
    return final
