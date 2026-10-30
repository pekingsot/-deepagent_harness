from abc import ABC, abstractmethod

from agent_platform.application.dto.agent_task_dto import ResumeAgentTask, TaskJob

from agent_platform.domain.types.common import TaskContext


class JobQueue(ABC):
    @abstractmethod
    async def enqueue(
        self, context: TaskContext, *, resume: ResumeAgentTask | None = None
    ) -> str:
        """将任务放入队列，返回消息编号。"""
        raise NotImplementedError

    @abstractmethod
    async def receive(
        self,
        *,
        timeout_seconds: int = 1,
    ) -> tuple[str, TaskJob] | None:
        """领取一条消息；超时返回 None，领取不代表确认完成。"""
        raise NotImplementedError

    @abstractmethod
    async def acknowledge(self, message_id: str) -> None:
        """确认消息已处理完成。"""
        raise NotImplementedError

