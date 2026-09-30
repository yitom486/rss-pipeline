"""Compatibility facade; conversation state lives in Codex threads, not local lists."""
from .. import codex_agent, db


def handle_stream(user_text, chat_id=None, max_steps=4, cancel_event=None):
    if chat_id is None:
        raise ValueError('A chat owner is required for a persistent session')
    yield from codex_agent.reply(user_text, chat_id, cancel_event=cancel_event)


def handle(user_text, chat_id=None, max_steps=4):
    return ''.join(handle_stream(user_text, chat_id=chat_id, max_steps=max_steps))


def reset_history(chat_id):
    # Never destroy a Codex thread on reset; create a distinct conversation instead.
    return db.new_session(chat_id, '新会话')
