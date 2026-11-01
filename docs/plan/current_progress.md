# 项目交接摘要

## 最新改动：任务面板按轮次展示执行标题

- 会话 title 保持独立；Agent 使用 set_execution_title 工具结合当前输入与上下文概括本轮标题，普通新轮清空标题和步骤，人工恢复不新增轮次。未生成时显示“第 N 轮执行”，不再拿会话标题替代。
- Domain 的 TaskExecution 类型及任务仓储契约保存轮次快照，领域服务维护归属与旧轮次写入保护；Application 协调标题/计划回调和短事务；Infrastructure 实现工具、图状态与 ORM；Interface 只做查询和 VO 转换。
- 新增 agent_task_executions 表，整数主键、task_id+attempt 唯一；新增 GET /tasks/{task_id}/executions。前端默认显示当前轮，可回看已保存的历史标题、步骤与结果，旧快照不能覆盖新标题。
- 新迁移 e62a8f31c904_add_task_execution_snapshots.py 未在用户数据库执行。重启前必须停止服务并运行 uv run alembic upgrade head。升级前未记录的历史不自动补造。
- 64 项后端回归、3 项子测试、16 项前端任务测试、12 项代理测试、TypeScript 与针对性静态检查通过；PostgreSQL 表 DDL 离线编译通过，未进行真实数据库、模型或浏览器端到端验证。详见 docs/plan/task_execution_titles.md。

## 最新修正：失败后续问与任务草稿隔离

- Domain 允许 failed → queued，新输入清除本轮错误并正常启动下一轮；等待人工仍需回复中断，停止中仍不能发送。失败的部分助手回答保存为 failed 消息，不随下一轮清空。
- Application/Runtime 内部参数正式改为 restart_after_interruption，覆盖停止及失败；复用已有清理节点、中断与未完成工具调用的机制，不自动重试旧工具，保留消息与文件。没有兼容壳或新增数据库字段。
- 前端失败后恢复输入并展示可修改要求继续。草稿由 use-task-composer 按账号和任务隔离，新任务独立草稿，旧提交回包只清理原任务草稿；创建期间切换任务不会被回包抢回。
- 51 项后端与架构测试、13 项前端状态/草稿测试、TypeScript、针对性 ESLint/Ruff 检查通过。未连接真实模型、数据库或浏览器端到端验证。重启 API/Worker 并刷新前端后生效。

## 最新补充：Langfuse Trace 标签

- 本次生产代码只修改 infrastructure/observability/langfuse.py，集中生成分类标签并通过官方 propagate_attributes 传播；不改 Domain、Application 或队列契约，不新增服务包装。
- 覆盖平台、任务工作流、API/Worker/Agent 边界、Agent、操作、新轮次/人工恢复、首轮/后续轮。任务和用户编号仍放 metadata，环境沿用原生 environment 字段。
- LangChain 同时传 tags 与 metadata.langfuse_tags；异常、取消和退出回收标签上下文，标签失败继续降级，不影响业务。
- 20 项离线追踪测试与针对性 Ruff 检查通过，未发送真实遥测。用法见 docs/plan/langfuse_tracing.md。需启用追踪开关并重启 API/Worker，只影响新产生的片段。

## 最新修正：停止本轮后继续原会话

- `cancelled` 只表示本轮停止，不再封死会话；停止完成后允许追加消息并重新排队，`task_id/thread_id` 不变，Worker 领取时递增 `attempt`。停止中仍禁止发送。
- 应用服务根据历史用户消息的 cancelled 标记传入 `restart_after_interruption`；Runtime 使用 LangGraph 的 `aupdate_state(config, None, as_node=END)` 清除旧调度现场与中断，补齐中止工具调用的 ToolMessage，重置计划和预算，保留消息与文件。未停止轮次仍不能跳过人工中断。
- HTTP 与 SSE 携带 `updated_at`，前端保留微秒精度，用轮次和版本拒绝旧响应；同轮次的重新排队不会被误拦截。
- 修正后 44 项后端离线测试、9 项前端状态测试、TypeScript、针对性 ESLint/Ruff 检查通过；未执行真实模型或数据库联调。关键源码片段与本次文件清单在 docs/plan/task_cancellation.md。
- 本次没有新增数据库字段或迁移；以前已停止的会话也可直接发送新内容。既有 cancelling 迁移未执行时仍需执行原迁移。

## 上次补充：运行中取消

- 新增 cancelling：先持久化取消意图，Worker 每约 0.5 秒检查并取消独立执行协程，确认退出后保存 cancelled 再 ACK，消费者继续处理后续任务。
- 使用现有应用服务和领域仓储，不新增 Redis 通知服务，不依赖 API 与 Worker 同进程。
- 区分用户取消和服务关闭，显式关闭图异步流；保留部分回答，未处理消息与部分助手消息使用独立的 cancelled 状态。
- 前端新增输入框停止按钮、停止中状态、发送限制，屏蔽迟到事件及 HTTP 响应的状态覆盖。
- 迁移 d40c6e2189ab_support_running_task_cancellation.py 已编写，未在用户数据库执行。重启前运行 uv run alembic upgrade head。
- 详细路径与代码说明见 docs/plan/task_cancellation.md。取消不能回滚外部副作用或保证供应商立即停止计费，故障退出后的 pending 回收仍未实现。

更新时间：2026-10-31。新窗口先读本文件与根目录 AGENTS.md，再检查当前代码。

## 协作要求

- 用户从 Java 转 Python，以学习为主；默认只分析并贴代码，明确授权当次修改 Python 后才能改。前端可直接修改。
- 改动必须给具体文件路径、行号和可复制代码，不用带加减号的 diff。注释、文档字符串用中文，字段标明用途。
- 遵循已有 DDD，避免预留空接口、无意义类型别名、重复包装、往 Container 堆业务 Service。
- 新数据库主键使用整数。已有任务、线程、消息标识不顺带重构。保留用户已有改动，不擅自提交或暂存 Git。
- 优先成熟框架；用户要学习的中间件才手写。RAG、对象存储后续再做。

## 已打通的业务

- FastAPI 收消息 → PostgreSQL 保存任务/消息 → Redis Streams 队列 → Worker → DeepAgents → Redis 执行事件 → SSE → Next.js 页面。
- 一个工作任务是一个会话，稳定 task_id/thread_id，支持连续消息、改名、历史、人工中断恢复、计划进度、工具动态及文件下载。
- 正常新一轮执行增加 attempt；人工恢复不增加。执行中的补充输入会排队，可能合并到下一轮。
- PostgreSQL 用户记忆 CRUD 与向量检索，BGE 本地 1024 维；个人中心可看、改、删自己的记忆。
- 用户登录、Redis 会话、管理员用户管理已接入；用户名和密码登录，不填公司代码。Next BFF 用 HttpOnly Cookie，后端鉴权生成 Principal。
- 开发环境 API 可同进程启动一个 Worker，生命周期可停机。部署可独立 Worker。
- 文件目前在 Redis checkpoint 的虚拟文件系统，RustFS 后续接入。

## DDD 与资源边界

- interface/api + vo：入站路由、请求响应、鉴权，调用 Application。
- application/services：具体 XxxApplicationService，编排领域服务、数据库事务、队列和 Runtime。
- domain/aggregates、types、services、repositories：业务规则、状态转换、仓储契约；不依赖上层或基础设施。
- infrastructure：ORM、仓储实现、Redis、checkpoint、模型和 harness、技术追踪。
- bootstrap：装配及生命周期；Container 只承载现有共享资源，业务 Service 通过装配函数获取。
- 数据库使用 sqlalchemy_transactional 的 sessionmaker_context/current_session；暂不扩展事务方案。
- 模型、Engine、连接池、Runtime/Agent 配置按进程复用；具体 Agent 当前每次 build 构建图；Session、执行状态和回调按协程/执行隔离。

## 最新完成：Langfuse 分布式追踪

- 集中实现于 infrastructure/observability，只接 API、队列、Worker、Agent Runtime 四个边界。
- 一轮输入一个 Trace；API → 队列 → Worker → 主 Agent → 模型/工具/子图同 Trace，Span 保留父子关系。
- 人工回复沿用原轮次 Trace，在 Redis 保存上下文，进程重启后可找回；正常下一条输入新 Trace，同 session。
- 多条补充输入合并执行时以 Span Link 关联来源，不伪造多父节点；没有重写调度逻辑。
- Domain 与 ApplicationService 业务方法不变，TaskJob DTO 只增加可选的纯数据 trace_context。
- API 返回 X-Trace-ID，Next BFF 透传；业务 trace_id 与观测 trace_id 不混用。SSE 长连接不创建执行 Span。
- 配置 LANGFUSE_TRACING_ENABLED、LANGFUSE_BASE_URL、LANGFUSE_PUBLIC_KEY、LANGFUSE_SECRET_KEY，仍由模块自行读根目录 .env。
- 没有改用户 .env，没有真实连接 Langfuse/模型验证。本地 SDK 5.0.4，需兼容服务端版本。
- 16 项离线 Python 追踪测试、11 项 Node 代理测试通过，TypeScript 检查通过。测试不初始化真实 SDK。
- 追踪上下文没有短 TTL，避免人工等待丢关联；任务归档清理尚未实现。追踪存储失败可降级为新 Trace，不阻断业务。

## 接下来先做什么

1. 按 docs/plan/langfuse_tracing.md，在实际 Langfuse 看新任务、子 Agent、人工恢复、下一轮输入的 Trace/Span。
2. 对照 docs/plan/langfuse_distributed_changes.md 阅读路径、行号、改动代码。
3. 真实导出、服务端调用树及 Span Link 显示方式尚需联调，不能当成已验证。
4. RAG、独立纯聊天、RustFS、Redis 队列未确认消息回收、追踪归档清理暂未在本次实现。

## 验证注意

- 环境是 Windows / Python 3.12 / uv，项目 .venv；Node 已安装，前端 frontpages。
- 只做针对性验证，不无故启动真实模型/数据库/外部遥测。
- 曾有认证测试因访问外部遥测域被自动审批拒绝，不应原样重试或绕过限制。当前追踪测试用假 SDK 与内存 Redis。
- 工作区有很多本次之前的暂存、未暂存和未跟踪文件，不能用 Git 总 diff 冒充本次改动清单。
