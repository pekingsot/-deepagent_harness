"""任务应用服务，协调领域能力、事务、队列和执行器。"""

import logging
from uuid import UUID
from agent_platform.application.dto.agent_task_dto import (
    InvalidHumanReplyError, TextReply, UserInputPayload,
)
from agent_platform.domain.aggregates.agent_task import AgentTaskStatus
from agent_platform.domain.types.task_message import TaskMessage
from pydantic import JsonValue
from sqlalchemy_transactional.asyncio import transactional
from sqlalchemy_transactional.common import Propagation

from agent_platform.application.dto.agent_task_dto import (
    AgentTaskExecutionResult,
    CreateAgentTask,
    ResumeAgentTask,
    TaskPlanItem,
    TaskActivity,
)
from agent_platform.application.interfaces.agent_task_runtime import AgentTaskRuntime
from agent_platform.application.interfaces.job_queue import JobQueue
from agent_platform.application.interfaces.task_events import TaskEvents
from agent_platform.domain.aggregates.agent_task import AgentTask
from agent_platform.domain.services.agent_task_domain_service import AgentTaskDomainService
from agent_platform.domain.types.common import Principal

logger = logging.getLogger(__name__)


class AgentTaskApplicationService:
    """协调任务用例，业务条件和状态变化交给领域层。"""

    def __init__(
            self,
            *,
            tasks: AgentTaskDomainService,
            queue: JobQueue,
            runtime: AgentTaskRuntime,
            events: TaskEvents,
    ) -> None:
        self._tasks = tasks  # 任务领域服务
        self._queue = queue  # 任务投递接口
        self._runtime = runtime  # Agent 执行接口
        self._events = events  # 执行事件接口，供 SSE 独立读取

    async def create(self, principal: Principal, command: CreateAgentTask) -> AgentTask:
        """作为顶层用例先提交任务，再安排队列执行。"""
        task = await self._create_task(principal, command)
        await self._publish(task, "queued", {"status": task.status.value})
        await self._queue.enqueue(task.context)
        return task

    @transactional(Propagation.REQUIRED)
    async def get(self, principal: Principal, task_id: UUID) -> AgentTask:
        """为独立查询提供短事务，由领域服务读取和校验任务。"""
        return await self._tasks.get(principal, task_id)

    async def execute(
            self,
            principal: Principal,
            task_id: UUID,
    ) -> AgentTask:
        """领取本轮消息，在数据库事务之外执行 Agent。"""
        claimed = await self._claim_task(principal, task_id)

        # 重复唤醒或当前没有可领取的消息时，不调用模型。
        if claimed is None:
            return await self.get(principal, task_id)

        task, messages = claimed

        await self._publish(task, "started", {})

        async def on_text(text: str) -> None:
            await self._publish(
                task,
                "text_delta",
                {"text": text},
            )

        async def on_plan(
                todos: tuple[TaskPlanItem, ...],
        ) -> None:
            await self._publish(
                task,
                "plan_updated",
                {
                    "todos": [
                        item.model_dump(mode="json")
                        for item in todos
                    ],
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
                on_text=on_text,
                on_plan=on_plan,
                on_activity=on_activity,
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
            await self._queue.enqueue(task.context)

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
        await self._queue.enqueue(task.context, resume=command)
        return task

    async def resume(
            self, principal: Principal, task_id: UUID, command: ResumeAgentTask,
    ) -> AgentTask:
        """先提交恢复状态，再在事务之外继续执行 Agent。"""
        task = await self._start_resume(principal, task_id)
        await self._publish(task, "resuming", {})

        async def on_text(text: str) -> None:
            await self._publish(task, "text_delta", {"text": text})

        async def on_plan(
                todos: tuple[TaskPlanItem, ...],
        ) -> None:
            await self._publish(
                task,
                "plan_updated",
                {
                    "todos": [
                        item.model_dump(mode="json")
                        for item in todos
                    ],
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
            result = await self._runtime.resume(task, command, on_text=on_text, on_plan=on_plan,
                                                on_activity=on_activity)
        except InvalidHumanReplyError:
            task = await self._reject_resume(principal, task)
            await self._publish(task, "resume_rejected", {"message": "回复不符合当前中断要求，请重新填写"})
            raise
        except Exception as e:
            logger.exception(f"恢复执行失败，task_id=%s,error={str(e)}", task.id)
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
        """先提交取消结果，再向前端发布事件。"""
        task = await self._cancel_task(principal, task_id)
        await self._publish(task, "cancelled", {"status": task.status.value})
        return task

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
        if result.status == "waiting":
            await self._publish(
                task,
                "waiting_human",
                {
                    "interrupts": [
                        item.model_dump(mode="json")
                        for item in result.interrupts
                    ],
                },
            )
        else:
            await self._publish(
                task,
                "completed",
                {"output": result.output},
            )

    async def _publish(
            self,
            task: AgentTask,
            event: str,
            data: dict[str, JsonValue],
    ) -> None:
        """每条事件携带轮次，避免旧轮次内容覆盖新轮次。"""
        try:
            await self._events.publish(
                task.context,
                event,
                {
                    **data,
                    "attempt": task.attempt,
                    "status": task.status.value,
                },
            )
        except Exception:
            logger.exception(
                "任务事件写入失败，task_id=%s，event=%s",
                task.id,
                event,
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
        questions: list[str] = []

        for interrupt in result.interrupts:
            payload = interrupt.payload

            if isinstance(payload, UserInputPayload):
                questions.append(payload.question)
            else:
                questions.append(
                    f"请确认是否允许执行工具：{payload.tool_name}"
                )

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
        """在独立于执行器调用的短事务中记录业务失败。"""
        return await self._tasks.fail(principal, task, reason)

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

        await self._queue.enqueue(task.context)

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
