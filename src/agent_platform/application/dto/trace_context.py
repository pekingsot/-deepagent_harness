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
