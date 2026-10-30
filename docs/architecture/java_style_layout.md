# Java 风格结构与业务命名

## 职责对应

| 熟悉的职责 | 本项目位置 |
| --- | --- |
| Controller | interface/api/routes |
| HTTP VO | interface/vo |
| 具体应用服务 | application/services |
| DTO | application/dto |
| 聚合根 | domain/aggregates |
| 领域服务 | domain/services |
| 业务类型和查询投影 | domain/types |
| Repository 接口 | domain/repositories |
| Repository 实现 | infrastructure/persistence/repositories |
| ORM Entity/DO | infrastructure/persistence/entities.py |
| Agent 框架适配 | infrastructure/harness |
| 依赖组装 | bootstrap/wiring.py |

不为每个 Service 创建接口与 Impl，不为每张表创建聚合，不预建没有行为的事件、实体、转换器或领域服务。

## 改名映射

| 原位置或名称 | 当前位置或名称 |
| --- | --- |
| api | interface/api |
| api/schemas | interface/vo |
| harness | infrastructure/harness |
| domain/runs/models.py 的 Run | domain/aggregates/agent_task.py 的 AgentTask |
| RunStatus | AgentTaskStatus |
| RunContext/run_id | TaskContext/task_id |
| domain/common/models.py | domain/types/common.py |
| domain/memory/models.py 的 MemoryMatch | domain/types/memory_match.py |
| 其他 domain/业务/models.py | domain/types 中对应的业务文件 |
| domain/repositories/runs.py | domain/repositories/agent_task_repository.py |
| domain/repositories/memories.py | domain/repositories/memory_repository.py |
| RunRepository | AgentTaskRepository |
| application/dto/runs.py | application/dto/agent_task_dto.py |
| CreateRun/ResumeRun | CreateAgentTask/ResumeAgentTask |
| RuntimeInterrupt/RuntimeResult | TaskInterrupt/AgentTaskExecutionResult |
| AgentRuntime/DeepAgentsRuntime | AgentTaskRuntime/DeepAgentsTaskRuntime |
| runtime/deepagents_adapter.py | runtime/deepagents_task_runtime.py |
| runtime/run_context.py | runtime/checkpoint_namespace.py |
| OrchestratorAgent/orchestrator | TaskPlanningAgent/task_planning |
| persistence/models.py 的 Memory | persistence/entities.py 的 MemoryRecord |
| persistence/repositories/memories.py | persistence/repositories/memory_repository.py |
| workers/run_worker.py | workers/agent_task_worker.py |

更早的 ports 仓储接口已归 Domain，队列、Runtime 等外部能力接口归 application/interfaces。原任务服务 ABC 保留为 application/services/agent_task_application_service.py，尚无具体用例实现。

## 聚合根的实际行为

AgentTask 代表用户任务，不代表一次模型调用，也不是 TaskPlanningAgent 的别名。

- start：只允许排队任务开始，并增加执行计数。
- wait_for_user：只允许运行中的任务进入人工等待。
- resume：只允许等待人工的任务恢复，不重复计为新执行。
- complete：提交非空结果后完成运行中的任务。
- fail：运行中的任务记录非空失败原因。
- cancel：只取消排队或人工等待中的任务，运行中的任务尚未接入停止能力。
- 终态不允许重新开始；构造或重建对象时也校验状态和结果的一致性。

业务方法返回新的不可变对象；Application 保存变化后的聚合并调用 Runtime。任务应用服务已实现这些步骤，API 与单消费者 Worker 已完成启动装配；正式认证、并发领取和进程恢复仍待实现。

聚合唯一身份为 context.task_id，id 属性读取这个编号。当前保留上下文结构，未增加重复的任务 ID，也没有假装已完成独立执行记录与任务计划聚合。

## 兼容性与数据

这是项目内部的显式重命名，不保留旧导入别名。Python 源码、测试、Demo 导入及启动入口同步更新；历史学习文档可能仍保留旧示例，应以当前 README 和源码为准。

TaskContext 的序列化字段由 run_id 改为 task_id，Agent 注册名由 orchestrator 改为 task_planning。旧的外部 JSON 或自行保存的任务对象需要相应转换，不能直接宣称兼容。

Checkpoint key 仍按租户、项目、用户、thread_id、任务 UUID 组成。使用相同 UUID 时键的拼接规则不变，但恢复旧图还需考虑节点名称等变化，不能保证旧的未完成任务可无条件恢复。

memories 表名、列名、索引及已有迁移不变；MemoryRecord 只是 ORM 类的改名。未创建任务表，未执行数据库迁移，未删除任何数据库数据。

## 后续工作

1. 选定成熟事务集成，验证异步并发和事务传播；当前单次仓储事务暂时保留，不自制同义装饰器。
2. 接通任务聚合、任务仓储和应用用例，再实现队列领取、幂等与 Worker。
3. 完成认证后增加 HTTP 路由、VO 转换、Agent 工具入口。
4. 实现执行事件和 SSE；Checkpoint 不替代任务领取锁和业务状态。
5. 记忆纠正、遗忘等规则明确后再建记忆聚合；MemoryMatch 只是检索结果。
6. RAG 与记忆共用向量编码能力，业务数据与授权分别管理。

应用服务直接使用具体类，统一命名为 `XxxApplicationService`，不额外拆分接口与 Impl。任务服务在 `application/services/agent_task_application_service.py`，个人记忆服务在 `application/services/user_memory_application_service.py`。仓储、队列和 Runtime 的接口继续保留，隔离外部技术实现。

任务领域服务位于 `domain/services/agent_task_domain_service.py`：创建、开始、等待人工、结束、失败和取消的业务过程由领域层负责，聚合根维护状态规则。应用服务协调领域服务、事务、队列和 Runtime；开始阶段的读取与保存共用短事务，执行模型时不持有业务数据库事务。仅排队或等待人工的任务可直接取消。数据库并发领取、旧状态覆盖保护和进程恢复仍待实现。


任务 HTTP、队列消费、模型文本回调、Redis 执行事件和 SSE 已接入。事件存储接口为 application/interfaces/task_events.py，具体实现为 infrastructure/messaging/redis_task_events.py；人工回复通过队列交给同一个 Worker 恢复。完整接口与流程参见 ../plan/run_task_pipeline.md。本轮仅补充代码，未执行测试。
