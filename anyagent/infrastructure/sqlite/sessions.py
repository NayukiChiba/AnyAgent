"""Persist complete bounded session snapshots with short SQLite transactions."""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import asdict
from pathlib import Path

from sqlalchemy import URL, func, select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from anyagent.core.domain.chat import ChatError, Message, Session
from anyagent.infrastructure.sqlite.models import Base, SessionRecord

logger = logging.getLogger(__name__)


class SQLiteSessionRepository:
    def __init__(
        self, file_path: Path, *, max_sessions: int, busy_timeout_seconds: int
    ):
        self.file_path = file_path
        self.max_sessions = max_sessions
        self.engine = create_async_engine(
            URL.create("sqlite+aiosqlite", database=str(file_path)),
            connect_args={"timeout": busy_timeout_seconds},
            hide_parameters=True,
        )
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False)

    async def initialize(self) -> None:
        """Create missing tables; existing or unreadable data is never reset."""
        self.file_path.parent.mkdir(parents=True, exist_ok=True)
        async with self.engine.begin() as connection:
            await connection.exec_driver_sql("PRAGMA journal_mode=WAL")
            await connection.run_sync(Base.metadata.create_all)

    async def aclose(self) -> None:
        await self.engine.dispose()

    @asynccontextmanager
    async def _transaction(self, *, write: bool = False) -> AsyncIterator[AsyncSession]:
        try:
            async with self.sessions() as transaction, transaction.begin():
                if write:
                    # Reserve the writer before counting so concurrent creates obey capacity.
                    await transaction.execute(text("BEGIN IMMEDIATE"))
                yield transaction
        except SQLAlchemyError as error:
            logger.warning(
                "Session database operation failed: %s", type(error).__name__
            )
            raise ChatError(
                "storage_unavailable",
                "会话数据库暂不可用，请稍后重试，或检查磁盘空间和数据库权限",
            ) from None

    @staticmethod
    def _snapshot(record: SessionRecord) -> Session:
        return Session(
            record.session_id,
            record.title,
            record.created_at,
            tuple(Message(**message) for message in record.messages),
        )

    async def list(self) -> tuple[Session, ...]:
        async with self._transaction() as transaction:
            records = await transaction.scalars(
                select(SessionRecord).order_by(SessionRecord.sequence.desc())
            )
            return tuple(self._snapshot(record) for record in records)

    async def get(self, session_id: str) -> Session:
        async with self._transaction() as transaction:
            record = await transaction.scalar(
                select(SessionRecord).where(SessionRecord.session_id == session_id)
            )
            if record is None:
                raise ChatError("session_not_found", "会话不存在或已删除")
            return self._snapshot(record)

    async def save(self, session: Session) -> None:
        """Atomically commit the title and complete ordered message snapshot.

        Args:
            session: Immutable snapshot produced after a successful agent round.

        Raises:
            ChatError: Capacity is exhausted or the database cannot commit.
        """
        async with self._transaction(write=True) as transaction:
            record = await transaction.scalar(
                select(SessionRecord).where(SessionRecord.session_id == session.id)
            )
            if record is None:
                count = await transaction.scalar(
                    select(func.count()).select_from(SessionRecord)
                )
                if count >= self.max_sessions:
                    raise ChatError(
                        "session_limit", "会话数量已达上限，请删除不用的会话"
                    )
                record = SessionRecord(
                    session_id=session.id, created_at=session.created_at
                )
                transaction.add(record)
            record.created_at = session.created_at
            record.title = session.title
            record.messages = [asdict(message) for message in session.messages]

    async def delete(self, session_id: str) -> None:
        async with self._transaction(write=True) as transaction:
            record = await transaction.scalar(
                select(SessionRecord).where(SessionRecord.session_id == session_id)
            )
            if record is None:
                raise ChatError("session_not_found", "会话不存在或已删除")
            await transaction.delete(record)
