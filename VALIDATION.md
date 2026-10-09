# 开发与验证记录

## 2026-10-09：可读性优先的编辑规则

- 移除推送、速读、深入解读与技术视角的字数和段数目标，并去除提交工具对解读正文的 10000 字符限制；标题和 URL 的参数限制保留。
- 编辑优先讲清主要内容，补足必要背景，在叙述中解释术语，以具体机制和例子解读亮点；GitHub 项目按实际使用场景解释用途、输入输出、使用入口和采用条件，不固定栏目。
- 原生富文本按理解需要使用标题、加粗、引用、比较表、代码及简洁箭头示意；来源图片需有真实公开 URL，没有新增 Mermaid 渲染或图像生成能力。
- 定时编辑读取候选文章后可补读相关公开资料，原有公开地址检查仍执行；补读链接不能绕过候选与已阅读校验成为新推送。
- `uv run pytest -q`：52 项离线测试通过；新增正文超过旧字符上限后完整保存的行为测试，以及补读前置阅读、补读成功和禁止补读链接入队的验证。
- `uv run python scripts/check_codex_protocol.py` 通过；`git diff --check` 通过。
- 已重启正式 `rss-bot.service` 加载新规则；重启前数据库没有 running 任务。定时采集进程在下一次启动加载新规则，已有会话保持原 thread，resume 时更新编辑指令。
- GitHub Trending 只读诊断：本机路由 HTTP 503，错误页明确包含 GitHub GraphQL `401 Unauthorized`。Compose 已注入 `GITHUB_ACCESS_TOKEN`；尚未更换令牌或恢复该来源，配置步骤已写入 README。
- 本轮未调用模型生成新的资讯样例，也未发送 Telegram 消息；测试验证流程行为，生成质量与手机端图片显示仍需实际阅读验收。

## 2026-10-01：新增三个公开订阅源

- 新增 Lobsters（RSS）、Simon Willison（Atom）、InfoQ（RSS），直接读取官方公开订阅地址，不依赖 RSSHub；GitHub Trending 的故障未处理。
- 已验证三个地址 HTTP 200，并通过项目解析器各返回六条候选；检查命令 `uv run python scripts/feed_probe.py`，不调用 Codex、不写数据库、不发送 Telegram 消息。
- RSS / Atom 统一返回文章标题、公开 HTTP(S) 链接和简介；Atom 选择文章 alternate 链接，支持 HTML 与 XHTML 正文，避免使用 self feed 链接。
- 同一 feed 与跨来源相同 URL 去重，忽略 URL 片段；数据库继续拦截已采集 URL。不同 URL 的同一事件由模型筛选，未实现确定性的语义去重。
- 扩展 news_refresh 的来源选项；旧持久会话使用 source=all 也会读取新增来源，不重建会话。每轮合计六篇的提交上限保留。
- 离线测试覆盖格式解析、无效条目、来源单独筛选、跨来源去重、历史条目排除、来源失败继续处理和跨来源总量上限。没有额外触发真实资讯推送；实际编辑与 Telegram 展示由后续定时任务验收。
- `uv run pytest -q`：51 项通过；`uv run python scripts/check_codex_protocol.py` 与 `git diff --check` 通过。
- 功能提交 `e1c9c46` 已快进合并到正式目录 master；正式目录 51 项测试再次通过。重启前只读检查无 running 任务，06:37:53 UTC 重启 rss-bot.service 后确认 active/running；定时入口下一轮自动加载新增来源，未修改 cron、凭据或数据库结构。

日期：2026-09-30 UTC。开发工作树 `/root/rss-native-preview`，分支 `feature/news-assistant-v1`。正式部署目录 `/root/rss-pipeline`。

## 正式部署

- 备份目录 `/root/rss-deploy-backups/20260930T193219Z`：SQLite backup API 备份数据库，保存旧 Git 版本、systemd 配置与完整 crontab。
- 正式目录快进至已验证新版提交，`uv sync --frozen` 完成，正式目录 30 项离线测试通过。
- 停止旧轮询服务，安装 uv systemd 入口并重载启动；`ActiveState=active`、`SubState=running`，启动日志确认新版原生富文本 Codex 助手。
- 采集 cron 已改为 uv，每小时第 5 分钟执行；保留原有证书维护任务。
- 正式目录 account/read 确认 chatgpt 登录；实际用户会话生成包含项目 skill 的使用说明，并完成原生草稿与正式消息发送。
- 发送函数验证了 rich_message 响应并正常返回正文。验收脚本发送后误把正文作为响应对象读取，导致元数据打印失败；未记录该消息编号，未重复发送。
- 服务启动后初步检查无 Telegram 更新获取错误；用户实际从 Telegram 发起的连续对话与按钮操作尚待客户端验收。

## 已通过

- 用户已确认原生富文本流式样例的阅读体验；对应真实 Telegram 消息 ID 1446，见 `NATIVE_RICH_PREVIEW.md`。
- `uv sync`：锁定依赖；生产网络依赖为 HTTPX，已移除 requests。
- `uv run pytest`：42 项离线行为测试；使用临时数据库与模拟网络，不发送消息。
- 测试覆盖：原生消息不回退、429 重试、发送超时不盲目重发、跨用户会话/报告隔离、偏好持久化、切换模型保留 thread、同一条资讯继续会话、停止事件鉴权、取消调用 turn/interrupt、报告分页不丢字符、来源数据与无效模型输出处理。
- `uv run python scripts/check_codex_protocol.py`：通过当前 CLI 0.159.2 的 experimental JSON Schema 校验 thread/start、thread/resume、动态工具响应。
- `uv run python .../skill-creator/scripts/quick_validate.py .agents/skills/news-assistant`：官方 skill 格式校验通过。
- `uv run python -m compileall -q src scripts` 和 `git diff --check` 通过。

## 真实 Codex 验证

### 真实事件与 agent 主导采集升级

- 20:18 UTC 已将升级代码（`2ccc230`）部署到正式目录并重启 uv 服务，active/running，启动后初步检查无更新获取错误；正式目录 42 项测试通过。
- 升级前数据库与版本备份：`/root/rss-deploy-backups/20260930T201837Z-events`。用户会话保留原 thread，未自动重建。
- `scripts/activity_probe.py --send` 在显式授权下使用真实 Hacker News 与 Codex，经过完整 bot producer queue 与原生草稿通道，正式消息 ID **1456**，任务 #1 已完成。
- 实际事件：公开进度说明、news_refresh 开始、Hacker News 返回 6 条、news_refresh 完成、news_read_url 开始、读取 space.bl2.net、读取完成、生成正文；最终消息不包含临时 thinking 块。
- `uv run python scripts/collector_probe.py` 使用真实 Codex 和隔离虚构来源/临时数据库，不发送 Telegram 消息。实际调用 news_refresh、news_preferences、news_read_url、news_queue_digest；提交两篇，逐篇投递回调长度为 1、2，GitHub 来源失败仍处理另一来源。
- 新测试覆盖工具事件路由与参数不泄露、草稿状态更新、最终正文移除状态、trace 用户隔离、队列只接受已取源且已阅读 URL、逐篇投递回调、报告 UTF-8 文件与发送未确认时不重复。
- 另验证真实 bot 队列保存事件与最终消息编号、进程重启仅恢复对应任务类型、采集连接失败写入执行记录，以及未支持的媒体输入明确提示。
- agent 并行调用提交工具时，提交和投递保持串行；并发投递测试确认同一条资讯不重复发送。
- 当前 CLI schema 校验同时覆盖交互工具与定时采集工具目录；项目 skill 校验通过。
- Markdown 文件导出已通过 HTTPX multipart 与权限测试；本轮没有额外发送报告附件，客户端文件打开验收尚未进行。

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

- 正式目录代码、cron 与 systemd 已切换新版；旧 bot 已停止，避免两套消费者争抢更新。
- 部署阶段已向用户发送一条 Codex 生成的原生流式使用说明；未自动补发历史新闻。
- 模型到 Telegram 的正式发送已通过；完整用户输入 → 线上 bot → Codex → Telegram 连续对话仍需用户实际交互验收。
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
