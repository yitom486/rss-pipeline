"""共享 HTTP 传输层。

全项目唯一直接 import requests 的地方——换 httpx / 异步 / 加重试，只改这里。
统一只做一件事：给所有出站请求一个默认超时（requests 不传 timeout 会永久挂起）。
调用方拿到的就是原生 Response，可继续用 .json()/.text/.content/.iter_lines() 等。
"""
import requests

DEFAULT_TIMEOUT = 30


def get(url, *, timeout=DEFAULT_TIMEOUT, **kwargs):
    return requests.get(url, timeout=timeout, **kwargs)


def post(url, *, timeout=DEFAULT_TIMEOUT, **kwargs):
    return requests.post(url, timeout=timeout, **kwargs)


def stream_post(url, *, timeout=DEFAULT_TIMEOUT, **kwargs):
    """流式 POST（SSE）：返回需用 `with` 管理的 Response。"""
    return requests.post(url, stream=True, timeout=timeout, **kwargs)
