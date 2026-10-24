# DeepAgent 企业级项目脚手架

基于 deepagents_enterprise_harness_architecture.md，采用模块化单体、src 布局，分离 API 与 Worker 入口。

这是开发脚手架：提供目录、基础类型、ABC 契约、Agent 资源组织和最小启动入口。
认证、多租户授权、持久化、任务消费、Agent 执行、审批及沙箱等业务能力留待实现。
当前仅 /health 可用；多租户模型和接口不等于已经实现安全隔离。

## 环境与启动

要求 uv、Python 3.12。

```powershell
uv python install 3.12
uv sync --group dev
Copy-Item .env.example .env
uv run harness-api
# 另一终端：目前只输出脚手架提示并退出
uv run harness-worker
```

API: http://127.0.0.1:8000/health
OpenAPI: http://127.0.0.1:8000/docs

## 开发检查

```powershell
uv run python scripts/check_structure.py
uv run python -m unittest discover -s tests/unit -v
uv run ruff check .
uv run mypy
```

## 依赖版本

Python 限定为 3.12；Pydantic 限定为 v2。依赖使用现代版本下限，
uv 默认解析约束内最新稳定兼容版本。2026-10-24 核对的核心下限：
DeepAgents 0.7.32、LangChain 1.4.7、LangGraph 1.2.17、
FastAPI 0.162.0、Pydantic 2.14.1。

首次成功联网执行 uv sync 将生成 uv.lock，请将其提交版本控制。
更新版本执行 uv lock --upgrade，再执行 uv sync --locked。
本次环境网络受限，未生成锁文件，未宣称最新依赖安装/集成验证通过。

## 目录职责

| 目录 | 职责 |
|---|---|
| apps | API / Worker 入口 |
| src/agent_platform/domain | Pydantic v2 严格领域类型；不依赖 Web/数据库/Agent SDK |
| src/agent_platform/application | 用例与 ABC Ports |
| src/agent_platform/harness | Agent 定义、Middleware、Backend、Skills 与 Runtime 适配边界 |
| src/agent_platform/infrastructure | 数据库、队列、模型 Provider、沙箱、Langfuse 等适配位置 |
| src/agent_platform/bootstrap | Settings 与依赖组装 |
| tests / evals | 分层测试与模型评估位置 |
| migrations / infra / docs | 迁移、部署与文档 |

每个 Agent 的 definition.py、system_prompt.md、tools.py、middleware.py、backend.py、
skills/ 就近放置。模型由 ModelProvider ABC 按 Agent profile 和可信上下文解析。
根 Agent 声明子 Agent 名称；自定义子 Agent 显式使用自己的 Skills，不合并父 Skills。
默认 general-purpose 子 Agent 的继承由 DeepAgents 原生行为决定。
不使用 agent.yaml 代替 Python 定义。

数据对象统一使用 ConfigDict(strict=True, extra="forbid", frozen=True)，
采用 model_validate / model_dump 等 v2 接口。环境变量解析是明确的字符串转换边界。
扩展实现继承 ABC；SDK 要求的 TypedDict、Any 或框架基类仅留在适配层。
ORM 预留 SQLAlchemy DeclarativeBase + Mapped / mapped_column，避免旧式 Column 声明。

详细边界和后续接入顺序见 docs/architecture/scaffold.md。
