"""认证模块装配；复用现有 Redis 和数据库上下文。"""

from functools import lru_cache

from agent_platform.application.services.authentication_application_service import (
    AuthenticationApplicationService,
)
from agent_platform.application.services.user_application_service import UserApplicationService
from agent_platform.domain.services.user_domain_service import UserDomainService
from agent_platform.infrastructure.cache.redis import get_redis
from agent_platform.infrastructure.persistence.repositories.user_repository import (
    PostgresUserRepository,
)
from agent_platform.infrastructure.security.password_hasher import Argon2PasswordHasher
from agent_platform.infrastructure.security.redis_login_sessions import RedisLoginSessions
from agent_platform.infrastructure.security.settings import get_authentication_settings


@lru_cache(maxsize=1)
def get_password_hasher() -> Argon2PasswordHasher:
    return Argon2PasswordHasher()


@lru_cache(maxsize=1)
def get_authentication_application_service() -> AuthenticationApplicationService:
    settings = get_authentication_settings()
    return AuthenticationApplicationService(
        PostgresUserRepository(),
        get_password_hasher(),
        RedisLoginSessions(
            get_redis().client,
            ttl=settings.session_ttl,
            login_limit=settings.login_limit,
            login_window=settings.login_window,
        ),
        session_ttl=settings.session_ttl,
    )


@lru_cache(maxsize=1)
def get_user_application_service() -> UserApplicationService:
    return UserApplicationService(
        UserDomainService(PostgresUserRepository()), get_password_hasher()
    )


def clear_authentication_services() -> None:
    """进程资源关闭时清理持有 Redis 客户端的应用服务缓存。"""
    get_authentication_application_service.cache_clear()
    get_user_application_service.cache_clear()
