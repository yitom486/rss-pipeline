"""SQLite 数据层：待审/已发布用 status 字段区分。"""
import sqlite3
import time
from contextlib import contextmanager
from .config import DB_PATH

SCHEMA = """
CREATE TABLE IF NOT EXISTS items (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    source       TEXT NOT NULL,
    title        TEXT NOT NULL,
    url          TEXT NOT NULL UNIQUE,
    orig_desc    TEXT,
    zh_title     TEXT,
    zh_summary   TEXT,
    status       TEXT NOT NULL DEFAULT 'pending',  -- pending|approved|discarded|published
    tg_message_id INTEGER,
    created_at   INTEGER NOT NULL,
    updated_at   INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_status ON items(status);
"""


@contextmanager
def conn():
    c = sqlite3.connect(DB_PATH, timeout=30)
    try:
        c.row_factory = sqlite3.Row
        c.execute("PRAGMA journal_mode=WAL")
        with c:
            yield c
    finally:
        c.close()


def init():
    with conn() as c:
        c.executescript(SCHEMA)
        columns = {r['name'] for r in c.execute('PRAGMA table_info(items)')}
        additions = {
            'material': "TEXT NOT NULL DEFAULT ''",
            'material_updated_at': 'INTEGER NOT NULL DEFAULT 0',
            'delivery_status': "TEXT NOT NULL DEFAULT 'queued'",
            'delivery_error': "TEXT NOT NULL DEFAULT ''",
            'delivery_attempts': 'INTEGER NOT NULL DEFAULT 0',
            'collection_task_id': 'INTEGER',
        }
        for name, declaration in additions.items():
            if name not in columns:
                c.execute(f'ALTER TABLE items ADD COLUMN {name} {declaration}')
                if name == 'delivery_status':
                    # Do not flood the user with old unsent rows after migration.
                    c.execute("UPDATE items SET delivery_status=CASE WHEN tg_message_id IS NOT NULL THEN 'sent' ELSE 'legacy' END")
        c.executescript(ASSISTANT_SCHEMA)
        session_columns = {r['name'] for r in c.execute('PRAGMA table_info(sessions)')}
        if 'model' not in session_columns:
            c.execute('ALTER TABLE sessions ADD COLUMN model TEXT')


def url_exists(c, url):
    return c.execute("SELECT 1 FROM items WHERE url=?", (url,)).fetchone() is not None


def insert_item(c, source, title, url, orig_desc, zh_title, zh_summary):
    now = int(time.time())
    cur = c.execute(
        """INSERT INTO items (source,title,url,orig_desc,zh_title,zh_summary,status,created_at,updated_at)
           VALUES (?,?,?,?,?,?, 'pending', ?, ?)""",
        (source, title, url, orig_desc, zh_title, zh_summary, now, now),
    )
    return cur.lastrowid


def set_tg_message_id(c, item_id, message_id):
    c.execute("UPDATE items SET tg_message_id=?, delivery_status='sent', delivery_error='', updated_at=? WHERE id=?",
              (message_id, int(time.time()), item_id))


def get_item(c, item_id):
    return c.execute("SELECT * FROM items WHERE id=?", (item_id,)).fetchone()


def set_status(c, item_id, status):
    c.execute("UPDATE items SET status=?, updated_at=? WHERE id=?",
              (status, int(time.time()), item_id))


def list_by_status(c, status, limit=10):
    return c.execute(
        "SELECT id,source,zh_title,url FROM items WHERE status=? ORDER BY id DESC LIMIT ?",
        (status, limit),
    ).fetchall()


def search(c, keyword, limit=10):
    kw = f"%{keyword}%"
    return c.execute(
        """SELECT id,source,zh_title,url,status FROM items
           WHERE zh_title LIKE ? OR zh_summary LIKE ? OR title LIKE ?
           ORDER BY id DESC LIMIT ?""",
        (kw, kw, kw, limit),
    ).fetchall()


def stats(c):
    rows = c.execute("SELECT status, COUNT(*) n FROM items GROUP BY status").fetchall()
    return {r["status"]: r["n"] for r in rows}



ASSISTANT_SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id TEXT NOT NULL, name TEXT NOT NULL, thread_id TEXT,
    active INTEGER NOT NULL DEFAULT 0, current_item_id INTEGER,
    created_at INTEGER NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_one_active_session ON sessions(chat_id) WHERE active=1;
CREATE TABLE IF NOT EXISTS preferences (
    chat_id TEXT NOT NULL, key TEXT NOT NULL, value TEXT NOT NULL,
    updated_at INTEGER NOT NULL, PRIMARY KEY(chat_id,key)
);
CREATE TABLE IF NOT EXISTS reports (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id TEXT NOT NULL, session_id INTEGER NOT NULL,
    title TEXT NOT NULL, content TEXT NOT NULL, created_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS conversations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id TEXT NOT NULL, role TEXT NOT NULL, content TEXT NOT NULL,
    created_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_conversation ON conversations(chat_id,id);
CREATE TABLE IF NOT EXISTS reader_state (
    chat_id TEXT PRIMARY KEY, current_item_id INTEGER,
    preferred_mode TEXT NOT NULL DEFAULT 'detail'
);
CREATE TABLE IF NOT EXISTS saved_items (
    chat_id TEXT NOT NULL, item_id INTEGER NOT NULL,
    created_at INTEGER NOT NULL, PRIMARY KEY(chat_id,item_id)
);
CREATE TABLE IF NOT EXISTS interest_feedback (
    chat_id TEXT NOT NULL, item_id INTEGER NOT NULL,
    preference TEXT NOT NULL, updated_at INTEGER NOT NULL,
    PRIMARY KEY(chat_id,item_id)
);
CREATE TABLE IF NOT EXISTS tasks (
    id INTEGER PRIMARY KEY AUTOINCREMENT, chat_id TEXT NOT NULL,
    kind TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'running',
    message_id INTEGER, created_at INTEGER NOT NULL, updated_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS task_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT, task_id INTEGER NOT NULL,
    event TEXT NOT NULL, message TEXT NOT NULL, tool TEXT, status TEXT,
    created_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_task_owner ON tasks(chat_id,id);
CREATE INDEX IF NOT EXISTS idx_task_events ON task_events(task_id,id);
"""


def start_task(chat_id, kind):
    now = int(time.time())
    with conn() as c:
        return c.execute('INSERT INTO tasks(chat_id,kind,created_at,updated_at) VALUES (?,?,?,?)',
                         (str(chat_id), kind, now, now)).lastrowid


def task_event(task_id, value):
    from .activity import public_text
    with conn() as c:
        c.execute('INSERT INTO task_events(task_id,event,message,tool,status,created_at) VALUES (?,?,?,?,?,?)',
                  (task_id, value['event'], public_text(value['message']), value.get('tool'),
                   value.get('status'), int(time.time())))
        c.execute('DELETE FROM task_events WHERE task_id=? AND id NOT IN '
                  '(SELECT id FROM task_events WHERE task_id=? ORDER BY id DESC LIMIT 500)', (task_id, task_id))
        c.execute('UPDATE tasks SET updated_at=? WHERE id=?', (int(time.time()), task_id))


def finish_task(task_id, status, message_id=None):
    with conn() as c:
        c.execute('UPDATE tasks SET status=?,message_id=?,updated_at=? WHERE id=?',
                  (status, message_id, int(time.time()), task_id))


def recover_tasks(kind):
    with conn() as c:
        rows = c.execute("SELECT id FROM tasks WHERE kind=? AND status='running'", (kind,)).fetchall()
        for row in rows:
            c.execute("UPDATE tasks SET status='unknown',updated_at=? WHERE id=?", (int(time.time()), row['id']))
            c.execute('INSERT INTO task_events(task_id,event,message,status,created_at) VALUES (?,?,?,?,?)',
                      (row['id'], 'process_interrupted', '上次任务进程已中断，执行结果待确认', 'unknown', int(time.time())))


def tasks(chat_id, limit=5):
    with conn() as c:
        return [dict(r) for r in c.execute('SELECT t.*, (SELECT message FROM task_events e WHERE e.task_id=t.id ORDER BY e.id DESC LIMIT 1) AS latest_event '
                                           'FROM tasks t WHERE chat_id=? ORDER BY t.id DESC LIMIT ?',
                                           (str(chat_id), limit))]


def trace(chat_id, task_id):
    with conn() as c:
        if not c.execute('SELECT 1 FROM tasks WHERE id=? AND chat_id=?', (task_id, str(chat_id))).fetchone():
            raise ValueError('任务不存在')
        return [dict(r) for r in c.execute('SELECT * FROM task_events WHERE task_id=? ORDER BY id', (task_id,))]


def save_material(c, item_id, text):
    c.execute('UPDATE items SET material=?, material_updated_at=? WHERE id=?',
              (text, int(time.time()), item_id))


def delivery_queue(c, limit=20):
    return c.execute("SELECT * FROM items WHERE delivery_status IN ('queued','failed') AND status != 'discarded' ORDER BY id LIMIT ?", (limit,)).fetchall()


def set_delivery(c, item_id, status, error=''):
    c.execute('UPDATE items SET delivery_status=?, delivery_error=?, updated_at=?, delivery_attempts=delivery_attempts+? WHERE id=?',
              (status, error[:500], int(time.time()), int(status == 'sending'), item_id))


def history(chat_id, limit=20):
    with conn() as c:
        rows = c.execute('SELECT role,content FROM conversations WHERE chat_id=? ORDER BY id DESC LIMIT ?', (str(chat_id), limit)).fetchall()
    return [dict(r) for r in reversed(rows)]


def remember(chat_id, user, assistant):
    with conn() as c:
        c.executemany('INSERT INTO conversations(chat_id,role,content,created_at) VALUES (?,?,?,?)',
                      [(str(chat_id), 'user', user, int(time.time())), (str(chat_id), 'assistant', assistant, int(time.time()))])
        c.execute('DELETE FROM conversations WHERE chat_id=? AND id NOT IN (SELECT id FROM conversations WHERE chat_id=? ORDER BY id DESC LIMIT 40)', (str(chat_id), str(chat_id)))


def reset_history(chat_id):
    with conn() as c:
        c.execute('DELETE FROM conversations WHERE chat_id=?', (str(chat_id),))
        c.execute('UPDATE reader_state SET current_item_id=NULL WHERE chat_id=?', (str(chat_id),))


def set_current(chat_id, item_id):
    session = active_session(chat_id)
    with conn() as c:
        c.execute('UPDATE sessions SET current_item_id=? WHERE id=? AND chat_id=?', (item_id, session['id'], str(chat_id)))


def current(chat_id):
    session = active_session(chat_id)
    with conn() as c:
        return c.execute('SELECT * FROM items WHERE id=?', (session['current_item_id'],)).fetchone()


def toggle_saved(chat_id, item_id):
    with conn() as c:
        row = c.execute('SELECT 1 FROM saved_items WHERE chat_id=? AND item_id=?', (str(chat_id), item_id)).fetchone()
        if row:
            c.execute('DELETE FROM saved_items WHERE chat_id=? AND item_id=?', (str(chat_id), item_id))
            return False
        c.execute('INSERT INTO saved_items VALUES (?,?,?)', (str(chat_id), item_id, int(time.time())))
        return True


def saved(chat_id):
    with conn() as c:
        return c.execute('SELECT items.* FROM items JOIN saved_items ON items.id=saved_items.item_id WHERE chat_id=? ORDER BY saved_items.created_at DESC LIMIT 20', (str(chat_id),)).fetchall()


def feedback(chat_id, item_id, preference):
    if preference not in ('more','less'):
        raise ValueError('Invalid interest feedback')
    with conn() as c:
        c.execute('INSERT INTO interest_feedback VALUES (?,?,?,?) ON CONFLICT(chat_id,item_id) DO UPDATE SET preference=excluded.preference,updated_at=excluded.updated_at',
                  (str(chat_id), item_id, preference, int(time.time())))


def feedback_context(chat_id):
    with conn() as c:
        rows = c.execute('SELECT items.zh_title,interest_feedback.preference FROM interest_feedback JOIN items ON items.id=interest_feedback.item_id WHERE chat_id=? ORDER BY interest_feedback.updated_at DESC LIMIT 10', (str(chat_id),)).fetchall()
    return [dict(r) for r in rows]


_session_lock = __import__('threading').RLock()


def new_session(chat_id, name='新会话'):
    with _session_lock, conn() as c:
        c.execute('UPDATE sessions SET active=0 WHERE chat_id=?', (str(chat_id),))
        cur = c.execute('INSERT INTO sessions(chat_id,name,active,created_at) VALUES (?,?,1,?)',
                        (str(chat_id), name[:100] or '新会话', int(time.time())))
        return dict(c.execute('SELECT * FROM sessions WHERE id=?', (cur.lastrowid,)).fetchone())


def active_session(chat_id):
    with _session_lock, conn() as c:
        row = c.execute('SELECT * FROM sessions WHERE chat_id=? AND active=1', (str(chat_id),)).fetchone()
        return dict(row) if row else new_session(chat_id, '默认会话')


def sessions(chat_id):
    with conn() as c:
        return [dict(r) for r in c.execute('SELECT * FROM sessions WHERE chat_id=? ORDER BY id DESC LIMIT 30', (str(chat_id),))]


def switch_session(chat_id, session_id):
    with _session_lock, conn() as c:
        row = c.execute('SELECT * FROM sessions WHERE id=? AND chat_id=?', (session_id, str(chat_id))).fetchone()
        if not row:
            raise ValueError('会话不存在或不属于当前用户')
        c.execute('UPDATE sessions SET active=0 WHERE chat_id=?', (str(chat_id),))
        c.execute('UPDATE sessions SET active=1 WHERE id=?', (session_id,))
        return dict(row)


def bind_thread(chat_id, session_id, thread_id):
    with conn() as c:
        cur = c.execute('UPDATE sessions SET thread_id=? WHERE id=? AND chat_id=?', (thread_id, session_id, str(chat_id)))
        if cur.rowcount != 1:
            raise ValueError('Invalid session owner')


def set_preference(chat_id, key, value):
    key, value = key.strip(), value.strip()
    if not key or len(key) > 80 or len(value) > 2000:
        raise ValueError('偏好名称最多 80 字，内容最多 2000 字')
    with conn() as c:
        if value:
            c.execute('INSERT INTO preferences VALUES (?,?,?,?) ON CONFLICT(chat_id,key) DO UPDATE SET value=excluded.value,updated_at=excluded.updated_at', (str(chat_id), key, value, int(time.time())))
        else:
            c.execute('DELETE FROM preferences WHERE chat_id=? AND key=?', (str(chat_id), key))


def preferences(chat_id):
    with conn() as c:
        return {r['key']: r['value'] for r in c.execute('SELECT key,value FROM preferences WHERE chat_id=? ORDER BY key', (str(chat_id),))}


def save_report(chat_id, session_id, title, content):
    if not title.strip() or not content.strip() or len(content) > 150000:
        raise ValueError('报告标题/内容为空或过长')
    with conn() as c:
        owner = c.execute('SELECT 1 FROM sessions WHERE id=? AND chat_id=?', (session_id, str(chat_id))).fetchone()
        if not owner:
            raise ValueError('Invalid session owner')
        cur = c.execute('INSERT INTO reports(chat_id,session_id,title,content,created_at) VALUES (?,?,?,?,?)',
                        (str(chat_id), session_id, title[:200], content, int(time.time())))
        return cur.lastrowid


def report(chat_id, report_id):
    with conn() as c:
        row = c.execute('SELECT * FROM reports WHERE id=? AND chat_id=?', (report_id, str(chat_id))).fetchone()
        return dict(row) if row else None


def list_reports(chat_id):
    with conn() as c:
        return [dict(r) for r in c.execute('SELECT id,title,session_id,created_at FROM reports WHERE chat_id=? ORDER BY id DESC LIMIT 20', (str(chat_id),))]



def set_model(chat_id, session_id, model):
    with conn() as c:
        cur = c.execute('UPDATE sessions SET model=? WHERE id=? AND chat_id=?', (model, session_id, str(chat_id)))
        if cur.rowcount != 1:
            raise ValueError('Invalid session owner')
