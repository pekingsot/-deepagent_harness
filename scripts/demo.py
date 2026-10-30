"""Loads the project-root .env. Add --invoke to send a real model request."""

import asyncio
import logging
import sys
from langchain_core.messages import AIMessage, ToolMessage

from agent_platform.domain.types.common import TaskContext
from agent_platform.infrastructure.harness.agents import TaskPlanningAgent
from agent_platform.infrastructure.harness.middleware.custom_model_call_limit import ModelCallLimitExceededError
from agent_platform.infrastructure.model_providers.providers.deepseek_provider import (
    DeepSeekProvider,
)
from langchain.agents.middleware import TodoListMiddleware


async def main() -> None:
    # Local test identity only; production context must come from verified server identity.
    context = TaskContext(tenant_id="local", user_id="developer", project_id="demo")
    # 模型由 TaskPlanningAgent 自己选择
    agent = TaskPlanningAgent()
    graph = agent.build(context)

    task = """
    请规划一份产品比较报告，只规划，不执行。

    请按顺序完成：
    1. 第一次调用 write_todos，记录三个粗略步骤，全部保持 pending。
    2. 收到工具返回后，第二次调用 write_todos，
       将计划细化为五个步骤，全部保持 pending。
    3. 收到第二次工具返回后，再向我说明最终计划。

    两次 write_todos 必须分开进行。
    不要调用子代理，也不要联网。
    """
    last_count = 0

    try:
        async for state in graph.astream(
                {"messages": [("user", task)]},
                context=context,
                config={"recursion_limit": 30},
                stream_mode="values",
        ):
            count = state.get("model_call_count", 0)

            if count != last_count:
                print(f"允许进入第 {count} 轮模型调用")
                last_count = count

    except ModelCallLimitExceededError as exc:
        print(f"\n成功拦截超限调用：{exc}")
    else:
        print(f"\n任务正常结束，共记录 {last_count} 轮。")
        print("如果未尝试第三轮，本次没有触发超限分支。")
if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s | %(message)s",
        stream=sys.stdout,
    )

    logging.getLogger(__name__).info("日志初始化完成")
    asyncio.run(main())
