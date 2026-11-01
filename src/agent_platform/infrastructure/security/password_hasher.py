"""复用 pwdlib 的 Argon2 实现，不自行设计密码算法。"""

from pwdlib import PasswordHash

from agent_platform.application.interfaces.password_hasher import PasswordHasher


class Argon2PasswordHasher(PasswordHasher):
    def __init__(self) -> None:
        self._hasher = PasswordHash.recommended()  # 开源库推荐的 Argon2 配置
        self._dummy = self._hasher.hash(
            "dummy-account-timing-normalization"
        )  # 不存在账号也执行密码校验

    def hash(self, password: str) -> str:
        return self._hasher.hash(password)

    def verify(self, password: str, password_hash: str | None) -> bool:
        valid = self._hasher.verify(password, password_hash or self._dummy)
        return valid and password_hash is not None
