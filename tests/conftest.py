import pytest
from rss_pipeline import db


@pytest.fixture
def database(tmp_path, monkeypatch):
    monkeypatch.setattr(db, 'DB_PATH', str(tmp_path / 'test.db'))
    db.init()
    yield db


@pytest.fixture
def article(database):
    with database.conn() as c:
        item_id = database.insert_item(c, 'Hacker News', 'Original title', 'https://example.com/news',
                                       'RSS preview', '中文标题', '解读正文')
    return item_id
