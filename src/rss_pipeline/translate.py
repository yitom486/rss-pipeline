"""翻译/摘要业务逻辑。可换厂商：通过 TRANSLATE_PROVIDER 切换；HTTP/SSE 细节在 clients.llm。"""
import json
from . import config
from .clients import llm


def _chat(system, user, max_tokens=800):
    """统一入口，将来加 anthropic 等只需在这里分支。"""
    if config.TRANSLATE_PROVIDER == "deepseek":
        msg = llm.chat(
            [{"role": "system", "content": system},
             {"role": "user", "content": user}],
            max_tokens=max_tokens, temperature=0.3,
        )
        return (msg.get("content") or "").strip()
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
    """流式版深入了解：逐段 yield 增量文本。仅 deepseek 走真流式，其余退化为一次性返回。"""
    if config.TRANSLATE_PROVIDER != "deepseek":
        yield deep_dive(title, url, material)
        return
    user = f"项目名：{title}\n链接：{url}\n\n资料：\n{material[:6000]}"
    yield from llm.chat_stream(
        [{"role": "system", "content": _DIVE_SYSTEM},
         {"role": "user", "content": user}],
        max_tokens=max_tokens, temperature=0.3,
    )
