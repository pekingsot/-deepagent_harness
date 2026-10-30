"""数据库迁移的配置和执行入口。"""

from logging.config import fileConfig

from alembic import context
from sqlalchemy import create_engine, pool
from sqlalchemy.engine import make_url

from agent_platform.bootstrap.settings import get_settings
from agent_platform.infrastructure.persistence.entities import BaseTable

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = BaseTable.metadata

# 复用项目配置，不在 alembic.ini 中重复保存数据库账号密码
settings = get_settings()
database_url = make_url(settings.database_url).set(drivername="postgresql+psycopg")


def include_object(obj, name, type_, reflected, compare_to):
    """自动生成迁移时，不删除 ORM 没有管理的数据库表。"""
    if type_ == "table" and reflected and compare_to is None:
        return False

    return True


def run_migrations_offline() -> None:
    """只生成 SQL，不连接数据库。"""
    context.configure(
        url=database_url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        include_object=include_object,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """连接数据库并执行迁移。"""
    engine = create_engine(
        database_url,
        poolclass=pool.NullPool,
        connect_args={"connect_timeout": 10},
    )

    try:
        with engine.connect() as connection:
            context.configure(
                connection=connection,
                target_metadata=target_metadata,
                include_object=include_object,
            )

            with context.begin_transaction():
                context.run_migrations()
    finally:
        engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
