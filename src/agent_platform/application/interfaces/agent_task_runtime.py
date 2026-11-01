from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable

from agent_platform.application.dto.agent_task_dto import (
    AgentTaskExecutionResult,
    ResumeAgentTask,
    TaskActivity,
    TaskPlanItem,
)
from agent_platform.domain.aggregates.agent_task import AgentTask
from agent_platform.domain.types.task_message import TaskMessage


class AgentTaskRuntime(ABC):
    """任务用例需要的 Agent 执行能力，由具体框架适配器实现。"""

    @abstractmethod
    async def execute(
        self,
        task: AgentTask,
        *,
        messages: tuple[TaskMessage, ...],
        restart_after_interruption: bool = False,  # 新输入前清理已停止或失败轮次的待执行现场
        on_text: Callable[[str], Awaitable[None]] | None = None,
        on_plan: Callable[
            [tuple[TaskPlanItem, ...]],
            Awaitable[None],
        ]
        | None = None,
        on_activity: Callable[[TaskActivity], Awaitable[None]] | None = None,
        on_title: Callable[[str], Awaitable[None]] | None = None,
    ) -> AgentTaskExecutionResult:
        raise NotImplementedError

    @abstractmethod
    async def resume(
        self,
        task: AgentTask,
        command: ResumeAgentTask,
        *,
        on_text: Callable[[str], Awaitable[None]] | None = None,
        on_plan: Callable[
            [tuple[TaskPlanItem, ...]],
            Awaitable[None],
        ]
        | None = None,
        on_activity: Callable[[TaskActivity], Awaitable[None]] | None = None,
        on_title: Callable[[str], Awaitable[None]] | None = None,
    ) -> AgentTaskExecutionResult:
        raise NotImplementedError

    @abstractmethod
    async def get_state(self, task: AgentTask) -> AgentTaskExecutionResult:
        raise NotImplementedError
