"""离线验证取消状态、真实应用编排和 Worker，不连接外部服务。"""

import asyncio
import unittest
from contextlib import asynccontextmanager
from contextvars import Context
from unittest.mock import AsyncMock, create_autospec
from uuid import uuid4

from sqlalchemy_transactional.asyncio import current_session, sessionmaker_context

from agent_platform.application.dto.agent_task_dto import (
    AgentTaskExecutionResult,
    CreateAgentTask,
    ResumeAgentTask,
    TaskJob,
    TextReply,
)
from agent_platform.application.interfaces.job_queue import JobQueue
from agent_platform.application.interfaces.task_events import TaskEvents
from agent_platform.application.interfaces.task_execution_guard import TaskExecutionGuard
from agent_platform.application.services.agent_task_application_service import (
    AgentTaskApplicationService,
)
from agent_platform.application.services.authentication_application_service import (
    AuthenticationApplicationService,
)
from agent_platform.domain.aggregates.agent_task import AgentTaskStatus
from agent_platform.domain.repositories.agent_task_repository import AgentTaskRepository
from agent_platform.domain.services.agent_task_domain_service import AgentTaskDomainService
from agent_platform.domain.types.common import ConflictError, NotFoundError, Principal
from agent_platform.domain.types.task_message import TaskMessage
from agent_platform.workers.agent_task_worker import AgentTaskWorker


class OfflineExecutionGuard(TaskExecutionGuard):
    """离线测试使用确定的执行权，生产装配必须提供 PG 实现。"""

    @asynccontextmanager
    async def acquire(self, task_id):
        yield True


class OfflineSession:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    @asynccontextmanager
    async def begin(self):
        yield


class OfflineRepository(AgentTaskRepository):
    async def recovery_candidates(self, *, after_id=None):
        return sorted(
            [t for t in self.tasks.values() if after_id is None or t.id > after_id],
            key=lambda t: t.id,
        )[:50]

    async def pending_deletions(self, *, after_id=None):
        return sorted(
            [
                t
                for t in self.tasks.values()
                if t.deletion_requested and (after_id is None or t.id > after_id)
            ],
            key=lambda t: t.id,
        )[:50]

    async def delete(self, principal, task_id):
        self.tasks[task_id].ensure_owned_by(principal)
        del self.tasks[task_id]
        self.history.pop(task_id, None)
        self.execution_records = {
            key: value for key, value in self.execution_records.items() if key[0] != task_id
        }

    def __init__(self):
        self.execution_records = {}  # 按会话和轮次保存执行快照
        self.tasks = {}  # 模拟持久化任务，供不同协程查询
        self.history = {}  # 模拟持久化消息

    async def save_execution(self, principal, task_id, execution):
        self.tasks[task_id].ensure_owned_by(principal)
        self.execution_records[(task_id, execution.attempt)] = execution

    async def executions(self, principal, task_id):
        self.tasks[task_id].ensure_owned_by(principal)
        return sorted(
            [value for (key, _), value in self.execution_records.items() if key == task_id],
            key=lambda value: value.attempt,
            reverse=True,
        )

    async def save(self, principal, task):
        current_session()
        task.ensure_owned_by(principal)
        self.tasks[task.id] = task

    async def get(self, principal, task_id, *, for_update=False):
        current_session()
        task = self.tasks.get(task_id)
        if task:
            task.ensure_owned_by(principal)
        return task

    async def list_recent(self, principal, *, limit=50):
        return list(self.tasks.values())[:limit]

    async def messages(self, principal, task_id):
        return list(self.history.get(task_id, []))

    async def add_message(self, principal, task_id, message):
        self.history.setdefault(task_id, []).append(message)

    async def set_message_state(self, principal, task_id, ids, state):
        self.history[task_id] = [
            TaskMessage.model_validate({**item.model_dump(), "state": state})
            if item.id in ids
            else item
            for item in self.history.get(task_id, [])
        ]


class OfflineQueue(JobQueue):
    def __init__(self):
        self.items = asyncio.Queue()  # 模拟共享队列
        self.acked = []  # 已确认的消息
        self.changed = asyncio.Event()  # 测试等待确认信号

    async def enqueue(self, context, *, resume=None):
        message_id = uuid4().hex
        await self.items.put((message_id, TaskJob(context=context, resume=resume)))
        return message_id

    async def receive(self, *, timeout_seconds=1):
        try:
            return await asyncio.wait_for(self.items.get(), timeout_seconds)
        except TimeoutError:
            return None

    async def acknowledge(self, message_id):
        self.acked.append(message_id)
        self.changed.set()


class BlockingRuntime:
    def __init__(self):
        self.started = asyncio.Event()  # 模拟模型连接已开始
        self.closed = asyncio.Event()  # 模拟根执行已退出
        self.child_closed = asyncio.Event()  # 模拟结构化子 Agent 已退出

    async def _child(self):
        try:
            await asyncio.Event().wait()
        finally:
            self.child_closed.set()

    async def execute(self, task, *, messages=(), on_text=None, **kwargs):
        if task.prompt == "下一项任务" or any(m.content == "正确的新要求" for m in messages):
            return AgentTaskExecutionResult(status="completed", output="正常完成")
        try:
            async with asyncio.TaskGroup() as group:
                group.create_task(self._child())
                if on_text:
                    await on_text("已经生成的部分回答")
                self.started.set()
                await asyncio.Event().wait()
        finally:
            self.closed.set()

    async def resume(self, task, command, **kwargs):
        return await self.execute(task, **kwargs)


class RunningTaskCancellationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.repository = OfflineRepository()
        self.queue = OfflineQueue()
        self.runtime = BlockingRuntime()
        self.events = create_autospec(TaskEvents, instance=True)
        self.principal = Principal(tenant_id=1, user_id=2, project_id="test")
        self.domain = AgentTaskDomainService(self.repository)
        self.service = AgentTaskApplicationService(
            execution_guard=OfflineExecutionGuard(),
            tasks=self.domain,
            queue=self.queue,
            runtime=self.runtime,
            events=self.events,
        )
        await self.enterAsyncContext(sessionmaker_context(OfflineSession))
        self.authentication = create_autospec(AuthenticationApplicationService, instance=True)
        self.worker = AgentTaskWorker(
            session_factory=OfflineSession,
            queue=self.queue,
            service=self.service,
            authentication=self.authentication,
        )

    async def create(self):
        return await self.service.create(self.principal, CreateAgentTask(prompt="长任务"))

    async def running(self):
        task = await self.create()
        task, _ = await self.service._claim_task(self.principal, task.id)
        return task

    async def test_running_cancel_requires_confirmation_and_is_idempotent(self):
        task = await self.running()
        requested = await self.service.cancel(self.principal, task.id)
        self.assertEqual(requested.status, AgentTaskStatus.CANCELLING)
        self.assertEqual(self.repository.history[task.id][0].state, "processing")
        self.assertEqual((await self.service.cancel(self.principal, task.id)).attempt, task.attempt)
        stopped = await self.service.complete_cancellation(
            self.principal,
            task.id,
            attempt=task.attempt,
            execution_id=task.execution_id,
            partial_output="部分回答",
        )
        await self.service.complete_cancellation(
            self.principal,
            task.id,
            attempt=task.attempt,
            execution_id=task.execution_id,
            partial_output="不应重复保存",
        )
        self.assertEqual(stopped.status, AgentTaskStatus.CANCELLED)
        self.assertIsNone(stopped.error)
        self.assertEqual(
            [m.state for m in self.repository.history[task.id]], ["cancelled", "cancelled"]
        )
        self.assertEqual(self.repository.history[task.id][-1].content, "部分回答")

    async def test_queued_and_waiting_tasks_cancel_immediately(self):
        queued = await self.create()
        self.assertEqual(
            (await self.service.cancel(self.principal, queued.id)).status, AgentTaskStatus.CANCELLED
        )
        waiting = await self.running()
        self.repository.tasks[waiting.id] = waiting.wait_for_user()
        self.assertEqual(
            (await self.service.cancel(self.principal, waiting.id)).status,
            AgentTaskStatus.CANCELLED,
        )

    async def test_cancel_rejects_wrong_owner_and_finished_task(self):
        task = await self.running()
        outsider = Principal(tenant_id=1, user_id=3, project_id="test")
        with self.assertRaises(NotFoundError):
            await self.service.cancel(outsider, task.id)
        self.repository.tasks[task.id] = task.complete("已完成")
        with self.assertRaises(ConflictError):
            await self.service.cancel(self.principal, task.id)

    async def test_stopping_rejects_new_input_and_late_aggregate_completion(self):
        task = await self.running()
        task = await self.service.cancel(self.principal, task.id)
        with self.assertRaises(ConflictError):
            task.complete("晚到的结果")
        with self.assertRaises(ConflictError):
            await self.service.send_message(self.principal, task.id, uuid4(), "新内容")

    async def test_cancel_wins_race_with_model_success_and_publishes_no_completed(self):
        task = await self.running()
        await self.service.cancel(self.principal, task.id)
        result = AgentTaskExecutionResult(status="completed", output="同时返回的结果")
        saved = await self.service._finish_task(self.principal, task, result)
        await self.service._publish_result(saved, result)
        self.assertEqual(saved.status, AgentTaskStatus.CANCELLED)
        self.assertEqual(self.events.publish.await_args.args[1], "cancelled")

    async def test_cancel_wins_race_with_failure_without_failed_event(self):
        task = await self.running()
        await self.service.cancel(self.principal, task.id)
        saved = await self.service._fail_task(self.principal, task, "连接同时中断")
        await self.service._publish(saved, "failed", {"error": saved.error})
        self.assertEqual(saved.status, AgentTaskStatus.CANCELLED)
        self.assertEqual(self.events.publish.await_args.args[1], "cancelled")

    async def test_stale_attempt_cannot_confirm_another_execution(self):
        task = await self.running()
        await self.service.cancel(self.principal, task.id)
        with self.assertRaises(ConflictError):
            await self.service.complete_cancellation(
                self.principal, task.id, attempt=task.attempt + 1, execution_id=task.execution_id
            )

    async def test_cancel_also_discards_pending_followup_messages(self):
        task = await self.running()
        await self.service.send_message(self.principal, task.id, uuid4(), "待处理的补充")
        await self.service.cancel(self.principal, task.id)
        await self.service.complete_cancellation(
            self.principal, task.id, attempt=task.attempt, execution_id=task.execution_id
        )
        self.assertEqual(
            [item.state for item in self.repository.history[task.id]],
            ["cancelled", "cancelled"],
        )
        self.assertIsNone(await self.service._claim_task(self.principal, task.id))

    async def test_cancel_during_result_commit_still_preserves_partial_text(self):
        task = await self.create()
        finishing = asyncio.Event()

        async def model_done(task, *, on_text=None, **kwargs):
            await on_text("提交前已经输出的内容")
            return AgentTaskExecutionResult(status="completed", output="最终内容")

        async def delayed_finish(*args, **kwargs):
            finishing.set()
            await asyncio.Event().wait()

        self.runtime.execute = model_done
        self.service._finish_task = AsyncMock(side_effect=delayed_finish)
        execution = asyncio.create_task(self.worker._execute_job(TaskJob(context=task.context)))
        await asyncio.wait_for(finishing.wait(), 2)
        await self.service.cancel(self.principal, task.id)
        await asyncio.wait_for(execution, 3)
        self.assertEqual(self.repository.tasks[task.id].status, AgentTaskStatus.CANCELLED)
        self.assertEqual(self.repository.history[task.id][-1].content, "提交前已经输出的内容")

    async def test_worker_stops_execution_saves_partial_text_and_processes_next_job(self):
        task = await self.create()
        stop = asyncio.Event()
        consumer = asyncio.create_task(self.worker.consume(stop), context=Context())
        try:
            await asyncio.wait_for(self.runtime.started.wait(), 2)
            await self.service.cancel(self.principal, task.id)
            await asyncio.wait_for(self.queue.changed.wait(), 3)
            self.assertTrue(self.runtime.closed.is_set())
            self.assertTrue(self.runtime.child_closed.is_set())
            self.assertFalse(consumer.done())
            self.assertEqual(self.repository.tasks[task.id].status, AgentTaskStatus.CANCELLED)
            self.assertEqual(self.repository.history[task.id][-1].content, "已经生成的部分回答")
            self.queue.changed.clear()
            await self.service.send_message(self.principal, task.id, uuid4(), "正确的新要求")
            await asyncio.wait_for(self.queue.changed.wait(), 3)
            self.assertEqual(self.repository.tasks[task.id].status, AgentTaskStatus.SUCCEEDED)
            self.assertEqual(self.repository.tasks[task.id].attempt, 2)
            self.queue.changed.clear()
            next_task = await self.service.create(
                self.principal, CreateAgentTask(prompt="下一项任务")
            )
            await asyncio.wait_for(self.queue.changed.wait(), 3)
            self.assertEqual(self.repository.tasks[next_task.id].status, AgentTaskStatus.SUCCEEDED)
            self.assertEqual(len(self.queue.acked), 3)
        finally:
            stop.set()
            await asyncio.wait_for(consumer, 2)

    async def test_stopped_session_accepts_corrected_input_and_increases_attempt(self):
        task = await self.running()
        await self.service.cancel(self.principal, task.id)
        await self.service.complete_cancellation(
            self.principal, task.id, attempt=task.attempt, execution_id=task.execution_id
        )
        message_id = uuid4()
        queued = await self.service.send_message(
            self.principal, task.id, message_id, "正确的新要求"
        )
        self.assertEqual(queued.status, AgentTaskStatus.QUEUED)
        self.assertEqual(queued.context.thread_id, task.context.thread_id)
        # 排队后旧轮次的确认也不能把新请求重新取消。
        with self.assertRaises(ConflictError):
            await self.service.complete_cancellation(
                self.principal, task.id, attempt=task.attempt, execution_id=task.execution_id
            )
        self.runtime.execute = AsyncMock(
            return_value=AgentTaskExecutionResult(status="completed", output="按正确内容完成")
        )
        completed = await self.service.execute(self.principal, task.id)
        self.assertEqual(completed.status, AgentTaskStatus.SUCCEEDED)
        self.assertEqual(completed.attempt, task.attempt + 1)
        self.assertEqual(completed.id, task.id)
        invocation = self.runtime.execute.await_args.kwargs
        self.assertTrue(invocation["restart_after_interruption"])
        self.assertEqual([m.id for m in invocation["messages"]], [message_id])
        self.assertEqual(self.repository.history[task.id][0].state, "cancelled")

    async def test_failed_round_accepts_new_input_and_preserves_partial_answer(self):
        task = await self.running()
        await self.service._fail_task(self.principal, task, "执行失败", partial_output="已生成部分")
        self.assertEqual(self.repository.history[task.id][-1].state, "failed")
        queued = await self.service.send_message(self.principal, task.id, uuid4(), "正确的新要求")
        self.assertEqual(queued.status, AgentTaskStatus.QUEUED)
        self.assertIsNone(queued.error)
        self.runtime.execute = AsyncMock(
            return_value=AgentTaskExecutionResult(status="completed", output="新一轮完成")
        )
        completed = await self.service.execute(self.principal, task.id)
        self.assertEqual(completed.id, task.id)
        self.assertEqual(completed.context.thread_id, task.context.thread_id)
        self.assertEqual(completed.attempt, task.attempt + 1)
        self.assertEqual(completed.status, AgentTaskStatus.SUCCEEDED)
        self.assertTrue(self.runtime.execute.await_args.kwargs["restart_after_interruption"])

    async def test_stopped_before_first_execution_can_start_in_same_session(self):
        task = await self.create()
        await self.service.cancel(self.principal, task.id)
        await self.service.send_message(self.principal, task.id, uuid4(), "正确的新要求")
        self.runtime.execute = AsyncMock(
            return_value=AgentTaskExecutionResult(status="completed", output="已完成")
        )
        completed = await self.service.execute(self.principal, task.id)
        self.assertEqual(completed.attempt, 1)
        self.assertTrue(self.runtime.execute.await_args.kwargs["restart_after_interruption"])

    async def test_execution_title_and_plan_are_scoped_to_round_and_survive_rename(self):
        from agent_platform.application.dto.agent_task_dto import TaskPlanItem

        first = await self.running()
        step = TaskPlanItem(content="编写策划文档", status="completed")
        await self.service._update_execution(
            self.principal, first, title="编写地图玩法", todos=(step,)
        )
        await self.service._finish_task(
            self.principal,
            first,
            AgentTaskExecutionResult(
                status="completed", output="地图策划完成", title="编写地图玩法", todos=(step,)
            ),
        )
        await self.service.rename(self.principal, first.id, "版本开发总会话")
        await self.service.send_message(self.principal, first.id, uuid4(), "继续检查上线风险")
        second, _ = await self.service._claim_task(self.principal, first.id)
        records = await self.service.executions(self.principal, first.id)
        self.assertEqual([item.attempt for item in records], [2, 1])
        self.assertEqual(records[0].title, "第 2 轮执行")
        self.assertEqual(records[0].todos, ())
        self.assertEqual(records[1].title, "编写地图玩法")
        self.assertEqual(records[1].output, "地图策划完成")
        self.assertEqual(records[1].status, AgentTaskStatus.SUCCEEDED)
        self.assertIsNone(
            await self.service._update_execution(self.principal, first, title="迟到标题")
        )
        await self.service._update_execution(self.principal, second, title="检查上线风险")
        outsider = Principal(tenant_id=1, user_id=999, project_id="test")
        with self.assertRaises(NotFoundError):
            await self.service.executions(outsider, first.id)

    async def test_cancelling_unstarted_followup_does_not_rewrite_previous_round(self):
        task = await self.running()
        await self.service._finish_task(
            self.principal,
            task,
            AgentTaskExecutionResult(
                status="completed",
                title="完成地图策划",
                output="已交付",
            ),
        )
        await self.service.send_message(self.principal, task.id, uuid4(), "尚未开始的新请求")
        await self.service.cancel(self.principal, task.id)
        records = await self.service.executions(self.principal, task.id)
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].status, AgentTaskStatus.SUCCEEDED)
        self.assertEqual(records[0].title, "完成地图策划")
        self.assertEqual(records[0].output, "已交付")

    async def test_human_resume_keeps_same_execution_title(self):
        from agent_platform.application.dto.agent_task_dto import TaskInterrupt, UserInputPayload

        task = await self.running()
        await self.service._update_execution(self.principal, task, title="确认上线时间")
        await self.service._finish_task(
            self.principal,
            task,
            AgentTaskExecutionResult(
                status="waiting",
                title="确认上线时间",
                interrupts=(
                    TaskInterrupt(id="date", payload=UserInputPayload(question="何时上线？")),
                ),
            ),
        )
        resumed = await self.service._start_resume(self.principal, task.id)
        records = await self.service.executions(self.principal, task.id)
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].title, "确认上线时间")
        self.assertEqual(resumed.attempt, task.attempt)
        await self.service._reject_resume(self.principal, resumed)
        records = await self.service.executions(self.principal, task.id)
        self.assertEqual(records[0].status, AgentTaskStatus.WAITING_HUMAN)
        self.assertEqual(records[0].title, "确认上线时间")

    async def test_server_shutdown_cleans_execution_without_ack_or_user_cancel(self):
        task = await self.create()
        consumer = asyncio.create_task(self.worker.consume(asyncio.Event()), context=Context())
        await asyncio.wait_for(self.runtime.started.wait(), 2)
        consumer.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await consumer
        self.assertTrue(self.runtime.closed.is_set())
        self.assertTrue(self.runtime.child_closed.is_set())
        self.assertEqual(self.queue.acked, [])
        self.assertEqual(self.repository.tasks[task.id].status, AgentTaskStatus.RUNNING)

    async def test_cancel_also_stops_human_resume_execution(self):
        task = await self.running()
        self.repository.tasks[task.id] = task.wait_for_user()
        command = ResumeAgentTask(answers={"question": TextReply(answer="继续")})
        execution = asyncio.create_task(
            self.worker._execute_job(TaskJob(context=task.context, resume=command))
        )
        await asyncio.wait_for(self.runtime.started.wait(), 2)
        await self.service.cancel(self.principal, task.id)
        await asyncio.wait_for(execution, 3)
        self.assertEqual(self.repository.tasks[task.id].status, AgentTaskStatus.CANCELLED)
        self.assertEqual(self.repository.tasks[task.id].attempt, task.attempt)

    async def test_runtime_closes_stream_when_text_callback_is_cancelled(self):
        from langchain_core.messages import AIMessage

        from agent_platform.infrastructure.harness.runtime.deepagents_task_runtime import (
            DeepAgentsTaskRuntime,
        )

        entered = asyncio.Event()
        closed = asyncio.Event()

        class StreamingGraph:
            async def astream(self, *args, **kwargs):
                try:
                    yield "messages", (AIMessage(content="部分文本"), {})
                    await asyncio.Event().wait()
                finally:
                    closed.set()

        async def on_text(text):
            entered.set()
            await asyncio.Event().wait()

        task = await self.create()
        runtime = DeepAgentsTaskRuntime({})
        execution = asyncio.create_task(
            runtime._invoke_graph(
                StreamingGraph(),
                task,
                {},
                on_text,
                None,
                None,
                operation="execute",
            )
        )
        await asyncio.wait_for(entered.wait(), 2)
        execution.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await execution
        self.assertTrue(closed.is_set())


if __name__ == "__main__":
    unittest.main()
