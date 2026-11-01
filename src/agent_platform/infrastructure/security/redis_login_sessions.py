"""Redis 保存可撤销的登录会话，键中不存原始令牌或账号。"""

import hashlib
import secrets

from redis.asyncio import Redis

from agent_platform.application.dto.authentication_dto import LoginLimitedError
from agent_platform.application.interfaces.login_sessions import LoginSession, LoginSessions


class RedisLoginSessions(LoginSessions):
    def __init__(self, client: Redis, *, ttl: int, login_limit: int, login_window: int) -> None:
        self._client = client  # 复用进程共享的 Redis 连接池
        self._ttl = ttl  # 会话绝对过期秒数
        self._login_limit = login_limit  # 单账号窗口阈值
        self._login_window = login_window  # 登录窗口秒数

    @staticmethod
    def _key(token: str) -> str:
        return "auth:session:" + hashlib.sha256(token.encode()).hexdigest()

    async def create(self, session: LoginSession) -> str:
        token = secrets.token_urlsafe(32)
        await self._client.set(self._key(token), session.model_dump_json(), ex=self._ttl)
        return token

    async def get(self, token: str) -> LoginSession | None:
        if not 40 <= len(token) <= 128:
            return None
        data = await self._client.get(self._key(token))
        return LoginSession.model_validate_json(data) if data else None

    async def delete(self, token: str) -> None:
        await self._client.delete(self._key(token))

    async def check_login_limit(self, client: str, account: str) -> None:
        # Lua 保证计数和首次设置过期时间原子执行，避免永久锁定账号。
        script = "local n=redis.call('INCR',KEYS[1]); if n==1 then redis.call('EXPIRE',KEYS[1],ARGV[1]) end; return n"
        for kind, value, limit in (
            ("account", account, self._login_limit),
            ("client", client, self._login_limit * 10),
        ):
            key = f"auth:limit:{kind}:" + hashlib.sha256(value.encode()).hexdigest()
            count = await self._client.eval(script, 1, key, self._login_window)
            if int(count) > limit:
                raise LoginLimitedError(
                    "登录尝试过于频繁，请稍后重试", retry_after=self._login_window
                )
