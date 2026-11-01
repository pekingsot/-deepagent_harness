"""个人中心的记忆编辑参数，复用领域内容约束。"""

from agent_platform.domain.types.user_memory import MemoryContent


class UpdateUserMemoryRequest(MemoryContent):
    """只接收完整内容，身份和记忆编号不允许在请求体中覆盖。"""
