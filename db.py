"""SQLite 数据层：待审/已发布用 status 字段区分。"""
import sqlite3
import time
from config import DB_PATH

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


def conn():
    c = sqlite3.connect(DB_PATH, timeout=30)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA journal_mode=WAL")
    return c


def init():
    with conn() as c:
        c.executescript(SCHEMA)


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
    c.execute("UPDATE items SET tg_message_id=?, updated_at=? WHERE id=?",
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


if __name__ == "__main__":
    init()
    print("DB 初始化完成:", DB_PATH)
