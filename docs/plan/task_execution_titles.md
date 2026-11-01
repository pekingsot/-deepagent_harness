# 本轮执行标题与历史计划

## 会话标题与本轮执行标题

会话列表和聊天顶部继续展示可手动修改的会话名称。任务面板展示当前轮的执行标题、步骤和状态，例如同一“版本开发”会话内先“编写地图策划”，下一轮再“检查上线风险”。Agent 通过 `set_execution_title` 工具结合最新输入与上下文概括标题，不单独调用一个标题生成模型；该工具仍计入现有工具预算，简单问答也可能因此增加工具往返。

每个正常新轮次清空 execution_title 和 todos；人工中断恢复保留原轮次和标题。尚未生成标题时显示“第 N 轮执行”，排队时显示“等待新一轮执行”，不使用整个会话名称代替。模型若未调用标题工具，保留轮次占位标题。

`agent_task_executions` 按 task_id + attempt 唯一保存本轮标题、步骤、状态与完整/部分结果。历史选择器可回看已经保存的轮次，会话重命名不会改动历史执行标题。历史轮次的文件版本和浏览器关闭前的完整动态时间线不在本次持久化范围内；交付物仍为当前虚拟工作区中的文件。

部署前需执行新增迁移：先停止后端，在根目录运行 `uv run alembic upgrade head`，然后重启 API/Worker 并刷新前端。不会为升级前未记录的轮次编造标题或步骤历史。

## DDD 边界与持久化

| 层 | 改动 |
| --- | --- |
| Domain | types/task_execution.py 定义轮次快照；任务仓储增加保存/读取执行记录；领域服务检查归属、轮次及写入状态，并保存本轮结果 |
| Application | AgentTaskExecutionResult 增加可选 title；Runtime 契约增加 on_title；应用服务用短事务处理标题/计划回调，再发布 SSE |
| Infrastructure / Harness | ExecutionTitleMiddleware 注入工具和状态，BaseAgent 统一装配及补充提示词；Runtime 每轮重置状态、解析标题更新，人工恢复保留状态 |
| Infrastructure / Persistence | entities/agent_task_executions.py 与原任务仓储实现保存快照，表只通过所属会话授权，不额外建立虚假聚合或 Service Impl |
| Interface | TaskExecutionResponse 与 GET /tasks/{task_id}/executions，通过应用服务读取，越权返回 404 |
| 前端 | 轮次快照类型与校验、SSE 版本合并、BFF GET 白名单、当前标题和历史选择器 |

生命周期：领取消息时创建本轮快照；标题和计划更新时保存；结束时保存成功/等待人工/失败/停止状态与结果。排队中的新请求被停止时不会修改上一轮已结束快照；正常新一轮不覆盖上一轮，标题回调不能写入旧轮次；人工恢复与恢复被拒绝仍更新同一条记录。

新迁移：migrations/alembic/versions/e62a8f31c904_add_task_execution_snapshots.py，前置 d40c6e2189ab。新表以整数为主键，引用既有 UUID 任务编号，唯一约束为 task_id+attempt。没有修改 .env 或自动执行迁移，没有暂存或提交 Git。

## 前端行为

- 侧栏、聊天顶部：会话名称。
- 面板当前标题：本轮概括；排队、未生成标题有明确占位。
- 历史选择器：只回看已经保存的轮次。历史步骤、结果只读，不把停止按钮指向另一个正在运行的轮次。
- 动态事件带 attempt，面板按轮次过滤；刷新后可从 SSE 保留事件恢复浏览器时间线，但历史时间线不是新增快照表的一部分。
- 标题/计划事件携带轮次快照，HTTP 与 SSE 按快照 updated_at 合并，迟到响应不覆盖新标题。每次新执行都会清掉旧计划。

## 关键源码

### src/agent_platform/domain/types/task_execution.py 第 16 行

```python
class TaskExecution(StrictModel):
    attempt: int = Field(ge=1)  # 所属轮次，人工恢复不新增轮次
    title: str = Field(min_length=1, max_length=120, pattern=r"\S")  # 本轮执行标题
    status: AgentTaskStatus  # 此轮状态，不随下一轮排队覆盖
    todos: tuple[TaskExecutionStep, ...] = ()  # 此轮最后保存的步骤
    output: str | None = None  # 此轮完整结果或停止、失败前的部分结果
    error: str | None = None  # 此轮失败原因
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))  # 轮次开始时间
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))  # 快照更新时间
```

### src/agent_platform/infrastructure/harness/middleware/execution_title.py 第 19 行

```python
@tool
def set_execution_title(title: str, runtime: ToolRuntime[TaskContext]) -> Command | str:
    """概括本轮正在做的事情作为标题。结合最新要求与上下文，不能复用整个会话名称。"""
    if runtime.state.get("execution_title"):
        return "本轮已有执行标题，继续执行当前计划。"
    title = " ".join(title.split())
    if not title or len(title) > 120:
        return "标题必须是 1 至 120 个字符的简短任务概括。"
    return Command(
        update={
            "execution_title": title,
            "messages": [
                ToolMessage(content=f"本轮标题：{title}", tool_call_id=runtime.tool_call_id)
            ],
        }
    )


class ExecutionTitleMiddleware(AgentMiddleware[ExecutionTitleState, TaskContext]):
    state_schema = ExecutionTitleState
    tools = [set_execution_title]
```

### src/agent_platform/domain/services/agent_task_domain_service.py 第 59 行

```python
    async def update_execution(
        self,
        principal: Principal,
        task: AgentTask,
        *,
        title: str | None = None,
        todos: tuple[TaskExecutionStep, ...] | None = None,
    ) -> TaskExecution | None:
        """仅接收当前正在执行轮次的标题与步骤，拒绝旧轮次回写。"""
        current = await self.get(principal, task.id, for_update=True)
        if current.attempt != task.attempt or current.status != AgentTaskStatus.RUNNING:
            return None
        if title is not None:
            title = " ".join(title.split())
            if not title:
                raise ValueError("执行标题不能为空白")
        return await self._record_execution(principal, current, title=title, todos=todos)
```

## 验证结果

64 项后端回归、3 项子测试通过，覆盖真实内存图的两轮不同标题/计划、当前轮占位、人工恢复、重命名独立性、历史结果保存、旧回调拒绝与跨用户 404。前端 16 项任务/草稿测试、12 项代理测试通过，包含新接口 GET 白名单与写入拒绝；TypeScript 和针对性 Ruff/ESLint 检查通过。新表 PostgreSQL DDL 离线编译通过，尚未对真实数据库执行迁移或调用真实模型、浏览器联调。
