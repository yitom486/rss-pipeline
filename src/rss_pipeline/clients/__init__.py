"""出站 I/O 客户端层：HTTP / Telegram / LLM。

所有对外的网络调用都收口在这一层——将来从 requests 换 httpx、
从同步换异步，原则上只动这个子包，业务逻辑（feeds/translate/agent…）不受影响。
"""
