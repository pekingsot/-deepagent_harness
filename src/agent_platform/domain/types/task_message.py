from datetime import UTC, datetime
from typing import Literal
from uuid import UUID, uuid4

from pydantic import Field

from agent_platform.domain.types.common import StrictModel


class TaskMessage(StrictModel):
    """同一任务会话中的一条消息。"""

    id: UUID = Field(default_factory=uuid4)  # 消息唯一编号

    role: Literal["user", "assistant"]  # 消息发送方

    content: str = Field(min_length=1)  # 消息正文

    state: Literal[
        "pending",
        "processing",
        "applied",
        "failed",
        "cancelled",
    ] = "applied"  # 待处理、处理中、已处理、失败或用户取消

    position: int = 0  # 数据库生成的消息顺序，入库前默认为零

    created_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
    )  # 消息创建时间
