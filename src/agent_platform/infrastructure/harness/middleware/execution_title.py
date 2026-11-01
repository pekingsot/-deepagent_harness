"""让 Agent 在现有推理中概括本轮标题，标题随图状态保存。"""

from typing import NotRequired

from langchain.agents import AgentState
from langchain.agents.middleware import AgentMiddleware
from langchain.tools import ToolRuntime
from langchain_core.messages import ToolMessage
from langchain_core.tools import tool
from langgraph.types import Command

from agent_platform.domain.types.common import TaskContext


class ExecutionTitleState(AgentState):
    execution_title: NotRequired[str | None]  # 当前轮标题，普通新一轮清空，人工恢复保留


@tool
def set_execution_title(title: str, runtime: ToolRuntime[TaskContext]) -> Command | str:
    """概括本轮正在做的事情作为标题。结合最新要求与上下文，不能复用整个会话名称。"""
    if runtime.state.get("execution_title"):
        return "本轮已有执行标题，继续执行当前计划。"
    title = " ".join(title.split())
    if not title or len(title) > 120:
        return "标题必须是 1 至 120 个字符的简短任务概括。"
    return Command(
        update={
            "execution_title": title,
            "messages": [
                ToolMessage(content=f"本轮标题：{title}", tool_call_id=runtime.tool_call_id)
            ],
        }
    )


class ExecutionTitleMiddleware(AgentMiddleware[ExecutionTitleState, TaskContext]):
    state_schema = ExecutionTitleState
    tools = [set_execution_title]
