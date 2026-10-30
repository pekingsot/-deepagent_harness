from collections.abc import Awaitable, Callable, Mapping
from time import perf_counter

from langchain_core.messages import AIMessage,ToolMessage
from langchain_core.runnables import RunnableConfig
from langgraph.types import Command, StateSnapshot
from deepagents.backends.utils import file_data_to_string
from agent_platform.application.dto.agent_task_dto import (
    AgentTaskExecutionResult,
    ApprovalReply,
    ResumeAgentTask,
    TaskInterrupt,
    TextReply,
    ToolApprovalPayload,
    UserInputPayload,
    InvalidHumanReplyError,
    TaskPlanItem,
    TaskArtifact,
    TaskActivity
)
from agent_platform.application.interfaces.agent_task_runtime import AgentTaskRuntime
from agent_platform.domain.aggregates.agent_task import AgentTask
from agent_platform.domain.types.common import (
    ConflictError,
    NotFoundError,
)
from agent_platform.infrastructure.harness.agents.base import AgentGraph, BaseAgent
from agent_platform.infrastructure.harness.runtime.checkpoint_namespace import checkpoint_thread
from agent_platform.domain.types.task_message import TaskMessage


class DeepAgentsTaskRuntime(AgentTaskRuntime):
    def __init__(
            self,
            agents: Mapping[str, BaseAgent],
    ) -> None:
        # 复用 Agent 定义，执行状态通过线程上下文及 checkpoint 隔离。
        self._agents = dict(agents)
        for name, agent in self._agents.items():
            if not isinstance(agent, BaseAgent):
                raise TypeError("必须传入 BaseAgent 实例")
            if agent.name != name:
                raise ValueError("注册名称与 Agent 名称不一致")

    def _build(self, task: AgentTask) -> AgentGraph:
        agent = self._agents.get(task.agent)
        if agent is None:
            raise NotFoundError(f"Agent 不存在：{task.agent}")
        return agent.build(task.context)

    @staticmethod
    def _config(task: AgentTask) -> RunnableConfig:
        return {
            "configurable": {
                "thread_id": checkpoint_thread(task.context),
            },
            "recursion_limit": 50,
        }

    @staticmethod
    def _result(snapshot: StateSnapshot) -> AgentTaskExecutionResult:
        if snapshot.created_at is None:
            raise NotFoundError("任务尚无执行记录")

        for task in snapshot.tasks:
            if task.error is not None:
                raise RuntimeError(f"Agent 节点执行失败：{task.name}")

        interrupts = tuple(
            TaskInterrupt(
                id=item.id,
                payload=item.value,
            )
            for item in snapshot.interrupts
        )
        todos = tuple(
            TaskPlanItem.model_validate(item)
            for item in snapshot.values.get("todos", [])
        )
        # 只展示任务交付目录中的文本文件，不暴露技能和其他内部文件。
        files = snapshot.values.get("files", {})

        artifacts = tuple(
            TaskArtifact(
                path=path,
                content=file_data_to_string(file_data),
            )
            for path, file_data in sorted(files.items())
            if path.startswith("/deliverables/")
            and file_data.get("encoding", "utf-8") == "utf-8"
        )
        if interrupts:
            return AgentTaskExecutionResult(
                status="waiting",
                interrupts=interrupts,
                todos=todos,
                artifacts=artifacts,
            )

        if snapshot.next:
            raise ConflictError("任务仍有待执行节点，当前不是完成状态")

        messages = snapshot.values.get("messages", [])

        if not messages:
            raise RuntimeError("Agent 执行结束但没有消息")

        last_message = messages[-1]

        if not isinstance(last_message, AIMessage) or last_message.tool_calls:
            raise RuntimeError("Agent 缺少最终回答")

        return AgentTaskExecutionResult(
            status="completed",
            output=last_message.text,
            todos=todos,
            artifacts=artifacts,
        )

    async def execute(
            self,
            task: AgentTask,
            *,
            messages: tuple[TaskMessage, ...],
            on_text: Callable[[str], Awaitable[None]] | None = None,
            on_plan: Callable[
                         [tuple[TaskPlanItem, ...]],
                         Awaitable[None],
                     ] | None = None,
            on_activity: Callable[[TaskActivity], Awaitable[None]] | None = None,
    ) -> AgentTaskExecutionResult:
        graph = self._build(task)
        config = self._config(task)

        snapshot = await graph.aget_state(config)

        # 上一轮没有结束时，不能直接追加新一轮输入。
        if snapshot.interrupts or snapshot.next:
            raise ConflictError(
                "上一轮尚未结束，请先处理人工中断或恢复执行"
            )

        if not messages:
            raise ValueError("本轮没有待处理消息")

        # 后续轮次必须保留原来的执行现场，避免悄悄丢失上下文。
        if task.attempt > 1 and snapshot.created_at is None:
            raise ConflictError(
                "当前会话的 checkpoint 已丢失，无法延续上下文"
            )

        await self._invoke(
            graph,
            task,
            {
                # 新一轮输入重新计算调用额度；人工恢复仍沿用当前轮的计数。
                "model_call_count": 0,
                "tool_call_count": 0,
                "tool_call_counts": {},
                "messages": [
                    {
                        "id": str(item.id),
                        "role": "user",
                        "content": item.content,
                    }
                    for item in messages
                ]
            },
            on_text,
            on_plan,
            on_activity,
        )

        snapshot = await graph.aget_state(config)
        return self._result(snapshot)

    async def get_state(self, task: AgentTask) -> AgentTaskExecutionResult:
        graph = self._build(task)
        snapshot = await graph.aget_state(self._config(task))
        return self._result(snapshot)

    async def resume(
            self,
            task: AgentTask,
            command: ResumeAgentTask,
            *,
            on_text: Callable[[str], Awaitable[None]] | None = None,
            on_plan: Callable[
                         [tuple[TaskPlanItem, ...]],
                         Awaitable[None],
                     ] | None = None,
            on_activity: Callable[[TaskActivity], Awaitable[None]] | None = None,
    ) -> AgentTaskExecutionResult:
        graph = self._build(task)
        config = self._config(task)

        snapshot = await graph.aget_state(config)
        current = self._result(snapshot)

        if current.status != "waiting":
            raise ConflictError("任务没有等待人工处理")

        pending = {item.id: item for item in current.interrupts}

        if set(command.answers) != set(pending):
            raise InvalidHumanReplyError(
                "回答必须与当前全部待处理中断一一对应"
            )

        answers: dict[str, str | bool] = {}

        for interrupt_id, reply in command.answers.items():
            payload = pending[interrupt_id].payload

            if isinstance(payload, UserInputPayload) and isinstance(reply, TextReply):
                if not reply.answer.strip():
                    raise InvalidHumanReplyError("回答不能为空白")

                answers[interrupt_id] = reply.answer

            elif isinstance(payload, ToolApprovalPayload) and isinstance(reply, ApprovalReply):
                answers[interrupt_id] = reply.approved

            else:
                raise InvalidHumanReplyError(
                    f"回答类型与中断类型不匹配：{interrupt_id}"
                )

        await self._invoke(graph, task, Command(resume=answers), on_text, on_plan,on_activity)

        snapshot = await graph.aget_state(config)
        return self._result(snapshot)

    async def _invoke(
            self,
            graph: AgentGraph,
            task: AgentTask,
            inputs: dict | Command,
            on_text: Callable[[str], Awaitable[None]] | None,
            on_plan: Callable[
                         [tuple[TaskPlanItem, ...]],
                         Awaitable[None],
                     ] | None,
            on_activity: Callable[
                             [TaskActivity],
                             Awaitable[None],
                         ] | None,
    ) -> None:
        """转发文本、计划更新以及主 Agent 的工具调用动态。"""
        config = self._config(task)

        if on_text is None and on_plan is None and on_activity is None:
            await graph.ainvoke(
                inputs,
                config=config,
                context=task.context,
            )
            return

        last_plan: tuple[TaskPlanItem, ...] | None = None
        calls: dict[str, TaskActivity] = {}  # 当前执行段内的调用信息
        returned: set[str] = set()  # 已发布返回事件的调用编号
        started_at: dict[str, float] = {}  # 当前执行段内，各次请求的观察时间

        async for mode, data in graph.astream(
                inputs,
                config=config,
                context=task.context,
                stream_mode=["messages", "updates"],
        ):
            if mode == "messages":
                message, _metadata = data

                if (
                        on_text is not None
                        and isinstance(message, AIMessage)
                        and message.text
                ):
                    await on_text(message.text)

            elif mode == "updates":
                for update in data.values():
                    if not isinstance(update, Mapping):
                        continue

                    if "todos" in update and on_plan is not None:
                        plan = tuple(
                            TaskPlanItem.model_validate(item)
                            for item in update["todos"]
                        )

                        if plan != last_plan:
                            await on_plan(plan)
                            last_plan = plan

                    if on_activity is None:
                        continue

                    for message in update.get("messages", []):
                        # 使用完整模型消息中的工具调用，不解析零碎参数。
                        if isinstance(message, AIMessage):
                            for call in message.tool_calls:
                                call_id = call.get("id")

                                if not call_id:
                                    raise ValueError("工具调用缺少编号")

                                if call_id in calls:
                                    continue

                                subagent = (
                                    call["args"].get("subagent_type")
                                    if call["name"] == "task"
                                    else None
                                )

                                file_path = (
                                    call["args"].get("file_path")
                                    if call["name"] in {
                                        "read_file",
                                        "write_file",
                                        "edit_file",
                                    }
                                    else None
                                )
                                started_at[call_id] = perf_counter()

                                activity = TaskActivity(
                                    event="tool_requested",
                                    tool_name=call["name"],
                                    call_id=call_id,
                                    subagent=subagent,
                                    file_path=file_path,
                                )

                                calls[call_id] = activity
                                await on_activity(activity)

                        elif isinstance(message, ToolMessage):
                            call_id = message.tool_call_id

                            if call_id in returned:
                                continue

                            previous = calls.get(call_id)
                            tool_name = (
                                previous.tool_name
                                if previous is not None
                                else message.name
                            )

                            if not tool_name:
                                raise ValueError("工具返回消息缺少工具名称")

                            # 跨人工恢复的返回可能没有本段的请求时间，不伪造耗时。
                            started = started_at.get(call_id)
                            elapsed_ms = (
                                round((perf_counter() - started) * 1000)
                                if started is not None
                                else None
                            )

                            activity = TaskActivity(
                                event=(
                                    "tool_failed"
                                    if message.status == "error"
                                    else "tool_returned"
                                ),
                                tool_name=tool_name,
                                call_id=call_id,
                                subagent=(
                                    previous.subagent
                                    if previous is not None
                                    else None
                                ),
                                file_path=(
                                    previous.file_path
                                    if previous is not None
                                    else None
                                ),
                                elapsed_ms=elapsed_ms,
                            )

                            await on_activity(activity)
                            returned.add(call_id)
