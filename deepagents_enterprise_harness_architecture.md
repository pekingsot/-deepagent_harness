# 基于 DeepAgents 的企业级 Agent Harness：目录与架构设计

> 版本：Architecture Draft 1.0\
> 目标：以 DeepAgents 为 Agent Runtime 基础，构建支持多租户、可扩展
> Middleware、Backend、Skills、子 Agent、长任务与远程沙箱执行的企业级
> Harness。\
> 设计取向：**模块化单体优先、Python 定义
> Agent、资源与代码就近组织、共享能力统一实现、运行时策略显式化。**

------------------------------------------------------------------------

## 1. 设计目标与核心原则

### 1.1 目标

项目需要支持：

-   基于 DeepAgents 创建根 Agent 与自定义 SubAgent。
-   不同 Agent 使用不同模型、System Prompt、Tools、Middleware、Skills 和
    Backend 配置。
-   Agent 专属 Skills 与 Agent 定义放在一起；共享 Skills 可独立管理。
-   正确区分 DeepAgents 默认生成的子 Agent 与平台自定义 SubAgent。
-   多租户隔离：身份、数据、会话、检查点、工具权限、文件、沙箱、缓存、任务和追踪。
-   支持 Middleware 扩展、Backend 适配、远程沙箱、长任务
    Worker、审批和可观测性。
-   以 Python 作为 Agent 的主要定义和组装方式，不强制使用 `agent.yaml`
    描述全部行为。
-   保持架构边界清晰，后续可以按实际需求拆分服务，而不是一开始就引入大量微服务。

### 1.2 核心原则

1.  **DeepAgents 是 Agent Runtime 的基础，不重复实现 Agent Loop。**
    Harness 负责企业能力的组装、策略和生命周期管理。
2.  **Agent 是可编程的执行单元。** 每个 Agent 通过 Python
    定义模型、提示词、工具、中间件、Skills、Backend 和子 Agent。
3.  **Agent 资源就近组织。** Agent 专属
    Prompt、Skills、测试与定义代码放在同一个 Agent 目录。
4.  **共享能力统一实现。** 公共 Tools、Middleware、Backend 适配器、模型
    Provider 和沙箱 Provider 不在各 Agent 目录中重复实现。
5.  **父子关系不等于能力继承。** 父 Agent 负责声明可委派给哪些子
    Agent；每个自定义子 Agent 的能力由自己的定义和运行策略决定。
6.  **租户上下文贯穿全链路。** 每次运行都具有明确的
    tenant、user、run、thread 和 trace 上下文。
7.  **接口先于实现。** Application 通过
    Port/接口调用队列、数据库、Checkpoint、Backend 和沙箱等能力。
8.  **模块化单体优先。** 初期按 API 和 Worker
    两种进程部署即可，后续再按实际负载拆分。

------------------------------------------------------------------------

## 2. 推荐项目目录

``` text
deepagent-platform/
├── apps/
│   ├── api/
│   │   ├── main.py                     # API 进程入口
│   │   └── Dockerfile
│   └── worker/
│       ├── main.py                     # 后台任务进程入口
│       └── Dockerfile
│
├── src/
│   └── agent_platform/
│       ├── bootstrap/                  # 应用启动、依赖组装
│       │   ├── container.py
│       │   ├── wiring.py
│       │   └── lifespan.py
│       │
│       ├── api/                        # HTTP / SSE / WebSocket 接入层
│       │   ├── app.py
│       │   ├── dependencies.py
│       │   ├── routes/
│       │   │   └── v1/
│       │   │       ├── agents.py
│       │   │       ├── runs.py
│       │   │       ├── sessions.py
│       │   │       ├── approvals.py
│       │   │       ├── skills.py
│       │   │       └── health.py
│       │   ├── schemas/
│       │   └── middleware/             # HTTP 层中间件
│       │       ├── authentication.py
│       │       ├── tenant_resolution.py
│       │       ├── request_id.py
│       │       ├── rate_limit.py
│       │       └── exception_handler.py
│       │
│       ├── domain/                     # 领域模型，不依赖具体框架
│       │   ├── tenants/
│       │   ├── agents/
│       │   ├── runs/
│       │   ├── sessions/
│       │   ├── skills/
│       │   ├── tools/
│       │   ├── sandbox/
│       │   └── common/
│       │
│       ├── application/                # 用例编排
│       │   ├── agents/
│       │   │   ├── create_agent.py
│       │   │   ├── publish_agent.py
│       │   │   └── resolve_agent.py
│       │   ├── runs/
│       │   │   ├── create_run.py
│       │   │   ├── execute_run.py
│       │   │   ├── cancel_run.py
│       │   │   └── resume_run.py
│       │   ├── sessions/
│       │   ├── approvals/
│       │   ├── tenants/
│       │   ├── ports/                  # 外部依赖接口
│       │   │   ├── repositories.py
│       │   │   ├── checkpointer.py
│       │   │   ├── job_queue.py
│       │   │   ├── sandbox_provider.py
│       │   │   └── secret_provider.py
│       │   └── dto/
│       │
│       ├── harness/                    # Harness 组合与运行控制层
│       │   ├── agents/                  # Agent 定义、发现与构建
│       │   │   ├── __init__.py
│       │   │   ├── contracts.py
│       │   │   ├── registry.py
│       │   │   ├── factory.py
│       │   │   ├── subagent_dispatcher.py
│       │   │   │
│       │   │   ├── orchestrator/        # 根 Agent 示例
│       │   │   │   ├── __init__.py
│       │   │   │   ├── definition.py
│       │   │   │   ├── system_prompt.md
│       │   │   │   ├── tools.py
│       │   │   │   ├── middleware.py
│       │   │   │   ├── backend.py
│       │   │   │   ├── skills/
│       │   │   │   │   └── task-planning/
│       │   │   │   │       └── SKILL.md
│       │   │   │   └── tests/
│       │   │   │
│       │   │   ├── researcher/          # 自定义研究 SubAgent
│       │   │   │   ├── __init__.py
│       │   │   │   ├── definition.py
│       │   │   │   ├── system_prompt.md
│       │   │   │   ├── tools.py
│       │   │   │   ├── middleware.py
│       │   │   │   ├── backend.py
│       │   │   │   ├── skills/
│       │   │   │   │   ├── web-research/
│       │   │   │   │   │   └── SKILL.md
│       │   │   │   │   └── source-evaluation/
│       │   │   │   │       └── SKILL.md
│       │   │   │   └── tests/
│       │   │   │
│       │   │   ├── coder/
│       │   │   │   ├── __init__.py
│       │   │   │   ├── definition.py
│       │   │   │   ├── system_prompt.md
│       │   │   │   ├── tools.py
│       │   │   │   ├── middleware.py
│       │   │   │   ├── backend.py
│       │   │   │   ├── skills/
│       │   │   │   │   ├── code-debugging/
│       │   │   │   │   │   └── SKILL.md
│       │   │   │   │   └── test-writing/
│       │   │   │   │       └── SKILL.md
│       │   │   │   └── tests/
│       │   │   │
│       │   │   └── reviewer/
│       │   │       ├── __init__.py
│       │   │       ├── definition.py
│       │   │       ├── system_prompt.md
│       │   │       ├── tools.py
│       │   │       ├── middleware.py
│       │   │       ├── backend.py
│       │   │       ├── skills/
│       │   │       └── tests/
│       │   │
│       │   ├── middleware/              # 可复用 Agent Middleware 实现
│       │   │   ├── permission_guard.py
│       │   │   ├── budget_limit.py
│       │   │   ├── tool_call_audit.py
│       │   │   ├── human_approval.py
│       │   │   ├── input_guard.py
│       │   │   ├── output_guard.py
│       │   │   ├── pii_redaction.py
│       │   │   └── trace_context.py
│       │   │
│       │   ├── tools/                   # 可复用工具实现
│       │   │   ├── registry.py
│       │   │   ├── builtins/
│       │   │   ├── search/
│       │   │   ├── database/
│       │   │   ├── filesystem/
│       │   │   ├── code_execution/
│       │   │   └── mcp/
│       │   │
│       │   ├── skills/                  # Skill 加载与校验机制
│       │   │   ├── loader.py
│       │   │   ├── resolver.py
│       │   │   ├── registry.py
│       │   │   └── validator.py
│       │   │
│       │   ├── backends/                # DeepAgents Backend 适配与组合
│       │   │   ├── factory.py
│       │   │   ├── tenant_scoped.py
│       │   │   ├── composite.py
│       │   │   ├── state_backend.py
│       │   │   ├── store_backend.py
│       │   │   └── sandbox_backend.py
│       │   │
│       │   ├── runtime/
│       │   │   ├── deepagents_adapter.py
│       │   │   ├── graph_builder.py
│       │   │   ├── run_executor.py
│       │   │   ├── run_context.py
│       │   │   └── graph_registry.py
│       │   │
│       │   └── policies/
│       │       ├── tool_access.py
│       │       ├── skill_access.py
│       │       └── execution_limits.py
│       │
│       ├── infrastructure/              # 外部系统的具体实现
│       │   ├── persistence/
│       │   │   ├── database.py
│       │   │   ├── models/
│       │   │   ├── repositories/
│       │   │   └── unit_of_work.py
│       │   ├── checkpoint/
│       │   │   └── langgraph_checkpointer.py
│       │   ├── store/
│       │   ├── queue/
│       │   │   ├── producer.py
│       │   │   └── consumer.py
│       │   ├── cache/
│       │   ├── model_providers/
│       │   │   ├── factory.py
│       │   │   └── providers/
│       │   ├── sandbox/
│       │   │   ├── manager.py
│       │   │   ├── lifecycle.py
│       │   │   └── providers/
│       │   │       ├── docker.py
│       │   │       ├── remote_http.py
│       │   │       └── kubernetes.py
│       │   ├── object_storage/
│       │   ├── secrets/
│       │   └── observability/
│       │       ├── langfuse.py
│       │       ├── logging.py
│       │       └── metrics.py
│       │
│       └── workers/
│           ├── run_worker.py
│           ├── sandbox_worker.py
│           └── cleanup_worker.py
│
├── migrations/
├── tests/
│   ├── unit/
│   ├── integration/
│   ├── contract/
│   ├── e2e/
│   ├── security/
│   └── multi_tenant/
├── evals/
│   ├── datasets/
│   ├── cases/
│   ├── graders/
│   └── regression/
├── infra/
│   ├── docker/
│   ├── compose/
│   ├── kubernetes/
│   ├── helm/
│   └── terraform/
├── docs/
│   ├── architecture/
│   ├── adr/
│   ├── api/
│   ├── security/
│   └── runbooks/
├── scripts/
├── pyproject.toml
├── uv.lock
├── Makefile
├── compose.yaml
├── .env.example
└── README.md
```

> 这是目标目录，不代表第一天就要创建所有文件。按实现阶段逐步落地，避免空目录和过早抽象。

------------------------------------------------------------------------

## 3. 每个 Agent 是独立的可编程执行单元

### 3.1 Agent 目录约定

每个 Agent 可以按自身需要包含：

  -------------------------------------------------------------------------------------------------
  文件/目录                           职责
  ----------------------------------- -------------------------------------------------------------
  `definition.py`                     该 Agent
                                      的组装入口：模型、提示词、工具、中间件、Skills、Backend、子
                                      Agent

  `system_prompt.md`                  System Prompt，便于独立编辑、审查和版本控制

  `tools.py`                          选择、配置该 Agent 可使用的工具；工具实现本身放在公共模块

  `middleware.py`                     选择该 Agent 需要的 Middleware；公共 Middleware 实现放在
                                      `harness/middleware/`

  `backend.py`                        声明或组装该 Agent 使用的 Backend；通用适配器放在
                                      `harness/backends/`

  `skills/`                           Agent 专属 Skills，按 DeepAgents 支持的 Skill 文件布局组织

  `tests/`                            针对该 Agent 的行为、能力和回归测试
  -------------------------------------------------------------------------------------------------

不是每个 Agent 都必须有上述所有文件。例如，简单 Agent 可以只包含
`definition.py`、`system_prompt.md` 和 `skills/`。

### 3.2 Python 定义示意

``` python
from pathlib import Path

BASE_DIR = Path(__file__).parent


def build_subagent(ctx, deps):
    return {
        "name": "researcher",
        "description": "Research topics and verify evidence.",
        "model": deps.models.resolve(
            profile="researcher",
            tenant_id=ctx.tenant_id,
        ),
        "system_prompt": (
            BASE_DIR / "system_prompt.md"
        ).read_text(encoding="utf-8"),
        "tools": build_tools(ctx, deps),
        "middleware": build_middleware(ctx, deps),
        "skills": [str(BASE_DIR / "skills")],
    }
```

以上是平台设计示意，不是可直接复制运行的完整实现。`ctx`、`deps`、`build_tools()`、`build_middleware()`
和 `deps.models.resolve()`
都需要在项目中定义；最终配置必须适配锁定版本的 DeepAgents API。

### 3.3 父 Agent 只组装子 Agent

``` python
def build_root_agent(ctx, deps):
    subagents = [
        build_researcher(ctx, deps),
        build_coder(ctx, deps),
    ]

    return create_deep_agent(
        model=deps.models.resolve(
            profile="orchestrator",
            tenant_id=ctx.tenant_id,
        ),
        system_prompt=load_root_prompt(),
        tools=build_root_tools(ctx, deps),
        skills=[str(ROOT_SKILLS_DIR)],
        subagents=subagents,
        backend=deps.backends.resolve(ctx),
    )
```

根 Agent 负责决定哪些 SubAgent 可用。子 Agent 的内部模型、提示词、工具和
Skills 由各自的定义模块负责。避免将所有 Agent 的构建逻辑集中到一个巨大的
`agent.py`。

------------------------------------------------------------------------

## 4. Skills 的归属与继承规则

### 4.1 目录组织

-   Agent 专属 Skills 放在对应 Agent 的 `skills/` 目录。
-   多个 Agent 共享的 Skills 可放在独立的 `shared-skills/`
    资源目录，或通过受控的 Skill Registry 提供。
-   不因为一个 Skill 放在 `common/` 或 `shared-skills/`
    中，就默认授权所有 Agent 使用它。
-   通过 Agent 定义显式指定 Skills；对共享 Skill 也要显式引用和授权。
-   租户上传的 Skill
    应经过校验、版本管理和权限检查；其中的脚本必须在受限环境中执行。

如果共享 Skill 较少，可以先直接放在对应 Agent
目录；只有出现真实复用需求时，再建立共享仓库，避免过早设计。

### 4.2 子 Agent 的行为约定

  -----------------------------------------------------------------------------------------
  类型                    Skills 行为                      平台设计要求
  ----------------------- -------------------------------- --------------------------------
  DeepAgents 默认         按当前 DeepAgents                不要在 Harness
  `general-purpose` 子    版本的默认行为继承父 Agent       中重复实现一套继承逻辑
  Agent                   Skills                           

  自定义 SubAgent         默认不继承父 Agent               加载自己的
                          Skills，应由自己的定义明确指定   Skills，并做租户和版本校验

  `mode="fork"`           继承行为和可配置项受 DeepAgents  在 Adapter
  等特殊执行模式          当前版本约束                     层明确处理并添加版本对应的测试
  -----------------------------------------------------------------------------------------

注意：DeepAgents
的具体默认值和字段支持可能随版本变化。应锁定依赖版本，并以该版本的官方
API 和测试为准。不要只根据目录名推断 Skills 是否会被加载。

### 4.3 Skills 不等于完整的安全边界

Skill 主要提供可加载的指令和资源，不能单独承担权限控制。即使某个 Skill
告诉 Agent"只能读取当前租户数据"，真实的数据访问仍需由
Tool、Middleware、Backend、Repository 和沙箱执行策略实施强制校验。

------------------------------------------------------------------------

## 5. Middleware 与 Backend 的职责边界

### 5.1 两种 Middleware

  --------------------------------------------------------------------------------------------------------------
  类型                    位置                    职责
  ----------------------- ----------------------- --------------------------------------------------------------
  HTTP Middleware         `api/middleware/`       身份认证、租户解析、请求 ID、限流、HTTP 异常处理

  Agent Middleware        `harness/middleware/`   工具调用权限、预算、审批、审计、输入输出检查、脱敏、执行追踪
  --------------------------------------------------------------------------------------------------------------

两者可以传递相同的 `tenant_id`、`run_id` 和
`trace_id`，但属于不同层次，不应混成一个中间件目录。

### 5.2 Backend 与 Sandbox Provider

-   **DeepAgents Backend**：向 Agent 提供文件读写等抽象能力。
-   **Sandbox
    Backend**：将适当的文件访问或执行操作路由到某个沙箱工作区。
-   **Sandbox Provider**：真正创建、连接、管理和销毁
    Docker、远程执行服务或 Kubernetes 中的执行环境。
-   **Infrastructure**：实现沙箱生命周期、文件传输、命令执行、超时、取消、资源配额和凭证管理。

示例路由：

``` text
/workspace/  -> 当前 Run 的沙箱工作区
/memories/   -> 按租户隔离的持久化记忆
/artifacts/  -> 对象存储中的执行产物
```

实际路由能力应以当前 DeepAgents Backend 协议为准。不要把业务数据库
Repository 与 DeepAgents Backend 混为一谈。

------------------------------------------------------------------------

## 6. 多租户上下文与隔离

每次 Run 都应具有明确的运行上下文。可以使用 Pydantic
模型或其他项目认可的类型来实现。

``` python
@dataclass(frozen=True)
class RunContext:
    tenant_id: str
    user_id: str
    project_id: str
    run_id: str
    thread_id: str
    trace_id: str
    agent_version: str
    policy_version: str
```

该结构是示例，字段应根据业务需要调整。租户身份必须从已验证的身份与成员关系中解析，不能信任客户端自行提交的
`tenant_id`。

### 多租户检查清单

  层级                   关键要求
  ---------------------- ------------------------------------------------------
  API                    认证身份、租户成员关系和授权检查
  Application            每个用例显式接收可信的运行上下文
  Database               Repository 查询按租户约束；必要时使用 PostgreSQL RLS
  Checkpointer / Store   检查线程、检查点和记忆的租户归属
  Backend                限制虚拟路径、文件读写、工作区与长期记忆范围
  Tools / MCP            每次敏感操作校验租户、用户与工具权限
  Sandbox                隔离工作目录、进程、凭证、网络和资源配额
  Cache / Queue          键、任务载荷、结果和状态都绑定可靠的租户标识
  Observability          追踪关联租户与 Run，并控制敏感信息采集和展示

不要将租户上下文、用户凭证或工作区路径放进可跨租户共享的可变全局单例中。可缓存不含租户状态的组件，但任何缓存的
Agent 图、工具或 Provider
如果持有租户专属配置，都必须按安全边界设计缓存键与生命周期。

------------------------------------------------------------------------

## 7. 长任务与远程沙箱执行链路

推荐把 API 接入与长任务执行分开：

``` text
HTTP Request
    |
    v
Authentication + Tenant Resolution
    |
    v
Application Use Case
    |
    v
Create Run + Persist State + Enqueue Job
    |
    v
Worker
    |
    v
Harness Agent Factory
    |
    +--> Load Agent Definition / Version
    +--> Resolve Model and Policy
    +--> Build Middleware Stack
    +--> Resolve Tools and Skills
    +--> Resolve Tenant-Scoped Backend
    |
    v
DeepAgents / LangGraph Runtime
    |
    +--> Model Calls
    +--> Tool Calls
    +--> Backend Access
    +--> Subagent Delegation
    +--> Checkpoints / Store
    +--> Sandbox Provider
    +--> Langfuse Tracing
    |
    v
Run Events + Result + Cleanup
```

建议流程：

1.  API 创建 Run、保存状态并提交任务队列。
2.  Worker 获取任务，使用可信的租户上下文构建 Harness。
3.  Harness 调用 DeepAgents Runtime。
4.  Agent 通过 Backend 和工具访问文件或执行能力；需要代码执行时，Sandbox
    Provider 负责远程或本地沙箱。
5.  事件、检查点和追踪信息持续写入对应存储。
6.  客户端通过 SSE、WebSocket 或轮询获取状态。
7.  任务完成、失败或取消后执行清理和资源回收。

沙箱 Provider 应提供清晰的接口，避免 Harness 依赖某个 Docker
主机或容器地址。远程部署时，Provider
负责认证、超时、重试、取消和文件传输。

------------------------------------------------------------------------

## 8. 依赖方向与模块边界

推荐的依赖规则：

-   `domain/` 不依赖 FastAPI、SQLAlchemy、DeepAgents 等具体技术。
-   `application/` 通过接口调用外部能力，不直接创建 Docker
    容器或数据库连接。
-   `harness/` 负责 DeepAgents、LangChain、LangGraph
    的集成与执行组装，不处理 HTTP 参数解析。
-   `infrastructure/` 实现数据库、队列、模型 Provider、沙箱
    Provider、对象存储和可观测性等外部适配器。
-   `bootstrap/` 负责依赖注入和组装。
-   `apps/api` 与 `apps/worker` 保持轻薄，避免重复业务逻辑。
-   Agent 定义可以依赖 Harness
    提供的稳定接口，但不应绕过权限和租户校验直接访问基础设施。
-   公共 Tool、Middleware 和 Backend 的实现只维护一份；Agent
    目录只负责选择和配置。

虽然整体采用 DDD
的分层思想，但不必把每个小功能都拆成独立微服务或复杂聚合。先保持清晰的模块边界和依赖规则，再根据业务复杂度细化领域模型。

------------------------------------------------------------------------

## 9. 数据模型建议

如果未来 Agent、Skills
和工具需要在运行中动态创建、发布或版本化，可考虑以下概念模型：

-   `Tenant`
-   `AgentDefinition`
-   `AgentVersion`
-   `SubagentBinding`
-   `SkillDefinition`
-   `SkillVersion`
-   `AgentSkillBinding`
-   `ToolDefinition`
-   `Run`
-   `Session` / `Thread`
-   `Approval`
-   `SandboxExecution`

关键关系：

-   `AgentVersion` 描述某个 Agent 的不可变发布版本。
-   `SubagentBinding` 描述某个父 Agent 版本允许委派给哪些子 Agent 版本。
-   `AgentSkillBinding` 显式记录某个 Agent 版本使用哪些 Skill 版本。
-   父子 Agent 关系不自动等同于 Skill 继承关系。
-   Skill 绑定需要校验租户归属、版本状态与访问授权。
-   如果某个 Agent
    的模型或工具配置会影响安全边界，应将其纳入版本或策略快照，确保 Run
    可审计、可复现。

如果初期所有 Agent 都由代码维护，可以先使用 Python
定义和版本控制；等出现租户自助配置、动态发布等需求后，再引入数据库驱动的
Agent Definition。不要为了"企业级"提前搭建一套不需要的配置平台。

------------------------------------------------------------------------

## 10. 测试策略

至少保留以下测试层：

-   **Unit**：Agent 配置解析、Skill
    Resolver、工具策略、中间件逻辑、Backend 路由。
-   **Integration**：DeepAgents Adapter、Checkpoint、数据库、队列和沙箱
    Provider。
-   **Contract**：自定义 Backend、Tool、Sandbox Provider
    与框架接口的兼容性。
-   **E2E**：创建 Run、执行 Agent、委派 SubAgent、恢复任务、取消任务。
-   **Security**：工具越权、路径穿越、凭证泄露、沙箱逃逸风险、输入注入等。
-   **Multi-tenant**：租户 A 无法读取租户 B
    的会话、记忆、文件、任务结果和沙箱资源。
-   **Evals / Regression**：对 Agent
    的输出质量、工具选择和关键工作流做回归评估。

建议把 Skill 的加载规则、默认子 Agent 的继承行为和自定义 SubAgent
的隔离行为纳入自动化测试，避免升级 DeepAgents 后出现隐式行为变化。

------------------------------------------------------------------------

## 11. 分阶段落地路线

### 阶段一：跑通 Harness 核心链路

实现：

-   API 和 Worker 入口。
-   Run 生命周期。
-   Agent Registry / Factory。
-   根 Agent 与至少一个自定义 SubAgent。
-   Agent 专属 Prompt、Tools、Middleware、Skills 目录约定。
-   DeepAgents Adapter。
-   基础 Backend 和 Checkpointer。
-   Langfuse 链路追踪。
-   基础单元测试与集成测试。

目标：一个 Run 能可靠运行、记录、失败处理和恢复。

### 阶段二：建立多租户与权限边界

实现：

-   Tenant / User / Project 上下文。
-   Repository 租户过滤与必要的数据库策略。
-   Tenant-scoped Backend、Store、Checkpointer。
-   Tool 与 Skill 的显式授权。
-   模型配置与策略解析。
-   `tests/multi_tenant/` 和安全回归测试。

目标：不同租户的状态、数据、工具和资源得到可靠隔离。

### 阶段三：支持长任务和远程执行

实现：

-   Job Queue 与 Worker。
-   Sandbox Provider 接口及一个实际 Provider。
-   沙箱创建、复用、取消、超时与清理。
-   文件传输和产物持久化。
-   预算控制、审批与执行审计。
-   Evals、指标与运行手册。

目标：支持长任务、代码执行、远程沙箱和企业治理。

### 阶段四：按真实需求扩展

视需求增加：

-   Agent / Skill 的动态注册和版本发布。
-   租户级 Agent 配置。
-   MCP 集成。
-   更细粒度的策略引擎。
-   多环境部署、Kubernetes、弹性 Worker。
-   Agent 评估平台与发布门禁。

不要在第一阶段就实现所有功能，也不要为了未来可能的需求提前拆分大量微服务。

------------------------------------------------------------------------

## 12. 最终决策摘要

1.  采用 Python Monorepo，初期模块化单体，部署上区分 API 与 Worker。
2.  不强制使用 `agent.yaml`；每个 Agent 以 `definition.py`
    作为主要组装入口。
3.  Agent 的 `system_prompt.md`、专属 `skills/`
    和针对性测试放在各自目录下。
4.  `tools.py`、`middleware.py`、`backend.py`
    用来选择或组装能力；公共能力实现集中管理。
5.  默认生成的子 Agent 与自定义 SubAgent 按 DeepAgents
    的实际语义处理，不在 Harness 中重复造一套继承机制。
6.  自定义 SubAgent 的模型、Prompt、Tools、Middleware、Skills 和 Backend
    可以独立配置。
7.  父子关系与 Skill 绑定关系分开建模；共享 Skill 需要显式引用和授权。
8.  多租户上下文贯穿
    API、Application、Run、Tool、Backend、Store、Queue、Sandbox 和
    Observability。
9.  Backend 是 Agent 的能力适配层，Sandbox Provider
    是真实执行环境的适配层，两者职责不同。
10. 锁定 DeepAgents 依赖版本，并用契约测试覆盖 Adapter、Backend 和
    SubAgent 继承行为。

> 总体方向：让 DeepAgents 负责 Agent Runtime，让 Harness
> 负责企业级运行治理，让每个 Agent 通过 Python
> 定义自身能力，并通过清晰的边界实现多租户、安全、可观测和可持续扩展。
