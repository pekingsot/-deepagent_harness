"""供前端消费的任务执行事件。"""

from pydantic import Field, JsonValue

from agent_platform.domain.types.common import StrictModel


class TaskEvent(StrictModel):
    id: str  # Redis Stream 事件编号，也是 SSE 的事件编号
    event: str = Field(pattern=r"^[a-z_]{1,32}$")  # 事件类型
    data: dict[str, JsonValue]  # 可序列化的进度、文本或人工提问
