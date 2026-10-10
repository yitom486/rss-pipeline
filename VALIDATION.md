# 开发与验证记录

## 2026-10-10：富文本能力、依据与延伸解读

- 核对 Telegram 官方 Rich Message Formatting Options：原生消息支持表格、脚注、公式、媒体和折叠块，Rich Markdown 可混用受支持的 HTML 标签；这不等于任意网页、CSS 或 JavaScript 渲染。
- 摘要和定时编辑增加完整资讯内容要求：相关背景、深入机制解读、后部的思维延伸/工具场景、可辨识的来源依据区域。继续不设编辑字数目标，不要求固定栏目或用齐全部格式。折叠按用户新要求用于单层补充细节，核心解释直接展示；此前客户端退出报告原因仍未定位。
- 使用现有 Codex 登录及条目 1321 保存的发布原文生成本地 Whistle 样稿，正文 3167 字符，含机制、性能口径、采用场景、来源依据、一个技术补充折叠块和独立流程/命令。检查扩展验证思路明确标为推论，厂商结果未写成独立复测。样稿位于被忽略的 `reports/live-previews/whistle-rich-editorial.md`。
- `uv run pytest`：54 项通过；新增测试验证复杂 Markdown 经分块流式生成后在完整草稿和正式请求中保持原样，以及原生 HTML 请求没有退回旧 parse_mode。skill-creator 的 quick_validate 验证运行时技能通过，`git diff --check` 通过。
- 本轮没有发送或修改 Telegram 消息，未验收实际 API 对新折叠语法的解析及各客户端交互。传输测试与本地模型样稿不能代替客户端视觉验收。
- 本机 Codex 功能目录显示 `image_generation` 已启用；官方说明内置生图能力。应用尚未处理生成图片的产物、上传及消息嵌入，不能把 CLI 功能开关等同于自动资讯配图已经接通。没有新增生图 API 或凭据配置。

## 2026-10-09：新版排版规则的自动生成样例

- 用户再次授权拉取并推送一篇。执行单篇 Hacker News 实际采集，任务 **214** 完成，调用来源、偏好、原文读取与逐篇提交工具，选中 Cactus Compute 的 Whistle 发布文章。
- 条目 **1321**，正式 Telegram 消息 **1632**，正文 1763 字符，数据库状态 `sent`。消息按新版编辑规则自动生成并直接投递，没有人工重新排版。
- API 确认主标题、四个内容小标题、一个引用块、一个竖向流程代码块和四行真实阅读按钮。核对原文后，模型大小、语言支持、音频片段压缩、共享音频表示、首 token 延迟的测试口径以及语音转工具请求的解释均有依据。
- 正文明确说明不支持中文、厂商测试条件及模型文件大小不等于运行内存；客户端阅读效果待用户查看。正文与安全验收元数据保存在被忽略的 `reports/live-previews/`。

## 2026-10-09：REA 原消息结构化排版修订

- 用户反馈 REA 解读虽然有内容，但连续长段落密度过高，要求更充分使用 Markdown 阅读层次。问题来自生成正文的排版约束偏弱，传输仍为原生富文本。
- 更新统一编辑提示、AGENTS、阅读标准和输出说明：长文按语义使用小标题、短段落、列表、适量加粗、引用和独立代码块；不设字数目标或固定栏目。长命令按合法语法换行，流程须用围栏 `text` 或有序步骤列表，避免普通换行被合并。
- 使用现有 Codex 登录对条目 1317 的原正文生成重新排版草稿，保留原事实、证据限制、链接和 Node.js 版本条件。人工检查并将流程置于独立 `text` 块，把长命令拆成可执行的多行 Bash 命令。
- 更新原 Telegram 消息 **1628**，没有新增推送；API 返回原生 `rich_message`，包括五个 heading（主标题与四个内容标题）、两个 list、一个 blockquote、三个 pre，保留四行阅读/反馈按钮。数据库同步新正文，原正文备份与验收元数据保存在被忽略的 `reports/live-previews/`。
- `uv run pytest -q`：52 项通过；`git diff --check` 通过。实际生成草稿和 Telegram API 渲染结构均已验证，手机端视觉效果待用户查看原消息。

## 2026-10-09：Hacker News 取源修复与真实新闻样例

- 用户明确授权拉取并推送一篇 Hacker News 新闻。GitHub 样例仅在测试进程临时限定来源，正式配置一直保留 Hacker News。
- 首次样例遇到正在运行的定时采集锁，等待原任务结束后执行；任务 212 的 RSSHub `/hackernews/best` 两次取源失败，没有提交或发送任何消息。
- 直接诊断本机路由 HTTP 503；Hacker News 官方 `https://news.ycombinator.com/rss` 返回 HTTP 200，正式解析器取得六条有效文章。配置改为直连官方首页 RSS，选文范围从原 best 榜单改为首页，不再依赖 RSSHub。
- `uv run pytest -q`：52 项通过；`git diff --check` 通过。空闲时重启正式机器人加载取源配置，定时进程在下次运行使用新地址。
- 使用正式 collector 与投递代码执行单篇真实样例，任务 **213** 完成；实际调用 `news_refresh`、`news_preferences`、`news_read_url`、`news_queue_digest`。
- 条目 **1320**：LWN《Reducing undefined behavior in the C language》，中文标题《C 正在减少“未定义行为”，但离完整内存安全仍有距离》。原文资料 9794 字符，解读 1519 字符，Telegram 正式消息 **1631**，数据库状态 `sent`。
- 返回原生 heading、paragraph、divider 和四行阅读/反馈按钮；本次成功样例只推送一篇，没有生成图片。核对正文中的编译优化例子、“禁止时间旅行”、C2y 草案减少 45 处未定义行为及内存安全讨论均有原文依据；客户端视觉体验待用户阅读。
- 运行时正文和安全元数据保存于被忽略的 `reports/live-previews/`，未提交凭据、数据库或运行时文章。

## 2026-10-09：一篇真实 GitHub 资讯推送验收

- 用户明确授权拉取并推送一篇样例。使用现有 ChatGPT 登录和正式 `collect_news`、应用工具、投递代码；本次进程只配置 GitHub 来源，提交上限为一篇，投递队列只允许本次新增条目。使用正式采集锁，不消费 Telegram 更新。
- 任务 **210** 完成，实际调用 `news_refresh`、`news_preferences`、两次 `news_read_url` 和 `news_queue_digest`，取得 README 并补读项目发布说明。
- 条目 **1315**：RAD Debugger；解读正文 1397 字符，数据库状态 `sent`，Telegram 正式消息 **1626**。API 返回原生 `rich_message`，包含 heading、paragraph、divider，附四行实际阅读与反馈按钮；本轮没有生成图片或发送额外样例。
- 人工检查正文覆盖主要用途、具体调试场景、调用栈/PDB/RDI/链接器等解释、工作机制、使用入口和影响采用的平台限制。补查官方 releases/latest：v0.9.29-alpha，确认初步 Linux x64 支持、没有预编译 Linux 包、不支持 fork/vfork 和选中线程断点的描述。
- 正文正确指出 README 的平台描述与最新发布说明不同。当前仍有较长自然段，流程示意嵌在段落中；API 验收不代表手机端视觉验收，实际客户端阅读感受待用户反馈。
- 生成正文和只含安全元数据的验收结果保存在被忽略的 `reports/live-previews/`，未提交数据库、运行时正文或凭据。

## 2026-10-09：GitHub Trending 恢复

- 初次取源仍返回 RSSHub 503，错误页包含 GitHub GraphQL `401 Unauthorized`。安全比较确认 `.env` 与运行容器中的 `GITHUB_ACCESS_TOKEN` 不一致；未输出令牌、哈希或容器完整环境。
- 使用用户更新到 `/root/rsshub/.env` 的令牌执行只读公开仓库 GraphQL 查询：HTTP 200，返回预期仓库，没有 GraphQL errors。
- 执行 `docker compose up -d --force-recreate --no-deps rsshub` 加载新配置，Redis 服务保持运行；未修改用户令牌。
- 使用正式项目的 `feeds.fetch` 读取配置路由 `/github/trending/daily/any`，取得八个有效项目；首个项目通过 `material.fetch_material` 返回 2639 字符资料，包含仓库元信息与 README。
- 本次只验证真实取源与项目资料读取，不写资讯数据库、不调用模型、不发送 Telegram 消息；每轮采集仍由编辑从全部来源中选择最多六篇。

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
