"""Coordinate bounded sessions and commit only successful conversation turns."""

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import aclosing
from dataclasses import replace
from datetime import UTC, datetime
from uuid import uuid4

from anyagent.core.domain.chat import ChatError, Event, Message, Session
from anyagent.core.ports.chat import AgentRunner, RunnerFactory, SessionRepository

logger = logging.getLogger(__name__)


class ChatService:
    def __init__(
        self,
        repository: SessionRepository,
        runners: RunnerFactory,
        *,
        timeout_seconds: float,
        max_concurrent_runs: int,
        max_history_messages: int,
        max_input_chars: int,
        max_output_chars: int,
        max_event_chars: int,
        cleanup_timeout_seconds: float,
    ):
        self.repository = repository
        self.runners = runners
        self.timeout_seconds = timeout_seconds
        self.max_concurrent_runs = max_concurrent_runs
        self.max_history_messages = max_history_messages // 2 * 2
        self.max_input_chars = max_input_chars
        self.max_output_chars = max_output_chars
        self.max_event_chars = max_event_chars
        self.cleanup_timeout_seconds = cleanup_timeout_seconds
        self._active: dict[str, asyncio.Task] = {}
        self._closing: set[asyncio.Task] = set()

    async def create_session(self) -> Session:
        session = Session(uuid4().hex, "新会话", datetime.now(UTC).isoformat())
        await self.repository.save(session)
        return session

    async def delete_session(self, session_id: str) -> None:
        if session_id in self._active:
            raise ChatError("session_busy", "会话正在执行，请先停止生成")
        await self.repository.delete(session_id)

    async def stream(self, session_id: str, content: str) -> AsyncIterator[Event]:
        """Execute a turn while preserving the previous snapshot on failure.

        Args:
            session_id: Existing session identifier.
            content: User message, bounded by the injected input limit.

        Yields:
            Normalized deltas and tool events, followed by one committed result.

        Raises:
            ChatError: The session, capacity, model or execution is unavailable.
        """
        content = self.validate_message(content)
        if session_id in self._active:
            raise ChatError("session_busy", "这个会话已有执行中的请求")
        if len(self._active) >= self.max_concurrent_runs:
            raise ChatError("capacity_exceeded", "当前执行数量已达上限，请稍后重试")
        self._active[session_id] = asyncio.current_task()
        runner = None
        try:
            session = await self.repository.get(session_id)
            user = Message("user", content)
            async with asyncio.timeout(self.timeout_seconds):
                runner = await self.runners.create()
                result = None
                output_size = 0
                async with aclosing(
                    runner.stream(session.messages + (user,))
                ) as events:
                    async for event in events:
                        if event.type == "result":
                            result = event.data.get("content")
                        else:
                            output_size += len(str(event.data))
                            if output_size > self.max_event_chars:
                                raise ChatError(
                                    "output_limit", "模型输出超过单次执行限制"
                                )
                            yield event
                if not isinstance(result, str) or not result.strip():
                    raise ChatError("runner_failed", "模型未返回有效回复")
                if len(result) > self.max_output_chars:
                    raise ChatError("output_limit", "模型回复超过长度限制")
                messages = (session.messages + (user, Message("assistant", result)))[
                    -self.max_history_messages :
                ]
                updated = replace(
                    session,
                    title=content[:28] if not session.messages else session.title,
                    messages=messages,
                )
                await self.repository.save(updated)
                yield Event("result", {"content": result, "session_id": session_id})
        except TimeoutError as exc:
            raise ChatError("run_timeout", "执行超时，请稍后重试") from exc
        except ChatError:
            raise
        except Exception as exc:
            # SDK exception text may include upstream response bodies or credentials.
            logger.warning("Agent execution failed: %s", type(exc).__name__)
            raise ChatError(
                "runner_failed", "模型执行失败，请检查模型配置和服务状态"
            ) from exc
        finally:
            try:
                if runner is not None:
                    await self._dispose(runner)
            finally:
                self._active.pop(session_id, None)

    async def _dispose(self, runner: AgentRunner) -> None:
        async def close():
            try:
                async with asyncio.timeout(self.cleanup_timeout_seconds):
                    await runner.aclose()
            except Exception as exc:
                logger.warning("Runner cleanup failed: %s", type(exc).__name__)

        task = asyncio.create_task(close())
        self._closing.add(task)
        task.add_done_callback(self._closing.discard)
        # Disconnect cancellation must not interrupt disposal of owned connections.
        await asyncio.shield(task)

    def validate_message(self, content: str) -> str:
        content = content.strip()
        if not content or len(content) > self.max_input_chars:
            raise ChatError(
                "invalid_message",
                f"消息不能为空，且不能超过 {self.max_input_chars} 个字符",
            )
        return content

    async def shutdown(self) -> None:
        tasks = set(self._active.values()) - {asyncio.current_task()}
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        if self._closing:
            await asyncio.gather(*tuple(self._closing), return_exceptions=True)
