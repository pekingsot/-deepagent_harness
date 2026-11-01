"""永久删除会话所需的外部执行数据清理契约。"""

from abc import ABC, abstractmethod

from agent_platform.domain.aggregates.agent_task import AgentTask


class TaskDataCleaner(ABC):
    @abstractmethod
    async def cleanup(self, task: AgentTask) -> None:
        """幂等清理执行状态与临时数据，任何失败必须向上传递。"""
        raise NotImplementedError
