"""Explicit opt-in live Telegram preview; no model requests or update polling."""
import argparse
import json
import os
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))

SECTIONS = [
    '# 你的资讯助手，可以这样读\n\n',
    '这是一条**原生富文本流式体验样例**，不是今日新闻，也不是模型实时生成的分析。它会逐步展开，最后完整保存在聊天里。\n\n',
    '以后读到一个新项目，我希望先让你知道它为什么值得关注：它解决了什么问题，背后的方法有什么不同，以及你是否真的有必要花时间了解。正文可以自然地展开，而不是每次都套用同一张资讯卡片。\n\n',
    '## 多一点理解，少一点模板\n\n一篇有用的解读应该把原文中的关键事实讲清楚，再解释背景和采用条件。作者的主张、社区的讨论和助手的判断需要分开；资料不足时，直接说明缺少什么。\n\n',
    '> 阅读体验的目标：你看完能够判断“这与我有什么关系”，还可以选择继续深入。\n\n',
    '| 阅读方式 | 你会得到什么 |\n| --- | --- |\n| 速读 | 快速抓住变化与价值 |\n| 深入解读 | 背景、机制、影响与局限 |\n| 技术视角 | 实现方法与采用条件 |\n\n',
    '<details>\n<summary>展开看看：更深入的内容可以放在这里</summary>\n\n默认正文保持自然可读，额外的实现细节、补充背景或对比可以放在折叠区域。你可以按需要展开，不必每次被一长串固定栏目打断。\n\n这次只测试折叠显示；真正的取材、总结模式、收藏和追问功能会在你确认体验后继续开发。\n</details>\n\n',
    '---\n\n<tg-button-row>\n<tg-button type="url" style="primary" url="https://core.telegram.org/bots/features#rich-messages">查看原生富文本说明</tg-button>\n<tg-button type="copy_text" text="我看到了原生流式输出，标题、表格、折叠详情和按钮显示正常。">复制体验反馈</tg-button>\n</tg-button-row>\n\n*请在当前开发对话中反馈显示效果；这条消息的“复制体验反馈”按钮只负责复制文字，不代表自动批准。*',
]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--env-file', required=True)
    parser.add_argument('--send', action='store_true', help='Send one preview to the configured chat')
    args = parser.parse_args()
    if not args.send:
        parser.error('--send is required for the live preview')
    for line in Path(args.env_file).read_text().splitlines():
        key, sep, value = line.strip().partition('=')
        if sep and key and not key.startswith('#'):
            os.environ.setdefault(key.strip(), value.strip())
    from rss_pipeline.clients import native_rich

    def chunks():
        for section in SECTIONS:
            time.sleep(1.3)
            yield section

    def report(event):
        print(json.dumps(event, ensure_ascii=False), flush=True)

    try:
        native_rich.stream(chunks(), on_event=report)
    except (native_rich.NativeRichError, ValueError, TypeError) as exc:
        print(json.dumps({'event': 'failed', 'reason': str(exc)}, ensure_ascii=False), flush=True)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
