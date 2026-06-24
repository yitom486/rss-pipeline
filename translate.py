"""翻译/摘要模块。可换厂商：通过 TRANSLATE_PROVIDER 切换，对外只暴露两个函数。"""
import json
import requests
import config

TIMEOUT = 60


def _deepseek_chat(system, user, max_tokens=800):
    r = requests.post(
        f"{config.DEEPSEEK_BASE}/chat/completions",
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {config.DEEPSEEK_API_KEY}",
        },
        json={
            "model": config.DEEPSEEK_MODEL,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "max_tokens": max_tokens,
            "temperature": 0.3,
        },
        timeout=TIMEOUT,
    )
    r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"].strip()


def _chat(system, user, max_tokens=800):
    """统一入口，将来加 anthropic 等只需在这里分支。"""
    if config.TRANSLATE_PROVIDER == "deepseek":
        return _deepseek_chat(system, user, max_tokens)
    raise ValueError(f"未知翻译厂商: {config.TRANSLATE_PROVIDER}")


def translate_summarize(title, desc):
    """把一条英文新闻翻成中文标题 + 提炼要点。返回 (zh_title, zh_summary)。"""
    system = (
        "你是科技资讯编辑。把英文技术新闻翻译成简洁中文并提炼要点。"
        "严格只输出 JSON，格式：{\"title\":\"中文标题\",\"summary\":\"2-3句中文要点\"}，不要任何额外文字。"
    )
    user = f"标题：{title}\n\n内容：{desc[:1500]}"
    raw = _chat(system, user, max_tokens=500)
    # 容错：去掉可能的 ```json 包裹
    raw = raw.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    try:
        d = json.loads(raw)
        return d.get("title", title).strip(), d.get("summary", "").strip()
    except json.JSONDecodeError:
        # 解析失败时退化：标题用原文，摘要用整段返回
        return title, raw[:300]


_DIVE_SYSTEM = (
    "你是技术分析师。根据提供的项目资料，用中文写一份通俗的深入介绍，"
    "包含：①这是什么 ②解决什么问题 ③核心亮点 ④适合谁用。控制在 400 字内，分点清晰。"
)


def deep_dive(title, url, material):
    """对一个项目/文章做深入中文汇总。material 是抓回来的 README/正文。"""
    user = f"项目名：{title}\n链接：{url}\n\n资料：\n{material[:6000]}"
    return _chat(_DIVE_SYSTEM, user, max_tokens=900)


def deep_dive_stream(title, url, material, max_tokens=900):
    """流式版深入了解：逐段 yield 增量文本。仅支持 deepseek。"""
    if config.TRANSLATE_PROVIDER != "deepseek":
        # 不支持流式的厂商：退化为一次性返回
        yield deep_dive(title, url, material)
        return
    user = f"项目名：{title}\n链接：{url}\n\n资料：\n{material[:6000]}"
    with requests.post(
        f"{config.DEEPSEEK_BASE}/chat/completions",
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {config.DEEPSEEK_API_KEY}",
        },
        json={
            "model": config.DEEPSEEK_MODEL,
            "messages": [
                {"role": "system", "content": _DIVE_SYSTEM},
                {"role": "user", "content": user},
            ],
            "max_tokens": max_tokens,
            "temperature": 0.3,
            "stream": True,
        },
        timeout=TIMEOUT,
        stream=True,
    ) as r:
        r.raise_for_status()
        for line in r.iter_lines(decode_unicode=True):
            if not line or not line.startswith("data:"):
                continue
            payload = line[5:].strip()
            if payload == "[DONE]":
                break
            try:
                delta = json.loads(payload)["choices"][0]["delta"].get("content")
            except (json.JSONDecodeError, KeyError, IndexError):
                continue
            if delta:
                yield delta
