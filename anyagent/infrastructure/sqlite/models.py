"""ORM records kept separate from immutable domain snapshots."""

from sqlalchemy import JSON, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class SessionRecord(Base):
    __tablename__ = "anyagent_chat_sessions"
    __table_args__ = {"sqlite_autoincrement": True}

    sequence: Mapped[int] = mapped_column(Integer, primary_key=True)
    session_id: Mapped[str] = mapped_column(String(32), unique=True)
    title: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[str] = mapped_column(String(40))
    messages: Mapped[list[dict[str, str]]] = mapped_column(JSON)


class RunRecord(Base):
    """Run 的输入、结果与终态；进行中的事件流与订阅状态不入库。"""

    __tablename__ = "anyagent_runs"

    run_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    session_id: Mapped[str | None] = mapped_column(String(32), index=True)
    profile_id: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(16))
    # input 形状：{"messages": [...], "truncated": bool}
    input: Mapped[dict] = mapped_column(JSON)
    result: Mapped[str | None] = mapped_column(Text)
    # error 形状：{"code": str, "message": str}
    error: Mapped[dict | None] = mapped_column(JSON)
    config_snapshot: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[str] = mapped_column(String(40))
    finished_at: Mapped[str | None] = mapped_column(String(40))
