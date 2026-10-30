# DeepAgent Enterprise Harness

企业内部 Agent 应用项目。使用 Python 3.12、FastAPI、DeepAgents、LangGraph、SQLAlchemy、PostgreSQL/pgvector 和 Redis，采用面向 Java 开发者的四层职责命名。

## 当前目录

```text
src/agent_platform/
├── interface/                         # 入站适配层
│   ├── api/                           # FastAPI 应用、路由、认证和依赖注入
│   └── vo/                            # HTTP 请求和响应类型
├── application/
│   ├── services/                      # 具体应用服务，不再拆分接口与 Impl
│   ├── dto/agent_task_dto.py           # 任务创建、人工回复和执行结果
│   └── interfaces/                    # Runtime、队列等外部能力契约
├── domain/
│   ├── aggregates/agent_task.py        # AgentTask 任务聚合根及其状态规则
│   ├── types/                         # 身份、记忆查询结果等业务类型
│   └── repositories/
│       ├── agent_task_repository.py   # AgentTaskRepository
│       └── memory_repository.py       # MemoryRepository
├── infrastructure/
│   ├── harness/
│   │   ├── agents/task_planning/       # TaskPlanningAgent、Prompt 和 Skills
│   │   ├── middleware/                # DeepAgents 执行控制中间件
│   │   ├── runtime/                   # DeepAgentsTaskRuntime
│   │   └── tools/                     # Agent 工具适配
│   ├── persistence/
│   │   ├── database.py                # Engine、连接池与会话工厂
│   │   ├── entities.py                # ORM 映射，MemoryRecord 对应 memories 表
│   │   └── repositories/              # 业务仓储的数据库实现
│   ├── embeddings/                    # 记忆与未来 RAG 共用的向量编码
│   ├── model_providers/               # DeepSeek、Qwen、OpenAI
│   ├── checkpoint/                    # Redis/PostgreSQL Checkpoint
│   └── cache/                         # Redis 客户端
├── bootstrap/                         # 依赖组装和进程资源生命周期
└── workers/agent_task_worker.py        # 队列消费与独立 Worker 入口
```

根目录 models 存放本地模型权重，与 domain/types 的业务类型含义不同。

## 业务名称

| 名称 | 含义 |
| --- | --- |
| AgentTask | 用户提交的业务任务聚合，维护身份、状态、结果和错误 |
| TaskContext | 可信任务上下文，包含 task_id、thread_id、trace_id 和身份 |
| TaskPlanningAgent | 生成计划的技术实现，不是领域聚合根 |
| AgentTaskRepository | 任务持久化契约，目前尚无数据库实现 |
| UserMemoryApplicationService | 生成记忆向量，再调用仓储保存或检索 |
| MemoryMatch | 记忆检索结果，不是记忆聚合根 |
| MemoryRecord | SQLAlchemy ORM 映射，不向应用层暴露 |

任务身份以 context.task_id 为准，聚合通过 id 属性读取同一个编号，不重复生成两套 ID。

## 领域行为

```python
from agent_platform.domain.aggregates.agent_task import AgentTask
from agent_platform.domain.types.common import TaskContext

context = TaskContext(tenant_id=1, user_id=2, project_id="game-version")
task = AgentTask(context=context, prompt="制定游戏版本迭代计划")
running = task.start()
waiting = running.wait_for_user()
resumed = waiting.resume()
completed = resumed.complete("计划已生成")
```

聚合不可变，业务方法返回新对象。领域规则限制状态迁移、完成结果和失败原因；从持久化数据重建时仍会校验。领域层不操作数据库或调用模型。

本次没有增加独立 TaskPlan 聚合、领域事件或 TaskExecution 实体。先沿用 DeepAgents 的计划和 Checkpoint 状态，避免制造两套尚未同步的计划数据。

## 依赖边界

- Interface 调用 Application，取得可信身份并转换请求。
- Application 编排用例，依赖领域仓储接口和已有的 Embeddings 抽象。
- Domain 定义业务对象、规则及仓储契约，不导入外层或数据库、Agent 框架。
- Infrastructure 实现契约，管理 ORM、驱动、框架、模型等技术细节。
- Bootstrap 组装具体实现；业务代码不接收 Container 或 Request。
- 仓储接口和实现使用对应文件名，例如 domain/repositories/memory_repository.py 与 infrastructure/persistence/repositories/memory_repository.py。

## 当前能力与未完成部分

已实现：任务聚合状态规则、Agent 定义及学习中间件、Runtime 执行与人工恢复、Redis/PostgreSQL Checkpoint、PG 连接池、记忆 ORM 和迁移、本地 BGE、记忆保存与检索服务。

任务创建、查询路由和单消费者启动已接入；开发身份需显式配置。正式认证、SSE、RAG、沙箱、并发领取和进程故障恢复尚未完成。

TaskPlanningAgent 当前提示词限定为生成计划，不执行计划。注册其他专用 Agent 不等于已把它们挂为主 Agent 的自定义子 Agent。

记忆服务可通过 bootstrap/wiring.py 的 create_memory_service(database) 按需组装。数据库和 BGE 按进程复用，Session 按短操作管理。当前仓储仍保留单次操作事务，尚未接入声明式事务传播框架。

## 安装和启动

```powershell
uv sync --locked --group dev
uv run harness-api
```

控制台命令名保留，内部入口已变更为 agent_platform.interface.api.app:main。移动入口后需要同步项目安装元数据；uv sync 会完成该操作。

- 健康检查：/health；接口文档：/docs。
- 业务路由仍是骨架；任务路由前缀为 /api/v1/tasks，尚无处理方法。
- 认证未配置时 get_principal 默认拒绝请求。
- 启动生命周期会连接配置的 Checkpoint，并预加载本地模型。

```powershell
uv run harness-worker
```

Worker 入口为 agent_platform.workers.agent_task_worker:main，目前输出提示后退出，不消费消息。

Windows 下 Psycopg 异步调用需要兼容的事件循环；Demo 的启动设置不会自动作用于其他进程，真实部署启动仍需验证。

## 配置和迁移

根目录 .env 保存配置。业务数据库为 HARNESS_DATABASE_URL，Checkpoint 使用 REDIS_URL 或 POSTGRES_URL；HARNESS_CHECKPOINT_BACKEND 选择 redis 或 postgres。模型配置由各 Provider 按模块维护。

业务数据库入口支持标准 postgresql:// URL，并由 SQLAlchemy 指定 Psycopg 驱动。Checkpoint 使用 PostgreSQL 标准 URL。URL 中密码的 @ 需要写成 %40，不提交真实凭据或本地权重。

目标数据库先启用 vector 扩展：

```sql
CREATE EXTENSION IF NOT EXISTS vector;
```

```powershell
uv run alembic revision --autogenerate -m "describe change"
# 检查生成的迁移再执行
uv run alembic upgrade head
```

Alembic 加载 infrastructure/persistence/entities.py 的 Base.metadata，不扫描领域聚合。现有 memories 表和迁移历史未因本次重命名而改变，也没有执行迁移。

PostgreSQL Checkpoint 结构由框架管理，初始化入口为 python -m agent_platform.bootstrap.database。

## 验证

```powershell
uv run python scripts/check_structure.py
uv run pytest tests -q
uv run ruff check src tests migrations scripts/check_structure.py
```

离线测试覆盖领域规则、身份严格校验、记忆服务与租户过滤、Agent 图、人工中断恢复、分层依赖和启动入口；不连接真实 PG、Redis 或模型服务。

详细改名映射、兼容性说明与后续任务见 [Java 风格结构说明](docs/architecture/java_style_layout.md)。

具体应用服务直接放在 `application/services/`，类名采用 `XxxApplicationService`，不额外拆分单一实现的接口与 Impl。当前已有 `AgentTaskApplicationService` 和 `UserMemoryApplicationService`。队列、Runtime 等外部能力接口继续放在 `application/interfaces/`。

任务领域服务位于 `domain/services/agent_task_domain_service.py`：创建、开始、等待人工、结束、失败和取消的业务过程由领域层负责，聚合根维护状态规则。应用服务协调领域服务、事务、队列和 Runtime；开始阶段的读取与保存共用短事务，执行模型时不持有业务数据库事务。仅排队或等待人工的任务可直接取消。数据库并发领取、旧状态覆盖保护和进程恢复仍待实现。

任务提交、Redis 队列消费和结果查询已接入，具体启动与验证步骤见 [任务链路联调](docs/plan/run_task_pipeline.md)。开发阶段仅启动一个消费者，开发令牌需显式配置，生产环境不会使用联调身份。应用服务通过 `bootstrap/wiring.py` 的无参缓存工厂获取，不登记到 Container。SSE 和逐段模型输出仍待接入。
