import logging
from uuid import uuid4

from redis.asyncio import Redis
from redis.exceptions import ResponseError

from agent_platform.application.dto.agent_task_dto import ResumeAgentTask, TaskJob
from agent_platform.application.dto.trace_context import TraceContext
from agent_platform.application.interfaces.job_queue import JobQueue
from agent_platform.domain.types.common import TaskContext
from agent_platform.infrastructure.observability.langfuse import LangfuseTracing


class RedisJobQueue(JobQueue):
    def _task_index(self, context: TaskContext) -> str:
        return (
            f"{self._stream_name}:task:{context.tenant_id}:{context.project_id}:"
            f"{context.user_id}:{context.task_id}"
        )

    async def _index_existing_jobs(self) -> None:
        """仅升级时遍历旧队列；持久化游标，后续启动直接跳过。"""
        progress = self._stream_name + ":task-index-v1"
        while True:
            cursor = await self._client.get(progress) or "-"
            if isinstance(cursor, bytes):
                cursor = cursor.decode()
            if cursor == "complete":
                return
            records = await self._client.xrange(
                self._stream_name,
                min="-" if cursor == "-" else f"({cursor}",
                count=200,
            )
            indexes = []
            ids = []
            for message_id, fields in records:
                context = TaskContext.model_validate_json(
                    fields.get("context", fields.get(b"context"))
                )
                indexes.append(self._task_index(context))
                ids.append(message_id)
            next_cursor = records[-1][0] if len(records) == 200 else "complete"
            # 并发启动只允许一个游标版本提交，重复处理同一页不会破坏索引。
            await self._client.eval(
                "local current = redis.call('GET', KEYS[1]) or '-'; "
                "if current ~= ARGV[1] then return 0 end; "
                "for i=2,#KEYS do redis.call('SADD', KEYS[i], ARGV[i+1]) end; "
                "redis.call('SET', KEYS[1], ARGV[2]); return 1",
                1 + len(indexes),
                progress,
                *indexes,
                cursor,
                next_cursor,
                *ids,
            )

    async def delete_task(self, context: TaskContext) -> None:
        """按会话索引分批清理，不再为每次删除扫描共享 Stream。"""
        ready = await self._client.get(self._stream_name + ":task-index-v1")
        if ready not in ("complete", b"complete"):
            raise RuntimeError("Queue task index is not ready; retry after startup migration")
        key = self._task_index(context)
        groups = await self._client.xinfo_groups(self._stream_name)
        group_names = [g.get("name", g.get(b"name")) for g in groups]
        while ids := await self._client.srandmember(key, number=200):
            pipeline = self._client.pipeline(transaction=True)
            for group in group_names:
                pipeline.xack(self._stream_name, group, *ids)
            pipeline.xdel(self._stream_name, *ids)
            pipeline.srem(key, *ids)
            await pipeline.execute()
        await self._client.delete(key)

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

    async def setup(self) -> None:
        """初始化消费组，允许多个进程重复调用。"""
        try:
            await self._client.xgroup_create(
                name=self._stream_name,
                groupname=self._group_name,
                id="0-0",
                mkstream=True,
            )
        except ResponseError as exc:
            # 多个进程同时启动时，消费组已存在属于正常情况
            if not str(exc).startswith("BUSYGROUP"):
                raise
        await self._index_existing_jobs()

    async def enqueue(self, context: TaskContext, *, resume: ResumeAgentTask | None = None) -> str:
        """将任务上下文序列化后写入队列。"""
        fields = {"context": context.model_dump_json()}
        trace_context = self._tracing.current_context() if self._tracing else None
        if trace_context:
            fields["trace_context"] = trace_context.model_dump_json()
        if resume is not None:
            fields["resume"] = resume.model_dump_json()
        arguments = [part for item in fields.items() for part in item]
        message_id = await self._client.eval(
            "local id = redis.call('XADD', KEYS[1], '*', unpack(ARGV)); "
            "redis.call('SADD', KEYS[2], id); return id",
            2,
            self._stream_name,
            self._task_index(context),
            *arguments,
        )

        return message_id

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

    async def acknowledge(self, message_id: str) -> None:
        """将消息从消费组的待确认列表中移除。"""
        records = await self._client.xrange(self._stream_name, min=message_id, max=message_id)
        pipeline = self._client.pipeline(transaction=True)
        pipeline.xack(self._stream_name, self._group_name, message_id)
        pipeline.xdel(self._stream_name, message_id)
        if records:
            fields = records[0][1]
            context = TaskContext.model_validate_json(fields.get("context", fields.get(b"context")))
            pipeline.srem(self._task_index(context), message_id)
        await pipeline.execute()
