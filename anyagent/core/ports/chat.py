"""Runner and session storage contracts without SDK dependencies."""

from collections.abc import AsyncIterator
from typing import Protocol

from anyagent.core.domain.chat import Event, Message, Session


class AgentRunner(Protocol):
    def stream(self, messages: tuple[Message, ...]) -> AsyncIterator[Event]: ...

    async def aclose(self) -> None: ...


class RunnerFactory(Protocol):
    async def create(self) -> AgentRunner: ...


class SessionRepository(Protocol):
    async def list(self) -> tuple[Session, ...]: ...

    async def get(self, session_id: str) -> Session: ...

    async def save(self, session: Session) -> None: ...

    async def delete(self, session_id: str) -> None: ...
