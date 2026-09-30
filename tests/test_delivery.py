from rss_pipeline import pipeline
from rss_pipeline.clients.native_rich import NativeRichError


def test_failed_delivery_is_retried_without_recollecting(database, article, monkeypatch):
    calls = []

    def send(*args, **kwargs):
        calls.append(args)
        if len(calls) == 1:
            raise NativeRichError('rejected')
        return {'message_id': 99}

    monkeypatch.setattr(pipeline.telegram, 'send_rich_message', send)
    pipeline._deliver()
    with database.conn() as c:
        assert database.get_item(c, article)['delivery_status'] == 'failed'
    pipeline._deliver()
    with database.conn() as c:
        row = database.get_item(c, article)
        assert row['delivery_status'] == 'sent'
        assert row['tg_message_id'] == 99
    pipeline._deliver()
    assert len(calls) == 2


def test_ambiguous_timeout_is_not_blindly_resent(database, article, monkeypatch):
    calls = []

    def send(*args, **kwargs):
        calls.append(True)
        raise NativeRichError('delivery unknown', unconfirmed=True)

    monkeypatch.setattr(pipeline.telegram, 'send_rich_message', send)
    pipeline._deliver()
    pipeline._deliver()
    assert len(calls) == 1
    with database.conn() as c:
        assert database.get_item(c, article)['delivery_status'] == 'unknown'


def test_old_unconfirmed_rows_do_not_flood_after_migration(tmp_path, monkeypatch):
    import sqlite3
    from rss_pipeline import db
    path = str(tmp_path / 'old.db')
    monkeypatch.setattr(db, 'DB_PATH', path)
    with sqlite3.connect(path) as c:
        c.executescript(db.SCHEMA)
        db.insert_item(c, 'HN', 'old', 'https://example.com', '', 'old', 'old')
    db.init()
    with db.conn() as c:
        assert db.delivery_queue(c) == []
        assert db.get_item(c, 1)['delivery_status'] == 'legacy'
