"""Immutable chat snapshots and public execution events."""

from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class Message:
    role: Literal["user", "assistant"]
    content: str


@dataclass(frozen=True)
class Session:
    id: str
    title: str
    created_at: str
    messages: tuple[Message, ...] = ()


@dataclass(frozen=True)
class Event:
    type: Literal["delta", "tool_call", "tool_result", "result"]
    data: dict


class ChatError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message
