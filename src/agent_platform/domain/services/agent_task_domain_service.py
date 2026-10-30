"""任务生命周期的领域服务，不依赖事务组件或 Agent 框架。"""

from uuid import UUID

from agent_platform.domain.aggregates.agent_task import (
    AgentTask,
    AgentTaskStatus,
)
from agent_platform.domain.types.task_message import TaskMessage
from agent_platform.domain.repositories.agent_task_repository import AgentTaskRepository
from agent_platform.domain.types.common import (
    ConflictError,
    NotFoundError,
    Principal,
    TaskContext,
)

class AgentTaskDomainService:
    """组织任务生命周期、归属检查及执行结果的业务处理。"""

    def __init__(self, repository: AgentTaskRepository) -> None:
        self._repository = repository  # 任务领域仓储接口

    async def create(
        self,
        principal: Principal,
        *,
        agent: str,
        prompt: str,
    ) -> AgentTask:
        """创建会话，并保存第一条待处理的用户消息。"""
        task = AgentTask(
            context=TaskContext(
                tenant_id=principal.tenant_id,
                project_id=principal.project_id,
                user_id=principal.user_id,
            ),
            agent=agent,
            title=prompt.strip()[:60],
            prompt=prompt,
        )

        await self._repository.save(principal, task)

        message = TaskMessage(
            role="user",
            content=prompt,
            state="pending",
        )
        await self._repository.add_message(
            principal,
            task.id,
            message,
        )

        return task

    async def get(
        self,
        principal: Principal,
        task_id: UUID,
        *,
        for_update: bool = False,
    ) -> AgentTask:
        """读取会话并检查归属，写入操作可按需锁定记录。"""
        task = await self._repository.get(
            principal,
            task_id,
            for_update=for_update,
        )

        if task is None:
            raise NotFoundError("会话不存在或无权访问")

        task.ensure_owned_by(principal)
        return task

    async def start(self, principal: Principal, task_id: UUID) -> AgentTask:
        """从最新任务构造开始状态，并持久化业务变化。"""
        task = await self.get(principal, task_id)
        started_task = task.start()
        await self._repository.save(principal, started_task)
        return started_task

    async def prepare_resume(self, principal: Principal, task_id: UUID) -> AgentTask:
        """校验恢复条件，回复尚未被执行器接受前不改变状态。"""
        task = await self.get(principal, task_id)
        task.ensure_can_resume()
        return task

    async def finish(
        self,
        principal: Principal,
        task: AgentTask,
        *,
        waiting_for_user: bool,
        output: str | None,
        question: str | None = None,
    ) -> AgentTask:
        """保存本轮回答，并判断是否还有下一轮待处理消息。"""
        task.ensure_owned_by(principal)

        # 重新读取最新状态，避免使用执行开始时的旧对象。
        current = await self.get(
            principal,
            task.id,
            for_update=True,
        )

        if (
            current.status != AgentTaskStatus.RUNNING
            or current.attempt != task.attempt
        ):
            raise ConflictError(
                "当前执行轮次与待保存的结果不一致"
            )

        history = await self._repository.messages(
            principal,
            task.id,
        )

        if waiting_for_user:
            if not question or not question.strip():
                raise ValueError("人工中断缺少问题说明")

            await self._repository.add_message(
                principal,
                task.id,
                TaskMessage(
                    role="assistant",
                    content=question,
                ),
            )

            # 原输入保持 processing，人工回复后仍继续这一轮。
            finished_task = current.wait_for_user()

        else:
            if not output or not output.strip():
                raise ValueError("本轮执行结束，但没有有效回答")

            await self._repository.add_message(
                principal,
                task.id,
                TaskMessage(
                    role="assistant",
                    content=output,
                ),
            )

            processing_ids = [
                message.id
                for message in history
                if message.role == "user"
                and message.state == "processing"
            ]

            await self._repository.set_message_state(
                principal,
                task.id,
                ids=processing_ids,
                state="applied",
            )

            finished_task = current.complete(output)

            has_pending = any(
                message.role == "user"
                and message.state == "pending"
                for message in history
            )

            if has_pending:
                finished_task = finished_task.queue_next()

        await self._repository.save(
            principal,
            finished_task,
        )

        return finished_task

    async def finish_resume(
        self,
        principal: Principal,
        task: AgentTask,
        *,
        waiting_for_user: bool,
        output: str | None,
        question: str | None = None,
    ) -> AgentTask:
        """保存人工恢复后的结果，不再次切换为执行中。"""
        return await self.finish(
            principal,
            task,
            waiting_for_user=waiting_for_user,
            output=output,
            question=question,
        )

    async def fail(
        self,
        principal: Principal,
        task: AgentTask,
        reason: str,
    ) -> AgentTask:
        """记录本轮失败，同时停止当前会话中尚未完成的消息。"""
        task.ensure_owned_by(principal)

        current = await self.get(
            principal,
            task.id,
            for_update=True,
        )

        if (
            current.status != AgentTaskStatus.RUNNING
            or current.attempt != task.attempt
        ):
            raise ConflictError("失败结果不属于当前执行轮次")

        failed_task = current.fail(reason)

        history = await self._repository.messages(
            principal,
            task.id,
        )

        unfinished_ids = [
            message.id
            for message in history
            if message.role == "user"
            and message.state in {"pending", "processing"}
        ]

        await self._repository.set_message_state(
            principal,
            task.id,
            ids=unfinished_ids,
            state="failed",
        )

        await self._repository.save(
            principal,
            failed_task,
        )

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
        principal: Principal,
    ) -> list[AgentTask]:
        """查询当前用户最近的会话。"""
        return await self._repository.list_recent(principal)

    async def messages(
        self,
        principal: Principal,
        task_id: UUID,
    ) -> list[TaskMessage]:
        """确认有权访问会话后，读取消息历史。"""
        await self.get(principal, task_id)

        return await self._repository.messages(
            principal,
            task_id,
        )

    async def claim(
        self,
        principal: Principal,
        task_id: UUID,
    ) -> tuple[AgentTask, tuple[TaskMessage, ...]] | None:
        """领取本轮输入，并在同一事务中标记为处理中。"""
        task = await self.get(
            principal,
            task_id,
            for_update=True,
        )

        # 正在执行、等待人工或已经结束时，不重复启动。
        if task.status != AgentTaskStatus.QUEUED:
            return None

        history = await self._repository.messages(
            principal,
            task_id,
        )

        pending = tuple(
            message
            for message in history
            if message.role == "user"
            and message.state == "pending"
        )

        if not pending:
            return None

        started_task = task.start()

        await self._repository.set_message_state(
            principal,
            task_id,
            ids=[message.id for message in pending],
            state="processing",
        )

        await self._repository.save(
            principal,
            started_task,
        )

        return started_task, pending

    async def append(
        self,
        principal: Principal,
        task_id: UUID,
        message_id: UUID,
        content: str,
    ) -> AgentTask:
        """向同一会话追加用户消息，等待后续执行。"""
        task = await self.get(
            principal,
            task_id,
            for_update=True,
        )

        history = await self._repository.messages(
            principal,
            task_id,
        )

        # 同一消息编号重复提交时，不重复保存。
        existing = next(
            (
                message
                for message in history
                if message.id == message_id
            ),
            None,
        )

        if existing is not None:
            if (
                existing.role != "user"
                or existing.content != content
            ):
                raise ConflictError(
                    "同一个消息编号不能对应不同内容"
                )

            return task

        task.ensure_accepts_messages()

        if not content.strip():
            raise ValueError("消息不能为空白")

        await self._repository.add_message(
            principal,
            task_id,
            TaskMessage(
                id=message_id,
                role="user",
                content=content,
                state="pending",
            ),
        )

        # 空闲的会话重新排队；正在执行的会话保持原状态。
        if task.status == AgentTaskStatus.SUCCEEDED:
            task = task.queue_next()

        await self._repository.save(principal, task)
        return task

    async def start_resume(
        self,
        principal: Principal,
        task_id: UUID,
    ) -> AgentTask:
        """人工恢复开始时，先将会话保存为执行中。"""
        task = await self.get(
            principal,
            task_id,
            for_update=True,
        )

        resumed_task = task.resume()

        await self._repository.save(
            principal,
            resumed_task,
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
