"""Bounded in-memory session repository; no database connections."""

from anyagent.core.domain.chat import ChatError, Session


class MemorySessionRepository:
    def __init__(self, *, max_sessions: int = 64):
        self._sessions: dict[str, Session] = {}
        self.max_sessions = max_sessions

    async def list(self) -> tuple[Session, ...]:
        return tuple(reversed(tuple(self._sessions.values())))

    async def get(self, session_id: str) -> Session:
        try:
            return self._sessions[session_id]
        except KeyError as exc:
            raise ChatError(
                "session_not_found", "会话不存在或已因服务重启清空"
            ) from exc

    async def save(self, session: Session) -> None:
        if (
            session.id not in self._sessions
            and len(self._sessions) >= self.max_sessions
        ):
            raise ChatError("session_limit", "会话数量已达上限，请删除不用的会话")
        self._sessions[session.id] = session

    async def delete(self, session_id: str) -> None:
        await self.get(session_id)
        del self._sessions[session_id]
