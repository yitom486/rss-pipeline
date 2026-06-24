"""为「深入了解」抓取素材：GitHub 项目抓 README+元信息；其他网页抓正文。"""
import re
import html
import requests

TIMEOUT = 30
UA = {"User-Agent": "Mozilla/5.0 (rss-pipeline deep-dive)"}

GH_RE = re.compile(r"github\.com/([^/]+)/([^/?#]+)")


def _strip_html(s):
    s = re.sub(r"(?is)<(script|style).*?</\1>", " ", s)
    s = re.sub(r"<[^>]+>", " ", s)
    s = html.unescape(s)
    return re.sub(r"\s+", " ", s).strip()


def fetch_material(url):
    """返回抓回来的文本素材（已截断到合理长度）。"""
    m = GH_RE.search(url)
    if m:
        return _github_material(m.group(1), m.group(2))
    return _web_material(url)


def _github_material(owner, repo):
    repo = repo.removesuffix(".git")
    parts = []
    try:
        meta = requests.get(f"https://api.github.com/repos/{owner}/{repo}",
                            headers=UA, timeout=TIMEOUT).json()
        if isinstance(meta, dict):
            parts.append(f"描述: {meta.get('description') or '无'}")
            parts.append(f"语言: {meta.get('language') or '未知'}  Stars: {meta.get('stargazers_count', '?')}")
            if meta.get("topics"):
                parts.append("标签: " + ", ".join(meta["topics"]))
    except Exception:
        pass
    try:
        readme = requests.get(
            f"https://api.github.com/repos/{owner}/{repo}/readme",
            headers={**UA, "Accept": "application/vnd.github.raw"},
            timeout=TIMEOUT,
        )
        if readme.status_code == 200:
            parts.append("\nREADME:\n" + readme.text[:6000])
    except Exception:
        pass
    return "\n".join(parts) if parts else "（未能抓到项目资料）"


def _web_material(url):
    try:
        r = requests.get(url, headers=UA, timeout=TIMEOUT)
        return _strip_html(r.text)[:6000] or "（未能抓到正文）"
    except Exception as e:
        return f"（抓取失败: {e}）"
