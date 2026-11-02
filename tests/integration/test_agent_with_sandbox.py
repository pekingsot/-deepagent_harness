import logging
import unittest

from langgraph.checkpoint.memory import InMemorySaver

from agent_platform.domain.types.common import TaskContext
from agent_platform.infrastructure.harness.agents import TaskPlanningAgent
from agent_platform.infrastructure.harness.backends.opensandbox import (
    OpenSandboxBackend,
)
from agent_platform.infrastructure.harness.runtime.checkpoint_namespace import (
    checkpoint_thread,
)
from agent_platform.infrastructure.sandbox.opensandbox import (
    OpenSandboxClient,
)
from agent_platform.infrastructure.sandbox.settings import (
    get_opensandbox_settings,
)

logger = logging.getLogger(__name__)


class AgentWithSandboxTests(unittest.IsolatedAsyncioTestCase):
    async def test_agent_executes_python_in_sandbox(self):
        settings = get_opensandbox_settings()
        client = OpenSandboxClient(settings)

        # 仅用于本次独立测试的身份和线程。
        context = TaskContext(
            tenant_id=1,
            user_id=1,
            project_id="sandbox-test",
        )

        sandbox = await client.create(
            metadata={
                "purpose": "agent-integration-test",
                "task_id": str(context.task_id),
            }
        )

        logger.info("测试沙箱创建成功：%s", sandbox.id)

        try:
            backend = OpenSandboxBackend(
                sandbox,
                command_timeout=settings.command_timeout_seconds,
            )

            # 每次测试独立创建 Agent 和 Checkpointer。
            agent = TaskPlanningAgent(
                backend=backend,
                checkpointer=InMemorySaver(),
            )

            graph = agent.build(context)

            await graph.ainvoke(
                {
                    "messages": [
                        (
                            "user",
                            """
请实际执行以下任务：

1. 在 /workspace/hello.py 写入 Python 程序：
   计算 1 + 1，并把字符串 2 写入
   /deliverables/result.txt。
2. 使用 execute 工具运行这个程序。
3. 读取 /deliverables/result.txt，确认结果。

请实际调用工具完成，不要只输出示例代码。
最后简短说明执行结果。
""",
                        )
                    ]
                },
                config={
                    "configurable": {
                        "thread_id": checkpoint_thread(context),
                    },
                    "recursion_limit": 50,
                },
                context=context,
            )

            # 从远端沙箱直接检查文件。
            # 验证依据是实际副作用，而不是模型声称自己成功了。
            actual = await sandbox.files.read_file(
                "/deliverables/result.txt"
            )

            logger.info("沙箱内的计算结果：%s", actual)
            self.assertEqual(actual.strip(), "2")

        finally:
            logger.info("销毁测试沙箱：%s", sandbox.id)
            await sandbox.destroy()
