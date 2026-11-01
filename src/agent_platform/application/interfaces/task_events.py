"""任务事件的发布和读取能力，与具体消息存储解耦。"""

from abc import ABC, abstractmethod

from pydantic import JsonValue

from agent_platform.application.dto.task_event_dto import TaskEvent
from agent_platform.domain.types.common import TaskContext


class TaskEvents(ABC):
    @abstractmethod
    async def initialize(self, context: TaskContext) -> None:
        """仅在创建会话时建立事件流，删除后的发布不得重建事件流。"""
        raise NotImplementedError

    @abstractmethod
    async def activate(self, context: TaskContext, execution_id: str, *, active: bool) -> None:
        """切换当前执行标识；关闭后拒绝该执行的流式回调。"""
        raise NotImplementedError

    @abstractmethod
    async def publish(self, context: TaskContext, event: str, data: dict[str, JsonValue]) -> str:
        """追加事件并返回事件编号。"""
        raise NotImplementedError

    @abstractmethod
    async def read(
        self, context: TaskContext, after_id: str, *, block_ms: int = 1000
    ) -> list[TaskEvent]:
        """从指定游标之后独立读取事件，不使用任务消费组。"""
        raise NotImplementedError
