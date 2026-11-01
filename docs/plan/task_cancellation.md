# 停止本轮执行与原会话续问

## 2026-10-31 后续修正：失败续问与草稿隔离

- `failed` 与 `cancelled` 均为本轮结果，不会永久封死会话。Domain 放行新输入并重新排队；原消息保留失败/停止标记，失败前部分回答入库保存。
- 执行契约参数为 `restart_after_interruption`，同步所有调用、测试和文档；Application 识别历史结果，由 Infrastructure 清理旧执行现场。Domain 不导入框架，Application 不导入基础设施实现。
- `frontpages/src/hooks/use-task-composer.ts` 按账号和任务保存输入草稿。切换会话时分开显示，旧提交完成只清空原草稿；新建任务不会清掉其他任务草稿。页面刷新后未发送草稿不保留。
- `use-task-workspace.ts` 跟踪会话选择版本，旧创建回包不能切回已离开的任务，旧请求的错误不覆盖当前会话提示。
- 本次修改聚合、领域服务、应用执行契约与编排、Runtime 清理提示；前端修改状态合并、草稿 Hook、工作区 Hook、页面与部分回答提示。同步现有内存执行器参数、补充后端失败恢复与前端草稿测试。
- 51 项后端与架构检查、13 项前端状态/草稿测试、TypeScript 与针对性 ESLint/Ruff 检查通过。包含真实内存图工具抛错后重发不重跑旧工具；没有执行外部服务验证或浏览器端到端验证。无需新增迁移，重启后端并刷新前端。

## 2026-10-31 停止语义修正

停止只结束当前请求的一轮执行。等待后台确认停止后，可以在原输入框重新输入正确内容，继续使用同一会话，不要求新建工作任务。

- 允许 `cancelled → queued → running`，正常启动新一轮时递增 attempt；停止中仍禁止发送，避免与旧执行重叠。
- 旧输入与部分回答保留 cancelled 消息状态，不重新当成待执行输入。
- Runtime 清除旧 checkpoint 的待执行节点和中断，为尚未返回的工具调用添加中止结果；新输入不会恢复旧工具或旧人工问题。历史、文件保留，旧计划和计数重置。
- 前端使用 attempt 与服务端 updated_at 区分新排队和旧响应，保留微秒精度。停止完成后恢复发送，按钮改为“停止本轮”。
- 不增加数据库字段或迁移；若之前已经执行 cancelling 迁移，本次直接重启后端并刷新前端即可。

## 本次修正的验证与代码定位

本次 44 项后端离线测试通过，覆盖聚合、领域服务、应用编排、Worker、真实 DeepAgents 内存图和 HTTP 路由；9 项前端状态测试、TypeScript 和针对性 ESLint/Ruff 检查通过。后端测试在不创建网络连接的内存事件循环中执行，未连接真实数据库、Redis、模型或 Langfuse。Windows 默认测试事件循环在创建本地自唤醒 TCP 连接时阻塞，因此本次测试进程使用临时的无网络事件循环；未修改项目的生产事件循环。

扩展检查发现旧领域测试未提供最新持久化状态及人工问题，HTTP 测试未替换追踪依赖。本次仅补齐其离线模拟配置，并同步内存执行器的 execute 关键字参数。

| 文件 | 本次修正 |
| --- | --- |
| src/agent_platform/domain/aggregates/agent_task.py | 停止后允许追加消息与重新排队 |
| src/agent_platform/domain/services/agent_task_domain_service.py | 停止会话收到新输入时进入 queued |
| src/agent_platform/application/interfaces/agent_task_runtime.py | restart_after_interruption 执行参数 |
| src/agent_platform/application/services/agent_task_application_service.py | 识别历史停止标记、通知 Runtime、发布状态更新时间 |
| src/agent_platform/infrastructure/harness/runtime/deepagents_task_runtime.py | 清除旧调度现场、中止工具协议消息、重置计划 |
| src/agent_platform/interface/api/routes/v1/agent_tasks.py | SSE state 携带状态更新时间 |
| frontpages/src/lib/task-state.ts | 接受停止后的新排队、屏蔽旧响应与旧内容 |
| frontpages/src/lib/task-types.ts | 本轮停止的展示文案 |
| frontpages/src/hooks/use-task-workspace.ts | 停止后恢复发送 |
| frontpages/src/components/workspace/workspace.tsx | 停止本轮按钮与可继续输入提示 |
| frontpages/src/components/workspace/conversation-thread.tsx | 停止只针对本轮的提示 |
| tests/unit/test_running_task_cancellation.py | 同会话重新发送、轮次、Worker 后续消费 |
| tests/unit/test_agent_task_runtime.py | 真实工具取消、旧中断清理、无 checkpoint 的停止后重发 |
| tests/unit/test_agent_task_domain_service.py | 同步领域测试的仓储状态与人工问题 |
| tests/unit/test_task_pipeline.py | 停止后重发的 HTTP 用例、空追踪依赖、执行契约 |
| tests/integration/test_task_pipeline_postgres_redis.py | 仅同步执行契约；未运行真实集成验证 |
| frontpages/tests/task-cancellation.test.cjs | 同轮次重新排队、微秒版本、旧响应与跨页面同步 |
| README.md、docs/plan/current_progress.md | 同步状态语义、运行说明和当前进度 |

以下是本次修正的关键源码片段，可直接对照学习；原有停止机制说明保留在后文。

### src/agent_platform/domain/aggregates/agent_task.py，第 98 行

```python
    def ensure_accepts_messages(self) -> None:
        """判断当前会话是否允许追加普通消息。"""
        if self.status == AgentTaskStatus.WAITING_HUMAN:
            raise ConflictError("当前正在等待人工回复，请先回答待处理的问题")

        if self.status == AgentTaskStatus.CANCELLING:
            raise ConflictError("本轮正在停止，请等待停止完成后重新发送")

    def queue_next(self) -> Self:
        """上一轮完成、失败或停止后，将同一会话重新安排为待执行。"""
        return self._transition(AgentTaskStatus.QUEUED)
```

### src/agent_platform/domain/services/agent_task_domain_service.py，第 425 行

```python
        # 空闲的会话重新排队；正在执行的会话保持原状态。
        if task.status in {
            AgentTaskStatus.SUCCEEDED,
            AgentTaskStatus.FAILED,
            AgentTaskStatus.CANCELLED,
        }:
            task = task.queue_next()

        await self._repository.save(principal, task)
        return task
```

### src/agent_platform/application/services/agent_task_application_service.py，第 115 行

```python
        # 消息结果已持久化，跨进程及重启后仍能识别上轮停止或失败。
        history = await self.messages(principal, task_id)
        current_ids = {item.id for item in messages}
        previous_inputs = [
            item
            for item in history
            if item.role == "user"
            and item.id not in current_ids
            and item.state in {"applied", "cancelled", "failed"}
        ]
        restart_after_interruption = bool(
            previous_inputs and previous_inputs[-1].state in {"cancelled", "failed"}
        )
```

### src/agent_platform/infrastructure/harness/runtime/deepagents_task_runtime.py，第 145 行

```python
        stopped_tools: list[ToolMessage] = []  # 为中止的调用补齐协议消息，不执行旧工具
        if restart_after_interruption and snapshot.created_at is not None:
            # 官方更新接口清除待执行节点及中断，保留消息和虚拟文件。
            await graph.aupdate_state(config, None, as_node=END)
            snapshot = await graph.aget_state(config)
            answered = {
                item.tool_call_id
                for item in snapshot.values.get("messages", [])
                if isinstance(item, ToolMessage)
            }
            stopped_tools = [
                ToolMessage(
                    id=f"stopped-{call['id']}",
                    tool_call_id=call["id"],
                    content="上一轮执行已结束或中断，此调用未完成。请根据最新输入重新判断。",
                    status="error",
                )
                for item in snapshot.values.get("messages", [])
                if isinstance(item, AIMessage)
                for call in item.tool_calls
                if call["id"] not in answered
            ]
```

### frontpages/src/lib/task-state.ts，第 3 行

```typescript
// 保留微秒，避免同一毫秒内的停止和重新排队被误判为同一版本。
function version(value: string) {
  return value.replace("+00:00", "Z").replace(/(?:\.(\d+))?Z$/, (_, digits: string | undefined) => `.${(digits ?? "").padEnd(6, "0")}Z`);
}

function acceptsStatus(current: LocalTask, incoming: TaskStatus, attempt: number, updatedAt?: string) {
  if (attempt < current.attempt) return false;
  if (attempt > current.attempt) return true;
  const newer = updatedAt !== undefined && version(updatedAt) > version(current.updated_at);
  if (updatedAt && version(updatedAt) < version(current.updated_at)) return false;
  // 本轮停止后，只有服务端确认的新输入能在同轮次重新排队。
  if (["cancelled", "failed"].includes(current.status)) return incoming === current.status || (incoming === "queued" && newer);
  if (current.status === "cancelling") return incoming === "cancelling" || incoming === "cancelled";
  return true;
}

export function mergeTask(local: LocalTask, remote: TaskResponse): LocalTask {
  if (!acceptsStatus(local, remote.status, remote.attempt, remote.updated_at)) return local;
  return {
    ...local, ...remote,
    ...(["cancelled", "failed"].includes(local.status) && remote.status === "queued"
      ? { draft: "", todos: null, interrupts: [], result: null, error: null } : {}),
    replyPending: remote.status === "waiting_human" && local.replyPending,
    draft: remote.attempt > local.attempt || (["cancelled", "failed"].includes(local.status) && remote.status === "queued") ? "" : local.draft,
  };
}
```

## 原有停止机制

- 排队、等待人工：直接 cancelled。
- 运行中：先持久化 cancelling，前端显示正在停止；Worker 约每 0.5 秒查询数据库，取消当前执行 Task，等待退出后再保存 cancelled 并 ACK。
- 停止的是当前执行，不是消费者。消费者随后处理下一条任务。
- API 与 Worker 可以分进程，取消意图保存在业务数据库，不依赖内存字典或瞬时通知。
- 取消重复请求和确认保持幂等；确认校验 attempt，晚到结果不能覆盖取消状态。
- 未处理消息用 cancelled 标记；部分助手文本保存到消息历史，刷新后仍可查看，最终 result 不伪装为成功回答。
- 服务关闭若没有用户取消请求，继续传播 CancelledError，不误记失败或正常取消，不 ACK 未完成消息。
- Runtime 用 aclosing 关闭异步流；框架管理的异步子任务随取消退出。已经完成的副作用无法撤回，非协作同步工具或后台线程不能强制杀掉。
- 已生成 Token 无法退回，断开连接也不保证远端立即停止计费。

## 先做数据库迁移

停止旧后端，在项目根目录执行，然后重新启动：

```powershell
uv run alembic upgrade head
uv run harness-api
```

迁移文件：`migrations/alembic/versions/d40c6e2189ab_support_running_task_cancellation.py`。它扩展任务、消息两张表的检查约束，不创建新表，不修改既有 ID。已离线检查 PostgreSQL 升降级 SQL，未连接或修改用户数据库。若跳过迁移，保存新状态会被旧检查约束拒绝。

## DDD 分工

| 层 | 本次职责 |
| --- | --- |
| Domain | 取消状态、可取消条件、归属、轮次、未完成消息收尾 |
| Application | 短事务、整段执行的取消处理、部分文本、提交后发布事件 |
| Worker | 独立执行 Task、跨进程可见的状态检查、等待退出后确认消息 |
| Infrastructure | ORM 约束与消息状态、异步图流关闭 |
| API | 继续调用现有 cancel 用例，不直接查模型连接或线程 |
| 前端 | 停止按钮、停止中状态、停止期间禁止发送、停止后恢复发送、保留内容、防止迟到数据回退状态 |

## 改动清单

以下路径均相对项目根目录 `D:\project\deepagent\deepagent_ddd`：

| 文件 | 修改内容 |
| --- | --- |
| src/agent_platform/domain/aggregates/agent_task.py | cancelling 状态、请求与确认取消 |
| src/agent_platform/domain/services/agent_task_domain_service.py | 取消持久化、同轮确认、部分消息与竞争处理 |
| src/agent_platform/domain/types/task_message.py | 消息 cancelled 类型 |
| src/agent_platform/domain/repositories/agent_task_repository.py | 仓储允许 cancelled 消息状态 |
| src/agent_platform/application/services/agent_task_application_service.py | 执行取消收尾、部分回答、停止事件 |
| src/agent_platform/infrastructure/persistence/repositories/agent_task_repository.py | 新消息状态的类型契约 |
| src/agent_platform/infrastructure/persistence/entities/agent_tasks.py | 任务状态约束 |
| src/agent_platform/infrastructure/persistence/entities/agent_task_messages.py | 消息状态约束 |
| src/agent_platform/infrastructure/harness/runtime/deepagents_task_runtime.py | 显式关闭流，保留原事件解析 |
| src/agent_platform/workers/agent_task_worker.py | 只取消执行协程，继续消费 |
| src/agent_platform/interface/api/routes/v1/agent_tasks.py | 更新取消接口说明 |
| migrations/alembic/versions/d40c6e2189ab_support_running_task_cancellation.py | 新增业务表约束迁移 |
| frontpages/src/lib/task-types.ts | 新状态与展示标签 |
| frontpages/src/lib/task-state.ts | 提取纯状态转换，拒绝取消后的迟到状态 |
| frontpages/src/hooks/use-task-workspace.ts | 使用状态转换，停止中禁止发送 |
| frontpages/src/components/workspace/workspace.tsx | 输入框停止按钮与停止提示 |
| frontpages/src/components/workspace/conversation-thread.tsx | 部分回答、停止记录与消息标识 |
| frontpages/src/components/workspace/task-plan.tsx | 停止后不再旋转执行图标 |
| frontpages/src/app/globals.css | 停止中状态配色 |
| frontpages/package.json | 新增 test:tasks 命令，无新依赖 |
| frontpages/tests/task-cancellation.test.cjs | 前端状态与迟到事件测试 |
| tests/unit/test_running_task_cancellation.py | 离线领域、应用、Worker、流关闭测试 |
| tests/unit/test_agent_task_domain_service.py | 更新原有运行中不允许取消的测试预期 |
| README.md | 更新取消能力、状态图、接口与操作说明 |
| docs/plan/current_progress.md | 更新交接摘要 |

没有修改模型配置、SDK 密钥、队列协议或登录鉴权。没有自动执行数据库迁移，也没有暂存或提交 Git。

## 关键改动代码

下面是实际代码，没有加减号；行号对应本次生成时的源码，后续编辑可能变化。领域服务的 finish、fail、return_to_waiting 也检查最新取消状态，取消先提交时不再写成功或失败结果。


### src/agent_platform/domain/aggregates/agent_task.py

完整路径：`D:\project\deepagent\deepagent_ddd\src\agent_platform\domain\aggregates\agent_task.py`


**AgentTask.cancel，第 151 行起：**

```python
    def cancel(self) -> Self:
        """运行中先请求停止；未运行则立即取消，重复请求保持幂等。"""
        if self.status in {AgentTaskStatus.CANCELLING, AgentTaskStatus.CANCELLED}:
            return self
        if self.status == AgentTaskStatus.RUNNING:
            return self._transition(AgentTaskStatus.CANCELLING)
        return self._transition(AgentTaskStatus.CANCELLED)
```


**AgentTask.confirm_cancelled，第 159 行起：**

```python
    def confirm_cancelled(self) -> Self:
        """执行方确认退出后结束取消，不将用户停止记为执行失败。"""
        if self.status == AgentTaskStatus.CANCELLED:
            return self
        return self._transition(AgentTaskStatus.CANCELLED)
```


### src/agent_platform/domain/services/agent_task_domain_service.py

完整路径：`D:\project\deepagent\deepagent_ddd\src\agent_platform\domain\services\agent_task_domain_service.py`


**AgentTaskDomainService.cancel，第 250 行起：**

```python
    async def cancel(self, principal: Principal, task_id: UUID) -> AgentTask:
        """持久化取消意图，运行中的任务交给执行方确认退出。"""
        task = await self.get(principal, task_id, for_update=True)
        requested = task.cancel()
        if requested.status == AgentTaskStatus.CANCELLING:
            await self._repository.save(principal, requested)
            return requested
        return await self._save_cancelled(principal, task)
```


**AgentTaskDomainService.confirm_cancellation，第 259 行起：**

```python
    async def confirm_cancellation(
        self,
        principal: Principal,
        task_id: UUID,
        *,
        attempt: int,
        partial_output: str | None = None,
    ) -> AgentTask:
        """只确认同一轮已持久化的取消请求，避免旧执行影响其他轮次。"""
        task = await self.get(principal, task_id, for_update=True)
        if task.attempt != attempt:
            raise ConflictError("取消确认不属于当前执行轮次")
        if task.status not in {AgentTaskStatus.CANCELLING, AgentTaskStatus.CANCELLED}:
            raise ConflictError("任务没有待确认的取消请求")
        return await self._save_cancelled(principal, task, partial_output=partial_output)
```


**AgentTaskDomainService._save_cancelled，第 275 行起：**

```python
    async def _save_cancelled(
        self,
        principal: Principal,
        task: AgentTask,
        *,
        partial_output: str | None = None,
    ) -> AgentTask:
        """在调用方持有的任务行锁内保存停止结果，保留可用的部分回答。"""
        if task.status == AgentTaskStatus.CANCELLED:
            return task
        cancelled = task.confirm_cancelled()
        history = await self._repository.messages(principal, task.id)
        ids = [
            item.id
            for item in history
            if item.role == "user" and item.state in {"pending", "processing"}
        ]
        await self._repository.set_message_state(
            principal,
            task.id,
            ids=ids,
            state="cancelled",
        )
        if partial_output and partial_output.strip():
            await self._repository.add_message(
                principal,
                task.id,
                TaskMessage(role="assistant", content=partial_output, state="cancelled"),
            )
        await self._repository.save(principal, cancelled)
        return cancelled
```


### src/agent_platform/application/services/agent_task_application_service.py

完整路径：`D:\project\deepagent\deepagent_ddd\src\agent_platform\application\services\agent_task_application_service.py`


**_TaskExecution，第 33 行起：**

```python
@dataclass
class _TaskExecution:
    task: AgentTask | None = None  # 当前协程实际领取的轮次，不与其他任务共享
    partial_output: list[str] = field(default_factory=list)  # 已接收的本轮文本
```


**AgentTaskApplicationService._run_cancellable，第 75 行起：**

```python
    async def _run_cancellable(
        self,
        principal: Principal,
        task_id: UUID,
        command: ResumeAgentTask | None = None,
    ) -> AgentTask:
        """覆盖领取之后的推理、结果提交和事件发布，避免取消漏掉收尾阶段。"""
        execution = _TaskExecution()
        try:
            if command is None:
                return await self._execute(principal, task_id, execution)
            return await self._resume(principal, task_id, command, execution)
        except asyncio.CancelledError:
            if execution.task is None:
                raise
            cancelled = await self._cancel_interrupted_execution(
                principal,
                execution.task,
                execution.partial_output,
            )
            if cancelled is not None:
                return cancelled
            raise
```


**AgentTaskApplicationService.cancel，第 312 行起：**

```python
    async def cancel(self, principal: Principal, task_id: UUID) -> AgentTask:
        """提交取消意图或立即取消结果，再向前端发布对应事件。"""
        task = await self._cancel_task(principal, task_id)
        await self._publish(task, task.status.value, {"status": task.status.value})
        return task
```


**AgentTaskApplicationService.complete_cancellation，第 318 行起：**

```python
    async def complete_cancellation(
        self,
        principal: Principal,
        task_id: UUID,
        *,
        attempt: int,
        partial_output: str | None = None,
    ) -> AgentTask:
        """执行协程退出后确认取消，提交业务状态后发布最终事件。"""
        task = await self._confirm_cancellation(
            principal,
            task_id,
            attempt=attempt,
            partial_output=partial_output,
        )
        await self._publish(task, "cancelled", {})
        return task
```


**AgentTaskApplicationService._cancel_interrupted_execution，第 353 行起：**

```python
    async def _cancel_interrupted_execution(
        self,
        principal: Principal,
        task: AgentTask,
        partial_output: list[str],
    ) -> AgentTask | None:
        """只消费用户取消信号，服务关闭导致的取消继续向上传播。"""
        current = await self.get(principal, task.id)
        if current.attempt != task.attempt or current.status not in {
            AgentTaskStatus.CANCELLING,
            AgentTaskStatus.CANCELLED,
        }:
            return None
        return await self.complete_cancellation(
            principal,
            task.id,
            attempt=task.attempt,
            partial_output="".join(partial_output),
        )
```


### src/agent_platform/workers/agent_task_worker.py

完整路径：`D:\project\deepagent\deepagent_ddd\src\agent_platform\workers\agent_task_worker.py`


**AgentTaskWorker._execute_job，第 114 行起：**

```python
    async def _execute_job(self, job: TaskJob) -> None:
        """执行和检查取消分属不同协程，只停止执行，不停止消费者。"""
        context = job.context
        invocation = (
            self._service.execute(principal=context, task_id=context.task_id)
            if job.resume is None
            else self._service.resume(
                principal=context,
                task_id=context.task_id,
                command=job.resume,
            )
        )
        execution = asyncio.create_task(invocation, name=f"agent-task-{context.task_id}")
        try:
            while not execution.done():
                done, _ = await asyncio.wait({execution}, timeout=0.5)
                if done:
                    break
                # 每次查询独立短事务，API 与 Worker 不必在同一进程。
                current = await self._service.get(context, context.task_id)
                if current.status == AgentTaskStatus.CANCELLING:
                    execution.cancel()
                    stopped = None  # 应用服务可能已保存部分回答并确认取消
                    try:
                        stopped = await execution
                    except asyncio.CancelledError:
                        consumer = asyncio.current_task()
                        if consumer is not None and consumer.cancelling():
                            raise
                    # 必须等执行真正退出，才可以确认取消并 ACK。
                    if stopped is None or stopped.status != AgentTaskStatus.CANCELLED:
                        await self._service.complete_cancellation(
                            context,
                            context.task_id,
                            attempt=current.attempt,
                        )
                    return
            await execution
        finally:
            # 服务关闭或检查失败时回收执行协程，不能遗留模型请求。
            if not execution.done():
                execution.cancel()
                try:
                    await execution
                except asyncio.CancelledError:
                    pass
```


## 前端如何测试

1. 发起会持续执行的任务，看到文本或工具动态后，点击输入框旁的“停止任务”。
2. 先看到“正在停止”，发送和停止按钮禁用；收到确认后显示已停止或已取消。
3. 已收到的文字保留，刷新后从数据库读取部分回答，不能显示为完整成功结果。
4. 停止期间发起的旧查询和迟到事件不能让页面回到运行、完成或失败。
5. 新建另一工作任务，确认 Worker 继续消费。
6. 触发人工提问后恢复，再在恢复执行期间停止；仍然使用同一轮次收尾。

## 验证范围

上次实现记录：13 项专用后端离线测试通过，覆盖运行中停止、立即取消、幂等、权限、轮次、完成/失败竞争、待处理输入取消、提交阶段取消、部分文本、子任务退出、流关闭、服务关闭和消费者继续运行。原领域取消用例已更新并通过；16 项既有追踪离线测试通过。

前端现有 9 项停止状态测试，另有既有代理测试；TypeScript 与针对性 lint 检查通过。迁移的 PostgreSQL DDL 已离线生成检查。

以上不代替真实模型、数据库和 Redis 的端到端验收。本次未启动真实模型请求或操作用户数据库。仍按当前单消费者方案运行；Worker 异常退出后的 pending 回收、失联执行租约和多消费者恢复不在本次实现内。

## 输入框草稿代码

`frontpages/src/hooks/use-task-composer.ts` 第 5 行：

```typescript
export function useTaskComposer(identity: string, taskId: string | null) {
  const [drafts, setDrafts] = useState<Record<string, string>>({}); // 各账号、会话的未发送草稿
  const key = JSON.stringify([identity, taskId]); // null 表示新任务输入区，避免与已有任务混用

  function setPrompt(value: string) {
    // 捕获本次渲染的任务键：旧提交完成后只清空原任务草稿。
    setDrafts((current) => ({ ...current, [key]: value }));
  }

  function clearNewDraft() {
    setDrafts((current) => ({ ...current, [JSON.stringify([identity, null])]: "" }));
  }

  return { prompt: drafts[key] ?? "", setPrompt, clearNewDraft };
}
```
