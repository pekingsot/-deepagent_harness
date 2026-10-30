import asyncio
from uuid import UUID

from langchain_core.runnables import RunnableConfig

from agent_platform.domain.types.common import TaskContext
from agent_platform.infrastructure.harness.agents import TaskPlanningAgent
from agent_platform.infrastructure.harness.tools.builtins.ask_user import ask_user
from agent_platform.infrastructure.cache.redis import get_redis
from agent_platform.infrastructure.checkpoint.redis_checkpoint import (
    get_redis_checkpointer,
)


async def main() -> None:
    context = TaskContext(
        tenant_id="local",
        user_id="developer",
        project_id="demo",
        thread_id=UUID(int=1001),
        task_id=UUID(int=1001),
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

        agent = TaskPlanningAgent(
            tools=[ask_user],
        )
        graph = agent.build(context)

        # 防止重复运行时覆盖已有的测试线程。
        snapshot = await graph.aget_state(config)
        if snapshot.values or snapshot.tasks:
            raise RuntimeError(
                "这个测试线程已经有状态。"
                "请运行恢复脚本，或同时修改两个脚本的 thread_id。"
            )

        result = await graph.ainvoke(
            {
                "messages": [
                    (
                        "user",
                        "请制定一个三步 Python 学习计划。"
                        "必须先调用 ask_user，询问我每天能学习多久。"
                        "在收到回答之前，不要制定计划。"
                        "收到回答后，用 write_todos 保存计划，"
                        "所有任务保持 pending。",
                    )
                ],
            },
            context=context,
            config=config,
        )

        pending = result.get("__interrupt__", ())

        if not pending:
            print("没有触发中断，本次未验证到暂停保存。")
            print(result["messages"][-1].content)
            return

        print("线程：", context.checkpoint_thread)

        for item in pending:
            print("中断 ID：", item.id)
            print("中断内容：", item.value)

        print("\n任务已暂停，现在退出程序。")
        print("不要在这里回答，请启动 demo_checkpoint_resume.py。")

    finally:
        get_redis_checkpointer.cache_clear()
        await redis.shutdown()


if __name__ == "__main__":
    asyncio.run(main())