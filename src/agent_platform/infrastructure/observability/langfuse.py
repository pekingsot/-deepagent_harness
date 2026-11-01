"""使用 Langfuse 官方 LangChain 回调采集模型、工具和子图执行。"""

import logging
import sys
from collections.abc import AsyncIterator, Iterator
from contextlib import ExitStack, asynccontextmanager, contextmanager
from typing import TYPE_CHECKING, Literal
from uuid import uuid4

from langchain_core.runnables import RunnableConfig

from agent_platform.application.dto.trace_context import TraceContext
from agent_platform.domain.aggregates.agent_task import AgentTask
from agent_platform.infrastructure.harness.runtime.checkpoint_namespace import checkpoint_thread
from agent_platform.infrastructure.observability.redis_trace_context import RedisTraceContextStore
from agent_platform.infrastructure.observability.settings import LangfuseSettings

if TYPE_CHECKING:
    from langfuse import Langfuse

logger = logging.getLogger(__name__)


class LangfuseTracing:
    """客户端按进程复用；有运行状态的回调按每次执行单独创建。"""

    def __init__(
        self, settings: LangfuseSettings, store: RedisTraceContextStore | None = None
    ) -> None:
        self._store = store  # 人工恢复所需的持久化上下文
        self._settings = settings  # 本模块的不可变配置
        self._public_key: str | None = None  # 官方回调选择当前进程的客户端
        self._client: Langfuse | None = None  # 由启动生命周期管理的 SDK 客户端
        if not settings.tracing_enabled:
            logger.info("Langfuse 追踪未启用")
            return
        # 关闭时不导入或初始化 SDK，避免隐式创建全局导出器。
        from langfuse import Langfuse as LangfuseClient

        assert settings.public_key is not None and settings.secret_key is not None
        self._public_key = settings.public_key.get_secret_value()
        try:
            self._client = LangfuseClient(
                public_key=self._public_key,
                secret_key=settings.secret_key.get_secret_value(),
                base_url=str(settings.base_url).rstrip("/"),
                tracing_enabled=True,
                environment=settings.tracing_environment,
                timeout=settings.timeout,
            )
        except Exception:
            logger.warning("Langfuse 初始化失败，暂时关闭追踪", exc_info=True)
            return

        logger.info("Langfuse 追踪客户端已初始化，environment=%s", settings.tracing_environment)

    @staticmethod
    def _tags(
        task: AgentTask | None = None,
        operation: str | None = None,
        boundary: str | None = None,
    ) -> list[str]:
        """用有限分类描述执行，不将用户、任务编号或输入正文放入标签。"""
        tags = ["agent-platform", "workflow:task"]
        if boundary:
            tags.append(f"boundary:{boundary}")
        if operation:
            tags.extend([operation, f"operation:{operation}"])
        if task:
            tags.extend([task.agent, f"agent:{task.agent}"])
            if boundary == "agent":
                tags.append("round:first" if task.attempt <= 1 else "round:followup")
        if operation in {"execute", "resume"}:
            tags.append(
                "invocation:human_resume" if operation == "resume" else "invocation:new_round"
            )
        return list(dict.fromkeys(tags))

    def invocation_config(
        self, task: AgentTask, operation: Literal["execute", "resume"]
    ) -> RunnableConfig:
        """回调初始化失败只影响追踪，不影响模型调用。"""
        try:
            return self._invocation_config(task, operation)
        except Exception:
            logger.warning("初始化模型追踪回调失败，继续业务执行", exc_info=True)
            return {}

    def _invocation_config(
        self,
        task: AgentTask,
        operation: Literal["execute", "resume"],
    ) -> RunnableConfig:
        if self._client is None:
            return {}
        from langfuse.langchain import CallbackHandler

        # 回调沿用当前 Agent 片段，模型、工具与子图保持官方父子关系。
        context = self.current_context()
        trace_id = context.trace_id if context else uuid4().hex
        handler = CallbackHandler(
            public_key=self._public_key,
            trace_context=context.model_dump() if context else {"trace_id": trace_id},
        )
        logger.info(
            "Agent 追踪：task_id=%s，attempt=%s，operation=%s，langfuse_trace_id=%s",
            task.id,
            task.attempt,
            operation,
            trace_id,
        )
        return {
            "callbacks": [handler],
            "run_name": f"{task.agent}.{operation}",
            "tags": self._tags(task, operation, "agent"),
            "metadata": {
                "langfuse_tags": self._tags(task, operation, "agent"),
                "langfuse_session_id": checkpoint_thread(task.context),
                "langfuse_user_id": f"{task.context.tenant_id}:{task.context.user_id}",
                "langfuse_trace_name": f"{task.agent}.{operation}",
                "task_id": str(task.id),
                "task_trace_id": str(task.context.trace_id),
                "thread_id": str(task.context.thread_id),
                "tenant_id": task.context.tenant_id,
                "project_id": task.context.project_id,
                "user_id": task.context.user_id,
                "attempt": task.attempt,
                "operation": operation,
            },
        }

    def current_context(self) -> TraceContext | None:
        """读取当前协程的 SDK 上下文，单例不保存请求状态。"""
        if self._client is None:
            return None
        try:
            trace_id = self._client.get_current_trace_id()
            span_id = self._client.get_current_observation_id()
            if isinstance(trace_id, str) and isinstance(span_id, str):
                return TraceContext(trace_id=trace_id, parent_span_id=span_id)
        except Exception:
            logger.warning("读取当前追踪上下文失败", exc_info=True)
        return None

    @contextmanager
    def observation(
        self,
        name: str,
        *,
        parent: TraceContext | None = None,
        new_trace: bool = False,
        metadata: dict[str, object] | None = None,
        agent: bool = False,
        tags: list[str] | None = None,
    ) -> Iterator[TraceContext | None]:
        """隔离追踪错误，业务异常和取消信号仍向外传播。"""
        if self._client is None:
            yield None
            return
        stack = ExitStack()  # 当前协程的 SDK 片段与标签传播作用域
        try:
            from langfuse import propagate_attributes

            context = (
                parent.model_dump()
                if parent
                else ({"trace_id": uuid4().hex} if new_trace else None)
            )
            manager = self._client.start_as_current_observation(
                name=name,
                as_type="agent" if agent else "span",
                trace_context=context,
                metadata=metadata,
            )
            stack.enter_context(manager)
            stack.enter_context(
                propagate_attributes(
                    tags=tags or self._tags(boundary=name.partition(".")[0]),
                )
            )
        except Exception:
            try:
                stack.close()
            except Exception:
                logger.warning("清理未完成的追踪作用域失败", exc_info=True)
            logger.warning("创建追踪片段失败，继续业务执行", exc_info=True)
            yield None
            return
        try:
            active = self.current_context()
            logger.info(
                "追踪开始 name=%s trace_id=%s span_id=%s metadata=%s",
                name,
                active.trace_id if active else "-",
                active.parent_span_id if active else "-",
                metadata,
            )
            yield self.current_context()
        except BaseException:
            error = sys.exc_info()
            try:
                stack.__exit__(*error)
            except Exception:
                logger.warning("结束异常追踪片段失败", exc_info=True)
            raise
        else:
            try:
                stack.close()
            except Exception:
                logger.warning("结束追踪片段失败", exc_info=True)

    @asynccontextmanager
    async def api(
        self, operation: str, *, task: AgentTask | None = None, message_id: str | None = None
    ) -> AsyncIterator[TraceContext | None]:
        """新输入创建新 Trace；人工回复在鉴权后衔接原轮次。"""
        parent = None
        if self._client is not None and self._store and task and operation == "resume":
            parent = await self._store.get(task, f"round:{task.attempt}")
        with self.observation(
            f"api.tasks.{operation}",
            parent=parent,
            new_trace=parent is None,
            metadata={"task_id": str(task.id)} if task else {},
            tags=self._tags(task, operation, "api"),
        ) as context:
            if self._store and task and message_id and context:
                await self._store.put(task, f"message:{message_id}", context)
            yield context

    @asynccontextmanager
    async def agent(
        self, task: AgentTask, operation: str, message_ids: tuple[str, ...] = ()
    ) -> AsyncIterator[None]:
        """发布等待事件前保存轮次，跨进程人工恢复仍属于同一 Trace。"""
        with self.observation(
            f"{task.agent}.{operation}",
            metadata={"task_id": str(task.id), "attempt": task.attempt},
            agent=True,
            tags=self._tags(task, operation, "agent"),
        ) as context:
            if context and self._store:
                if operation == "execute":
                    await self._store.put(task, f"round:{task.attempt}", context)
                for message_id in message_ids:
                    source = await self._store.get(task, f"message:{message_id}")
                    if source:
                        self._link(source, message_id)
            yield

    def _link(self, source: TraceContext, message_id: str) -> None:
        """合并输入用 Span Link 表达多个来源，保持单一父节点。"""
        try:
            from opentelemetry import trace

            context = trace.SpanContext(
                trace_id=int(source.trace_id, 16),
                span_id=int(source.parent_span_id, 16),
                is_remote=True,
                trace_flags=trace.TraceFlags(1),
            )
            trace.get_current_span().add_link(context, {"message_id": message_id})
        except Exception:
            logger.warning("关联补充消息追踪失败", exc_info=True)

    def shutdown(self) -> None:
        """由启动层在线程中调用，发送待上报数据，避免阻塞事件循环。"""
        if self._client is not None:
            client, self._client = self._client, None
            try:
                client.shutdown()
            except Exception:
                logger.warning("Langfuse 关闭失败", exc_info=True)
