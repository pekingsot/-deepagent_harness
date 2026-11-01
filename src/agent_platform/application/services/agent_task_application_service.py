"""任务应用服务，协调领域能力、事务、队列和执行器。"""

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from uuid import UUID

from pydantic import JsonValue
from sqlalchemy_transactional.asyncio import transactional
from sqlalchemy_transactional.common import Propagation

from agent_platform.application.dto.agent_task_dto import (
    AgentTaskExecutionResult,
    CreateAgentTask,
    InvalidHumanReplyError,
    ResumeAgentTask,
    TaskActivity,
    TaskPlanItem,
    TextReply,
    UserInputPayload,
)
from agent_platform.application.dto.task_event_types import STREAMING_EVENTS
from agent_platform.application.interfaces.agent_task_runtime import AgentTaskRuntime
from agent_platform.application.interfaces.job_queue import JobQueue
from agent_platform.application.interfaces.task_data_cleaner import TaskDataCleaner
from agent_platform.application.interfaces.task_events import TaskEvents
from agent_platform.application.interfaces.task_execution_guard import TaskExecutionGuard
from agent_platform.domain.aggregates.agent_task import AgentTask, AgentTaskStatus
from agent_platform.domain.services.agent_task_domain_service import AgentTaskDomainService
from agent_platform.domain.types.common import ConflictError, NotFoundError, Principal, TaskContext
from agent_platform.domain.types.task_execution import TaskExecution, TaskExecutionStep
from agent_platform.domain.types.task_message import TaskMessage

logger = logging.getLogger(__name__)


@dataclass
class _TaskExecution:
    task: AgentTask | None = None  # 当前协程实际领取的轮次，不与其他任务共享
    partial_output: list[str] = field(default_factory=list)  # 已接收的本轮文本


class AgentTaskApplicationService:
    """协调任务用例，业务条件和状态变化交给领域层。"""

    def __init__(
        self,
        *,
        tasks: AgentTaskDomainService,
        queue: JobQueue,
        runtime: AgentTaskRuntime,
        events: TaskEvents,
        cleaner: TaskDataCleaner | None = None,
        execution_guard: TaskExecutionGuard,
    ) -> None:
        self._recovery_cursor: UUID | None = None
        self._deletion_cursor: UUID | None = None
        self._execution_guard = execution_guard  # 执行和异常补偿共用的互斥凭证
        self._cleaner = cleaner  # 永久删除时清理外部执行数据，业务层不依赖其具体存储
        self._tasks = tasks  # 任务领域服务
        self._queue = queue  # 任务投递接口
        self._runtime = runtime  # Agent 执行接口
        self._events = events  # 执行事件接口，供 SSE 独立读取

    async def request_deletion(self, principal: Principal, task_id: UUID) -> None:
        """快速确认删除已持久化，清理流程独立重试。"""
        if self._cleaner is None:
            raise RuntimeError("未配置会话数据清理器")
        await self._request_deletion(principal, task_id)

    @transactional(Propagation.REQUIRED)
    async def _pending_deletions(self) -> list[AgentTask]:
        return await self._tasks.pending_deletions(after_id=self._deletion_cursor)

    @transactional(Propagation.REQUIRED)
    async def _recovery_candidates(self) -> list[AgentTask]:
        return await self._tasks.recovery_candidates(after_id=self._recovery_cursor)

    async def recover_orphans(self) -> None:
        candidates = await self._recovery_candidates()
        self._recovery_cursor = candidates[-1].id if len(candidates) == 50 else None
        for task in candidates:
            try:
                await self.reconcile(task)
            except NotFoundError:
                pass
            except Exception:
                logger.exception("任务状态补偿失败，将重试，task_id=%s", task.id)

    async def cleanup_pending_deletions(self) -> None:
        """跳过尚未退出的执行；单个故障不会阻断其他会话清理。"""
        candidates = await self._pending_deletions()
        self._deletion_cursor = candidates[-1].id if len(candidates) == 50 else None
        for task in candidates:
            try:
                await self.reconcile(task)
                task = await self._read_task(task.context, task.id)
                if task.status in {AgentTaskStatus.RUNNING, AgentTaskStatus.CANCELLING}:
                    continue
                await self._purge_task(task.context, task.id)
            except NotFoundError:
                pass
            except Exception:
                logger.exception("后台删除会话失败，将重试，task_id=%s", task.id)

    async def delete(self, principal: Principal, task_id: UUID) -> None:
        """停止并永久删除；未确认停止或清理失败时保留删除意图供重试。"""
        if self._cleaner is None:
            raise RuntimeError("未配置会话数据清理器")
        await self._request_deletion(principal, task_id)
        for _ in range(20):
            task = await self.get(principal, task_id)
            if task.status not in {AgentTaskStatus.RUNNING, AgentTaskStatus.CANCELLING}:
                break
            await asyncio.sleep(0.25)
        else:
            raise ConflictError("正在等待执行退出，请稍后再次点击永久删除")
        await self._purge_task(principal, task_id)

    @transactional(Propagation.REQUIRED)
    async def _request_deletion(self, principal: Principal, task_id: UUID) -> AgentTask:
        return await self._tasks.request_deletion(principal, task_id)

    async def _purge_task(self, principal: Principal, task_id: UUID) -> None:
        """短事务验证、事务外清理、短事务删除；外部失败保留删除意图。"""
        async with self._execution_guard.acquire(task_id) as owned:
            if owned:
                await self._purge_owned(principal, task_id)

    async def _purge_owned(self, principal: Principal, task_id: UUID) -> None:
        task = await self._prepare_purge(principal, task_id)
        if self._cleaner is None:
            raise RuntimeError("Task data cleaner is required")
        async with asyncio.timeout(8):
            await self._cleaner.cleanup(task)
        await self._delete_task(principal, task)

    @transactional(Propagation.REQUIRED)
    async def _prepare_purge(self, principal: Principal, task_id: UUID) -> AgentTask:
        task = await self._tasks.get(principal, task_id)
        task.ensure_deletable()
        return task

    @transactional(Propagation.REQUIRED)
    async def _delete_task(self, principal: Principal, expected: AgentTask) -> None:
        current = await self._tasks.get(principal, expected.id, for_update=True)
        current.ensure_current_execution(expected)
        await self._tasks.delete(principal, expected.id)

    @transactional(Propagation.REQUIRED)
    async def _enqueue(
        self,
        context: TaskContext,
        *,
        resume: ResumeAgentTask | None = None,
    ) -> None:
        """投递前锁定归属记录；删除中的旧请求不得再产生队列消息。"""
        try:
            task = await self._tasks.get(context, context.task_id, for_update=True)
        except NotFoundError:
            return
        if not task.deletion_requested:
            await self._queue.enqueue(context, resume=resume)

    async def create(self, principal: Principal, command: CreateAgentTask) -> AgentTask:
        """作为顶层用例先提交任务，再安排队列执行。"""
        task = await self._create_task(principal, command)
        await self._publish(task, "queued", {"status": task.status.value})
        await self._enqueue(task.context)
        return task

    async def execution_state(self, principal: Principal, task_id: UUID) -> AgentTask:
        """执行者自身只检查取消状态，不重复争抢补偿锁。"""
        return await self._read_task(principal, task_id)

    async def get(self, principal: Principal, task_id: UUID) -> AgentTask:
        """普通查询只读，打开会话时显式调用 open_task。"""
        return await self._read_task(principal, task_id)

    async def open_task(self, principal: Principal, task_id: UUID) -> AgentTask:
        task = await self._read_task(principal, task_id)
        if self._needs_recovery(task):
            await self.reconcile(task)
            return await self._read_task(principal, task_id)
        return task

    @staticmethod
    def _needs_recovery(task: AgentTask) -> bool:
        return task.status in {AgentTaskStatus.RUNNING, AgentTaskStatus.CANCELLING} and (
            datetime.now(UTC) - task.updated_at > timedelta(seconds=60)
        )

    async def reconcile(self, task: AgentTask) -> None:
        """仅修复超过宽限期且已无执行权持有者的任务。"""
        if not self._needs_recovery(task):
            return
        async with self._execution_guard.acquire(task.id) as owned:
            if owned:
                repaired = await self._repair_orphan(task)
                await self._publish(repaired, repaired.status.value, {})

    @transactional(Propagation.REQUIRED)
    async def _repair_orphan(self, expected: AgentTask) -> AgentTask:
        current = await self._tasks.get(expected.context, expected.id, for_update=True)
        if not self._needs_recovery(current):
            return current
        current.ensure_current_execution(expected)
        return await self._tasks.recover_interrupted(expected.context, expected)

    @transactional(Propagation.REQUIRED)
    async def _read_task(self, principal: Principal, task_id: UUID) -> AgentTask:
        """为独立查询提供短事务，由领域服务读取和校验任务。"""
        return await self._tasks.get(principal, task_id)

    async def execute(
        self,
        principal: Principal,
        task_id: UUID,
    ) -> AgentTask:
        """执行任务，并统一处理整段调用中的用户取消。"""
        return await self._run_cancellable(principal, task_id)

    async def _run_cancellable(
        self,
        principal: Principal,
        task_id: UUID,
        command: ResumeAgentTask | None = None,
    ) -> AgentTask:
        async with self._execution_guard.acquire(task_id) as owned:
            if not owned:
                raise ConflictError("任务已有执行者，不能重复执行")
            return await self._run_owned(principal, task_id, command)

    async def _run_owned(
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

    async def _execute(
        self,
        principal: Principal,
        task_id: UUID,
        execution: _TaskExecution,
    ) -> AgentTask:
        """领取本轮消息，在数据库事务之外执行 Agent。"""
        claimed = await self._claim_task(principal, task_id)

        # 重复唤醒或当前没有可领取的消息时，不调用模型。
        if claimed is None:
            return await self.get(principal, task_id)

        task, messages = claimed
        execution.task = task

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

        await self._publish(task, "started", {})
        partial_output = execution.partial_output

        async def on_text(text: str) -> None:
            partial_output.append(text)
            await self._publish(
                task,
                "text_delta",
                {"text": text},
            )

        async def on_title(title: str) -> None:
            record = await self._update_execution(principal, task, title=title)
            if record:
                await self._publish(
                    task,
                    "execution_titled",
                    {"title": record.title, "execution": record.model_dump(mode="json")},
                )

        async def on_plan(
            todos: tuple[TaskPlanItem, ...],
        ) -> None:
            record = await self._update_execution(principal, task, todos=todos)
            if record is None:
                return
            await self._publish(
                task,
                "plan_updated",
                {
                    "todos": [item.model_dump(mode="json") for item in todos],
                    **({"execution": record.model_dump(mode="json")} if record else {}),
                },
            )

        async def on_activity(activity: TaskActivity) -> None:
            await self._publish(
                task,
                activity.event,
                {
                    "tool_name": activity.tool_name,
                    "call_id": activity.call_id,
                    "subagent": activity.subagent,
                    "file_path": activity.file_path,
                    "elapsed_ms": activity.elapsed_ms,
                },
            )

        try:
            result = await self._runtime.execute(
                task,
                messages=messages,
                restart_after_interruption=restart_after_interruption,
                on_text=on_text,
                on_plan=on_plan,
                on_activity=on_activity,
                on_title=on_title,
            )
        except Exception:
            logger.exception(
                "Agent 执行失败，task_id=%s",
                task.id,
            )

            task = await self._fail_task(
                principal,
                task,
                "Agent 执行失败，请联系管理员查看日志",
                partial_output="".join(partial_output),
            )

            await self._publish(
                task,
                "failed",
                {"error": task.error},
            )
            return task

        try:
            task = await self._finish_task(
                principal,
                task,
                result,
            )
        except ValueError as exc:
            task = await self._fail_task(
                principal,
                task,
                str(exc),
                partial_output="".join(partial_output),
            )

            await self._publish(
                task,
                "failed",
                {"error": task.error},
            )
            return task

        await self._publish_result(task, result)

        # 当前轮完成后，如果还有补充消息，唤醒下一轮执行。
        if task.status == AgentTaskStatus.QUEUED:
            await self._enqueue(task.context)

        return task

    async def get_execution_state(
        self, principal: Principal, task_id: UUID
    ) -> AgentTaskExecutionResult:
        """先完成领域访问检查，再读取执行器的技术状态。"""
        task = await self.get(principal, task_id)
        return await self._runtime.get_state(task)

    async def request_resume(
        self, principal: Principal, task_id: UUID, command: ResumeAgentTask
    ) -> AgentTask:
        """HTTP 只校验并投递人工回复，实际恢复仍交给 Worker。"""
        task = await self._prepare_resume(principal, task_id)
        await self._enqueue(task.context, resume=command)
        return task

    async def resume(
        self,
        principal: Principal,
        task_id: UUID,
        command: ResumeAgentTask,
    ) -> AgentTask:
        """人工恢复也使用同一取消收尾流程。"""
        return await self._run_cancellable(principal, task_id, command)

    async def _resume(
        self,
        principal: Principal,
        task_id: UUID,
        command: ResumeAgentTask,
        execution: _TaskExecution,
    ) -> AgentTask:
        """先提交恢复状态，再在事务之外继续执行 Agent。"""
        task = await self._start_resume(principal, task_id)
        execution.task = task
        await self._publish(task, "resuming", {})
        partial_output = execution.partial_output

        async def on_text(text: str) -> None:
            partial_output.append(text)
            await self._publish(task, "text_delta", {"text": text})

        async def on_title(title: str) -> None:
            record = await self._update_execution(principal, task, title=title)
            if record:
                await self._publish(
                    task,
                    "execution_titled",
                    {"title": record.title, "execution": record.model_dump(mode="json")},
                )

        async def on_plan(
            todos: tuple[TaskPlanItem, ...],
        ) -> None:
            record = await self._update_execution(principal, task, todos=todos)
            if record is None:
                return
            await self._publish(
                task,
                "plan_updated",
                {
                    "todos": [item.model_dump(mode="json") for item in todos],
                    **({"execution": record.model_dump(mode="json")} if record else {}),
                },
            )

        async def on_activity(activity: TaskActivity) -> None:
            await self._publish(
                task,
                activity.event,
                {
                    "tool_name": activity.tool_name,
                    "call_id": activity.call_id,
                    "subagent": activity.subagent,
                    "file_path": activity.file_path,
                    "elapsed_ms": activity.elapsed_ms,
                },
            )

        try:
            result = await self._runtime.resume(
                task,
                command,
                on_text=on_text,
                on_plan=on_plan,
                on_activity=on_activity,
                on_title=on_title,
            )
        except InvalidHumanReplyError:
            task = await self._reject_resume(principal, task)
            if task.status == AgentTaskStatus.CANCELLED:
                await self._publish(task, "cancelled", {})
                return task
            await self._publish(
                task, "resume_rejected", {"message": "回复不符合当前中断要求，请重新填写"}
            )
            raise
        except Exception as e:
            logger.exception(f"恢复执行失败，task_id=%s,error={str(e)}", task.id)
            task = await self._fail_task(
                principal,
                task,
                "恢复执行失败，请联系管理员查看日志",
                partial_output="".join(partial_output),
            )
            await self._publish(task, "failed", {"error": task.error})
            return task

        try:
            task = await self._finish_resume(principal, task, command, result)
        except ValueError as exc:
            task = await self._fail_task(
                principal,
                task,
                str(exc),
                partial_output="".join(partial_output),
            )
            await self._publish(task, "failed", {"error": task.error})
            return task
        await self._publish_result(task, result)
        if task.status == AgentTaskStatus.QUEUED:
            await self._enqueue(task.context)
        return task

    async def cancel(self, principal: Principal, task_id: UUID) -> AgentTask:
        """提交取消意图或立即取消结果，再向前端发布对应事件。"""
        task = await self._cancel_task(principal, task_id)
        await self._publish(task, task.status.value, {"status": task.status.value})
        return task

    async def complete_cancellation(
        self,
        principal: Principal,
        task_id: UUID,
        *,
        attempt: int,
        execution_id: UUID | None,
        partial_output: str | None = None,
    ) -> AgentTask:
        """执行协程退出后确认取消，提交业务状态后发布最终事件。"""
        task = await self._confirm_cancellation(
            principal,
            task_id,
            attempt=attempt,
            execution_id=execution_id,
            partial_output=partial_output,
        )
        await self._publish(task, "cancelled", {})
        return task

    @transactional(Propagation.REQUIRED)
    async def _confirm_cancellation(
        self,
        principal: Principal,
        task_id: UUID,
        *,
        attempt: int,
        execution_id: UUID | None,
        partial_output: str | None = None,
    ) -> AgentTask:
        """取消确认与消息收尾使用同一短事务。"""
        return await self._tasks.confirm_cancellation(
            principal,
            task_id,
            attempt=attempt,
            execution_id=execution_id,
            partial_output=partial_output,
        )

    async def _cancel_interrupted_execution(
        self,
        principal: Principal,
        task: AgentTask,
        partial_output: list[str],
    ) -> AgentTask | None:
        """只消费用户取消信号，服务关闭导致的取消继续向上传播。"""
        current = await self.get(principal, task.id)
        if (
            current.attempt != task.attempt
            or current.execution_id != task.execution_id
            or current.status
            not in {
                AgentTaskStatus.CANCELLING,
                AgentTaskStatus.CANCELLED,
            }
        ):
            return None
        return await self.complete_cancellation(
            principal,
            task.id,
            attempt=task.attempt,
            execution_id=task.execution_id,
            partial_output="".join(partial_output),
        )

    @transactional(Propagation.REQUIRED)
    async def _cancel_task(self, principal: Principal, task_id: UUID) -> AgentTask:
        """取消操作的读取、领域判断和保存属于同一个事务。"""
        return await self._tasks.cancel(principal, task_id)

    async def _publish_result(
        self,
        task: AgentTask,
        result: AgentTaskExecutionResult,
    ) -> None:
        """发布本轮结果，供前端更新展示。"""
        if task.status == AgentTaskStatus.CANCELLED:
            await self._publish(task, "cancelled", {})
        elif result.status == "waiting":
            await self._publish(
                task,
                "waiting_human",
                {
                    "interrupts": [item.model_dump(mode="json") for item in result.interrupts],
                },
            )
        else:
            await self._publish(
                task,
                "completed",
                {"output": result.output},
            )

    @transactional(Propagation.REQUIRED)
    async def _prepare_event(self, task: AgentTask) -> AgentTask | None:
        """仅状态事件读取业务行；流式片段由事件存储校验执行标识。"""
        try:
            current = await self._tasks.get(task.context, task.id, for_update=True)
        except NotFoundError:
            return None
        if current.deletion_requested:
            return None
        if (
            current.execution_id != task.execution_id
            or current.attempt != task.attempt
            or current.status != task.status
        ):
            return None
        await self._events.initialize(current.context)
        await self._events.activate(
            current.context,
            str(current.execution_id or ""),
            active=current.status == AgentTaskStatus.RUNNING,
        )
        return current

    async def _publish(
        self,
        task: AgentTask,
        event: str,
        data: dict[str, JsonValue],
    ) -> None:
        try:
            if event not in STREAMING_EVENTS:
                current = await self._prepare_event(task)
                if current is None:
                    return
                task = current
            if task.status == AgentTaskStatus.CANCELLED and event == "failed":
                event, data = "cancelled", {}
            await self._events.publish(
                task.context,
                event,
                {
                    **data,
                    "attempt": task.attempt,
                    "execution_id": str(task.execution_id or ""),
                    "status": task.status.value,
                    "updated_at": task.updated_at.isoformat(),
                },
            )
        except Exception:
            logger.exception("Task event publish failed: task_id=%s event=%s", task.id, event)

    @transactional(Propagation.REQUIRED)
    async def executions(self, principal: Principal, task_id: UUID) -> list[TaskExecution]:
        """查询该会话各轮执行，身份与轮次规则交给领域服务。"""
        return await self._tasks.executions(principal, task_id)

    @transactional(Propagation.REQUIRED)
    async def _update_execution(
        self,
        principal: Principal,
        task: AgentTask,
        *,
        title: str | None = None,
        todos: tuple[TaskPlanItem, ...] | None = None,
    ) -> TaskExecution | None:
        return await self._tasks.update_execution(
            principal,
            task,
            title=title,
            todos=tuple(TaskExecutionStep.model_validate(item.model_dump()) for item in todos)
            if todos is not None
            else None,
        )

    @transactional(Propagation.REQUIRED)
    async def _create_task(self, principal: Principal, command: CreateAgentTask) -> AgentTask:
        """在短事务中创建任务。"""
        return await self._tasks.create(principal, agent=command.agent, prompt=command.prompt)

    @transactional(Propagation.REQUIRED)
    async def _claim_task(
        self,
        principal: Principal,
        task_id: UUID,
    ) -> tuple[AgentTask, tuple[TaskMessage, ...]] | None:
        """在短事务内领取消息并更新执行状态。"""
        return await self._tasks.claim(
            principal,
            task_id,
        )

    @transactional(Propagation.REQUIRED)
    async def _prepare_resume(self, principal: Principal, task_id: UUID) -> AgentTask:
        """在短事务中检查人工恢复条件。"""
        return await self._tasks.prepare_resume(principal, task_id)

    @transactional(Propagation.REQUIRED)
    async def _finish_task(
        self,
        principal: Principal,
        task: AgentTask,
        result: AgentTaskExecutionResult,
    ) -> AgentTask:
        """将 Runtime 结果交给领域层保存。"""
        await self._update_execution(principal, task, title=result.title, todos=result.todos)
        questions: list[str] = []

        for interrupt in result.interrupts:
            payload = interrupt.payload

            if isinstance(payload, UserInputPayload):
                questions.append(payload.question)
            else:
                questions.append(f"请确认是否允许执行工具：{payload.tool_name}")

        question = "\n\n".join(questions) or None

        return await self._tasks.finish(
            principal,
            task,
            waiting_for_user=result.status == "waiting",
            output=result.output,
            question=question,
        )

    @transactional(Propagation.REQUIRED)
    async def _finish_resume(
        self,
        principal: Principal,
        task: AgentTask,
        command: ResumeAgentTask,
        result: AgentTaskExecutionResult,
    ) -> AgentTask:
        """人工回复与恢复结果在同一短事务中保存。"""
        replies: list[str] = []
        for reply in command.answers.values():
            if isinstance(reply, TextReply):
                replies.append(reply.answer)
            else:
                replies.append("允许工具执行" if reply.approved else "拒绝工具执行")
        await self._tasks.record_reply(principal, task, "\n\n".join(replies))
        return await self._finish_task(principal, task, result)

    @transactional(Propagation.REQUIRED)
    async def _fail_task(
        self,
        principal: Principal,
        task: AgentTask,
        reason: str,
        *,
        partial_output: str | None = None,
    ) -> AgentTask:
        """在独立于执行器调用的短事务中记录业务失败。"""
        return await self._tasks.fail(principal, task, reason, partial_output=partial_output)

    async def send_message(
        self,
        principal: Principal,
        task_id: UUID,
        message_id: UUID,
        content: str,
    ) -> AgentTask:
        """先提交补充消息，再通知 Worker 处理。"""
        task = await self._append_message(
            principal,
            task_id,
            message_id,
            content,
        )

        await self._enqueue(task.context)

        await self._publish(
            task,
            "message_received",
            {},
        )

        return task

    @transactional(Propagation.REQUIRED)
    async def _append_message(
        self,
        principal: Principal,
        task_id: UUID,
        message_id: UUID,
        content: str,
    ) -> AgentTask:
        """消息写入及会话状态变化属于同一个事务。"""
        return await self._tasks.append(
            principal,
            task_id,
            message_id,
            content,
        )

    @transactional(Propagation.REQUIRED)
    async def list_recent(
        self,
        principal: Principal,
    ) -> list[AgentTask]:
        """读取当前用户最近的会话。"""
        return await self._tasks.list_recent(principal)

    @transactional(Propagation.REQUIRED)
    async def messages(
        self,
        principal: Principal,
        task_id: UUID,
    ) -> list[TaskMessage]:
        """读取当前会话的消息历史。"""
        return await self._tasks.messages(
            principal,
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
