"""Application-owned diagram-design guidance, static rendering and media ownership."""
import re
import tempfile
import subprocess
import uuid
from pathlib import Path
import xml.etree.ElementTree as ET

from . import config, db

TYPES = ('flowchart', 'architecture', 'sequence', 'state', 'tree', 'data-flow',
         'layers', 'process', 'timeline', 'bar', 'line', 'deployment')
MEDIA_RE = re.compile(r'tg://photo\?id=(diagram_[0-9a-f]{32})(?![0-9a-z_])')


def guide(kind):
    root = Path(config.DIAGRAM_SKILL_PATH)
    if kind not in TYPES:
        raise ValueError('Unsupported diagram type')
    if config.DIAGRAM_STYLE not in ('default', 'blue'):
        return {'ready': False, 'reason': 'diagram-design 首次绘图配色尚未确认，继续提供文本解读。'}
    files = ['SKILL.md', 'references/style-guide.md', f'references/type-{kind}.md',
             'references/output-spec.md', 'references/primitives-core.md']
    if kind in ('flowchart', 'architecture', 'state', 'data-flow', 'layers', 'process'):
        files.append('references/semantic-patterns.md')
    parts = {name: (root / name).read_text(encoding='utf-8') for name in files}
    return {'ready': True, 'kind': kind, 'references': parts, 'style': config.DIAGRAM_STYLE,
            'application_contract': '用户已授权绘图并导出 PNG。按 skill 生成静态、自包含 HTML+SVG；'
            '选 doc-inline 尺寸，中文短标签，最多九节点。不使用 Mermaid，不使用动画、脚本或外部资源。'
            '绘图计划简短公开说明后，将 HTML 交给 news_draw_diagram，程序执行 self_check 并渲染 PNG。'
            '宿主使用本地系统字体（含中文回退），不下载远程品牌字体；蓝色风格选 #2e5aa8 为重点，否则保留默认色。'
            '这是应用对既定资讯任务的导出授权，不需要每篇重复询问是否导出或保存个人品牌 profile。'}


def render(document):
    if not isinstance(document, str) or len(document) > 100000:
        raise ValueError('Diagram HTML exceeds the supported size')
    if re.search(r'<\s*(script|iframe|object|embed)\b|\bon\w+\s*=', document, re.I):
        raise ValueError('Only static diagrams are supported')
    match = re.search(r'<svg\b.*?</svg\s*>', document, re.I | re.S)
    if not match or re.search(r'<!\s*(DOCTYPE|ENTITY)', match[0], re.I):
        raise ValueError('A static inline SVG is required')
    try:
        svg = ET.fromstring(match[0])
        _, _, width, height = map(float, svg.attrib['viewBox'].split())
    except (ET.ParseError, KeyError, ValueError):
        raise ValueError('SVG requires a valid viewBox') from None
    if not (200 <= width <= 2000 and 100 <= height <= 2000):
        raise ValueError('Diagram dimensions exceed the reading preset')
    with tempfile.TemporaryDirectory(prefix='news-diagram-') as folder:
        source = Path(folder) / 'diagram.html'
        source.write_text(document, encoding='utf-8')
        check = subprocess.run(['uv', 'run', 'python', str(Path(config.DIAGRAM_SKILL_PATH) / 'scripts/self_check.py'),
                                str(source)], capture_output=True, text=True, timeout=20)
        if check.returncode:
            raise ValueError('Diagram self_check failed: ' + check.stdout[-1600:] + check.stderr[-400:])
        from playwright.sync_api import sync_playwright
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(timeout=20000)
            try:
                page = browser.new_page(device_scale_factor=2, java_script_enabled=False,
                                        viewport={'width': 2200, 'height': 2200})
                # Rendering cannot fetch source URLs, local files or external fonts.
                page.route('**/*', lambda route: route.abort())
                css = (f'svg {{width: {width}px !important; height: {height}px !important;'
                    'min-width: 0 !important; overflow: visible !important;} '
                    '* {font-family: Arial, "WenQuanYi Zen Hei", sans-serif !important;} '
                    'body, main, div {overflow: visible !important;}')
                prepared = re.sub(r'<link\b[^>]*>', '', document, flags=re.I)
                prepared = re.sub(r'@import\b[^;]+;', '', prepared, flags=re.I)
                # Inject before parsing: add_style_tag relies on script callbacks,
                # which never fire when JavaScript is disabled in this context.
                prepared += '<style>' + css + '</style>'
                page.set_content(prepared, wait_until='domcontentloaded', timeout=15000)
                figure = page.locator('svg').first
                bounds = figure.bounding_box()
                if not bounds or not (100 <= bounds['width'] <= 2100 and 100 <= bounds['height'] <= 2100):
                    raise ValueError('Rendered diagram size is unsuitable')
                png = figure.screenshot(omit_background=True, timeout=15000)
            finally:
                browser.close()
    if len(png) > 8_000_000:
        raise ValueError('Diagram PNG exceeds upload budget')
    return png


def save(binding, title, document):
    png = render(document)
    asset_id = 'diagram_' + uuid.uuid4().hex
    with db.conn() as connection:
        connection.execute('INSERT INTO diagram_assets(id,chat_id,title,html,png) VALUES(?,?,?,?,?)',
                           (asset_id, binding['chat_id'], title, document, png))
    binding.setdefault('diagrams', []).append(asset_id)
    return {'asset_id': asset_id, 'markdown': f'![AI 示意图：{title}](tg://photo?id={asset_id})',
            'format': 'png', 'rendered': True, 'note': '图为 AI 根据资料绘制的解释示意，非原文配图。'}


def attachments(markdown, *, chat_id=None, allowed=None):
    ids = list(dict.fromkeys(MEDIA_RE.findall(markdown)))
    if allowed is not None and not set(ids) <= set(allowed):
        raise ValueError('Diagram does not belong to this task')
    files, media = {}, []
    if not ids:
        return media, files
    with db.conn() as connection:
        for asset_id in ids:
            row = connection.execute('SELECT * FROM diagram_assets WHERE id=? AND chat_id=?',
                                     (asset_id, str(chat_id or config.TELEGRAM_CHAT_ID))).fetchone()
            if row is None:
                raise ValueError('Diagram is unavailable for this user')
            files[asset_id] = (asset_id + '.png', bytes(row['png']), 'image/png')
            media.append({'id': asset_id, 'media': {'type': 'photo', 'media': 'attach://' + asset_id}})
    return media, files
