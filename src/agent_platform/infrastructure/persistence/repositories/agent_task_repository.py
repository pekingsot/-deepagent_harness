from datetime import UTC, datetime, timedelta
from typing import Literal
from uuid import UUID

from sqlalchemy import delete, select, update
from sqlalchemy_transactional.asyncio import current_session

from agent_platform.domain.aggregates.agent_task import (
    AgentTask,
    AgentTaskStatus,
)
from agent_platform.domain.repositories.agent_task_repository import (
    AgentTaskRepository,
)
from agent_platform.domain.types.common import (
    ConflictError,
    NotFoundError,
    Principal,
    TaskContext,
)
from agent_platform.domain.types.task_execution import TaskExecution, TaskExecutionStep
from agent_platform.domain.types.task_message import TaskMessage
from agent_platform.infrastructure.persistence.entities.agent_task_executions import (
    AgentTaskExecutionRecord,
)
from agent_platform.infrastructure.persistence.entities.agent_task_messages import (
    AgentTaskMessageRecord,
)
from agent_platform.infrastructure.persistence.entities.agent_tasks import (
    AgentTaskRecord,
)


class PostgresAgentTaskRepository(AgentTaskRepository):
    """通过 SQLAlchemy 保存和读取任务聚合。"""

    async def recovery_candidates(self, *, after_id: UUID | None = None) -> list[AgentTask]:
        records = await current_session().scalars(
            select(AgentTaskRecord)
            .where(
                AgentTaskRecord.status.in_(["running", "cancelling"]),
                AgentTaskRecord.updated_at < datetime.now(UTC) - timedelta(seconds=60),
                AgentTaskRecord.id > after_id if after_id is not None else True,
            )
            .order_by(AgentTaskRecord.id)
            .limit(50)
        )
        return [self._to_domain(record) for record in records]

    async def pending_deletions(self, *, after_id: UUID | None = None) -> list[AgentTask]:
        records = await current_session().scalars(
            select(AgentTaskRecord)
            .where(
                AgentTaskRecord.deletion_requested.is_(True),
                AgentTaskRecord.id > after_id if after_id is not None else True,
            )
            .order_by(AgentTaskRecord.id)
            .limit(50)
        )
        return [self._to_domain(record) for record in records]

    async def delete(self, principal: Principal, task_id: UUID) -> None:
        """通过归属条件删除会话，子记录由外键级联清理。"""
        # 消息外键没有级联删除，需要显式清理；先通过带归属条件的会话确认所有权。
        if await self.get(principal, task_id, for_update=True) is None:
            raise NotFoundError("会话不存在或无权访问")
        await current_session().execute(
            delete(AgentTaskMessageRecord).where(AgentTaskMessageRecord.task_id == task_id)
        )
        await current_session().execute(
            delete(AgentTaskRecord).where(
                AgentTaskRecord.id == task_id, *self._owner_conditions(principal)
            )
        )

    async def executions(self, principal: Principal, task_id: UUID) -> list[TaskExecution]:
        statement = (
            select(AgentTaskExecutionRecord)
            .join(AgentTaskRecord, AgentTaskExecutionRecord.task_id == AgentTaskRecord.id)
            .where(AgentTaskRecord.id == task_id, *self._owner_conditions(principal))
            .order_by(AgentTaskExecutionRecord.attempt.desc())
        )
        records = await current_session().scalars(statement)
        return [
            TaskExecution.model_validate(
                {
                    **{name: getattr(record, name) for name in TaskExecution.model_fields},
                    # 数据库存储字符串和 JSON 列表，在仓储边界还原领域类型。
                    "status": AgentTaskStatus(record.status),
                    "todos": tuple(TaskExecutionStep.model_validate(item) for item in record.todos),
                }
            )
            for record in records
        ]

    async def save_execution(
        self, principal: Principal, task_id: UUID, execution: TaskExecution
    ) -> None:
        if await self.get(principal, task_id) is None:
            raise NotFoundError("会话不存在或无权访问")
        session = current_session()
        record = await session.scalar(
            select(AgentTaskExecutionRecord).where(
                AgentTaskExecutionRecord.task_id == task_id,
                AgentTaskExecutionRecord.attempt == execution.attempt,
            )
        )
        if record is None:
            record = AgentTaskExecutionRecord(task_id=task_id, attempt=execution.attempt)
            session.add(record)
        for name, value in execution.model_dump().items():
            if name == "status":
                value = execution.status.value
            setattr(
                record,
                name,
                [item.model_dump() for item in execution.todos] if name == "todos" else value,
            )
        await session.flush()

    async def save(
        self,
        principal: Principal,
        task: AgentTask,
    ) -> None:
        """在调用方的事务中保存任务，不自行提交事务。"""
        self._check_owner(principal, task.context)

        session = current_session()  # 获取当前事务绑定的 Session
        record = await session.get(AgentTaskRecord, task.id)

        if record is None:
            if task.status != AgentTaskStatus.QUEUED:
                raise ConflictError("新建任务必须处于排队状态")

            record = AgentTaskRecord(
                id=task.id,
                tenant_id=task.context.tenant_id,
                project_id=task.context.project_id,
                user_id=task.context.user_id,
                thread_id=task.context.thread_id,
                trace_id=task.context.trace_id,
                agent=task.agent,
                prompt=task.prompt,
                created_at=task.created_at,
            )
            session.add(record)
        else:
            self._check_owner(principal, record)

            if (
                record.thread_id != task.context.thread_id
                or record.trace_id != task.context.trace_id
                or record.agent != task.agent
                or record.prompt != task.prompt
                or record.created_at != task.created_at
            ):
                raise ConflictError("不允许修改已有任务的固定信息")

        record.title = task.title
        record.deletion_requested = task.deletion_requested
        record.status = task.status.value
        record.result = task.result
        record.error = task.error
        record.execution_id = task.execution_id
        record.attempt = task.attempt
        record.updated_at = task.updated_at

        # 执行写入并检查数据库约束，提交由外层事务负责
        await session.flush()

    async def get(
        self,
        principal: Principal,
        task_id: UUID,
        *,
        for_update: bool = False,
    ) -> AgentTask | None:
        """读取当前身份有权访问的会话，按需锁定记录。"""
        statement = select(AgentTaskRecord).where(
            AgentTaskRecord.id == task_id,
            *self._owner_conditions(principal),
        )

        if for_update:
            statement = statement.with_for_update().execution_options(populate_existing=True)

        session = current_session()
        record = await session.scalar(statement)

        if record is None:
            return None

        return self._to_domain(record)

    @staticmethod
    def _check_owner(
        principal: Principal,
        owner: TaskContext | AgentTaskRecord,
    ) -> None:
        """对任务上下文和数据库记录执行相同的归属检查。"""
        if (
            principal.tenant_id != owner.tenant_id
            or principal.project_id != owner.project_id
            or principal.user_id != owner.user_id
        ):
            raise NotFoundError("任务不存在或无权访问")

    @staticmethod
    def _to_domain(record: AgentTaskRecord) -> AgentTask:
        """将数据库记录还原为经过领域校验的任务聚合。"""
        return AgentTask(
            context=TaskContext(
                tenant_id=record.tenant_id,
                project_id=record.project_id,
                user_id=record.user_id,
                task_id=record.id,
                thread_id=record.thread_id,
                trace_id=record.trace_id,
            ),
            title=record.title,
            deletion_requested=record.deletion_requested,
            agent=record.agent,
            prompt=record.prompt,
            status=AgentTaskStatus(record.status),
            result=record.result,
            error=record.error,
            execution_id=record.execution_id,
            attempt=record.attempt,
            created_at=record.created_at,
            updated_at=record.updated_at,
        )

    @staticmethod
    def _owner_conditions(principal: Principal):
        """生成按租户、项目和用户过滤的查询条件。"""
        return (
            AgentTaskRecord.tenant_id == principal.tenant_id,
            AgentTaskRecord.project_id == principal.project_id,
            AgentTaskRecord.user_id == principal.user_id,
        )

    async def list_recent(
        self,
        principal: Principal,
        *,
        limit: int = 50,
    ) -> list[AgentTask]:
        """读取当前用户最近更新的会话。"""
        statement = (
            select(AgentTaskRecord)
            .where(
                *self._owner_conditions(principal), AgentTaskRecord.deletion_requested.is_(False)
            )
            .order_by(
                AgentTaskRecord.updated_at.desc(),
                AgentTaskRecord.id,
            )
            .limit(limit)
        )

        session = current_session()
        records = await session.scalars(statement)

        return [self._to_domain(record) for record in records]

    async def messages(
        self,
        principal: Principal,
        task_id: UUID,
    ) -> list[TaskMessage]:
        """按数据库生成的顺序读取会话消息。"""
        statement = (
            select(AgentTaskMessageRecord)
            .join(
                AgentTaskRecord,
                AgentTaskMessageRecord.task_id == AgentTaskRecord.id,
            )
            .where(
                AgentTaskRecord.id == task_id,
                *self._owner_conditions(principal),
            )
            .order_by(AgentTaskMessageRecord.position)
        )

        session = current_session()
        records = await session.scalars(statement)

        return [
            TaskMessage.model_validate(
                {
                    "id": record.id,
                    "role": record.role,
                    "content": record.content,
                    "state": record.state,
                    "position": record.position,
                    "created_at": record.created_at,
                }
            )
            for record in records
        ]

    async def add_message(
        self,
        principal: Principal,
        task_id: UUID,
        message: TaskMessage,
    ) -> None:
        """新增消息，不在仓储内部提交事务。"""
        task = await self.get(principal, task_id)

        if task is None:
            raise NotFoundError("会话不存在或无权访问")

        record = AgentTaskMessageRecord(
            id=message.id,
            task_id=task_id,
            role=message.role,
            content=message.content,
            state=message.state,
            created_at=message.created_at,
        )

        session = current_session()
        session.add(record)

        # position 由数据库生成，不使用领域对象入库前的默认值。
        await session.flush()

    async def set_message_state(
        self,
        principal: Principal,
        task_id: UUID,
        ids: list[UUID],
        state: Literal["pending", "processing", "applied", "failed", "cancelled"],
    ) -> None:
        """只更新当前身份有权访问的会话消息。"""
        if not ids:
            return

        authorized_task = select(AgentTaskRecord.id).where(
            AgentTaskRecord.id == task_id,
            *self._owner_conditions(principal),
        )

        statement = (
            update(AgentTaskMessageRecord)
            .where(
                AgentTaskMessageRecord.task_id.in_(authorized_task),
                AgentTaskMessageRecord.id.in_(ids),
            )
            .values(state=state)
        )

        session = current_session()
        await session.execute(statement)
