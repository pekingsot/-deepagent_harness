from collections.abc import  Mapping

from langchain_core.messages import AIMessage
from langchain_core.runnables import RunnableConfig
from langgraph.types import Command, StateSnapshot

from agent_platform.application.dto.runs import (
    ApprovalReply,
    ResumeRun,
    RuntimeInterrupt,
    RuntimeResult,
    TextReply,
    ToolApprovalPayload,
    UserInputPayload,
)
from agent_platform.application.ports.runtime import AgentRuntime
from agent_platform.domain.common.models import (
    ConflictError,
    NotFoundError,
)
from agent_platform.domain.runs.models import Run
from agent_platform.harness.agents.base import AgentGraph, BaseAgent
from agent_platform.harness.runtime.run_context import checkpoint_thread




class DeepAgentsRuntime(AgentRuntime):
    def __init__(
        self,
        agents: Mapping[str, BaseAgent],
    ) -> None:
        # Reuse definitions within this runtime; build execution graphs per call.
        self._agents= dict(agents)
        for name, agent in self._agents.items():
            if not isinstance(agent, BaseAgent):
                raise TypeError("必须传入 BaseAgent 实例")
            if agent.name != name:
                raise ValueError("注册名称与 Agent 名称不一致")


    def _build(self, run: Run) -> AgentGraph:
        agent = self._agents.get(run.agent)
        if agent is None:
            raise NotFoundError(f"Agent 不存在：{run.agent}")
        return agent.build(run.context)

    @staticmethod
    def _config(run: Run) -> RunnableConfig:
        return {
            "configurable": {
                "thread_id": checkpoint_thread(run.context),
            },
            "recursion_limit": 50,
        }

    @staticmethod
    def _result(snapshot: StateSnapshot) -> RuntimeResult:
        if snapshot.created_at is None:
            raise NotFoundError("任务尚无执行记录")

        for task in snapshot.tasks:
            if task.error is not None:
                raise RuntimeError(
                    f"Agent 节点执行失败：{task.name}"
                )

        interrupts = tuple(
            RuntimeInterrupt(
                id=item.id,
                payload=item.value,
            )
            for item in snapshot.interrupts
        )

        if interrupts:
            return RuntimeResult(
                status="waiting",
                interrupts=interrupts,
            )

        if snapshot.next:
            raise ConflictError(
                "任务仍有待执行节点，当前不是完成状态"
            )

        messages = snapshot.values.get("messages", [])

        if not messages:
            raise RuntimeError("Agent 执行结束但没有消息")

        last_message = messages[-1]

        if (
            not isinstance(last_message, AIMessage)
            or last_message.tool_calls
        ):
            raise RuntimeError("Agent 缺少最终回答")

        return RuntimeResult(
            status="completed",
            output=last_message.text,
        )

    async def execute(self, run: Run) -> RuntimeResult:
        graph = self._build(run)
        config = self._config(run)

        snapshot = await graph.aget_state(config)
        if snapshot.created_at is not None:
            raise ConflictError(
                "任务已有执行记录，不能重复开始"
            )

        await graph.ainvoke(
            {
                "messages": [
                    {
                        "role": "user",
                        "content": run.prompt,
                    }
                ]
            },
            config=config,
            context=run.context,
        )

        snapshot = await graph.aget_state(config)
        return self._result(snapshot)

    async def get_state(self, run: Run) -> RuntimeResult:
        graph = self._build(run)
        snapshot = await graph.aget_state(
            self._config(run)
        )
        return self._result(snapshot)

    async def resume(
        self,
        run: Run,
        command: ResumeRun,
    ) -> RuntimeResult:
        graph = self._build(run)
        config = self._config(run)

        snapshot = await graph.aget_state(config)
        current = self._result(snapshot)

        if current.status != "waiting":
            raise ConflictError("任务没有等待人工处理")

        pending = {
            item.id: item
            for item in current.interrupts
        }

        if set(command.answers) != set(pending):
            raise ValueError(
                "回答必须与当前全部待处理中断一一对应"
            )

        answers: dict[str, str | bool] = {}

        for interrupt_id, reply in command.answers.items():
            payload = pending[interrupt_id].payload

            if (
                isinstance(payload, UserInputPayload)
                and isinstance(reply, TextReply)
            ):
                if not reply.answer.strip():
                    raise ValueError("回答不能为空白")

                answers[interrupt_id] = reply.answer

            elif (
                isinstance(payload, ToolApprovalPayload)
                and isinstance(reply, ApprovalReply)
            ):
                answers[interrupt_id] = reply.approved

            else:
                raise ValueError(
                    f"回答类型与中断类型不匹配：{interrupt_id}"
                )

        await graph.ainvoke(
            Command(resume=answers),
            config=config,
            context=run.context,
        )

        snapshot = await graph.aget_state(config)
        return self._result(snapshot)