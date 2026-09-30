"""Pooled HTTPX transport; bounded connect/read/write/pool timeouts."""
import atexit
import httpx

_client = httpx.Client(timeout=httpx.Timeout(30, connect=8, pool=10), follow_redirects=True,
                       limits=httpx.Limits(max_connections=20, max_keepalive_connections=10))
atexit.register(_client.close)


def _timeout(value):
    if isinstance(value, tuple):
        return httpx.Timeout(value[1], connect=value[0], pool=10)
    return httpx.Timeout(value, connect=min(value, 8), pool=10)


def get(url, *, timeout=30, stream=False, **kwargs):
    if stream:
        return _client.stream('GET', url, timeout=_timeout(timeout), **kwargs)
    return _client.get(url, timeout=_timeout(timeout), **kwargs)


def post(url, *, timeout=30, **kwargs):
    return _client.post(url, timeout=_timeout(timeout), **kwargs)


def stream_post(url, *, timeout=30, **kwargs):
    return _client.stream('POST', url, timeout=_timeout(timeout), **kwargs)
