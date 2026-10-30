from uuid import uuid4

from redis.asyncio import Redis
from redis.exceptions import ResponseError

from agent_platform.application.dto.agent_task_dto import ResumeAgentTask, TaskJob

from agent_platform.application.interfaces.job_queue import JobQueue
from agent_platform.domain.types.common import TaskContext


class RedisJobQueue(JobQueue):
    def __init__(
        self,
        *,
        client: Redis,
        stream_name: str,
        group_name: str,
    ) -> None:
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

    async def enqueue(
        self, context: TaskContext, *, resume: ResumeAgentTask | None = None
    ) -> str:
        """将任务上下文序列化后写入队列。"""
        fields = {"context": context.model_dump_json()}
        if resume is not None:
            fields["resume"] = resume.model_dump_json()
        message_id = await self._client.xadd(
            name=self._stream_name,
            fields=fields,
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
            ResumeAgentTask.model_validate_json(fields["resume"])
            if "resume" in fields
            else None
        )
        return message_id, TaskJob(context=context, resume=resume)

    async def acknowledge(self, message_id: str) -> None:
        """将消息从消费组的待确认列表中移除。"""
        await self._client.xack(
            self._stream_name,
            self._group_name,
            message_id,
        )
