"""Alembic 迁移环境：数据库连接由调用方经 config.attributes 注入。

迁移由 anyagent.infrastructure.sqlite.migrate 以编程方式驱动，
不使用 alembic.ini；target_metadata 供未来 autogenerate 对比。
业务代码不直接 import alembic，统一经 migrate 模块执行。
"""

from alembic import context
from sqlalchemy import create_engine

from anyagent.infrastructure.sqlite.models import Base

config = context.config
target_metadata = Base.metadata


def run_migrations_online() -> None:
    """以调用方注入的数据库 URL 在线执行迁移。"""
    url = config.attributes.get("sqlalchemy.url")
    if url is None:
        raise RuntimeError("迁移执行缺少 sqlalchemy.url 注入")
    engine = create_engine(url)
    try:
        with engine.connect() as connection:
            context.configure(connection=connection, target_metadata=target_metadata)
            with context.begin_transaction():
                context.run_migrations()
    finally:
        engine.dispose()


run_migrations_online()
