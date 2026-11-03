"""Run 的 SQLite 持久化：短事务、按需序列化领域快照。

只保存输入、结果与终态；表结构由 Alembic 迁移创建，本模块不负责建表。
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import asdict
from pathlib import Path

from sqlalchemy import URL, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from anyagent.core.domain.chat import ChatError, Message
from anyagent.core.domain.run import (
    TERMINAL_STATUSES,
    PreparedInput,
    Run,
    RunError,
)
from anyagent.infrastructure.sqlite.models import RunRecord
from anyagent.utils.logger import get_logger

logger = get_logger(__name__)


def _to_record(run: Run) -> RunRecord:
    return RunRecord(
        run_id=run.id,
        session_id=run.session_id,
        profile_id=run.profile_id,
        status=run.status,
        input={
            "messages": [asdict(message) for message in run.input.messages],
            "truncated": run.input.truncated,
        },
        result=run.result,
        error=asdict(run.error) if run.error else None,
        config_snapshot=run.config_snapshot,
        created_at=run.created_at,
        finished_at=run.finished_at,
    )


def _to_domain(record: RunRecord) -> Run:
    return Run(
        id=record.run_id,
        session_id=record.session_id,
        profile_id=record.profile_id,
        status=record.status,
        input=PreparedInput(
            tuple(Message(**item) for item in record.input["messages"]),
            truncated=record.input.get("truncated", False),
        ),
        result=record.result,
        error=RunError(**record.error) if record.error else None,
        config_snapshot=record.config_snapshot,
        created_at=record.created_at,
        finished_at=record.finished_at,
    )


class SQLiteRunRepository:
    """anyagent_runs 表的异步仓储；各操作使用独立短事务。"""

    def __init__(self, file_path: Path, *, busy_timeout_seconds: int):
        self.file_path = file_path
        self.engine = create_async_engine(
            URL.create("sqlite+aiosqlite", database=str(file_path)),
            connect_args={"timeout": busy_timeout_seconds},
            hide_parameters=True,
        )
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False)

    async def initialize(self) -> None:
        """连接就绪检查；表结构由会话仓储入口的迁移统一创建。"""
        async with self.engine.begin() as connection:
            await connection.exec_driver_sql("PRAGMA journal_mode=WAL")

    async def aclose(self) -> None:
        await self.engine.dispose()

    @asynccontextmanager
    async def _transaction(self) -> AsyncIterator[AsyncSession]:
        try:
            async with self.sessions() as transaction, transaction.begin():
                yield transaction
        except SQLAlchemyError as error:
            logger.warning("Run database operation failed: %s", type(error).__name__)
            raise ChatError(
                "storage_unavailable",
                "执行记录数据库暂不可用，请稍后重试，或检查磁盘空间和数据库权限",
            ) from None

    async def save(self, run: Run) -> None:
        """按 run.id 新增或覆盖记录（merge upsert；终态唯一由状态机保证）。"""
        async with self._transaction() as transaction:
            await transaction.merge(_to_record(run))

    async def get(self, run_id: str) -> Run:
        async with self._transaction() as transaction:
            record = await transaction.get(RunRecord, run_id)
            if record is None:
                raise ChatError("run_not_found", "执行不存在或已被清理")
            return _to_domain(record)

    async def list_nonterminal(self) -> tuple[Run, ...]:
        async with self._transaction() as transaction:
            records = await transaction.scalars(
                select(RunRecord).where(
                    RunRecord.status.not_in(sorted(TERMINAL_STATUSES))
                )
            )
            return tuple(_to_domain(record) for record in records)
