import asyncio
import json
import logging
import sys

from langchain_core.messages import ToolMessage
from langchain_core.runnables import RunnableConfig
from langgraph.types import Command

from agent_platform.domain.common.models import RunContext
from agent_platform.harness.agents import OrchestratorAgent
from agent_platform.harness.middleware.human_approval import (
    HumanApprovalMiddleware,
    ToolApprovalRejectedError,
)


async def main() -> None:
    context = RunContext(
        tenant_id="local",
        user_id="developer",
        project_id="demo",
    )

    agent = OrchestratorAgent(
        middleware=[
            HumanApprovalMiddleware(
                approval_tools={"write_todos"},
            ),
        ],
    )
    graph = agent.build(context)

    config: RunnableConfig = {
        "configurable": {
            "thread_id": context.checkpoint_thread,
        },
        "recursion_limit": 30,
    }

    task = """
    请制定一个三步 Python 学习计划。
    必须调用一次 write_todos 保存计划，三个任务全部标记为 pending。
    不执行计划，不委派子代理。
    保存后简短说明计划。
    """

    try:
        result = await graph.ainvoke(
            {"messages": [("user", task)]},
            context=context,
            config=config,
        )

        if not result.get("__interrupt__"):
            print("本次没有触发审批，请检查模型是否调用了 write_todos。")
            print(result["messages"][-1].content)
            return

        while result.get("__interrupt__"):
            print("\n任务已暂停，等待人工审批。")
            print("当前已保存的计划：", result.get("todos", []))

            decisions: dict[str, bool] = {}

            for pending in result["__interrupt__"]:
                print(
                    json.dumps(
                        pending.value,
                        ensure_ascii=False,
                        indent=2,
                    )
                )

                answer = ""
                while answer not in {"y", "n"}:
                    answer = (
                        await asyncio.to_thread(
                            input,
                            "允许执行？输入 y 同意，n 拒绝：",
                        )
                    ).strip().lower()

                decisions[pending.id] = answer == "y"

            # 恢复同一个图、同一个线程，不能重新发送原任务。
            result = await graph.ainvoke(
                Command(resume=decisions),
                context=context,
                config=config,
            )

    except ToolApprovalRejectedError as exc:
        print(f"\n审批被拒绝，本次执行结束：{exc}")
        return

    print("\n任务执行结束。")
    print("已保存的计划：", result.get("todos", []))

    for message in result["messages"]:
        if (
            isinstance(message, ToolMessage)
            and message.name == "write_todos"
        ):
            print("write_todos 返回：", message.content)

    print("\n模型最终回复：")
    print(result["messages"][-1].content)


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s | %(message)s",
        stream=sys.stdout,
    )

    asyncio.run(main())