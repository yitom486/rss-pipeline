# 开发与验证记录

日期：2026-09-30 UTC。开发工作树 `/root/rss-native-preview`，分支 `feature/news-assistant-v1`。

## 已通过

- 用户已确认原生富文本流式样例的阅读体验；对应真实 Telegram 消息 ID 1446，见 `NATIVE_RICH_PREVIEW.md`。
- `uv sync`：锁定依赖；生产网络依赖为 HTTPX，已移除 requests。
- `uv run pytest`：30 项离线行为测试；使用临时数据库与模拟网络，不发送消息。
- 测试覆盖：原生消息不回退、429 重试、发送超时不盲目重发、跨用户会话/报告隔离、偏好持久化、切换模型保留 thread、同一条资讯继续会话、停止事件鉴权、取消调用 turn/interrupt、报告分页不丢字符、来源数据与无效模型输出处理。
- `uv run python scripts/check_codex_protocol.py`：通过当前 CLI 0.159.2 的 experimental JSON Schema 校验 thread/start、thread/resume、动态工具响应。
- `uv run python .../skill-creator/scripts/quick_validate.py .agents/skills/news-assistant`：官方 skill 格式校验通过。
- `uv run python -m compileall -q src scripts` 和 `git diff --check` 通过。

## 真实 Codex 验证

执行 `uv run python scripts/codex_probe.py --inference`，使用现有 ChatGPT 登录和独立临时数据库；未发送 Telegram 消息。

- App Server 完成 initialize / initialized 握手。
- account/read 确认登录类型 chatgpt；未读取/输出认证内容。
- model/list 返回 8 个目录条目，默认 gpt-6.1-sol；目录不等于每个模型的权限验证。
- thread/start 的 instructionSources 确认加载 `/root/rss-native-preview/AGENTS.md`。
- 第一轮记住测试代号；关闭并重启 App Server 后 resume 原 thread，正确回答代号。
- 实际动态调用 news_remember_preference，将测试偏好保存到隔离数据库。
- 实际动态调用 news_save_report，保存报告并取得报告编号。
- 新建另一个 thread 后，仍正确使用应用提供的长期偏好。
- 切回第一会话，仍保留原 thread_id。
- 结构化摘要使用虚构且明确标注的来源资料：实际返回有效 JSON、自然中文段落，并说明缺少性能、许可证和安全性证据，没有把演示项目当作真实新闻。

## 范围与尚未验证的事项

- 当前为可运行开发版本，未替换线上 `/root/rss-pipeline` 的代码、cron 或 systemd 服务。
- 最新完整 bot 尚未与线上 bot 同时轮询，也没有额外向用户发送测试消息。
- 原生传输样例和 Codex 真实验证分别通过；完整线上 Telegram → Codex → Telegram 的连续对话需在部署后验收。
- 用户此前报告点击详情退出 Telegram；具体操作、客户端及版本未确认，不能声称已经确定或修复客户端崩溃。新版默认正文不嵌入折叠详情，阅读按钮发送独立原生回复。
- GitHub Trending 的 RSSHub 路由此前报 503，用户说明 Token 已过期；未修改 RSSHub Token，本次不将该数据源故障算作已修复。
- 自动个性化排序、订阅时间设置及 PDF 导出尚未实现；现有偏好和兴趣反馈用于会话分析，报告提供持久存储与原生分页阅读。
- Codex 动态工具是实验性协议；升级 CLI 后应重新跑协议与真实恢复测试。

## 部署检查点

1. 备份旧代码版本与 SQLite 数据库（含 WAL 的数据库应使用 SQLite backup API）。
2. 将已验证提交部署到正式目录，执行 `uv sync --frozen`。
3. 停止旧 getUpdates 消费者，再更新 systemd 到 uv 启动方式，避免两套 bot 争抢更新。
4. 更新采集 cron 为 uv 启动方式；保留原有其他定时任务。
5. 验收 `/models`、`/new`、`/sessions`、深入解读、继续追问、停止生成、偏好和报告。
6. 回退时恢复旧提交和服务入口；保留新增数据库表，不做破坏性降级。
