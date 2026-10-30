# 本轮会话改造：修改前后对照

比较基准是你本轮授权我修改之前的文件内容，不是 Git HEAD，因此不会把你之前自己的改动算作本轮修改。

本轮没有执行测试、构建、数据库迁移或真实模型调用。已经存在的 Git 改动、暂存内容均未提交或重置。

## 主要改动

- 把误放在应用服务的 return_to_waiting、record_reply 移回领域服务。
- 接通人工恢复：先改变执行状态，校验拒绝时回到等待，成功后保存回复和回答。
- 增加会话 title，完成聚合、ORM、仓储和响应映射；新增改名接口。
- 增加会话列表、消息历史、追加消息 HTTP 接口，继续使用已有身份校验。
- SSE 一轮结束后不断开，后续轮次继续使用相同 task_id 和 thread_id。
- 新轮次重置模型和工具调用额度；人工恢复不重置。
- 前端修正刷新后的会话定位、人工回复等待标记及状态显示。
- 准备标题迁移和旧记录回填，未运行迁移。

## 手动执行数据库更新

先停止 API 和 Worker，在项目根目录执行：

```powershell
uv run alembic upgrade head
uv run harness-api
```

不需要再 autogenerate，新迁移文件已经写好，接在 622b123e76fc 后面。旧 running/queued 任务的队列接管没有在本次实现，不能把迁移当成任务恢复。

## 逐文件代码对照

下面使用“修改前”和“修改后”，没有 diff 加减号，可直接复制代码。行号是本轮完成时的位置，之后你继续编辑会变化。

### `src/agent_platform/domain/aggregates/agent_task.py`

**改动 1：修改前（旧第 54 行）**

```python
    """一个用户任务对应一个聚合；业务方法返回新的不可变任务对象。"""

    context: TaskContext  # 任务编号、可信归属及当前执行上下文
    agent: Identifier = "task_planning"  # 执行该任务的 Agent 注册名
    prompt: str = Field(min_length=1, max_length=32000)  # 用户提交的任务要求
    status: AgentTaskStatus = AgentTaskStatus.QUEUED  # 当前任务状态
```

**修改后（当前第 54 行）**

```python
    """一个用户任务对应一个聚合；业务方法返回新的不可变任务对象。"""

    context: TaskContext  # 任务编号、可信归属及当前执行上下文
    title: str = Field(default="新会话", min_length=1, max_length=120, pattern=r"\S")  # 会话名称
    agent: Identifier = "task_planning"  # 执行该任务的 Agent 注册名
    prompt: str = Field(min_length=1, max_length=32000)  # 用户提交的任务要求
    status: AgentTaskStatus = AgentTaskStatus.QUEUED  # 当前任务状态
```

**改动 2：修改前（旧第 172 行）**

```python
        # return type(self).model_validate(data)
        return self.model_validate(data)
        # return AgentTask.model_validate(data)
```

**修改后（当前第 173 行）**

```python
        # return type(self).model_validate(data)
        return self.model_validate(data)
        # return AgentTask.model_validate(data)

    def rename(self, title: str) -> Self:
        """更新展示名称，不改变会话身份或模型上下文。"""
        title = title.strip()
        if not title:
            raise ValueError("会话名称不能为空白")
        data = self.model_dump()
        data.update(title=title, updated_at=datetime.now(UTC))
        return type(self).model_validate(data)
```

### `src/agent_platform/domain/services/agent_task_domain_service.py`

**改动 1：修改前（旧第 36 行）**

```python
                user_id=principal.user_id,
            ),
            agent=agent,
            prompt=prompt,
        )

```

**修改后（当前第 36 行）**

```python
                user_id=principal.user_id,
            ),
            agent=agent,
            title=prompt.strip()[:60],
            prompt=prompt,
        )

```

**改动 2：修改前（旧第 248 行）**

```python
        return failed_task

    async def cancel(self, principal: Principal, task_id: UUID) -> AgentTask:
        """取消任务，允许取消的状态完全由聚合根决定。"""
        task = await self.get(principal, task_id)
        cancelled_task = task.cancel()
        await self._repository.save(principal, cancelled_task)
        return cancelled_task

    async def list_recent(
        self,
```

**修改后（当前第 249 行）**

```python
        return failed_task

    async def cancel(self, principal: Principal, task_id: UUID) -> AgentTask:
        """取消允许取消的会话，并清理尚未完成的消息状态。"""
        task = await self.get(principal, task_id, for_update=True)
        cancelled = task.cancel()
        history = await self._repository.messages(principal, task_id)
        ids = [item.id for item in history if item.role == "user" and item.state in {"pending", "processing"}]
        await self._repository.set_message_state(principal, task_id, ids=ids, state="failed")
        await self._repository.save(principal, cancelled)
        return cancelled

    async def list_recent(
        self,
```

**改动 3：修改前（旧第 404 行）**

```python
        )

        return resumed_task
```

**修改后（当前第 408 行）**

```python
        )

        return resumed_task

    async def return_to_waiting(
        self,
        principal: Principal,
        task: AgentTask,
    ) -> AgentTask:
        """人工回复校验失败时，恢复为等待用户回复。"""
        current = await self.get(
            principal,
            task.id,
            for_update=True,
        )

        if (
            current.status != AgentTaskStatus.RUNNING
            or current.attempt != task.attempt
        ):
            raise ConflictError("当前执行轮次已经发生变化")

        waiting_task = current.wait_for_user()

        await self._repository.save(
            principal,
            waiting_task,
        )

        return waiting_task

    async def record_reply(
        self,
        principal: Principal,
        task_id: UUID,
        content: str,
    ) -> None:
        """将成功恢复执行的人工回复保存到消息历史。"""
        task = await self.get(
            principal,
            task_id,
            for_update=True,
        )

        if task.status != AgentTaskStatus.RUNNING:
            raise ConflictError("当前会话没有正在恢复的执行")

        await self._repository.add_message(
            principal,
            task_id,
            TaskMessage(
                role="user",
                content=content,
                state="applied",
            ),
        )

    async def rename(self, principal: Principal, task_id: UUID, title: str) -> AgentTask:
        """锁定最新会话后改名，避免覆盖执行中的其他状态。"""
        task = await self.get(principal, task_id, for_update=True)
        renamed = task.rename(title)
        await self._repository.save(principal, renamed)
        return renamed
```

### `src/agent_platform/application/services/agent_task_application_service.py`

**改动 1：修改前（旧第 2 行）**

```python

import logging
from uuid import UUID
from agent_platform.application.dto.agent_task_dto import UserInputPayload
from agent_platform.domain.aggregates.agent_task import AgentTaskStatus
from agent_platform.domain.types.task_message import TaskMessage
from pydantic import JsonValue
```

**修改后（当前第 2 行）**

```python

import logging
from uuid import UUID
from agent_platform.application.dto.agent_task_dto import (
    InvalidHumanReplyError, TextReply, UserInputPayload,
)
from agent_platform.domain.aggregates.agent_task import AgentTaskStatus
from agent_platform.domain.types.task_message import TaskMessage
from pydantic import JsonValue
```

**改动 2：修改前（旧第 144 行）**

```python
        return task

    async def resume(
        self, principal: Principal, task_id: UUID, command: ResumeAgentTask
    ) -> AgentTask:
        """领域校验恢复条件后调用执行器，再提交恢复结果。"""
        task = await self._prepare_resume(principal, task_id)
        await self._publish(task, "resuming", {})

        async def on_text(text: str) -> None:
```

**修改后（当前第 146 行）**

```python
        return task

    async def resume(
        self, principal: Principal, task_id: UUID, command: ResumeAgentTask,
    ) -> AgentTask:
        """先提交恢复状态，再在事务之外继续执行 Agent。"""
        task = await self._start_resume(principal, task_id)
        await self._publish(task, "resuming", {})

        async def on_text(text: str) -> None:
```

**改动 3：修改前（旧第 155 行）**

```python

        try:
            result = await self._runtime.resume(task, command, on_text=on_text)
            task = await self._finish_resume(principal, task, result)
        except ValueError:
            await self._publish(task, "resume_rejected", {"message": "人工回复不符合当前中断要求"})
            raise
        except Exception:
            await self._publish(task, "resume_error", {"message": "恢复执行失败，请查询任务状态"})
            raise
        await self._publish_result(task, result)
        return task

    async def cancel(self, principal: Principal, task_id: UUID) -> AgentTask:
```

**修改后（当前第 157 行）**

```python

        try:
            result = await self._runtime.resume(task, command, on_text=on_text)
        except InvalidHumanReplyError:
            task = await self._reject_resume(principal, task)
            await self._publish(task, "resume_rejected", {"message": "回复不符合当前中断要求，请重新填写"})
            raise
        except Exception:
            logger.exception("恢复执行失败，task_id=%s", task.id)
            task = await self._fail_task(principal, task, "恢复执行失败，请联系管理员查看日志")
            await self._publish(task, "failed", {"error": task.error})
            return task

        try:
            task = await self._finish_resume(principal, task, command, result)
        except ValueError as exc:
            task = await self._fail_task(principal, task, str(exc))
            await self._publish(task, "failed", {"error": task.error})
            return task
        await self._publish_result(task, result)
        if task.status == AgentTaskStatus.QUEUED:
            await self._queue.enqueue(task.context)
        return task

    async def cancel(self, principal: Principal, task_id: UUID) -> AgentTask:
```

**改动 4：修改前（旧第 278 行）**

```python

    @transactional(Propagation.REQUIRED)
    async def _finish_resume(
        self, principal: Principal, task: AgentTask, result: AgentTaskExecutionResult
    ) -> AgentTask:
        """在短事务中保存人工恢复后的业务结果。"""
        return await self._tasks.finish_resume(
            principal, task, waiting_for_user=result.status == "waiting", output=result.output
        )

    @transactional(Propagation.REQUIRED)
    async def _fail_task(self, principal: Principal, task: AgentTask, reason: str) -> AgentTask:
```

**修改后（当前第 291 行）**

```python

    @transactional(Propagation.REQUIRED)
    async def _finish_resume(
        self, principal: Principal, task: AgentTask,
        command: ResumeAgentTask, result: AgentTaskExecutionResult,
    ) -> AgentTask:
        """人工回复与恢复结果在同一短事务中保存。"""
        replies: list[str] = []
        for reply in command.answers.values():
            if isinstance(reply, TextReply):
                replies.append(reply.answer)
            else:
                replies.append("允许工具执行" if reply.approved else "拒绝工具执行")
        await self._tasks.record_reply(principal, task.id, "\n\n".join(replies))
        return await self._finish_task(principal, task, result)

    @transactional(Propagation.REQUIRED)
    async def _fail_task(self, principal: Principal, task: AgentTask, reason: str) -> AgentTask:
```

**改动 5：修改前（旧第 351 行）**

```python
            task_id,
        )

    async def return_to_waiting(
        self,
        principal: Principal,
        task: AgentTask,
    ) -> AgentTask:
        """人工回复校验失败时，恢复为等待用户回复。"""
        current = await self.get(
            principal,
            task.id,
            for_update=True,
        )

        if (
            current.status != AgentTaskStatus.RUNNING
            or current.attempt != task.attempt
        ):
            raise ConflictError("当前执行轮次已经发生变化")

        waiting_task = current.wait_for_user()

        await self._repository.save(
            principal,
            waiting_task,
        )

        return waiting_task

    async def record_reply(
        self,
        principal: Principal,
        task_id: UUID,
        content: str,
    ) -> None:
        """将成功恢复执行的人工回复保存到消息历史。"""
        task = await self.get(
            principal,
            task_id,
            for_update=True,
        )

        if task.status != AgentTaskStatus.RUNNING:
            raise ConflictError("当前会话没有正在恢复的执行")

        await self._repository.add_message(
            principal,
            task_id,
            TaskMessage(
                role="user",
                content=content,
                state="applied",
            ),
        )
```

**修改后（当前第 370 行）**

```python
            task_id,
        )

    @transactional(Propagation.REQUIRED)
    async def _start_resume(self, principal: Principal, task_id: UUID) -> AgentTask:
        """Worker 实际开始恢复时提交执行中状态。"""
        return await self._tasks.start_resume(principal, task_id)

    @transactional(Propagation.REQUIRED)
    async def _reject_resume(self, principal: Principal, task: AgentTask) -> AgentTask:
        """回复不合法时，恢复为等待状态。"""
        return await self._tasks.return_to_waiting(principal, task)

    @transactional(Propagation.REQUIRED)
    async def rename(self, principal: Principal, task_id: UUID, title: str) -> AgentTask:
        """修改会话名称，不改变执行线程。"""
        return await self._tasks.rename(principal, task_id, title)
```

### `src/agent_platform/infrastructure/harness/runtime/deepagents_task_runtime.py`

**改动 1：修改前（旧第 121 行）**

```python
            graph,
            task,
            {
                "messages": [
                    {
                        "id": str(item.id),
```

**修改后（当前第 121 行）**

```python
            graph,
            task,
            {
                # 新一轮输入重新计算调用额度；人工恢复仍沿用当前轮的计数。
                "model_call_count": 0,
                "tool_call_count": 0,
                "tool_call_counts": {},
                "messages": [
                    {
                        "id": str(item.id),
```

### `src/agent_platform/infrastructure/persistence/entities/agent_tasks.py`

**改动 1：修改前（旧第 73 行）**

```python
        nullable=False,
    )  # 执行任务的 Agent 注册名称

    prompt: Mapped[str] = mapped_column(
        Text,
        nullable=False,
```

**修改后（当前第 73 行）**

```python
        nullable=False,
    )  # 执行任务的 Agent 注册名称

    title: Mapped[str] = mapped_column(
        String(120), nullable=False, server_default="新会话",
    )  # 会话名称，与首条输入分开保存

    prompt: Mapped[str] = mapped_column(
        Text,
        nullable=False,
```

### `src/agent_platform/infrastructure/persistence/repositories/agent_task_repository.py`

**改动 1：修改前（旧第 65 行）**

```python
            ):
                raise ConflictError("不允许修改已有任务的固定信息")

        record.status = task.status.value
        record.result = task.result
        record.error = task.error
```

**修改后（当前第 65 行）**

```python
            ):
                raise ConflictError("不允许修改已有任务的固定信息")

        record.title = task.title
        record.status = task.status.value
        record.result = task.result
        record.error = task.error
```

**改动 2：修改前（旧第 88 行）**

```python
        )

        if for_update:
            statement = statement.with_for_update()

        session = current_session()
        record = await session.scalar(statement)
```

**修改后（当前第 89 行）**

```python
        )

        if for_update:
            statement = statement.with_for_update().execution_options(populate_existing=True)

        session = current_session()
        record = await session.scalar(statement)
```

**改动 3：修改前（旧第 123 行）**

```python
                thread_id=record.thread_id,
                trace_id=record.trace_id,
            ),
            agent=record.agent,
            prompt=record.prompt,
            status=AgentTaskStatus(record.status),
```

**修改后（当前第 124 行）**

```python
                thread_id=record.thread_id,
                trace_id=record.trace_id,
            ),
            title=record.title,
            agent=record.agent,
            prompt=record.prompt,
            status=AgentTaskStatus(record.status),
```

### `src/agent_platform/interface/vo/agent_task_vo.py`

**改动 1：修改前（旧第 25 行）**

```python
    model_config = ConfigDict(frozen=True, extra="forbid")

    task_id: UUID  # 任务编号
    status: AgentTaskStatus  # 当前状态
    result: str | None  # 最终结果
    error: str | None  # 失败原因
```

**修改后（当前第 25 行）**

```python
    model_config = ConfigDict(frozen=True, extra="forbid")

    task_id: UUID  # 任务编号
    title: str  # 可修改的会话名称
    prompt: str  # 第一条用户输入
    attempt: int  # 当前执行轮次
    status: AgentTaskStatus  # 当前状态
    result: str | None  # 最终结果
    error: str | None  # 失败原因
```

**改动 2：修改前（旧第 36 行）**

```python
        """转换为供前端展示的业务结果。"""
        return cls(
            task_id=task.id,
            status=task.status,
            result=task.result,
            error=task.error,
            created_at=task.created_at,
            updated_at=task.updated_at,
        )
```

**修改后（当前第 39 行）**

```python
        """转换为供前端展示的业务结果。"""
        return cls(
            task_id=task.id,
            title=task.title,
            prompt=task.prompt,
            attempt=task.attempt,
            status=task.status,
            result=task.result,
            error=task.error,
            created_at=task.created_at,
            updated_at=task.updated_at,
        )


class SendTaskMessageRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID  # 客户端生成的消息编号，用于识别重复提交
    content: str = Field(
        strict=True, min_length=1, max_length=32000, pattern=r"\S",
    )  # 同一会话中的新输入


class RenameTaskRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(
        strict=True, min_length=1, max_length=120, pattern=r"\S",
    )  # 新的会话名称
```

### `src/agent_platform/interface/api/routes/v1/agent_tasks.py`

**改动 1：修改前（旧第 10 行）**

```python
from fastapi.responses import StreamingResponse

from agent_platform.application.dto.agent_task_dto import AgentTaskExecutionResult, ResumeAgentTask
from agent_platform.domain.aggregates.agent_task import AgentTaskStatus
from agent_platform.domain.types.common import ConflictError, NotFoundError
from agent_platform.interface.api.dependencies import (
    CurrentPrincipal,
    CurrentTaskApplicationService,
    CurrentTaskEvents,
)
from agent_platform.interface.vo.agent_task_vo import AgentTaskResponse, CreateAgentTaskRequest

router = APIRouter(prefix="/tasks", tags=["tasks"])

```

**修改后（当前第 10 行）**

```python
from fastapi.responses import StreamingResponse

from agent_platform.application.dto.agent_task_dto import AgentTaskExecutionResult, ResumeAgentTask
from agent_platform.domain.types.common import ConflictError, NotFoundError
from agent_platform.domain.types.task_message import TaskMessage
from agent_platform.interface.api.dependencies import (
    CurrentPrincipal,
    CurrentTaskApplicationService,
    CurrentTaskEvents,
)
from agent_platform.interface.vo.agent_task_vo import (
    AgentTaskResponse,
    CreateAgentTaskRequest,
    RenameTaskRequest,
    SendTaskMessageRequest,
)

router = APIRouter(prefix="/tasks", tags=["tasks"])

```

**改动 2：修改前（旧第 102 行）**

```python
    async def stream() -> AsyncIterator[str]:
        cursor = last_event_id or after
        last_status_check = monotonic()  # 空闲时每隔一段时间查询业务状态
        terminal = {
            AgentTaskStatus.SUCCEEDED: "completed",
            AgentTaskStatus.FAILED: "failed",
            AgentTaskStatus.CANCELLED: "cancelled",
        }
        while not await request.is_disconnected():
            batch = await events.read(task.context, cursor, block_ms=1000)
            if batch:
```

**修改后（当前第 107 行）**

```python
    async def stream() -> AsyncIterator[str]:
        cursor = last_event_id or after
        last_status_check = monotonic()  # 空闲时每隔一段时间查询业务状态
        while not await request.is_disconnected():
            batch = await events.read(task.context, cursor, block_ms=1000)
            if batch:
```

**改动 3：修改前（旧第 114 行）**

```python
                    data = json.dumps(item.data, ensure_ascii=False)
                    yield f"id: {item.id}\nevent: {item.event}\ndata: {data}\n\n"
                    cursor = item.id
                    if item.event in {"completed", "failed", "cancelled"}:
                        return
            else:
                # 最后一个事件已读过或写入失败时，用业务记录兜底结束连接。
                if task.status in terminal or monotonic() - last_status_check >= 15:
                    current = await service.get(principal, task_id)
                    last_status_check = monotonic()
                    if current.status in terminal:
                        data = json.dumps(
                            {
                                "status": current.status.value,
                                "output": current.result,
                                "error": current.error,
                            },
                            ensure_ascii=False,
                        )
                        yield f"event: {terminal[current.status]}\ndata: {data}\n\n"
                        return
                yield ": keep-alive\n\n"

    return StreamingResponse(
```

**修改后（当前第 114 行）**

```python
                    data = json.dumps(item.data, ensure_ascii=False)
                    yield f"id: {item.id}\nevent: {item.event}\ndata: {data}\n\n"
                    cursor = item.id
            else:
                # 一轮完成后仍保持连接，后续消息继续使用同一个会话。
                if monotonic() - last_status_check >= 15:
                    current = await service.get(principal, task_id)
                    last_status_check = monotonic()
                    data = json.dumps(
                        {
                            "attempt": current.attempt,
                            "status": current.status.value,
                            "output": current.result,
                            "error": current.error,
                        },
                        ensure_ascii=False,
                    )
                    # 状态通知不是持久化事件，不伪造 Redis 游标。
                    yield f"event: state\ndata: {data}\n\n"
                yield ": keep-alive\n\n"

    return StreamingResponse(
```

**改动 4：修改前（旧第 153 行）**

```python
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail="任务不存在或无权访问") from exc
    return AgentTaskResponse.from_task(task)
```

**修改后（当前第 151 行）**

```python
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail="任务不存在或无权访问") from exc
    return AgentTaskResponse.from_task(task)


@router.get("", response_model=list[AgentTaskResponse])
async def list_tasks(
    principal: CurrentPrincipal,
    service: CurrentTaskApplicationService,
) -> list[AgentTaskResponse]:
    """读取当前身份最近的五十条会话。"""
    tasks = await service.list_recent(principal)
    return [AgentTaskResponse.from_task(task) for task in tasks]


@router.get("/{task_id}/messages", response_model=list[TaskMessage])
async def list_messages(
    task_id: UUID,
    principal: CurrentPrincipal,
    service: CurrentTaskApplicationService,
) -> list[TaskMessage]:
    """读取会话消息，权限由领域服务及仓储共同约束。"""
    try:
        return await service.messages(principal, task_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/{task_id}/messages", response_model=AgentTaskResponse, status_code=202)
async def send_message(
    task_id: UUID,
    request: SendTaskMessageRequest,
    principal: CurrentPrincipal,
    service: CurrentTaskApplicationService,
) -> AgentTaskResponse:
    """追加同一会话的消息，执行中收到的补充先入库排队。"""
    try:
        task = await service.send_message(principal, task_id, request.id, request.content)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return AgentTaskResponse.from_task(task)


@router.patch("/{task_id}", response_model=AgentTaskResponse)
async def rename_task(
    task_id: UUID,
    request: RenameTaskRequest,
    principal: CurrentPrincipal,
    service: CurrentTaskApplicationService,
) -> AgentTaskResponse:
    """修改会话名称，不新建任务或执行线程。"""
    try:
        task = await service.rename(principal, task_id, request.title)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return AgentTaskResponse.from_task(task)
```

### `frontpages/src/hooks/use-task-workspace.ts`

**改动 1：修改前（旧第 20 行）**

```typescript

function mergeTask(local: LocalTask, remote: TaskResponse): LocalTask {
  if (remote.attempt < local.attempt) return local;
  return { ...local, ...remote, draft: remote.attempt > local.attempt ? "" : local.draft };
}

function applyEvent(task: LocalTask, item: StreamEvent): LocalTask {
```

**修改后（当前第 20 行）**

```typescript

function mergeTask(local: LocalTask, remote: TaskResponse): LocalTask {
  if (remote.attempt < local.attempt) return local;
  return {
    ...local, ...remote,
    replyPending: remote.status === "waiting_human" && local.replyPending,
    draft: remote.attempt > local.attempt ? "" : local.draft,
  };
}

function applyEvent(task: LocalTask, item: StreamEvent): LocalTask {
```

**改动 2：修改前（旧第 39 行）**

```typescript
  if (["resuming", "waiting_human", "completed", "failed", "cancelled", "resume_rejected", "resume_error"].includes(item.event)) next.replyPending = false;
  if (item.event === "completed" && typeof item.data.output === "string") next.result = item.data.output;
  if (item.event === "failed" && typeof item.data.error === "string") next.error = item.data.error;
  if (item.event !== "text_delta") next.timeline = [...task.timeline, { key: item.id || crypto.randomUUID(), event: item.event, time: new Date().toISOString() }].slice(-100);
  return next;
}

```

**修改后（当前第 43 行）**

```typescript
  if (["resuming", "waiting_human", "completed", "failed", "cancelled", "resume_rejected", "resume_error"].includes(item.event)) next.replyPending = false;
  if (item.event === "completed" && typeof item.data.output === "string") next.result = item.data.output;
  if (item.event === "failed" && typeof item.data.error === "string") next.error = item.data.error;
  if (!["text_delta", "state"].includes(item.event)) next.timeline = [...task.timeline, { key: item.id || crypto.randomUUID(), event: item.event, time: new Date().toISOString() }].slice(-100);
  return next;
}

```

**改动 3：修改前（旧第 55 行）**

```typescript
  const tokenRef = useRef(token); // 防止旧身份请求污染当前页面
  const cursors = useRef(new Map<string, string>()); // 当前页面已消费的 SSE 游标
  const writing = useRef(false); // 阻止同一页面重复提交
  useEffect(() => { tokenRef.current = token; }, [token]);

  useEffect(() => {
    try { setToken(sessionStorage.getItem("harness-token") ?? ""); } catch { /* 存储禁用时使用内存令牌。 */ }
  }, []);

```

**修改后（当前第 59 行）**

```typescript
  const tokenRef = useRef(token); // 防止旧身份请求污染当前页面
  const cursors = useRef(new Map<string, string>()); // 当前页面已消费的 SSE 游标
  const writing = useRef(false); // 阻止同一页面重复提交
  const initialTask = useRef<string | null>(null); // 刷新前地址栏中的会话编号
  useEffect(() => { tokenRef.current = token; }, [token]);

  useEffect(() => {
    initialTask.current = new URLSearchParams(window.location.search).get("task");
    try { setToken(sessionStorage.getItem("harness-token") ?? ""); } catch { /* 存储禁用时使用内存令牌。 */ }
  }, []);

```

**改动 4：修改前（旧第 84 行）**

```typescript
        const list = await taskApi.list(token, controller.signal);
        if (controller.signal.aborted) return;
        setTasks(list.map(localTask));
        const id = new URLSearchParams(window.location.search).get("task");
        if (id && list.some((task) => task.task_id === id)) setSelectedId(id);
      } catch (reason) { if (!controller.signal.aborted) setError(message(reason)); }
      finally { if (!controller.signal.aborted) setReady(true); }
```

**修改后（当前第 90 行）**

```typescript
        const list = await taskApi.list(token, controller.signal);
        if (controller.signal.aborted) return;
        setTasks(list.map(localTask));
        const id = initialTask.current;
        if (id && list.some((task) => task.task_id === id)) setSelectedId(id);
      } catch (reason) { if (!controller.signal.aborted) setError(message(reason)); }
      finally { if (!controller.signal.aborted) setReady(true); }
```

### `frontpages/src/lib/task-types.ts`

**改动 1：修改前（旧第 50 行）**

```typescript

export interface LocalTask extends TaskResponse {
  messages: TaskMessage[]; // 服务端返回的完整会话记录
  prompt: string; // 当前浏览器提交的原始任务
  draft: string; // SSE 接收的过程文本，最终回答单独保存在 result
  cursor: string; // 已处理事件编号
  interrupts: TaskInterrupt[]; // 当前待处理的人工问题
```

**修改后（当前第 50 行）**

```typescript

export interface LocalTask extends TaskResponse {
  messages: TaskMessage[]; // 服务端返回的完整会话记录
  draft: string; // SSE 接收的过程文本，最终回答单独保存在 result
  cursor: string; // 已处理事件编号
  interrupts: TaskInterrupt[]; // 当前待处理的人工问题
```

**改动 2：修改前（旧第 60 行）**

```typescript

export const statusLabels: Record<TaskStatus, string> = {
  queued: "排队中", running: "执行中", waiting_human: "等待你回复",
  succeeded: "已完成", failed: "执行失败", cancelled: "已取消",
};

export const eventLabels: Record<string, string> = {
  queued: "任务已保存", started: "开始执行任务", waiting_human: "需要你的确认",
  resuming: "继续执行任务", completed: "任务已完成", failed: "执行失败",
  cancelled: "任务已取消", resume_rejected: "回复未被接受", resume_error: "恢复执行异常",
```

**修改后（当前第 59 行）**

```typescript

export const statusLabels: Record<TaskStatus, string> = {
  queued: "排队中", running: "执行中", waiting_human: "等待你回复",
  succeeded: "本轮完成", failed: "执行失败", cancelled: "已取消",
};

export const eventLabels: Record<string, string> = {
  message_received: "补充信息已接收",
  queued: "任务已保存", started: "开始执行任务", waiting_human: "需要你的确认",
  resuming: "继续执行任务", completed: "任务已完成", failed: "执行失败",
  cancelled: "任务已取消", resume_rejected: "回复未被接受", resume_error: "恢复执行异常",
```

### `frontpages/src/components/workspace/workspace.tsx`

**改动 1：修改前（旧第 70 行）**

```tsx
          <button className="nav-item" onClick={() => { setImportOpen(true); setSidebarOpen(false); }}><FolderOpen />打开已有任务<ArrowUpRight className="ml-auto size-3.5" /></button>
        </nav>
        <div className="history-heading"><span>最近会话</span><button aria-label="搜索任务" onClick={() => setSearchOpen((open) => !open)}><Search className="size-3.5" /></button></div>
        {searchOpen && <div className="px-3 pb-2"><Input aria-label="搜索本地任务" className="h-8 text-xs" autoFocus placeholder="搜索任务…" value={search} onChange={(event) => setSearch(event.target.value)} /></div>}
        <div className="history-list">
          {filtered.length ? filtered.map((item) => <button key={item.task_id} className={cn("history-item", item.task_id === workspace.selectedId && "selected")} onClick={() => { workspace.setSelectedId(item.task_id); workspace.setError(""); setSidebarOpen(false); }}><MessageSquare className="size-3.5 shrink-0" /><span className="truncate">{item.title}</span>{item.status === "running" ? <LoaderCircle className="ml-auto size-3 animate-spin shrink-0" /> : item.status === "waiting_human" ? <span className="ml-auto size-1.5 shrink-0 rounded-full bg-amber-500" /> : null}</button>) : <div className="history-empty">{search ? "没有找到相关任务" : "你的下一项任务，从这里开始。"}</div>}
        </div>
```

**修改后（当前第 70 行）**

```tsx
          <button className="nav-item" onClick={() => { setImportOpen(true); setSidebarOpen(false); }}><FolderOpen />打开已有任务<ArrowUpRight className="ml-auto size-3.5" /></button>
        </nav>
        <div className="history-heading"><span>最近会话</span><button aria-label="搜索任务" onClick={() => setSearchOpen((open) => !open)}><Search className="size-3.5" /></button></div>
        {searchOpen && <div className="px-3 pb-2"><Input aria-label="搜索会话" className="h-8 text-xs" autoFocus placeholder="搜索任务…" value={search} onChange={(event) => setSearch(event.target.value)} /></div>}
        <div className="history-list">
          {filtered.length ? filtered.map((item) => <button key={item.task_id} className={cn("history-item", item.task_id === workspace.selectedId && "selected")} onClick={() => { workspace.setSelectedId(item.task_id); workspace.setError(""); setSidebarOpen(false); }}><MessageSquare className="size-3.5 shrink-0" /><span className="truncate">{item.title}</span>{item.status === "running" ? <LoaderCircle className="ml-auto size-3 animate-spin shrink-0" /> : item.status === "waiting_human" ? <span className="ml-auto size-1.5 shrink-0 rounded-full bg-amber-500" /> : null}</button>) : <div className="history-empty">{search ? "没有找到相关任务" : "你的下一项任务，从这里开始。"}</div>}
        </div>
```

**改动 2：修改前（旧第 108 行）**

```tsx
            <div className="composer-area">
              {task && <div className="next-task-note">
                <span className={cn("connection-dot", workspace.connection === "live" && "live")} />
                <span role="status">{isTerminal(task.status) ? "本次任务已结束" : workspace.connection === "live" ? "正在接收回答" : workspace.connection === "retrying" ? "正在恢复连接…" : workspace.connection === "connecting" ? "正在连接任务服务…" : "正在同步任务状态"}</span>
                <Button variant="ghost" size="sm" className="ml-auto" onClick={newTask}><Plus />新建会话</Button>
              </div>}
              {task?.status === "waiting_human" ? (
```

**修改后（当前第 108 行）**

```tsx
            <div className="composer-area">
              {task && <div className="next-task-note">
                <span className={cn("connection-dot", workspace.connection === "live" && "live")} />
                <span role="status">{isTerminal(task.status) ? "本轮执行已结束，可继续发送消息" : workspace.connection === "live" ? "正在接收回答" : workspace.connection === "retrying" ? "正在恢复连接…" : workspace.connection === "connecting" ? "正在连接任务服务…" : "正在同步任务状态"}</span>
                <Button variant="ghost" size="sm" className="ml-auto" onClick={newTask}><Plus />新建会话</Button>
              </div>}
              {task?.status === "waiting_human" ? (
```

**改动 3：修改前（旧第 148 行）**

```tsx
                </div>
              </form>}
              {task && task.status !== "waiting_human" && <p className="mt-2 text-center text-[10px] text-muted-foreground">补充信息保留在同一会话。执行中发送的消息会等待当前轮结束后处理。</p>}
              <p className="composer-disclaimer">AI 帮你推进工作，重要信息与执行结果请核实。</p>
            </div>
          </main>
```

**修改后（当前第 148 行）**

```tsx
                </div>
              </form>}
              {task && task.status !== "waiting_human" && <p className="mt-2 text-center text-[10px] text-muted-foreground">补充信息保留在同一会话。执行中发送的消息会等待当前轮结束后处理。</p>}
              {!workspace.canSend && <p className="mt-2 text-center text-xs text-muted-foreground">当前会话已失败或取消，请新建会话继续。</p>}
              <p className="composer-disclaimer">AI 帮你推进工作，重要信息与执行结果请核实。</p>
            </div>
          </main>
```

### 新增 `migrations/alembic/versions/7e42ab9013cd_add_conversation_title.py`

下面是完整内容，仅准备文件，本轮没有执行。

```python
"""增加会话名称，并回填旧任务中原本保留的输入与回答。"""

from uuid import uuid4

import sqlalchemy as sa
from alembic import op

revision = "7e42ab9013cd"
down_revision = "622b123e76fc"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "agent_tasks",
        sa.Column("title", sa.String(120), server_default="新会话", nullable=False),
    )
    connection = op.get_bind()
    connection.execute(sa.text(
        "UPDATE agent_tasks SET title = COALESCE(NULLIF(left(trim(prompt), 60), ''), '新会话')"
    ))
    # 旧实现只保留首条输入和最后回答；不能据此恢复其他中间消息。
    rows = connection.execute(sa.text(
        "SELECT id, prompt, result, status, created_at, updated_at FROM agent_tasks ORDER BY created_at"
    )).mappings()
    for task in rows:
        has_user = connection.scalar(sa.text(
            "SELECT EXISTS (SELECT 1 FROM agent_task_messages WHERE task_id = :id AND role = 'user')"
        ), {"id": task["id"]})
        if not has_user:
            state = (
                "applied" if task["status"] == "succeeded"
                else "processing" if task["status"] in {"running", "waiting_human"}
                else "pending" if task["status"] == "queued" else "failed"
            )
            connection.execute(sa.text(
                "INSERT INTO agent_task_messages (id, task_id, role, content, state, created_at) "
                "VALUES (:id, :task_id, 'user', :content, :state, :created_at)"
            ), {"id": uuid4(), "task_id": task["id"], "content": task["prompt"],
                "state": state, "created_at": task["created_at"]})
        has_answer = connection.scalar(sa.text(
            "SELECT EXISTS (SELECT 1 FROM agent_task_messages "
            "WHERE task_id = :id AND role = 'assistant' AND content = :content)"
        ), {"id": task["id"], "content": task["result"]})
        if task["result"] and not has_answer:
            connection.execute(sa.text(
                "INSERT INTO agent_task_messages (id, task_id, role, content, state, created_at) "
                "VALUES (:id, :task_id, 'assistant', :content, 'applied', :created_at)"
            ), {"id": uuid4(), "task_id": task["id"], "content": task["result"],
                "created_at": task["updated_at"]})
    # 修正旧版成功或失败任务中遗留的未完成消息状态。
    connection.execute(sa.text(
        "UPDATE agent_task_messages AS m "
        "SET state = CASE WHEN t.status = 'succeeded' THEN 'applied' ELSE 'failed' END "
        "FROM agent_tasks AS t WHERE m.task_id = t.id AND m.role = 'user' "
        "AND m.state IN ('pending', 'processing') "
        "AND t.status IN ('succeeded', 'failed', 'cancelled')"
    ))


def downgrade() -> None:
    # 保留已回填的消息，避免撤销标题字段时删除用户历史。
    op.drop_column("agent_tasks", "title")

```

## 文档同步

frontpages/README.md 与 backend-conversation-guide.md 已改成当前使用说明，旧手动覆盖示例不再适用。

## 实际边界

同一会话消息持久化与多轮执行已接入代码，但没有验证真实环境运行。执行中补充在下一轮处理，不抢占当前调用。长期记忆自动读写、上下文压缩、消息分页、队列故障接管、数据库与 Redis 原子一致性不在本轮范围。
