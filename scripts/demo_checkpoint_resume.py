import asyncio
from uuid import UUID

from langchain_core.runnables import RunnableConfig
from langgraph.types import Command

from agent_platform.domain.common.models import RunContext
from agent_platform.harness.agents import OrchestratorAgent
from agent_platform.harness.tools.builtins.ask_user import ask_user
from agent_platform.infrastructure.cache.redis import get_redis
from agent_platform.infrastructure.checkpoint.redis_checkpoint import (
    get_redis_checkpointer,
)


async def main() -> None:
    # 与启动脚本保持相同的身份和线程。
    context = RunContext(
        tenant_id="local",
        user_id="developer",
        project_id="demo",
        thread_id=UUID(int=1001),
        run_id=UUID(int=1001),
    )

    config: RunnableConfig = {
        "configurable": {
            "thread_id": context.checkpoint_thread,
        },
        "recursion_limit": 30,
    }

    redis = get_redis()

    try:
        await redis.init()
        checkpointer = get_redis_checkpointer()
        await checkpointer.asetup()

        # 新进程重新构建相同的图。
        agent = OrchestratorAgent(
            tools=[ask_user],
        )
        graph = agent.build(context)

        snapshot = await graph.aget_state(config)
        pending = [
            item
            for task in snapshot.tasks
            for item in task.interrupts
        ]

        if not pending:
            print("没有找到待回答的中断。")
            print("请确认启动脚本已暂停，并且使用同一个 Redis 和线程。")
            return

        print("从 Redis 读到原来的中断。")
        print("线程：", context.checkpoint_thread)

        while pending:
            answers: dict[str, str] = {}

            for item in pending:
                payload = item.value

                if (
                    not isinstance(payload, dict)
                    or payload.get("type") != "user_input"
                ):
                    raise ValueError(f"不是用户输入中断：{payload}")

                print("\nAgent 提问：", payload["question"])
                print("中断 ID：", item.id)

                answer = ""
                while not answer:
                    answer = (
                        await asyncio.to_thread(input, "你的回答：")
                    ).strip()

                answers[item.id] = answer

            # 提交恢复结果，不重新提交原任务。
            result = await graph.ainvoke(
                Command(resume=answers),
                context=context,
                config=config,
            )

            pending = list(result.get("__interrupt__", ()))

        print("\n恢复执行完成。")
        print("最终回复：", result["messages"][-1].content)
        print("学习计划：", result.get("todos", []))

    finally:
        get_redis_checkpointer.cache_clear()
        await redis.shutdown()


if __name__ == "__main__":
    asyncio.run(main())