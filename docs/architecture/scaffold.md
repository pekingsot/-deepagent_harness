# 脚手架约定

参考文档：deepagents_enterprise_harness_architecture.md（Architecture Draft 1.0）。

## 依赖方向

API → Application → Domain；Infrastructure 实现 Application Ports；
Bootstrap 负责绑定；Harness 集成 DeepAgents/LangChain/LangGraph。
Domain 不导入 FastAPI、SQLAlchemy 或 DeepAgents。

## 目前具备

- uv / Python 3.12 配置；核心现代版本下限，等待联网解析锁文件。
- Pydantic v2 严格基础类型、可信 Principal / RunContext / Run DTO。
- Repository、Queue、Runtime、Sandbox、Secret、Checkpoint 等 ABC 扩展契约。
- 四个 Python Agent 定义示例及各自的 Prompt、Tools、Middleware、Backend、Skills。
- 最小 FastAPI health 入口与 Worker 占位入口。
- 扩展目录及基础检查。

## 留待业务开发

认证/成员关系、授权/RBAC、Repository 租户过滤/RLS、队列与租约、
检查点/Store 租户命名空间、模型/凭证解析、DeepAgents 图编译、
长任务恢复取消、远程沙箱服务、Langfuse 初始化、审批、预算、审计。
脚手架不提供假实现，也不承诺以上能力已经可运行。

## 多租户约束

Principal 必须来源于验证后的身份和成员关系。
Application 每次显式传可信上下文；Repository、Tool、Backend、
Checkpointer、Store、Queue、Sandbox 均须校验租户范围。
不要共享持有租户状态的可变全局 Agent、Provider 或工作目录。
框架 SDK 类型留在适配层；业务数据尽量使用严格 Pydantic v2 类型。

## 接入顺序

1. 选定身份系统、数据库和迁移工具，绑定 Repository。
2. 选择 ModelProvider 与 Checkpointer，实现 AgentFactory 和 Runtime。
3. 接入 Queue 与 Worker，再添加 Run API。
4. 实现租户隔离集成测试后再开放业务接口。
5. 按需实现远程 SandboxProvider、Langfuse、审批与预算。
