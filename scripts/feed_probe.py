"""Read public feeds without Codex, database writes or Telegram sends."""
from rss_pipeline import config, feeds


def main():
    failed = False
    for source, route, limit in config.SOURCES:
        if not route.startswith(('https://', 'http://')):
            continue
        try:
            rows = feeds.fetch(route, limit)
            if not rows:
                raise ValueError('No valid articles')
            print(f'{source}: OK, {len(rows)} articles; first title: {rows[0][0]}', flush=True)
        except Exception as exc:
            print(f'{source}: FAILED ({type(exc).__name__})', flush=True)
            failed = True
    return int(failed)


if __name__ == '__main__':
    raise SystemExit(main())
