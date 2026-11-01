from functools import cached_property
from pathlib import Path
from typing import ClassVar

from deepagents import create_deep_agent
from langchain.agents.middleware import TodoListMiddleware
from langchain.agents.middleware.summarization import SummarizationMiddleware
from agent_platform.domain.types.common import TaskContext
from agent_platform.infrastructure.harness.agents.base import AgentGraph, BaseAgent
from agent_platform.infrastructure.harness.middleware.custom_model_call_limit import (
    CustomModelCallLimitMiddleware,
)
from agent_platform.infrastructure.harness.middleware.custom_model_fallback import (
    CustomModelFallbackMiddleware,
)
from agent_platform.infrastructure.harness.middleware.custom_model_retry import (
    CustomModelRetryMiddleware,
)
from agent_platform.infrastructure.harness.middleware.custom_tool_call_limit import (
    CustomToolCallLimitExceededMiddleware,
)
from agent_platform.infrastructure.harness.middleware.custom_tool_permission import (
    CustomToolPermissionMiddleware,
)
from agent_platform.infrastructure.harness.middleware.tool_call_audit import ToolCallAuditMiddleware
from agent_platform.infrastructure.model_providers.base import ModelProvider
from agent_platform.infrastructure.model_providers.providers.deepseek_provider import (
    DeepSeekProvider,
)
from agent_platform.infrastructure.model_providers.providers.qwen_provider import QwenProvider


class TaskPlanningAgent(BaseAgent):
    """任务规划 Agent 的框架配置，不负责领域任务状态转换。"""

    name = "task_planning"  # 应用选择该 Agent 时使用的注册名
    description = "Plan tasks, coordinate specialists, and synthesize results."  # 工具委派说明
    directory = Path(__file__).resolve().parent  # 本 Agent 的 Prompt 和 Skills 目录
    provider_class = DeepSeekProvider  # 当前默认聊天模型提供者
    fallback_provider_class: ClassVar[type[ModelProvider]] = QwenProvider  # 备用模型提供者

    @cached_property
    def fallback_provider(self) -> ModelProvider:
        """复用备用 Provider，避免每次构建图都重新创建客户端。"""
        return self.fallback_provider_class()

    def build(self, context: TaskContext) -> AgentGraph:
        return create_deep_agent(
            name=self.name,
            model=self.model(context),
            system_prompt=self.system_prompt(),
            tools=self.tools,
            middleware=[
                SummarizationMiddleware(
                    model=self.model(context),
                    backend=self.backend,
                    trigger=("tokens", 16000),  # 估算上下文达到此阈值时触发压缩
                    keep=("tokens", 4000),  # 保留近期消息的 token 预算
                    trim_tokens_to_summarize=None,  # 不预先裁掉待摘要的旧历史
                ),
                # HumanApprovalMiddleware(approval_tools={"write_todos"}),
                CustomModelCallLimitMiddleware(max_calls=10),
                CustomToolCallLimitExceededMiddleware(max_calls=20, tool_limits={}),
                ToolCallAuditMiddleware(),
                CustomToolPermissionMiddleware(deny_tools=set()),
                CustomModelFallbackMiddleware(
                    fallback_model=self.fallback_provider.get_model(context)
                ),
                CustomModelRetryMiddleware(),
                TodoListMiddleware(),
                *self.middleware,
            ],
            backend=self.backend(),
            permissions=self.permissions(),
            skills=["/skills/"],
            subagents=[agent.as_subagent(context) for agent in self.subagents],
            context_schema=TaskContext,
            checkpointer=self.checkpointer,
        )
