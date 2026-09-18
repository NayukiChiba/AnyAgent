"""ORM records kept separate from immutable domain snapshots."""

from sqlalchemy import JSON, Integer, String
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
