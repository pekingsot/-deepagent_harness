"""协调组件自己的清理接口，不了解各组件内部的键结构。"""

from typing import Any

from langgraph.checkpoint.base import BaseCheckpointSaver

from agent_platform.application.interfaces.task_data_cleaner import TaskDataCleaner
from agent_platform.domain.aggregates.agent_task import AgentTask
from agent_platform.infrastructure.harness.runtime.checkpoint_namespace import checkpoint_thread
from agent_platform.infrastructure.messaging.redis_job_queue import RedisJobQueue
from agent_platform.infrastructure.messaging.redis_task_events import RedisTaskEvents
from agent_platform.infrastructure.observability.redis_trace_context import RedisTraceContextStore


class PersistentTaskDataCleaner(TaskDataCleaner):
    def __init__(
        self,
        *,
        saver: BaseCheckpointSaver[Any],
        events: RedisTaskEvents,
        queue: RedisJobQueue,
        traces: RedisTraceContextStore,
    ) -> None:
        self._saver = saver
        self._events = events
        self._queue = queue
        self._traces = traces

    async def cleanup(self, task: AgentTask) -> None:
        """各步骤均幂等；失败向上传递，保留 PG 删除意图等待重试。"""
        await self._events.delete(task.context)
        await self._queue.delete_task(task.context)
        await self._saver.adelete_thread(checkpoint_thread(task.context))
        await self._traces.delete_task(task)
