"""一次性创建租户及初始管理员，不启动 Agent 或公开初始化接口。"""

import asyncio
import getpass
import sys

from pydantic import ValidationError
from sqlalchemy_transactional.asyncio import sessionmaker_context

from agent_platform.application.dto.user_command import CreateUserCommand
from agent_platform.application.services.user_application_service import UserApplicationService
from agent_platform.bootstrap.authentication import get_password_hasher
from agent_platform.bootstrap.settings import get_settings
from agent_platform.domain.services.user_domain_service import UserDomainService
from agent_platform.domain.types.common import ConflictError
from agent_platform.infrastructure.persistence.database import Database
from agent_platform.infrastructure.persistence.repositories.user_repository import (
    PostgresUserRepository,
)


async def run() -> None:
    code = input("公司代码（小写字母/数字，至少3位）：").strip()
    name = input("公司名称：").strip()
    username = input("管理员登录名：").strip()
    display_name = input("管理员显示名称：").strip()
    password = getpass.getpass("管理员密码（至少12位）：")
    if password != getpass.getpass("再次输入密码："):
        raise ValueError("两次密码不一致")
    command = CreateUserCommand(
        username=username, display_name=display_name, password=password, role="admin"
    )
    service = UserApplicationService(
        UserDomainService(PostgresUserRepository()), get_password_hasher()
    )
    database = Database(get_settings().database_url)
    try:
        async with sessionmaker_context(database.session_factory):
            user = await service.initialize_tenant(code, name, command)
        print(f"初始化成功，管理员整数ID：{user.id}。请前往前端登录页面。")
    finally:
        await database.close()


def main() -> None:
    loop_factory = asyncio.SelectorEventLoop if sys.platform == "win32" else None
    try:
        asyncio.run(run(), loop_factory=loop_factory)
    except ValidationError as exc:
        # 不打印包含原始密码的校验输入。
        for error in exc.errors(include_input=False):
            print(f"字段 {'.'.join(str(item) for item in error['loc'])}：{error['msg']}")
        raise SystemExit(1) from exc
    except (ValueError, ConflictError, KeyboardInterrupt) as exc:
        print(f"初始化未完成：{exc}")
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
