import asyncio
import logging
import sys
from langchain_core.runnables import RunnableConfig
from langgraph.types import Command

from agent_platform.domain.common.models import RunContext
from agent_platform.harness.agents import OrchestratorAgent
from agent_platform.harness.tools.builtins.ask_user import ask_user

async def main() -> None:
    context = RunContext(
        tenant_id="local",
        user_id="developer",
        project_id="demo",
    )

    agent = OrchestratorAgent(
        tools=[ask_user],
    )
    graph = agent.build(context)

    config: RunnableConfig = {
        "configurable": {"thread_id": "1"},
        "recursion_limit": 30,
    }

    task = """
    请帮我制定 Python 学习计划。

    你还不知道我每天能学习多久。
    请先调用 ask_user 询问每天可投入的学习时间。
    得到回答后，再调用 write_todos 保存三步学习计划。
    所有计划项保持 pending，不执行计划。
    """

    result = await graph.ainvoke(
        {"messages": [("user", task)]},
        context=context,
        config=config,
    )

    while result.get("__interrupt__"):
        answers: dict[str, str] = {}

        for pending in result["__interrupt__"]:
            payload = pending.value

            if (
                not isinstance(payload, dict)
                or payload.get("type") != "user_input"
            ):
                raise ValueError(f"不支持的中断类型：{payload}")

            print("\nAgent 提问：", payload["question"])

            answer = ""
            while not answer:
                answer = (
                    await asyncio.to_thread(input, "你的回答：")
                ).strip()

            answers[pending.id] = answer

        result = await graph.ainvoke(
            Command(resume=answers),
            context=context,
            config=config,
        )

    print("\n最终回复：")
    print(result["messages"][-1].content)
    print("\n已保存的计划：")
    print(result.get("todos", []))

if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s | %(message)s",
        stream=sys.stdout,
    )

    asyncio.run(main())