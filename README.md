# DeepAgent Enterprise Harness

[![License: 0BSD](https://img.shields.io/badge/License-0BSD-blue.svg)](LICENSE)

> **架构背景：基于 Java DDD 目录与职责划分组织的 Python 项目。** 作者从 Java 后端开发转向 Python，本项目的领域目录、分层方式和命名约定参考 Java 生态中常见的 DDD 实践，优先采用清晰的职责边界与显式接口契约。

**Java DDD 风格的领域结构：** 以 `domain/aggregates`、`domain/types`、`domain/services` 和 `domain/repositories` 组织聚合、领域类型、领域服务与仓储抽象；`application/services` 编排用例和事务，`application/dto` 表达用例输入输出；仓储及 ORM 实现放在 `infrastructure/persistence`，HTTP 与 VO 放在 `interface`，依赖装配放在 `bootstrap`。领域层不依赖数据库、Web 或 Agent 框架，应用层面向抽象使用外部能力。

**ABC 与显式继承约束：** 自定义核心扩展点采用 `ABC`、`@abstractmethod` 和显式继承，例如 `BaseAgent`、`ModelProvider`、`AgentTaskRuntime`；实现类必须实现抽象方法才能实例化，关键注入点结合 `isinstance` / `issubclass` 校验实现关系，不以“恰好有同名方法”的鸭子类型作为这些接口的接入依据。类型注解和参数校验进一步表达与检查契约；ABC 本身不替代方法签名、类型和业务行为的验证。

这一原则针对采用 ABC 的核心接口，并非宣称全项目完全排除结构类型：例如向量能力 `TextEmbeddings` 使用 `Protocol`，第三方框架也遵循各自的接口机制。项目借鉴 Java 的职责划分，不机械复制 Java 的类数量：不为单一实现额外拆分接口与 `Impl`，不为每张表建立聚合，也不让个别 Agent 的特殊能力扩张上层公共接口。

面向企业内部使用的 AI 任务执行平台。用户登录后，在同一个工作会话中提交目标、补充要求、回答 Agent 提问，查看计划、执行动态和交付文件；服务端通过任务队列驱动 Agent 执行，并将进展持续推送到页面。

后端采用 Python、FastAPI 和 DDD 分层，Agent 执行由 DeepAgents、LangGraph 承担。前端采用 Next.js App Router、React、TypeScript 和 shadcn/ui。PostgreSQL 保存业务数据和用户长期记忆，pgvector 提供向量检索，Redis 承担任务队列、执行事件、登录会话及默认 Checkpoint，Langfuse 记录执行链路。

当前主业务是**长任务规划与执行**。独立普通聊天、企业知识库 RAG、隔离代码执行沙箱和对象存储尚未接入主流程。

## 目录

- [开源协议](#开源协议)

- [当前能力](#当前能力)
- [技术栈](#技术栈)
- [系统组成与消息流转](#系统组成与消息流转)
- [DDD 架构与职责边界](#ddd-架构与职责边界)
- [项目目录](#项目目录)
- [任务会话与状态管理](#任务会话与状态管理)
- [Agent、子 Agent 与 Skills](#agent子-agent-与-skills)
- [执行中间件](#执行中间件)
- [前端架构与实时更新](#前端架构与实时更新)
- [数据库、事务与资源生命周期](#数据库事务与资源生命周期)
- [短期状态与长期记忆](#短期状态与长期记忆)
- [登录、用户管理与数据隔离](#登录用户管理与数据隔离)
- [Langfuse 链路追踪](#langfuse-链路追踪)
- [配置与本地启动](#配置与本地启动)
- [HTTP 接口](#http-接口)
- [开发与验证](#开发与验证)
- [当前边界与后续建设](#当前边界与后续建设)

## 当前能力

| 能力 | 当前实现 |
| --- | --- |
| 工作任务会话 | 创建任务、历史会话、修改名称、同一会话连续输入 |
| 异步执行 | FastAPI 接收请求，Redis Streams 投递，Worker 消费 |
| 任务规划 | `write_todos` 管理待执行、执行中、已完成的步骤 |
| 子 Agent 委派 | 框架通用子 Agent；支持装配独立的专业 Agent |
| 执行动态 | 模型文本、计划更新、工具请求与返回、子任务委派动态 |
| 人工参与 | `ask_user` 提问、Checkpoint 暂停、提交回复后继续执行 |
| 停止执行 | 运行中可请求停止，Worker 退出执行后确认取消，保留部分回答，同一会话可重新输入继续 |
| 工具审核 | 已有审批中间件与回复类型，默认规划 Agent 未启用 |
| 历史与恢复 | PostgreSQL 保存可展示消息，Checkpoint 保存图执行现场 |
| 交付物 | /deliverables/ 下的文本文件预览与下载 |
| 用户长期记忆 | 保存、语义检索、分页列表、修改、删除；个人中心可管理 |
| 用户与权限 | 登录、退出、修改密码、租户内管理员管理用户 |
| 运行控制 | 模型调用额度、工具额度、工具禁用、有限重试、备用模型 |
| 观测 | 控制台日志、工具审计日志、Langfuse 分布式 Trace 与 Span |

“已实现的类”和“默认已启用的功能”分别说明。专业 Agent 注册到 Runtime，不代表主 Agent 已自动拥有全部专业子 Agent；中间件文件存在，也不代表它已经加入执行链。

## 技术栈

| 层面 | 技术 | 在项目中的用途 |
| --- | --- | --- |
| 后端运行时 | Python 3.12、uv | 运行、依赖管理、命令入口 |
| HTTP 服务 | FastAPI、Uvicorn、Pydantic v2 | 路由、参数校验、认证依赖、生命周期 |
| Agent 执行 | DeepAgents、LangChain、LangGraph | 计划、工具、子图、人工中断和恢复 |
| 模型接入 | `DeepSeekProvider`、`QwenProvider`、`OpenAIProvider` | 模块自管配置，提供 `BaseChatModel` |
| 关系型存储 | PostgreSQL、SQLAlchemy AsyncIO、Psycopg | 任务、消息、用户、租户、个人记忆 |
| 事务管理 | sqlalchemy-transactional | 协程上下文中的 Session 与事务传播 |
| 数据库迁移 | Alembic | 业务表的结构变更 |
| 向量检索 | pgvector、Sentence Transformers、BGE | 本地编码与用户记忆余弦检索 |
| Redis | redis-py 异步客户端、Redis Streams | 队列、事件、登录会话、追踪关联 |
| Checkpoint | LangGraph Redis/PostgreSQL Saver | 执行状态保存与人工恢复 |
| 实时输出 | SSE、sse-starlette | 文本与进展推送、游标续传 |
| 链路观测 | Langfuse SDK、OpenTelemetry API | 调用树、分布式上下文、来源链接 |
| 前端框架 | Next.js 16.4.3、React 19、TypeScript | App Router、服务端鉴权、交互页面 |
| 前端 UI | shadcn/ui、Radix UI、Tailwind CSS 4、Lucide | 通用控件、布局、图标 |
| 内容展示 | react-markdown、remark-gfm | Markdown、表格和代码展示 |

具体依赖约束保存在 `pyproject.toml` 与 `frontpages/package.json`，安装解析结果由各自的锁文件管理。

## 系统组成与消息流转

### 系统拓扑

```mermaid
flowchart TD
    Browser["浏览器 · 工作区 / 个人中心 / 管理后台"] --> Next["Next.js · 页面与同源 BFF"]
    Next --> API["FastAPI · 鉴权与业务接口"]
    API --> App["Application · 用例编排"]
    App --> Domain["Domain · 业务规则与仓储契约"]
    Domain --> DB["PostgreSQL · 经仓储实现存取"]
    App --> Queue["Redis Streams · 任务队列"]
    Queue --> Worker["Worker · 消费与执行入口"]
    Worker --> App
    App --> Runtime["DeepAgents Runtime · 图执行"]
    Runtime --> Resources["模型 / 工具 / Skills / Checkpoint"]
    App --> Events["Redis Streams · 执行事件"]
    Events --> SSE["FastAPI SSE · 按游标读取"]
    SSE --> Next
```

图中的 Domain 到 PostgreSQL 表示业务存取经过仓储实现，不表示领域代码导入数据库驱动。任务队列和执行事件是两组不同的 Redis Stream，读写方式也不同。

### 提交一次工作任务

1. 用户输入目标，前端调用同源 /api/backend/tasks。
2. Next.js 从 HttpOnly Cookie 取出令牌，转为后端 Bearer Authorization；浏览器不能自行指定租户和用户身份。
3. FastAPI 完成认证，生成可信 `Principal`，把请求 VO 转为应用命令。
4. `AgentTaskApplicationService` 调用领域服务，在短事务中创建任务和首条用户消息。
5. 事务结束后，应用服务投递任务上下文到 Redis 队列，接口返回 202 Accepted。
6. Worker 通过消费组读取消息，复核账号状态，调用同一个应用服务的 `execute()`。
7. 领域服务领取待处理消息并迁移状态；Runtime 读取 Checkpoint，将本轮输入交给 Agent 图。
8. 模型文本、计划与工具动态通过回调返回应用服务，写入任务自己的事件 Stream。
9. FastAPI SSE 按客户端游标读取事件，经 Next.js 转发到浏览器，React 更新文本、步骤和时间线。
10. 本轮结束或等待人工时，应用服务在短事务中保存业务状态与消息，再发布对应事件。

HTTP 请求只负责接收与查询，不等待整个长任务完成。202 表示已接收，不表示模型执行成功。

### 队列和 SSE 如何连接

| 通道 | 写入方 | 读取方 | 读取方式 | 用途 |
| --- | --- | --- | --- | --- |
| 任务队列 | Application 经 `JobQueue` | Worker | `XREADGROUP`，处理后 `XACK` | 分发执行指令 |
| 执行事件 | Application 经 `TaskEvents` | FastAPI SSE | `XREAD`，各连接独立游标 | 向多个页面展示相同进展 |

SSE 不消费 Worker 的任务队列。Worker 不持有浏览器连接，只执行任务并写事件；API 独立读取事件并推送。API 与 Worker 可以在同一个进程中运行，也可以部署为不同进程。

后端重启后，只要 Redis 中的事件仍存在，客户端就能按 Stream ID 继续读取。已被 Worker 领取但未确认的任务需要 `pending` 消息回收，不能与 SSE 游标续传混为一谈。

## DDD 架构与职责边界

### 各层负责什么

| 层 | 目录 | 负责 | 不负责 |
| --- | --- | --- | --- |
| 接口层 | `interface/` | HTTP、认证依赖、VO、状态码、SSE 协议 | 直接操作 ORM、构造模型客户端、制定状态规则 |
| 应用层 | `application/` | 组合领域能力、短事务、队列、Runtime、事件 | 实现驱动、解析模型框架内部状态、复制聚合规则 |
| 领域层 | `domain/` | 聚合不变量、状态迁移、业务约束、领域服务、仓储抽象 | Request、Redis、SQLAlchemy、LangGraph、SDK 生命周期 |
| 基础设施层 | `infrastructure/` | 仓储实现、ORM、Redis、模型、Agent 框架、观测与安全技术 | 代替聚合随意决定能否取消、恢复或续问 |
| 装配层 | `bootstrap/` | 选择实现、创建资源、组装服务、启动和回收 | 承载业务流程、充当全部服务的全局注册表 |
| 消费入口 | `workers/` | 拉取队列、绑定上下文、复核身份、调用应用服务、确认消息 | 重新实现任务规划、消息状态机和持久化逻辑 |

### 依赖方向

```mermaid
flowchart TD
    Interface["Interface · HTTP 入口"] --> Application["Application · 应用用例"]
    Worker["Worker · 消费入口"] --> Application
    Application --> Domain["Domain · 聚合 / 领域服务 / 仓储抽象"]
    Application --> Contracts["Application Interfaces · 外部能力契约"]
    Infra["Infrastructure · 技术实现"] -. "实现仓储契约" .-> Domain
    Infra -. "实现执行契约" .-> Contracts
    Bootstrap["Bootstrap · 装配与生命周期"] --> Infra
    Bootstrap --> Application
```

运行时调用通过注入的接口对象进入基础设施实现，源码依赖仍然由基础设施指向契约。领域层不反向导入 bootstrap 或具体仓储。

应用服务直接使用具体的 XxxApplicationService，不为单一实现再拆接口和 impl。需要隔离技术实现的仓储、队列、执行器、会话等能力才定义抽象契约；向量编码复用框架已有的 `Embeddings` 抽象。

### 聚合根：维护一致性，不是属性集合

`domain/aggregates/agent_task.py` 中的 `AgentTask` 是任务聚合根，保存身份、归属、状态、轮次、结果与错误，并通过行为维护规则：

- `start()`：只有排队任务能启动，并增加轮次。
- `wait_for_user()`：将运行中的任务变为等待人工。
- `resume()`：只恢复等待人工的同一轮，不增加轮次。
- `complete()`：保存非空结果，完成当前轮。
- `queue_next()`：成功后允许同一会话进入下一轮。
- `cancel()`：排队或等待人工时立即取消；运行中先进入 cancelling，等待执行方确认。
- `confirm_cancelled()`：执行方退出后完成取消，重复确认保持幂等。
- `ensure_accepts_messages()`：拒绝在等待人工或停止中直接续问；本轮停止或失败后允许新输入。
- `ensure_owned_by()`：验证租户、项目和用户归属。
- `rename()`：修改展示名称，不改变任务或执行线程。

聚合是不可变对象，业务行为返回经过重新校验的新对象。仓储重建聚合时，也检查成功状态是否有结果、失败状态是否有原因，避免读出不一致对象。

`TaskPlanningAgent` 是技术执行器，配置模型、Prompt、工具、中间件和图；它不是领域任务聚合。

### 领域服务：组织业务细节

`AgentTaskDomainService` 通过 `AgentTaskRepository` 完成跨记录的业务操作：

- 创建任务及首条消息。
- 锁定并领取一批 `pending` 消息，标记为 `processing`。
- 检查重复消息是否内容一致，防止重复入库或同号不同内容。
- 接收执行结果，保存助手消息，将本轮输入变为 `applied`。
- 判断是否还有补充输入，决定成功结束还是再次排队。
- 检查人工恢复、取消、归属及执行轮次。

领域服务可以在业务需要一致性时要求仓储加行锁，具体 SQL 锁语句由仓储实现。“为什么要锁”与“如何加锁”分别放在各自层中。

用户领域由 `User` 聚合、`UserDomainService` 与 `UserRepository` 处理账号、角色及启停用等规则。记忆目前使用业务类型、内容校验和仓储契约，没有为了目录齐全额外制造复杂聚合。

### 应用服务：组合成完整用例

`AgentTaskApplicationService` 组织四种能力：

1. `AgentTaskDomainService`：业务判断、任务与消息存取。
2. `JobQueue`：投递异步指令。
3. `AgentTaskRuntime`：执行或恢复 Agent，返回统一结果。
4. `TaskEvents`：发布页面可消费的事件。

应用服务关心提交、领取、执行、完成、通知的顺序，不关心 Redis 命令和 `create_deep_agent()` 的具体配置。模型执行不包在业务数据库的长事务中。

### 仓储接口和实现

仓储表达领域怎样读写业务对象，接口由领域定义，PostgreSQL 是当前实现。

| 领域接口 | 基础设施实现 |
| --- | --- |
| `domain/repositories/agent_task_repository.py` | `infrastructure/persistence/repositories/agent_task_repository.py` |
| `domain/repositories/user_memory_repository.py` | `infrastructure/persistence/repositories/user_memory_repository.py` |
| `domain/repositories/user_repository.py` | `infrastructure/persistence/repositories/user_repository.py` |

文件名对应，方便从接口找到实现。ORM Record 不向应用层和领域层泄露，转换在仓储实现中完成。

`application/interfaces/` 保存用例依赖的外部能力，包括 `AgentTaskRuntime`、`JobQueue`、`TaskEvents`、`LoginSessions`、`PasswordHasher`。它们不是数据库仓储，不与领域仓储混放。

### Bootstrap 和 Container

`bootstrap/wiring.py` 将仓储实现、领域服务、应用服务、队列、模型与 Runtime 连接起来。这里决定使用哪个实现，业务代码使用装配好的对象。

`Container` 当前仅保存 `settings`、`runtime`、`database`，是进程共享资源的生命周期载体，不是业务服务目录。应用服务通过装配函数取得，不逐个塞入容器；底层模块不通过 Request.app.state 寻找依赖。

### 一次业务调用对应哪些文件

以下路径均位于 `src/agent_platform/` 下：

| 顺序 | 文件或目录 | 这一站完成什么 |
| --- | --- | --- |
| 1 | `interface/api/routes/v1/agent_tasks.py` | 接收创建或追加消息请求，调用应用服务 |
| 2 | `application/services/agent_task_application_service.py` | 组织保存、入队、执行和通知 |
| 3 | `domain/services/agent_task_domain_service.py` | 领取消息、检查归属与轮次，调用聚合行为 |
| 4 | `domain/aggregates/agent_task.py` | 校验并生成新的任务状态 |
| 5 | `infrastructure/persistence/repositories/agent_task_repository.py` | 通过 ORM 保存领域对象与消息 |
| 6 | `infrastructure/messaging/redis_job_queue.py` | 投递指令，供 Worker 领取 |
| 7 | `workers/agent_task_worker.py` | 消费指令，调用应用服务 execute 或 resume |
| 8 | `infrastructure/harness/runtime/deepagents_task_runtime.py` | 构建并运行图，转换流式输出与最终状态 |
| 9 | `infrastructure/harness/agents/task_planning/agent.py` | 提供模型、提示词、工具、中间件配置 |
| 10 | `infrastructure/messaging/redis_task_events.py` | 持久化执行事件，供 API 的 SSE 读取 |

这张表是业务路径定位，不是所有调用都按单向流水执行。Worker 会再次进入应用服务，领域服务也会在执行前后分别调用仓储；它们各自复用同一套业务规则。

### 新增能力放在哪里

- 新增业务规则：先判断是否属于现有聚合的不变量，放在聚合或领域服务，而不是 HTTP 路由。
- 新增用例：由应用服务组合领域能力与外部契约，例如创建任务后入队。
- 新增数据访问：领域定义仓储方法，基础设施实现 ORM 映射和查询，再由装配层注入。
- 新增模型、工具或中间件：放在基础设施对应模块，在 Agent 或装配层显式启用。
- 新增 HTTP 功能：添加 VO 与路由，通过认证身份调用应用服务。
- 新增页面：放入 Next.js App Router，通过现有 BFF 访问后端；同时维护 BFF 路径白名单。

不要求每张表都成为聚合，不要求每个服务都拥有接口与 impl，也不因新增一次调用就创建新的全局容器字段。

## 项目目录

```text
deepagent_ddd/
├── src/agent_platform/
│   ├── interface/                         # 接口层
│   │   ├── api/
│   │   │   ├── app.py                     # 应用工厂、会话上下文、异常转换
│   │   │   ├── dependencies.py            # 身份与服务依赖
│   │   │   └── routes/v1/                 # 任务、认证、用户、个人记忆等路由
│   │   └── vo/                            # HTTP 请求与响应类型
│   ├── application/
│   │   ├── dto/                           # 应用命令、执行结果、事件、队列数据
│   │   ├── services/                      # 任务、认证、用户、个人记忆应用服务
│   │   └── interfaces/                    # Runtime、队列、事件、会话等契约
│   ├── domain/
│   │   ├── aggregates/                    # AgentTask、User 聚合根
│   │   ├── services/                      # 任务与用户领域服务
│   │   ├── repositories/                  # 领域仓储抽象
│   │   └── types/                         # 身份、消息、记忆等业务类型
│   ├── infrastructure/
│   │   ├── persistence/
│   │   │   ├── database.py                # Engine、连接池、Session 工厂
│   │   │   ├── entities/                  # ORM 与表结构映射
│   │   │   └── repositories/              # 领域仓储的数据库实现
│   │   ├── harness/
│   │   │   ├── agents/
│   │   │   │   ├── base.py                # Agent 约束及公共资源配置
│   │   │   │   ├── task_planning/         # 规划执行 Agent、Prompt、Skills
│   │   │   │   ├── researcher/            # 研究 Agent、Prompt、Skills
│   │   │   │   ├── coder/                 # 编码 Agent、Prompt、Skills
│   │   │   │   └── reviewer/              # 审查 Agent、Prompt、Skills
│   │   │   ├── middleware/                # 控制、重试、降级、审核、审计
│   │   │   ├── runtime/                   # 图执行、Checkpoint、流式解析
│   │   │   └── tools/builtins/            # ask_user、用户记忆工具
│   │   ├── model_providers/               # 模型契约、各厂商配置与客户端
│   │   ├── embeddings/                    # 本地 BGE 向量编码
│   │   ├── checkpoint/                    # Redis / PostgreSQL Saver
│   │   ├── cache/                         # 共享 Redis 客户端
│   │   ├── messaging/                     # 队列、执行事件的 Redis 实现
│   │   ├── security/                      # 密码摘要、登录会话、认证配置
│   │   └── observability/                 # Langfuse 与追踪上下文
│   ├── bootstrap/                         # 配置、装配、生命周期、初始化
│   └── workers/                           # 异步任务消费入口
├── frontpages/
│   ├── src/app/                           # App Router 页面与 BFF
│   ├── src/components/                    # UI 控件和业务组件
│   ├── src/hooks/                         # 会话状态、SSE、同步逻辑
│   ├── src/lib/                           # API、类型、服务端鉴权
│   ├── tests/                             # 代理与安全边界测试
│   └── package.json
├── migrations/alembic/                    # 业务数据库迁移
├── models/                                # 本地模型权重
├── tests/                                 # 后端单元与集成测试
├── scripts/                               # 初始化、运维等工具脚本；测试统一在 tests/
├── docs/                                  # 开发文档与过程记录
├── evals/                                 # 评估目录
├── infra/                                 # 部署相关目录
├── pyproject.toml
└── uv.lock
```

`models/` 存放模型权重，不是领域对象目录；领域业务类型位于 `domain/types/`。persistence 表示持久化技术，其中 `entities/` 是数据库映射，repositories/ 是仓储实现。

部分接口、类型和部署文件仍是扩展占位，不能仅凭目录存在判断能力已经上线。

## 任务会话与状态管理

### 一个会话，多轮输入

一个 `AgentTask` 对应一个工作会话。后续输入继续使用同一 `task_id` 和 `thread_id`，不是每句话都创建新任务。

| 标识 | 含义 | 何时变化 |
| --- | --- | --- |
| `task_id` | 业务任务会话身份 | 创建新工作任务时 |
| `thread_id` | LangGraph 执行线程身份 | 创建新工作任务时 |
| message.id | 消息身份与重复提交依据 | 每条新消息 |
| `attempt` | 已开始执行的轮次 | 正常启动新一轮时增加；人工恢复不增加 |
| `TaskContext.trace_id` | 既有业务关联编号 | 随任务上下文保存 |
| Langfuse `trace_id` | 一轮交互的观测编号 | 新输入创建；人工恢复沿用原轮次 |

租户、用户、记忆主键使用整数。现有任务、线程和消息标识使用 UUID，两者按实际业务分别管理。

### 任务状态

```mermaid
stateDiagram-v2
    [*] --> queued
    queued --> running: 开始新一轮
    queued --> cancelled: 取消
    running --> waiting_human: 请求人工输入或审核
    waiting_human --> running: 回复后恢复
    waiting_human --> cancelled: 取消
    running --> succeeded: 提交结果
    running --> failed: 执行失败
    running --> cancelling: 用户请求停止
    cancelling --> cancelled: 执行方确认退出
    succeeded --> queued: 继续输入或有待处理消息
    cancelled --> queued: 用户提交新输入
    failed --> queued: 用户提交新输入
```

停止中的会话暂不能续问；`failed` 仅表示本轮失败，允许在原会话修改要求后重新发送，清除旧错误并开始新一轮。`cancelled` 表示本轮已停止，用户可在原会话输入正确内容，重新排队开始新一轮。运行中的任务可通过 cancel 请求停止；等待人工时可提交对应回复或取消任务，不能用普通消息接口跳过恢复流程。

### 停止运行中的任务

输入框旁的“停止本轮”调用现有 cancel 接口。取消请求在短事务中保存为 `cancelling`，API 发布停止中事件，前端禁用发送并展示“正在停止”。排队、等待人工的任务直接进入 `cancelled`。

Worker 将当前执行放入独立 asyncio Task，每约 0.5 秒通过应用服务读取状态。发现取消请求后只取消该执行协程，等待执行退出，保留部分文本，提交最终取消状态后再 ACK；消费者继续处理下一任务。API 与 Worker 可以分进程，不依赖本地任务字典或瞬时 Pub/Sub 通知。

Runtime 显式关闭异步输出流，应用层区分用户取消与服务关闭。用户取消不记录为执行失败；未处理的用户消息及部分助手回答使用 `cancelled` 消息状态，刷新页面仍可查看。服务关闭造成的取消若没有用户取消请求，继续向上传播，不冒充正常取消并 ACK。

取消与结果提交竞争时，以行锁下的最新状态为准；旧轮次不能确认新轮次的取消。前端结合轮次和服务端更新时间忽略迟到状态；重新排队时轮次尚未增加，也能接受新状态并拒绝旧取消响应。

失败或停止后提交新消息继续使用原 `task_id/thread_id`，Worker 领取时增加 `attempt`。应用服务根据持久化消息的失败或停止标记通知 Runtime：清除旧轮次的待执行节点与人工中断，为未返回的工具调用补齐中止消息，清空旧计划并重置调用额度，再执行最新输入。历史消息和虚拟文件保留，旧工具不会因重新发送而自动续跑。

这是协作式停止：已生成 Token 和已完成的副作用无法撤回；断开连接不保证供应商立即停止计费。同步线程或不响应取消的外部工具不能被 asyncio 强行终止，实际延迟还受数据库、连接关闭和工具清理影响。Worker 故障退出后的 pending 回收仍待完善。

### 执行中补充内容

运行中收到的普通消息先保存为 `pending`，不直接修改已经运行中的图输入。本轮结束后，领域服务检查是否还有待处理消息；如有，让会话重新排队进入下一轮。

一次领取可以合并多条待处理输入，消息状态按 `pending` → `processing` → `applied` 推进。人工暂停时，本轮输入保留 `processing`，恢复后继续同一轮。消息编号重复且内容相同不会重复保存，内容不同则视为冲突。

### 人工中断与恢复

1. Agent 调用 `ask_user`，或已启用的审核中间件调用 interrupt()。
2. LangGraph 保存暂停现场，Runtime 将中断转换为统一的 `TaskInterrupt`。
3. 任务进入 `waiting_human`，SSE 发送问题或审批数据，前端展示表单。
4. 用户提交 answers：键是实际中断 ID，值是文本回答或审批结果。
5. API 检查归属与恢复条件，将恢复命令入队。
6. Worker 使用相同线程读取 Checkpoint，以 `Command(resume=...)` 继续执行。

进程重启不要求重新生成整套计划，但必须保留可用的 Checkpoint、业务数据和正确线程。恢复时图可能重新进入中断节点附近的代码，高风险副作用仍需幂等保护。

## 会话标题与本轮执行标题

会话列表和聊天顶部继续展示可手动修改的会话名称。任务面板展示当前轮的执行标题、步骤和状态，例如同一“版本开发”会话内先“编写地图策划”，下一轮再“检查上线风险”。Agent 通过 `set_execution_title` 工具结合最新输入与上下文概括标题，不单独调用一个标题生成模型；该工具仍计入现有工具预算，简单问答也可能因此增加工具往返。

每个正常新轮次清空 execution_title 和 todos；人工中断恢复保留原轮次和标题。尚未生成标题时显示“第 N 轮执行”，排队时显示“等待新一轮执行”，不使用整个会话名称代替。模型若未调用标题工具，保留轮次占位标题。

`agent_task_executions` 按 task_id + attempt 唯一保存本轮标题、步骤、状态与完整/部分结果。历史选择器可回看已经保存的轮次，会话重命名不会改动历史执行标题。历史轮次的文件版本和浏览器关闭前的完整动态时间线不在本次持久化范围内；交付物仍为当前虚拟工作区中的文件。

部署前需执行新增迁移：先停止后端，在根目录运行 `uv run alembic upgrade head`，然后重启 API/Worker 并刷新前端。不会为升级前未记录的轮次编造标题或步骤历史。

## Agent、子 Agent 与 Skills

### 模型与 Provider

`ModelProvider` 规定 `get_model(context)` 返回 `BaseChatModel`。每个 Provider 管理自己的配置前缀与客户端：

| Provider | 配置前缀 | 当前实现 |
| --- | --- | --- |
| `DeepSeekProvider` | DEEPSEEK_ | 独立实现 `ModelProvider`，使用 `ChatOpenAI` 客户端 |
| `QwenProvider` | QWEN_ | 继承 `OpenAIProvider`，复用兼容协议客户端 |
| `OpenAIProvider` | OPENAI_ | OpenAI 兼容接口 |

Agent 通过 `provider_class` 明确模型，不让上层每次随意传入模型。默认规划 Agent 使用 DeepSeek，并配置 Qwen 为备用。备用客户端会在构建图时取得，因此默认链路也需要有效的 Qwen 配置。

同一 Provider 实例通过 `cached_property` 复用模型客户端，Agent 持有的 Provider 也按实例缓存。当前凭据属于平台级连接；context 尚未用于从数据库选择各用户自己的模型凭据。

### 主 Agent 的职责

`TaskPlanningAgent` 区分三类输入：简单问题直接回答；只要求方案时生成计划；要求完成任务时规划并推进执行。

复杂任务通过 `write_todos` 保存完整计划，开始步骤时标为 `in_progress`，验收后才标为 completed。页面状态来自模型实际写入的计划，不由前端按时间猜测。

委派只提供子任务需要的目标、背景、约束、输入、交付要求与验收条件，避免将完整历史和无关工具日志复制给每个子 Agent。子 Agent 返回后，主 Agent 仍需验收，再决定是否完成步骤。

### 两类子 Agent

| 类型 | 来源 | 配置方式 |
| --- | --- | --- |
| 通用子 Agent | DeepAgents 的 general-purpose 委派能力 | 在实际 task 工具提供的类型中选择 |
| 专业子 Agent | `ResearcherAgent`、`CoderAgent`、`ReviewerAgent` 等 | 在主 Agent 的 `subagents` 参数中显式装配 |

专业 Agent 有独立的模型配置、Prompt、Skills 和工具列表，不会因处于同一项目就自动获得主 Agent 的全部工具或技能。通用子 Agent 的资源传递遵循框架配置。

当前装配层注册了规划、研究、编码和审查 Agent，但默认规划 Agent 没有传入这三个专业 Agent 的 `subagents` 实例。它们可作为 Runtime 注册项使用，不能描述为默认已组成四角色协作团队。主流程仍可使用框架内置通用子 Agent。

### Skills 与文件 Backend

每个 Agent 的资源放在自己的目录：

```text
agents/task_planning/
├── agent.py
├── system_prompt.md
└── skills/
    └── task-planning/
        └── SKILL.md
```

公共 Backend 使用 `CompositeBackend`：默认工作文件写入图状态的 `StateBackend`，/skills/ 映射到该 Agent 的本地技能目录，并通过文件权限禁止写入技能资源。

工作文件不是直接写入宿主机任意目录。/deliverables/ 下的文本文件随 Checkpoint 保存，Runtime 提取内容给前端，浏览器用 Blob 下载。目前没有上传到 RustFS，也没有接入 Docker 或远程代码执行沙箱。

### 实例和状态的生命周期

Runtime 与注册的 Agent 配置对象在进程中复用，Provider 与模型客户端按 Agent 实例缓存。**当前具体 Agent 的 `build(context)` 仍会调用 `create_deep_agent()` 构建图，没有全局缓存编译图。**

消息、计划、工具计数与文件属于执行状态，放在 Checkpoint，不放在共享 Agent 的可变属性中。Langfuse 回调按调用创建，不把有执行状态的回调做成所有用户共用的单例。

## 执行中间件

中间件位于 `src/agent_platform/infrastructure/harness/middleware/`，负责 Agent 执行中的技术控制。HTTP 认证、数据库事务与 SSE 生命周期分别在各自边界处理，不与 Agent 中间件混为一层。

### 已实现的中间件

| 类与文件 | 作用 | 关键行为 | 默认规划 Agent |
| --- | --- | --- | --- |
| `CustomModelCallLimitMiddleware` · `custom_model_call_limit.py` | 限制模型逻辑调用 | `before_model` 检查并增加计数 | 启用，最多 10 次 |
| `CustomToolCallLimitExceededMiddleware` · `custom_tool_call_limit.py` | 工具总次数及单工具额度 | 模型输出工具调用后，执行前检查整批请求 | 启用，总上限 20，单工具表为空 |
| `ToolCallAuditMiddleware` · `tool_call_audit.py` | 工具开始、结束、异常、耗时日志 | 中断信号不当作普通故障 | 启用 |
| `CustomToolPermissionMiddleware` · `custom_tool_permission.py` | 禁用指定工具 | 工具执行入口检查黑名单 | 启用，默认黑名单为空 |
| `CustomModelFallbackMiddleware` · `custom_model_fallback.py` | 主模型故障时切换备用 | 连接、限流、服务异常时使用备用请求 | 启用，备用 Qwen |
| `CustomModelRetryMiddleware` · `custom_model_retry.py` | 有限模型重试 | 官方 `ModelRetryMiddleware`，指数退避与抖动 | 启用，最多重试 2 次 |
| `ExecutionTitleMiddleware` · `execution_title.py` | 本轮执行标题 | 注入标题工具及图状态，通过现有模型推理生成 | 启用，公共 Agent 配置装配 |
| `TodoListMiddleware` · 框架组件 | 计划工具与计划状态 | `write_todos` 更新步骤 | 显式配置 |
| `CustomToolRetryMiddleware` · `custom_tool_retry.py` | 指定工具的有限重试 | 只重试配置工具的 TimeoutError、ConnectionError | 已实现，默认未装配 |
| `HumanApprovalMiddleware` · `human_approval.py` | 工具执行前人工审核 | interrupt 暂停，批准后继续，拒绝则报错 | 已实现，默认未启用 |

额度是规划 Agent 当前代码的配置，不是平台统一配额。其他 Agent 或子图只有接入对应中间件才受相应控制；主 Agent 的局部计数不是整棵子 Agent 树的全局预算。

### 默认顺序与配合方式

规划 Agent 的显式顺序是：模型调用限制、工具次数限制、工具审计、工具权限、模型降级、模型重试、TodoList，再追加外部传入的中间件。

模型降级包裹重试：主模型先完成有限重试，仍命中降级异常时尝试备用模型；备用请求也经过内层重试。“重试两次”不表示整个任务最多只发送三次网络请求。

- **模型逻辑调用次数**：模型节点进入次数，控制推理循环规模。
- **底层重试次数**：一次逻辑调用内，连接或服务故障造成的额外尝试。
- **工具请求次数**：模型要求执行的工具数量，一条消息包含多个调用时按多个计数。
- **工具重试次数**：在一次逻辑调用内部额外尝试，不自动等价于业务幂等。

Runtime 在正常新一轮输入时重置模型和工具计数，人工恢复保留计数。计数存放在图状态中，原有 `messages` 仍保留，新增状态字段不会替代模型消息。

工具额度在执行前检查，约束的是请求预算，不是只统计成功副作用。需要重试的写操作仍要保证幂等，不能仅依靠重试中间件。

### 超时、限流与权限的边界

模型重试处理 APIConnectionError、APITimeoutError、RateLimitError、InternalServerError；这不等于已经实现平台限流器、熔断器或整轮任务统一截止时间。

模型客户端代码尚未启用自定义 `timeout` 和 `max_retries` 参数，底层 SDK 也可能保留默认重试。真实网络尝试次数需要结合 SDK 与中间件两层分析。

工具禁用是执行控制。用户能否读取任务、修改记忆，由服务端身份、领域规则和仓储过滤共同保证，不能仅靠提示词或工具名称黑名单。

## 前端架构与实时更新

### 页面和组件职责

| 路径 | 职责 |
| --- | --- |
| `frontpages/src/app/login/page.tsx` | 登录页面 |
| `frontpages/src/app/page.tsx` | 登录后的任务工作区 |
| `frontpages/src/app/account/page.tsx` | 个人中心、账户设置与长期记忆 |
| `frontpages/src/app/admin/users/page.tsx` | 管理员用户管理 |
| `frontpages/src/app/api/backend/[...path]/route.ts` | 同源 BFF、Cookie 转换、白名单、SSE 转发 |
| `frontpages/src/hooks/use-task-workspace.ts` | 会话状态、历史、SSE、重连、定期同步 |
| `frontpages/src/lib/task-api.ts` | 任务 HTTP 客户端与 SSE 流解析 |
| `frontpages/src/components/workspace/` | 对话、计划、人工回复、交付物与执行动态 |
| `frontpages/src/components/ui/` | 通用控件与 Radix 组合组件 |

页面入口在服务端检查登录状态，管理页面额外检查管理员角色。后端仍独立鉴权，前端隐藏按钮不能替代服务端权限控制。

工作区左侧“新工作任务”创建规划会话；“新对话”是禁用入口，尚未提供独立普通聊天或客服会话。

### SSE 如何更新页面

前端使用 Fetch 可读流解析 SSE，不依赖浏览器 EventSource 完成全部逻辑。解析器保留跨分片的半行、半条事件与 UTF-8 字符，识别 id、event 和 data。

| 事件 | 页面处理 |
| --- | --- |
| `queued`、started、resuming | 更新排队或运行状态 |
| `text_delta` | 追加当前轮次的文本草稿 |
| `plan_updated` | 替换完整计划，展示 `pending` / `in_progress` / completed |
| `tool_requested` | 展示工具或子 Agent 委派开始 |
| `tool_returned`、`tool_failed` | 展示返回、失败及可用耗时 |
| `waiting_human` | 显示输入或审核表单 |
| `resume_rejected` | 恢复等待状态，提示重新填写 |
| completed、`failed`、`cancelled` | 更新业务结果并触发同步 |
| state | 无新事件时辅助校准状态 |
| `auth_expired` | 返回登录页 |

事件携带 `attempt`，前端忽略旧轮次对当前内容的覆盖。持久化事件携带 Redis Stream ID，前端记录游标并过滤重复事件。state 是辅助通知，不伪造持久化事件编号。

断开后按游标重连，切换会话或卸载时通过 AbortController 关闭旧连接，避免旧会话污染当前页面。前端同时约每 5 秒同步状态、消息与执行结果，弥补通知失败或页面重开的情况。

输入框草稿按账号和任务独立保存在页面内存中。切换任务只展示该任务的草稿，切回时恢复；新建任务只清空新任务草稿。旧任务提交回包只清空原草稿，不覆盖另一个任务的输入；新任务创建期间若切换会话，回包不会抢回当前选择。刷新页面不保留未发送草稿。

工具事件主要传递工具名、调用编号、子 Agent、文件路径及耗时，不等于输出完整原始工具返回正文。时间线显示的是浏览器接收事件的时间。

### 同源 BFF

浏览器只访问 Next.js 的 /api/backend/...，由服务端代理到 FastAPI：

- 令牌写入 HttpOnly、SameSite=Lax Cookie，生产环境启用 Secure。
- BFF 从 Cookie 构造 Authorization，忽略浏览器伪造的 Authorization。
- 写请求校验 Origin，后端路径采用白名单。
- SSE 保留事件流、Last-Event-ID 与不缓冲响应头，不使用普通 JSON 请求的短超时。
- X-Trace-ID 从后端响应透传，便于在浏览器 Network 中定位链路。

`FRONTEND_ORIGIN` 必须与实际访问地址完全一致。localhost 与 127.0.0.1 是不同 Origin，即使端口相同也不能互换。

## 数据库、事务与资源生命周期

### 业务表

| 表 | ORM 文件 | 保存内容 |
| --- | --- | --- |
| `agent_tasks` | `entities/agent_tasks.py` | 任务归属、名称、状态、轮次、结果 |
| `agent_task_executions` | `entities/agent_task_executions.py` | 各轮标题、计划、状态及结果快照 |
| `agent_task_messages` | `entities/agent_task_messages.py` | 用户与助手消息、处理状态、顺序 |
| `user_memory` | `entities/user_memory.py` | 一条个人记忆、1024 维向量、模型标识 |
| `sys_tenant` | `entities/sys_tenant.py` | 租户、公司代码、默认项目、启用状态 |
| `sys_user` | `entities/sys_user.py` | 用户、密码摘要、角色、认证修订信息 |

ORM 位于 `src/agent_platform/infrastructure/persistence/`。模型统一导入 `entities/__init__.py`，Alembic 读取 `BaseTable.metadata`。

新增表后，需要使模型进入 metadata，再生成并审阅迁移。修改类名不会自动重命名数据库表；修改 `__tablename__` 也不能期望 Alembic 自动识别为重命名，应明确编写保留数据的迁移。

### Session 与事务传播

`Database` 创建异步 Engine、连接池与 Session 工厂。当前池大小为 5，额外溢出连接最多 5，启用连接存活检查。

API 与 Worker 入口通过 `sessionmaker_context()` 绑定会话工厂。需要数据库上下文的应用方法使用 `@transactional(Propagation.REQUIRED)`，仓储通过 `current_session()` 取得 Session，不自行创建、提交或关闭另一个 Session。

外层有 REQUIRED 事务时，内层 REQUIRED 加入它；没有外层时，装饰方法创建自己的事务。两个各自带事务的方法，被一个**没有事务**的方法依次调用，不会自动合成总事务。当前仓储也没有“无事务时自动创建并提交 Session”的兜底机制。

任务执行分三个阶段：

1. 短事务：读取并锁定任务、领取输入、保存运行状态。
2. 事务之外：模型推理、工具调用、人工暂停、流式输出。
3. 短事务：检查轮次、保存结果与消息、完成消息状态、判断下一轮。

这样不会为耗时几分钟的模型任务持续占用业务数据库事务。记忆保存与修改也先生成向量，再进入数据库短事务。

数据库提交与 Redis 入队是两个步骤，没有分布式原子提交，尚未实现 Outbox 或恰好一次投递。

### 共享资源与关闭顺序

| 对象 | 生命周期 | 隔离方式 |
| --- | --- | --- |
| PostgreSQL Engine / Pool | 每个进程共享 | Session 不共享 |
| Redis 客户端 | 每个进程共享 | 不同用途使用独立键或 Stream |
| BGE 模型 | 每个进程共享 | 同一实例串行推理，避免内存堆积 |
| Runtime / Agent 配置 | 进程复用 | 用户状态进入上下文与 Checkpoint |
| Provider / 聊天客户端 | 同一 Agent 实例缓存 | 不保存当前用户的请求状态 |
| 编译图 | 当前 build() 调用构建 | 尚无全局图缓存 |
| Session / 事务 | 当前调用链与协程 | 事务上下文管理 |
| Langfuse 回调 | 每次调用创建 | 不共享有状态回调 |

启动时初始化 Redis、追踪、队列消费组、数据库、Checkpoint，预热本地向量模型，然后接收请求并按配置启动 Worker。已有消费组会复用，不因重复启动而删除队列。

关闭时 SSE 主动结束；Worker 停止领取新消息，等待当前工作，超时后取消；随后回收业务资源、追踪和 Redis，清除相关装配缓存。Worker 等待上限 30 秒、SSE 关闭宽限 3 秒、Uvicorn 请求关闭上限 10 秒，分别属于不同阶段。

## 短期状态与长期记忆

### 数据分别保存在哪里

| 数据 | 当前存储 | 作用 |
| --- | --- | --- |
| 可展示聊天历史 | PostgreSQL `agent_task_messages` | 页面历史、顺序、输入处理状态 |
| 图执行现场 | Redis 或 PostgreSQL Checkpoint | 模型消息、计划、计数、中断、虚拟文件 |
| 用户长期记忆 | PostgreSQL `user_memory` + pgvector | 跨任务偏好与稳定事实 |
| SSE 执行事件 | Redis Streams | 实时更新与断线续传 |
| 登录状态 | Redis 会话键 | 令牌有效性与撤销 |
| Trace 恢复关联 | Redis 追踪上下文 | 人工恢复与原轮次观测关联 |

聊天历史不等于模型全部上下文，Checkpoint 不替代业务历史表。删除长期记忆不会自动删除聊天历史、Checkpoint 或已经导出的追踪内容。

### 用户长期记忆

每条记忆独立成行，使用整数主键，不把所有长期内容塞到一个大字段。保存租户、用户、正文、向量、向量模型与时间信息。当前作用域是**租户内个人记忆**，尚无团队共享记忆或部门授权。

本地模型 BAAI/bge-large-zh-v1.5 输出 1024 维归一化向量，查询添加检索指令。数据库按余弦距离排序，返回 1 - distance 作为相似度；相似度表示候选相关程度，不是事实正确率。

保存与检索使用相同模型标识，防止不同编码模型混用。当前有租户、用户联合索引，没有配置 HNSW 或 IVFFlat 近似向量索引。

| 工具 | 用途 |
| --- | --- |
| `save_user_memory` | 用户明确要求记住新偏好或事实时保存 |
| `search_user_memory` | 按主题检索相关记忆 |
| `list_user_memories` | 按游标分页列出记忆 |
| `update_user_memory` | 用真实编号纠正条目，重新生成向量 |
| `delete_user_memory` | 用真实编号删除条目 |

工具从 `ToolRuntime.context` 取得可信身份，调用 `UserMemoryApplicationService`，再通过领域仓储契约进入数据库实现。工具是入站适配器，不直接创建 Session 或模型。

纠正记忆时先检索或列表定位，再更新同一 ID，不能简单新增相互矛盾的记录。个人中心提供列表、编辑、删除；列表不调用向量模型。

当前长期记忆采用显式工具与业务仓储，未配置 LangGraph `store` 作为记忆存储，也未接入额外的图节点 `cache` 或语义回答缓存。配置 Store 本身不会使模型自动记住内容，仍需要业务定义保存、读取入口。

## 登录、用户管理与数据隔离

登录只填写全系统唯一的用户名和密码，租户归属由账号记录确定。公司代码用于初始化与内部管理，不要求每次登录输入。

密码由 pwdlib 的 Argon2 实现生成不可逆摘要。服务端生成随机不透明令牌，Redis 键保存令牌的 SHA-256 摘要，会话有绝对有效期；当前登录方案不是 JWT。

认证检查租户、用户是否启用，以及会话认证修订号。修改或重置密码可使旧修订会话失效。退出删除当前会话，但不会仅因浏览器退出就撤销已接收任务；Worker 开始执行前复核账号状态。

管理员可管理本租户用户、角色、启停用和密码重置。角色为 admin、user，尚未实现部门、文档与细粒度资源授权体系。

隔离落实在各边界：

- API 从认证会话构造 `Principal`，不接受请求体随意指定租户、用户。
- 任务聚合检查租户、项目、用户归属，仓储查询限制访问范围。
- 记忆仓储始终按租户、用户过滤。
- Checkpoint 命名空间包含租户、项目、用户、线程和任务编号。
- 事件与追踪上下文使用任务归属命名空间。
- SSE 定期复核会话，过期后发送 `auth_expired` 并结束。

登录限制含账号与客户端两维度，使用 Redis 原子计数和过期窗口。当前代理拓扑下，后端看到的客户端地址可能是 Next.js 地址，不等于已完成真实终端 IP 识别。

## Langfuse 链路追踪

追踪集中在 `infrastructure/observability/`，只接入 API、队列、Worker、Agent Runtime 四个边界，不向领域模型添加 SDK 对象，不改变应用服务业务方法。

### Trace 与 Span

- 正常输入建立 Trace，API 将当前上下文随队列消息发送。
- Worker 接续上下文创建消费 Span，主 Agent 建立下级执行 Span。
- 官方 LangChain 回调记录模型、工具和子图，子 Agent 可以挂在委派工具 Span 下。
- 人工暂停前，Redis 保存当前轮次 Trace 与 Span 上下文。
- 人工回复经过归属检查后沿用原 Trace，创建新的 API、Worker 和执行片段。
- 本轮结束后的新输入创建新 Trace，同一会话通过 `session_id` 聚合。

每个 Span 只有一个父节点。多条补充输入合并执行时，以实际队列来源保留父链，用 Span Link 关联其他输入来源，不伪造多父节点。

### Trace 标签筛选

标签统一由 `infrastructure/observability/langfuse.py` 生成与传播。可按 `workflow:task`、`boundary:api`、`boundary:worker`、`boundary:agent`、`agent:task_planning`、`operation:execute`、`operation:resume`、`invocation:new_round`、`invocation:human_resume` 和 `round:first`、`round:followup` 分类筛选。环境使用原生 environment 字段，任务与用户编号保留在 metadata。

例如组合 `agent:task_planning` 和 `invocation:human_resume` 查人工恢复的规划任务。同一 Trace 汇总多个片段的标签，人工恢复后可能同时包含 execute 与 resume。标签不回填历史数据；追踪开关启用并重启 API 和独立 Worker 后，再提交新请求验证。

### 关联与故障处理

追踪附带 `task_id`、`thread_id`、`attempt`、租户和用户信息；Worker 记录队列消息编号。API 返回 X-Trace-ID，BFF 透传，浏览器可据此定位执行。

恢复上下文保存到 Redis，不仅保留在内存中。技术上下文没有短 TTL，任务归档后的统一清理尚待完善。

关闭开关时不初始化真实 SDK。初始化、回调、上下文存取或关闭失败会记录日志，尽量不影响任务；追踪关联丢失时可能产生新 Trace，不能保证故障期间仍有完整调用树。

SSE 长连接、登录密码与查询轮询不纳入本次执行 Span。Langfuse 会采集模型和工具内容，部署位置、访问范围、脱敏需符合企业保密要求。当前接入不等于已经保证资料绝不出域。

## 配置与本地启动

### 环境要求

- Python 3.12 与 uv。
- Node.js 满足前端 engines 的 >=20.9.0，同时提供 npm。仓库使用 `package-lock.json`，不要求额外安装 pnpm。
- PostgreSQL 已启用 pgvector。
- Redis。默认 Redis Checkpoint 还需要相应 JSON、搜索能力，应以实际安装模块为准。
- 完整的 BGE 本地模型目录 `models/BAAI/bge-large-zh-v1.5/`，启动时只从本地加载。
- 可访问的模型服务；Langfuse 按需启用。

### 模块化配置

各模块共用根目录 `.env`，但由各自的配置类或资源模块读取，不统一堆进包含所有业务的 Settings。模块分别维护前缀、验证与客户端初始化。

| 模块 | 配置入口 | 变量 |
| --- | --- | --- |
| 应用与队列 | `bootstrap/settings.py` | HARNESS_* |
| 共享 Redis | `infrastructure/cache/redis.py` | `REDIS_URL` |
| PostgreSQL Checkpoint | `infrastructure/checkpoint/postgres_checkpoint.py` | `POSTGRES_URL` |
| 聊天模型 | `infrastructure/model_providers/` | DEEPSEEK_*、QWEN_*、OPENAI_* |
| 登录认证 | `infrastructure/security/settings.py` | AUTH_* |
| 追踪 | `infrastructure/observability/settings.py` | LANGFUSE_* |

下面是开发环境模板，账号、密码和密钥均需替换：

```dotenv
# HTTP 与开发环境消费者
HARNESS_ENVIRONMENT=development
HARNESS_HOST=127.0.0.1
HARNESS_PORT=8000
HARNESS_WORKER_ENABLED=true
HARNESS_WORKER_CONCURRENCY=1
HARNESS_TASK_QUEUE_STREAM=agent_platform:tasks
HARNESS_TASK_QUEUE_GROUP=agent_platform:task_workers

# 业务数据库
HARNESS_DATABASE_URL=postgresql://app_user:change_me@127.0.0.1:5432/agent_platform

# 共享 Redis：队列、事件、登录会话、默认 Checkpoint 等
REDIS_URL=redis://127.0.0.1:6379/0
HARNESS_CHECKPOINT_BACKEND=redis

# 选择 PostgreSQL Checkpoint 时配置
# POSTGRES_URL=postgresql://app_user:change_me@127.0.0.1:5432/agent_checkpoint

# 默认规划 Agent 的主模型与备用模型
DEEPSEEK_MODEL_NAME=deepseek-chat
DEEPSEEK_BASE_URL=https://api.deepseek.com
DEEPSEEK_API_KEY=replace_me
QWEN_MODEL_NAME=qwen-plus
QWEN_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
QWEN_API_KEY=replace_me

# 使用 OpenAIProvider 时配置
# OPENAI_MODEL_NAME=your_model
# OPENAI_BASE_URL=https://your_model_endpoint/v1
# OPENAI_API_KEY=replace_me

# 登录会话与限制窗口，时间单位为秒
AUTH_SESSION_TTL=28800
AUTH_LOGIN_LIMIT=10
AUTH_LOGIN_WINDOW=300

# 可选追踪，开启时需提供完整地址与密钥
LANGFUSE_TRACING_ENABLED=false
# LANGFUSE_BASE_URL=http://127.0.0.1:3001
# LANGFUSE_PUBLIC_KEY=replace_me
# LANGFUSE_SECRET_KEY=replace_me
LANGFUSE_TRACING_ENVIRONMENT=development
LANGFUSE_TIMEOUT=5
```

共享 Redis 实际读取 `REDIS_URL`，不能只设置 `HARNESS_REDIS_URL`。根目录 `.env.example` 未列出默认执行链的全部变量，应确认主模型、备用模型和 Worker 配置已补齐。

业务 `Database` 接收标准 PostgreSQL URL，在 SQLAlchemy 入口选择 Psycopg 驱动。Checkpoint 直接交给 Psycopg 的 `POSTGRES_URL` 使用标准 postgresql://，不要写成 postgresql+psycopg://。密码中的 @ 编码为 %40，其他 URL 保留字符同样需要正确编码。

### 安装后端与迁移业务表

在项目根目录执行：

```powershell
uv sync --locked --group dev
```

在目标 PostgreSQL 业务数据库启用扩展：

```sql
CREATE EXTENSION IF NOT EXISTS vector;
```

执行已有迁移：

```powershell
uv run alembic upgrade head
```

后续修改 ORM 时生成新的迁移，审阅后执行：

```powershell
uv run alembic revision --autogenerate -m "describe change"
uv run alembic upgrade head
```

Alembic 管理业务表。Checkpoint 的表、索引和初始化由对应 Saver 管理，不通过业务 ORM 代建。

### 初始化管理员

首次使用执行一次：

```powershell
uv run harness-init-admin
```

填写公司代码、名称、管理员登录名和密码。密码通过隐藏输入读取；完成后用登录名和密码进入页面。

管理员初始化仍是独立的一次性命令，不在每次 harness-api 启动时自动创建，也没有公开 HTTP 初始化入口。

### 启动后端

```powershell
uv run harness-api
```

联调设置 `HARNESS_WORKER_ENABLED`=true，API 生命周期同时启动一个消费者，无需再启动第二个 Worker。配置类中该开关默认为 false，因此必须显式启用，或启动独立消费者。

| 地址 | 用途 |
| --- | --- |
| `http://127.0.0.1:8000/health` | HTTP 健康检查 |
| `http://127.0.0.1:8000/docs` | OpenAPI 交互文档 |
| `http://127.0.0.1:8000/api/v1` | 业务接口前缀 |

健康检查成功不代表模型调用、队列恢复和全部业务流程已验收。

### 启动前端

```powershell
cd frontpages
Copy-Item .env.example .env.local
npm.cmd ci
npm.cmd run dev
```

前端 `.env.local`：

```dotenv
HARNESS_API_URL=http://127.0.0.1:8000
FRONTEND_ORIGIN=http://localhost:3000
```

浏览器访问 http://localhost:3000。改用 127.0.0.1 或其他域名时同步调整 `FRONTEND_ORIGIN`。前端开发脚本监听 127.0.0.1，对外部署时需调整监听地址。

`HARNESS_API_URL` 只在 Next.js 服务端使用，不加 NEXT_PUBLIC_。Windows PowerShell 若拦截 `npm.ps1`，可使用上述 `npm.cmd`。

### API 与 Worker 分开运行

需要独立部署时，在 API 环境关闭内置消费者：

```dotenv
HARNESS_WORKER_ENABLED=false
```

另一个终端或进程执行：

```powershell
uv run harness-worker
```

两进程使用相同业务库、队列配置、Checkpoint 与事件存储。资源缓存都是进程内缓存，不是多个进程共享 Python 对象。当前按单消费者联调，多消费者并发和故障恢复尚未作为完整生产能力验收。

### 可选 PostgreSQL Checkpoint

```dotenv
HARNESS_CHECKPOINT_BACKEND=postgres
POSTGRES_URL=postgresql://app_user:change_me@127.0.0.1:5432/agent_checkpoint
```

首次使用或升级 Saver 表结构时执行：

```powershell
uv run python -m agent_platform.bootstrap.database
```

该入口只初始化 PostgreSQL Checkpoint。Windows 的 Psycopg 异步连接需要 Selector 事件循环，API、Worker 和管理员入口已显式选择；这个数据库初始化模块仍使用默认 `asyncio.run()`，在 Windows 执行前需补齐相同的事件循环选择，不能假设所有辅助脚本均已统一处理。

即使 Checkpoint 选择 PostgreSQL，队列、事件和登录会话仍需要 Redis。

### 可选 Langfuse

开启 `LANGFUSE_TRACING_ENABLED`=true 并提供地址、公钥、私钥后，启动时初始化客户端。当前本地 SDK 为 5.0.4，自托管服务端需兼容 SDK 5，至少为 4.59.0。

从任务写请求的 X-Trace-ID 查找 Trace，查看 API、Worker、主 Agent、模型、工具和实际发生的子 Agent 委派。恢复人工中断核对 Trace 不变，新一轮输入核对 Trace 变化。

## HTTP 接口

除健康检查外，下列路径统一带 /api/v1 前缀。登录接口用于建立身份，其余业务接口需要有效身份；用户管理需要管理员权限。

### 认证与用户

| 方法 | 路径 | 用途 |
| --- | --- | --- |
| POST | `/auth/login` | 用户名、密码登录 |
| GET | `/auth/me` | 当前用户 |
| POST | `/auth/logout` | 退出当前会话 |
| PUT | `/auth/password` | 本人修改密码 |
| GET | `/users` | 查询本租户用户 |
| POST | `/users` | 创建用户 |
| PATCH | `/users/{user_id}` | 修改名称、角色、启用状态 |
| POST | `/users/{user_id}/reset-password` | 管理员重置密码 |

### 工作任务

| 方法 | 路径 | 用途 |
| --- | --- | --- |
| POST | `/tasks` | 创建任务会话并入队，返回 202 |
| GET | `/tasks` | 当前用户最近会话 |
| GET | `/tasks/{task_id}` | 业务状态与结果 |
| PATCH | `/tasks/{task_id}` | 修改名称 |
| GET | `/tasks/{task_id}/messages` | 消息历史 |
| POST | `/tasks/{task_id}/messages` | 同一任务追加消息，返回 202 |
| GET | `/tasks/{task_id}/executions` | 查询有权访问的会话各轮执行快照 |
| GET | `/tasks/{task_id}/execution` | 计划、中断与文本交付物 |
| GET | `/tasks/{task_id}/events` | SSE，支持 Last-Event-ID 或 after 游标 |
| POST | `/tasks/{task_id}/resume` | 提交中断回复并入队，返回 202 |
| POST | `/tasks/{task_id}/cancel` | 请求停止；运行中先返回 cancelling，退出后为 cancelled |

创建请求：

```json
{
  "agent": "task_planning",
  "prompt": "整理下一次版本的开发计划，列出依赖和验收标准"
}
```

同一会话追加消息：

```json
{
  "id": "a9178b37-750d-43d4-807a-e0417ac16ac4",
  "content": "补充：优先安排支付与活动配置相关任务"
}
```

客户端为每条新消息生成编号，重试同一消息时复用该编号。人工回复使用实际收到的中断 ID，不能任意填写序号。

### 个人记忆

| 方法 | 路径 | 用途 |
| --- | --- | --- |
| GET | `/user-memories` | 当前用户记忆列表，支持 cursor、limit |
| PATCH | `/user-memories/{memory_id}` | 修改正文并重新编码向量 |
| DELETE | `/user-memories/{memory_id}` | 删除自己的记忆 |

个人中心没有单独的新增、语义搜索 HTTP 路由，这两项能力由 Agent 工具和应用服务提供。工具能力不能直接当成已公开的 HTTP 接口。

## 开发与验证

### 后端

业务规则优先验证聚合、领域服务；适配器验证契约、隔离和失败分支。真实模型、Redis 与 PostgreSQL 集成验证需要对应环境，离线测试不能代替端到端验收。

追踪模块离线测试不初始化真实 SDK，不连接 Langfuse：

```powershell
uv run python -m unittest discover -s tests/unit -p "test_*tracing.py" -v
```

按改动范围执行对应测试与静态检查：

```powershell
uv run pytest tests/unit -q
uv run ruff check src tests
```

这些是开发命令，不表示整个历史测试集已经全部通过；部分历史测试仍需与持续调整的接口、装配方式同步。

### 前端

```powershell
cd frontpages
npm.cmd run typecheck
npm.cmd run lint
npm.cmd run test:auth
npm.cmd run test:tasks
npm.cmd run build
```

代理测试覆盖 Cookie、来源、白名单、SSE 转发与 Trace 响应头。生产构建和真实后端联调需在目标环境完成。

### 一次完整联调

1. 迁移数据库，初始化管理员，准备 Redis 与本地模型。
2. API 同时启动一个 Worker，启动前端并登录。
3. 创建任务，观察 `queued`、started、文本和计划事件。
4. 检查步骤真实从 `pending` 变为 `in_progress`、completed。
5. 产生 /deliverables/ 文本文件，预览并下载。
6. 同一会话续问，确认没有创建新任务身份。
7. 触发 `ask_user`，暂停后重启后端，以原中断回复恢复。
8. 保存、查询、纠正、删除个人记忆，在个人中心核对。
9. 使用另一用户确认任务和记忆不可互相访问。
10. 开启 Langfuse，核对 Trace、父子 Span、人工恢复和下一轮输入。

## 当前边界与后续建设

| 方向 | 当前边界 | 后续工作 |
| --- | --- | --- |
| 普通聊天与客服 | 前端入口未启用 | 独立会话、连续输入、多意图、客服流程 |
| 企业 RAG | 有向量基础，未接文档流水线 | 解析、切分、索引、混合检索、重排序、来源与授权 |
| Qdrant | 当前记忆实际使用 pgvector | 按知识库场景引入，明确索引与权限 |
| 隔离沙箱 | 有契约与类型，未接执行环境 | 资源限制、受控网络、文件交接 |
| RustFS | 未接当前交付物链路 | 对象存储、下载授权、生命周期 |
| 专业子 Agent | 类和资源已存在，默认未装配为子项 | 明确工具、Skills、交接与验收后装配 |
| 执行预算 | 单图局部计数为主 | 跨子图的任务级预算 |
| 队列恢复 | 已有消费组与 ACK | `pending` 回收、异常恢复、重投与幂等验证 |
| 数据库与队列一致性 | 提交数据库后再入队 | 可靠投递、补偿或 Outbox |
| 存储治理 | 状态、事件与关联数据持续增长 | 归档、保留周期、清理与容量监控 |
| 模型治理 | 平台级配置，重试和降级已接入 | 租户凭据、限流、统一超时与熔断 |
| 数据保密 | 已有身份隔离，服务按配置访问 | 内网模型、出口控制、脱敏和实际安全验证 |

后续能力沿现有契约扩展，保持领域规则、应用编排和技术实现各自清晰。

## 执行安全与 DDD 边界调整

本次调整保留 Interface → Application → Domain 的业务调用方向，数据库、Redis、DeepAgents 与连接监测仍属于 Infrastructure；Bootstrap 负责装配，Workers 负责后台入口。

| 责任 | 位置 | 行为 |
| --- | --- | --- |
| 业务状态与旧执行校验 | `domain/aggregates/agent_task.py`、`domain/services/agent_task_domain_service.py` | `attempt` 是展示轮次；`execution_id` 在每次启动和人工恢复时重新生成，结果、失败、人工回复及取消确认都校验执行身份 |
| 用例协调和事务 | `application/services/agent_task_application_service.py` | `get()` 只读；`open_task()` 显式检查异常执行；删除拆成短事务校验、事务外清理、短事务删除 |
| 执行权与断线监测 | `infrastructure/persistence/task_execution_guard.py` | PG 会话锁使用独立连接池；每两秒探测连接，探测最多等待两秒，失效时取消所属执行协程 |
| 流式事件 | `infrastructure/messaging/redis_task_events.py` | 文本、工具动态与计划回调不逐片查询业务表；Redis 原子校验执行标识，已关闭或已删除的流拒绝迟到片段 |
| 持久化清理 | Checkpoint、事件、队列及追踪组件 | 组件清理自己的存储；统一清理器只协调调用，不拼接其他组件的私有键 |
| 维护扫描 | `workers/task_maintenance_worker.py` | 每十五秒协调补偿与删除重试；每次按 ID 游标最多读取五十条，避免活跃任务占满第一页 |
| 用户创建规则 | `domain/services/user_domain_service.py` | 管理员权限、登录名唯一性和公司初始化规则由领域服务维护；应用层负责密码计算和事务 |

删除请求仍返回 202，并持久化删除意图，后台物理清理。外部清理失败时保留意图并重试，清理期间不持有业务行锁。队列消息在入队时原子建立会话索引，确认后移除消息及索引。升级后首次启动会按页回填旧队列索引并保存进度；后续启动与每次会话删除不再全量扫描共享队列。该队列由一个业务消费者组负责处理。

部署前先停止旧 API 和全部旧 Worker，执行 `uv run alembic upgrade head`，再启动新进程。本次新增迁移 `b72d19eaf305`：增加可空 `execution_id`，并调整补偿、删除扫描的部分索引。旧记录允许该字段为空，新执行自动生成标识。业务迁移与 Checkpoint Saver 自身的建表仍分别管理。

执行身份校验保护业务结果和事件流，连接监测负责终止协程；这些机制不能撤销已经发往外部系统的请求。写入外部系统的工具仍需自己的幂等键。PG 与 Redis 之间没有引入分布式事务，任务投递的可靠性增强仍属于 Outbox 的后续工作。

单元测试配置禁止外网 socket 连接和遥测导出。修改后应执行 `uv run pytest tests/unit -q`；真实 PostgreSQL、Redis 和迁移验证需在独立测试环境进行。

## 测试代码组织

所有 Python 测试统一放在根目录 `tests/`：`tests/unit/` 为离线单元测试，`tests/integration/` 为显式启用的真实依赖验证。`scripts/` 不再放演示或测试代码。

运行 `uv run pytest tests/unit -q` 验证单元测试；运行 `uv run pytest tests -q` 收集全部测试，未启用的集成测试默认跳过。配置方式见 [测试说明](tests/README.md)。

## 开源协议

本项目原创代码采用 [BSD Zero Clause License（0BSD）](LICENSE)。你可以自由使用、复制、修改和再分发，包括商业使用、收费分发及闭源集成；不要求署名、保留许可证副本或公开修改后的源码。

软件按原样提供，不附带担保，具体授权和免责条款以根目录 `LICENSE` 为准。

本协议不替代第三方依赖、模型权重、数据集及外部素材各自的许可证。使用或分发这些内容时，仍须遵守对应授权要求。
