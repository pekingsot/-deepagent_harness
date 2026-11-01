# 本次分布式追踪改动

代码片段是修改后的实际内容，无加减号，可复制。行号对应生成本文件时的代码；后续编辑可能变化。本次没有修改领域模型、应用服务业务方法、数据库表或用户 .env。


## src/agent_platform/application/dto/trace_context.py

完整路径：`D:\project\deepagent\deepagent_ddd\src\agent_platform\application\dto\trace_context.py`


新增文件。


第 1 行起：

```python
"""跨进程传递的纯数据，不包含 SDK 对象。"""

from pydantic import Field, field_validator

from agent_platform.domain.types.common import StrictModel


class TraceContext(StrictModel):
    trace_id: str = Field(pattern=r"^[0-9a-f]{32}$")  # 一轮交互的追踪编号
    parent_span_id: str = Field(pattern=r"^[0-9a-f]{16}$")  # 发送端当前执行片段

    @field_validator("trace_id", "parent_span_id")
    @classmethod
    def reject_zero(cls, value: str) -> str:
        if int(value, 16) == 0:
            raise ValueError("追踪编号不能全为零")
        return value
```


## src/agent_platform/application/dto/agent_task_dto.py

完整路径：`D:\project\deepagent\deepagent_ddd\src\agent_platform\application\dto\agent_task_dto.py`


**TaskJob：第 61 行起。**

```python
class TaskJob(StrictModel):
    trace_context: TraceContext | None = None  # 发送端追踪上下文，旧消息允许为空
    context: TaskContext  # 服务端生成的任务身份和执行上下文
    resume: ResumeAgentTask | None = None  # 为空表示首次执行，否则携带人工回复
```


## src/agent_platform/infrastructure/observability/redis_trace_context.py

完整路径：`D:\project\deepagent\deepagent_ddd\src\agent_platform\infrastructure\observability\redis_trace_context.py`


新增文件。


第 1 行起：

```python
"""复用已有 Redis，保存人工恢复与合并消息所需的追踪上下文。"""

import logging

from redis.asyncio import Redis

from agent_platform.application.dto.trace_context import TraceContext
from agent_platform.domain.aggregates.agent_task import AgentTask
from agent_platform.infrastructure.harness.runtime.checkpoint_namespace import checkpoint_thread

logger = logging.getLogger(__name__)


class RedisTraceContextStore:
    def __init__(self, client: Redis) -> None:
        self._client = client  # 共享连接池，不单独创建或关闭客户端

    @staticmethod
    def key(task: AgentTask, suffix: str) -> str:
        return f"harness:tracing:{checkpoint_thread(task.context)}:{task.id}:{suffix}"

    async def get(self, task: AgentTask, suffix: str) -> TraceContext | None:
        try:
            value = await self._client.get(self.key(task, suffix))
            return TraceContext.model_validate_json(value) if value else None
        except Exception:
            logger.warning("读取追踪上下文失败，继续业务执行", exc_info=True)
            return None

    async def put(self, task: AgentTask, suffix: str, context: TraceContext) -> None:
        try:
            # 不设置短 TTL，避免等待人工处理期间失去关联；按任务归档时统一清理。
            await self._client.set(self.key(task, suffix), context.model_dump_json())
        except Exception:
            logger.warning("保存追踪上下文失败，继续业务执行", exc_info=True)
```


## src/agent_platform/infrastructure/observability/langfuse.py

完整路径：`D:\project\deepagent\deepagent_ddd\src\agent_platform\infrastructure\observability\langfuse.py`


集中实现：客户端初始化、上下文读取、边界追踪、恢复关联、Span Link 与关闭。


第 1 行起：

```python
"""使用 Langfuse 官方 LangChain 回调采集模型、工具和子图执行。"""

import logging
import sys
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager, contextmanager
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
            "tags": ["agent-platform", task.agent, operation],
            "metadata": {
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
    ) -> Iterator[TraceContext | None]:
        """隔离追踪错误，业务异常和取消信号仍向外传播。"""
        if self._client is None:
            yield None
            return
        try:
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
            manager.__enter__()
        except Exception:
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
                manager.__exit__(*error)
            except Exception:
                logger.warning("结束异常追踪片段失败", exc_info=True)
            raise
        else:
            try:
                manager.__exit__(None, None, None)
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
```


## src/agent_platform/infrastructure/messaging/redis_job_queue.py

完整路径：`D:\project\deepagent\deepagent_ddd\src\agent_platform\infrastructure\messaging\redis_job_queue.py`


**RedisJobQueue.__init__：第 15 行起。**

```python
    def __init__(
        self,
        *,
        client: Redis,
        stream_name: str,
        group_name: str,
        tracing: LangfuseTracing | None = None,
    ) -> None:
        self._tracing = tracing  # 共享追踪资源，不保存某个任务的上下文
        if not stream_name.strip():
            raise ValueError("队列名称不能为空")

        if not group_name.strip():
            raise ValueError("消费组名称不能为空")

        self._client = client  # 复用已有的异步 Redis 客户端
        self._stream_name = stream_name  # 存放任务消息的 Stream
        self._group_name = group_name  # 共同分担任务的消费组
        self._consumer_name = uuid4().hex  # 当前队列实例的消费者标识
```


**RedisJobQueue.enqueue：第 49 行起。**

```python
    async def enqueue(self, context: TaskContext, *, resume: ResumeAgentTask | None = None) -> str:
        """将任务上下文序列化后写入队列。"""
        fields = {"context": context.model_dump_json()}
        trace_context = self._tracing.current_context() if self._tracing else None
        if trace_context:
            fields["trace_context"] = trace_context.model_dump_json()
        if resume is not None:
            fields["resume"] = resume.model_dump_json()
        message_id = await self._client.xadd(
            name=self._stream_name,
            fields=fields,
        )

        return message_id
```


**RedisJobQueue.receive：第 64 行起。**

```python
    async def receive(
        self,
        *,
        timeout_seconds: int = 1,
    ) -> tuple[str, TaskJob] | None:
        """从消费组领取一条尚未投递的新消息。"""
        if timeout_seconds < 1:
            raise ValueError("领取消息的超时时间不能小于一秒")

        records = await self._client.xreadgroup(
            groupname=self._group_name,
            consumername=self._consumer_name,
            streams={
                self._stream_name: ">",
            },
            count=1,
            block=timeout_seconds * 1000,
        )

        if not records:
            return None

        # 返回结构：Stream 列表 → 消息列表 → 消息编号与字段
        _, messages = records[0]
        message_id, fields = messages[0]

        # 通过 JSON 入口恢复 UUID，并执行 TaskContext 的严格校验
        context = TaskContext.model_validate_json(
            fields["context"],
        )

        resume = (
            ResumeAgentTask.model_validate_json(fields["resume"]) if "resume" in fields else None
        )
        trace_context = None
        if "trace_context" in fields:
            try:
                trace_context = TraceContext.model_validate_json(fields["trace_context"])
            except ValueError:
                logging.getLogger(__name__).warning("队列追踪字段无效，继续处理业务消息")
        return message_id, TaskJob(context=context, resume=resume, trace_context=trace_context)
```


## src/agent_platform/workers/agent_task_worker.py

完整路径：`D:\project\deepagent\deepagent_ddd\src\agent_platform\workers\agent_task_worker.py`


**AgentTaskWorker.__init__：第 25 行起。**

```python
    def __init__(
        self,
        *,
        session_factory: async_sessionmaker[AsyncSession],
        queue: JobQueue,
        service: AgentTaskApplicationService,
        authentication: AuthenticationApplicationService,
        tracing: LangfuseTracing | None = None,
    ) -> None:
        self._tracing = tracing  # 当前进程共享的追踪资源
        self._session_factory = session_factory  # 消费者上下文使用的会话工厂
        self._queue = queue  # 任务队列接口
        self._service = service  # 任务应用服务接口
        self._authentication = authentication  # 执行前复核账号状态
```


**AgentTaskWorker.consume：第 40 行起。**

```python
    async def consume(self, stop_event: asyncio.Event) -> None:
        """持续领取任务，收到停止信号后不再领取新任务。"""
        async with sessionmaker_context(self._session_factory):
            while not stop_event.is_set():
                message = await self._queue.receive(
                    timeout_seconds=1,
                )

                if message is None:
                    continue

                message_id, job = message
                context = job.context

                scope = (
                    self._tracing.observation(
                        "worker.consume",
                        parent=job.trace_context,
                        metadata={"task_id": str(context.task_id), "queue_message_id": message_id},
                    )
                    if self._tracing
                    else nullcontext()
                )
                with scope:
                    logger.info(
                        "开始处理任务，task_id=%s，message_id=%s",
                        context.task_id,
                        message_id,
                    )

                    try:
                        await self._authentication.require_active_principal(context)
                        if job.resume is None:
                            await self._service.execute(principal=context, task_id=context.task_id)
                        else:
                            await self._service.resume(
                                principal=context, task_id=context.task_id, command=job.resume
                            )

                        # 应用服务完成执行并保存业务状态后，再确认队列消息
                        await self._queue.acknowledge(message_id)

                    except AuthenticationError:
                        # 停用账号后不再执行排队任务，保留任务记录。
                        try:
                            await self._service.cancel(context, context.task_id)
                        except (ConflictError, NotFoundError):
                            pass
                        await self._queue.acknowledge(message_id)
                        logger.info("账号不可用，已拒绝任务：task_id=%s", context.task_id)

                    except (ConflictError, NotFoundError, ValueError):
                        # 已取消任务、重复指令及无效回复不应阻塞后续任务。
                        logger.warning("任务指令已拒绝，task_id=%s", context.task_id, exc_info=True)
                        await self._queue.acknowledge(message_id)

                    except asyncio.CancelledError:
                        # 关闭超时导致取消时，不确认未处理完成的消息
                        logger.warning(
                            "任务消费被取消，消息未确认，task_id=%s",
                            context.task_id,
                        )
                        raise

                    except Exception:
                        # 暂时向上抛出，让启动管理感知故障，不能静默丢失消息
                        logger.exception(
                            "任务处理异常，消息未确认，task_id=%s",
                            context.task_id,
                        )
                        raise

                    logger.info(
                        "任务消息处理完成，task_id=%s",
                        context.task_id,
                    )
```


**_run：第 118 行起。**

```python
async def _run() -> None:
    """独立 Worker 进程入口，与 API 使用同一套消费代码。"""
    from agent_platform.bootstrap.authentication import get_authentication_application_service
    from agent_platform.bootstrap.lifespan import start_workers
    from agent_platform.bootstrap.wiring import (
        get_agent_task_application_service,
        get_task_queue,
        get_tracing,
        open_container,
    )

    async with open_container() as container:
        worker = AgentTaskWorker(
            session_factory=container.database.session_factory,
            queue=get_task_queue(),
            tracing=get_tracing(),
            service=get_agent_task_application_service(runtime=container.runtime),
            authentication=get_authentication_application_service(),
        )
        async with start_workers(consume=worker.consume, concurrency=1):
            await asyncio.Event().wait()
```


## src/agent_platform/bootstrap/wiring.py

完整路径：`D:\project\deepagent\deepagent_ddd\src\agent_platform\bootstrap\wiring.py`


**get_tracing：第 97 行起。**

```python
@lru_cache(maxsize=1)
def get_tracing() -> LangfuseTracing:
    """启动 Redis 后装配追踪资源，不向业务容器添加服务。"""
    return LangfuseTracing(LangfuseSettings(), RedisTraceContextStore(get_redis().client))
```


**get_task_queue：第 103 行起。**

```python
@lru_cache(maxsize=1)
def get_task_queue() -> RedisJobQueue:
    """取得当前进程的任务队列，Redis 必须已完成初始化。"""
    settings = get_settings()
    return RedisJobQueue(
        client=get_redis().client,
        stream_name=settings.task_queue_stream,
        group_name=settings.task_queue_group,
        tracing=get_tracing(),
    )
```


**open_container：第 149 行起。**

```python
@asynccontextmanager
async def open_container() -> AsyncIterator[Container]:
    settings = get_settings()

    async with AsyncExitStack() as stack:
        # Redis 先初始化，再装配依赖它的追踪和队列资源。
        # 退出时先停止 Worker，再关闭业务资源、追踪与 Redis。
        redis = get_redis()

        stack.push_async_callback(redis.shutdown)
        await redis.init()
        tracing = get_tracing()
        stack.callback(get_tracing.cache_clear)
        stack.push_async_callback(asyncio.to_thread, tracing.shutdown)
        from agent_platform.bootstrap.authentication import (
            clear_authentication_services,
            get_password_hasher,
        )

        stack.callback(clear_authentication_services)
        await asyncio.to_thread(get_password_hasher)
        stack.callback(get_task_queue.cache_clear)
        stack.callback(get_task_events.cache_clear)
        stack.callback(_build_runtime.cache_clear)
        stack.callback(get_agent_task_application_service.cache_clear)
        queue = get_task_queue()
        await queue.setup()

        database = Database(settings.database_url)
        stack.push_async_callback(database.close)
        checkpointer: BaseCheckpointSaver[Any]
        if settings.checkpoint_backend == "redis":
            saver = get_redis_checkpointer()
            stack.callback(get_redis_checkpointer.cache_clear)

            await saver.asetup()
            checkpointer = saver

        else:
            postgres = get_postgres_checkpoint()

            stack.push_async_callback(postgres.shutdown)
            await postgres.init()

            checkpointer = postgres.saver

        # 提前加载向量模型，完成后再接收请求或任务
        from agent_platform.infrastructure.embeddings.bge import get_embeddings

        await asyncio.to_thread(get_embeddings)

        yield build_container(
            settings=settings,
            checkpointer=checkpointer,
            database=database,
            tracing=tracing,
        )
```


## src/agent_platform/bootstrap/lifespan.py

完整路径：`D:\project\deepagent\deepagent_ddd\src\agent_platform\bootstrap\lifespan.py`


**lifespan：第 8 行起。**

```python
@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """按配置随 API 启动消费者，先停消费者再释放共享资源。"""
    from contextlib import AsyncExitStack

    from agent_platform.bootstrap.authentication import get_authentication_application_service
    from agent_platform.bootstrap.wiring import (
        get_agent_task_application_service,
        get_task_queue,
        get_tracing,
        open_container,
    )
    from agent_platform.workers.agent_task_worker import AgentTaskWorker

    async with open_container() as container:
        app.state.container = container
        try:
            async with AsyncExitStack() as stack:
                if container.settings.worker_enabled:
                    if container.settings.worker_concurrency != 1:
                        raise ValueError("当前联调阶段请设置 HARNESS_WORKER_CONCURRENCY=1")
                    worker = AgentTaskWorker(
                        session_factory=container.database.session_factory,
                        queue=get_task_queue(),
                        tracing=get_tracing(),
                        authentication=get_authentication_application_service(),
                        service=get_agent_task_application_service(
                            runtime=container.runtime,
                        ),
                    )
                    await stack.enter_async_context(
                        start_workers(consume=worker.consume, concurrency=1)
                    )
                yield
        finally:
            del app.state.container
```


## src/agent_platform/interface/api/dependencies.py

完整路径：`D:\project\deepagent\deepagent_ddd\src\agent_platform\interface\api\dependencies.py`


**get_tracing：第 120 行起。**

```python
def get_tracing() -> LangfuseTracing:
    """接口通过装配入口取得追踪能力，不自行创建 SDK。"""
    from agent_platform.bootstrap.wiring import get_tracing as assembled_tracing

    return assembled_tracing()
```


第 127 行定义 `CurrentTracing = Annotated[LangfuseTracing, Depends(get_tracing)]`，并引入 `LangfuseTracing`。


## src/agent_platform/interface/api/routes/v1/agent_tasks.py

完整路径：`D:\project\deepagent\deepagent_ddd\src\agent_platform\interface\api\routes\v1\agent_tasks.py`


**create_task：第 35 行起。**

```python
@router.post("", response_model=AgentTaskResponse, status_code=status.HTTP_202_ACCEPTED)
async def create_task(
    request: CreateAgentTaskRequest,
    principal: CurrentPrincipal,
    response: Response,
    tracing: CurrentTracing,
    service: CurrentTaskApplicationService,
) -> AgentTaskResponse:
    """保存任务后入队，返回编号，由 Worker 异步执行。"""
    async with tracing.api("create") as context:
        task = await service.create(principal, request.to_command())
        if context:
            response.headers["X-Trace-ID"] = context.trace_id
    return AgentTaskResponse.from_task(task)
```


**resume_task：第 66 行起。**

```python
@router.post("/{task_id}/resume", response_model=AgentTaskResponse, status_code=202)
async def resume_task(
    task_id: UUID,
    command: ResumeAgentTask,
    principal: CurrentPrincipal,
    response: Response,
    tracing: CurrentTracing,
    service: CurrentTaskApplicationService,
) -> AgentTaskResponse:
    """人工回复入队，202 表示已接收，执行结果通过 SSE 或查询接口获取。"""
    try:
        owned_task = await service.get(principal, task_id)
        async with tracing.api("resume", task=owned_task) as context:
            task = await service.request_resume(principal, task_id, command)
            if context:
                response.headers["X-Trace-ID"] = context.trace_id
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return AgentTaskResponse.from_task(task)
```


**send_message：第 221 行起。**

```python
@router.post("/{task_id}/messages", response_model=AgentTaskResponse, status_code=202)
async def send_message(
    task_id: UUID,
    request: SendTaskMessageRequest,
    principal: CurrentPrincipal,
    response: Response,
    tracing: CurrentTracing,
    service: CurrentTaskApplicationService,
) -> AgentTaskResponse:
    """追加同一会话的消息，执行中收到的补充先入库排队。"""
    try:
        owned_task = await service.get(principal, task_id)
        async with tracing.api("message", task=owned_task, message_id=str(request.id)) as context:
            task = await service.send_message(principal, task_id, request.id, request.content)
            if context:
                response.headers["X-Trace-ID"] = context.trace_id
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return AgentTaskResponse.from_task(task)
```


## src/agent_platform/infrastructure/harness/runtime/deepagents_task_runtime.py

完整路径：`D:\project\deepagent\deepagent_ddd\src\agent_platform\infrastructure\harness\runtime\deepagents_task_runtime.py`


**DeepAgentsTaskRuntime._invoke：第 243 行起。**

```python
    async def _invoke(
            self,
            graph: AgentGraph,
            task: AgentTask,
            inputs: dict | Command,
            on_text: Callable[[str], Awaitable[None]] | None,
            on_plan: Callable[
                         [tuple[TaskPlanItem, ...]],
                         Awaitable[None],
                     ] | None,
            on_activity: Callable[
                             [TaskActivity],
                             Awaitable[None],
                         ] | None,
            *,
            operation: Literal["execute", "resume"],
    ) -> None:
        # 追踪范围覆盖完整异步执行和流式迭代，不改变业务与事件处理。
        message_ids = tuple(
            str(item["id"]) for item in inputs.get("messages", []) if "id" in item
        ) if isinstance(inputs, dict) else ()
        if self._tracing is None:
            await self._invoke_graph(graph, task, inputs, on_text, on_plan, on_activity,
                                     operation=operation)
            return
        async with self._tracing.agent(task, operation, message_ids):
            await self._invoke_graph(graph, task, inputs, on_text, on_plan, on_activity,
                                     operation=operation)
```


原 `_invoke` 主体改名 `_invoke_graph`；原有流式解析保留，`invocation_config` 现在拿到上面 Agent 片段的上下文。


## frontpages/src/app/api/backend/[...path]/route.ts

完整路径：`D:\project\deepagent\deepagent_ddd\frontpages\src\app\api\backend\[...path]\route.ts`

第 60 行起，响应透传：

```typescript
    const traceId = upstream.headers.get("x-trace-id");
    if (traceId) response.headers.set("X-Trace-ID", traceId);
```


## 依赖、测试与文档

- pyproject.toml：显式声明 opentelemetry-api>=1.39,<2，用于 Span Link；uv.lock 只为本次补充根项目的这条已有传递依赖，未执行安装或升级。
- tests/unit/test_distributed_tracing.py：新增离线测试，覆盖 API/队列/Worker 范围/Agent 上下文、重启恢复、并发、取消、合并消息、技术故障与旧字段。
- tests/unit/test_langfuse_tracing.py：原 6 项测试继续通过，没有改动。
- frontpages/tests/auth-proxy.test.cjs：新增 Trace 响应头透传与不接收伪造 traceparent 的测试。
- docs/plan/langfuse_tracing.md：更新追踪规则与实际联调步骤。
- docs/plan/current_progress.md：精简交接摘要，新窗口用它恢复项目上下文。

说明：部分原有文件为整理导入/格式有少量排版变化。本次前端业务只增加 BFF 响应头透传，不改聊天交互。没有做 Git 暂存或提交；工作区已有改动继续保留。
