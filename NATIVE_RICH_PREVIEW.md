# Telegram 原生富文本预览

## 范围

这是独立开发工作树中的传输预览，不是线上部署。仅流式回复路径改为原生富文本；既有普通消息辅助方法、采集卡片及线上根目录脚本尚未迁移。用户确认显示效果后再继续完整迁移。

原生传输实现：`src/rss_pipeline/clients/native_rich.py`。

- `sendRichMessageDraft` 更新相同非零 draft_id，`sendRichMessage` 保存最终内容。
- 内容格式支持 markdown、html 或 blocks，三者只能使用一种。
- 不调用 sendMessageDraft 或普通 sendMessage 作为回退。
- 每个聊天的草稿在本进程内以至少 1.1 秒间隔发送；429 按 retry_after 有界重试。其他进程使用同一 Bot 时仍需后续集中限流。
- 网络超时不自动重发最终消息，防止无法确认送达状态时重复发送；错误不暴露 Token。
- can_stop、keep_on_stop、message_thread_id 可传入底层方法。预览未实现停止事件消费，因此不启用停止按钮。
- 当前同步流要求调用方持续产出内容；长期取材等待、草稿续期、完整模型取消及长回复分页属于后续开发范围。

## 官方文档基线

2026-09-30 核对：Bot API 10.3（2026-08-24）。

- https://core.telegram.org/bots/api#inputrichmessage
- https://core.telegram.org/bots/api#sendrichmessagedraft
- https://core.telegram.org/bots/api#sendrichmessage
- https://core.telegram.org/bots/api#rich-html-style
- https://core.telegram.org/api/bots/ai#live-response-streaming

## 验证

离线测试，不需要凭据或网络：

```bash
uv run pytest tests/test_native_rich.py -v
```

6 项测试通过：原生草稿到最终消息的内容一致性、原生失败不回退、429 重试、超时不重发且不泄露凭据、最终响应原生类型确认、空输出不发送最终消息。

已执行一次真实发送（此命令再次执行会发送新的测试消息）：

```bash
uv run python scripts/native_rich_demo.py \
  --env-file /root/rss-pipeline/.env --send
```

该命令只读现有配置，不修改凭据；使用固定内容模拟生成增量，不调用模型、不读取 Telegram 更新。

## 本次 E2E 结果

- 日期：2026-09-30 UTC。
- 初次沙箱网络请求失败；获准联网后运行成功。
- 思考状态草稿：成功。
- 正文草稿更新：8 次，使用同一 draft_id 47667575。
- 最终消息：message_id 1446。
- API 返回原生 rich_message，块类型为 heading、paragraph、blockquote、table、details、divider、buttons。
- 示例按钮只打开官方文档或复制反馈文字，不包含尚未实现的动作。
- API 验证已通过；用户客户端视觉与流畅度验收仍待确认。
- 未重启线上机器人、修改 cron/systemd 或继续完整资讯助手改造。
