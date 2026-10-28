"""长期记忆用例的数据结构。"""

from pydantic import Field

from agent_platform.domain.common.models import StrictModel


class MemoryMatch(StrictModel):
    """检索到的一条记忆。"""

    id: int = Field(gt=0)  # 记忆编号，用于后续定位、修改或删除
    content: str = Field(min_length=1)  # 记忆的文字内容
    similarity: float = Field(allow_inf_nan=False)  # 余弦相似度，越大越相似