"""任务会话及其消息的仓储接口。"""

from abc import ABC, abstractmethod
from typing import Literal
from uuid import UUID

from agent_platform.domain.aggregates.agent_task import AgentTask
from agent_platform.domain.types.common import Principal
from agent_platform.domain.types.task_message import TaskMessage


class AgentTaskRepository(ABC):
    @abstractmethod
    async def save(
        self,
        principal: Principal,
        task: AgentTask,
    ) -> None:
        """保存任务会话。"""
        raise NotImplementedError

    @abstractmethod
    async def get(
        self,
        principal: Principal,
        task_id: UUID,
        *,
        for_update: bool = False,
    ) -> AgentTask | None:
        """读取会话，按需锁定记录。"""
        raise NotImplementedError

    @abstractmethod
    async def list_recent(
        self,
        principal: Principal,
        *,
        limit: int = 50,
    ) -> list[AgentTask]:
        """查询当前用户最近的会话。"""
        raise NotImplementedError

    @abstractmethod
    async def messages(
        self,
        principal: Principal,
        task_id: UUID,
    ) -> list[TaskMessage]:
        """按顺序读取会话消息。"""
        raise NotImplementedError

    @abstractmethod
    async def add_message(
        self,
        principal: Principal,
        task_id: UUID,
        message: TaskMessage,
    ) -> None:
        """新增一条消息。"""
        raise NotImplementedError

    @abstractmethod
    async def set_message_state(
        self,
        principal: Principal,
        task_id: UUID,
        ids: list[UUID],
        state: Literal["pending", "processing", "applied", "failed"],
    ) -> None:
        """批量更新指定消息的处理状态。"""
        raise NotImplementedError