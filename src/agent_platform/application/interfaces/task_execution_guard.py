"""执行与补偿共用的互斥凭证，不通过聊天内容推断任务存活。"""

from abc import ABC, abstractmethod
from contextlib import AbstractAsyncContextManager
from uuid import UUID

from agent_platform.domain.types.common import ConflictError


class ExecutionOwnershipLost(ConflictError):
    """执行所持连接失效，调用方必须停止运行。"""


class TaskExecutionGuard(ABC):
    @abstractmethod
    def acquire(self, task_id: UUID) -> AbstractAsyncContextManager[bool]:
        """非阻塞获取任务执行权，执行者存活时补偿方不能进入。"""
        raise NotImplementedError
