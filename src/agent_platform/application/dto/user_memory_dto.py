"""用户记忆管理用例的返回数据。"""

from pydantic import Field

from agent_platform.domain.types.common import StrictModel
from agent_platform.domain.types.user_memory import UserMemory


class UserMemoryPage(StrictModel):
    items: tuple[UserMemory, ...]  # 本页记忆，按编号从大到小排列
    next_cursor: int | None = Field(default=None, gt=0)  # 下一页游标，为空表示没有下一页
