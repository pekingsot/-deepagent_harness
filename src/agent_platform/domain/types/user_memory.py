"""用户记忆的内容约束和查询投影，不依赖数据库或 Agent 框架。"""

from datetime import datetime

from pydantic import Field, field_validator

from agent_platform.domain.types.common import StrictModel


class MemoryContent(StrictModel):
    """新增和修改记忆共用的内容约束。"""

    content: str = Field(min_length=1, max_length=8000)  # 一条完整、独立的记忆正文

    @field_validator("content")
    @classmethod
    def normalize(cls, value: str) -> str:
        """去除首尾空白，拒绝没有实际内容的记忆。"""
        value = value.strip()
        if not value:
            raise ValueError("记忆内容不能为空")
        return value


class UserMemory(StrictModel):
    """记忆列表的只读投影，不包含向量和数据库对象。"""

    id: int = Field(gt=0)  # 后续修改、删除使用的记忆编号
    content: str = Field(min_length=1)  # 当前保存的完整正文
    created_at: datetime  # 最初保存时间
    updated_at: datetime  # 最近修改时间
