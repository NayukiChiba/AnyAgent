"""Coordinate bounded sessions and commit only successful conversation turns."""

import asyncio
from collections.abc import AsyncIterator
from contextlib import aclosing
from dataclasses import replace
from datetime import UTC, datetime
from time import perf_counter
from uuid import uuid4

from anyagent.core.domain.chat import ChatError, Event, Message, Session
from anyagent.core.ports.chat import AgentRunner, RunnerFactory, SessionRepository
from anyagent.utils.logger import get_logger

logger = get_logger(__name__)


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
        # 运行统计：内存计数，重启清零
        self._stats = {
            "runs_started": 0,
            "runs_completed": 0,
            "runs_failed": 0,
            "runs_cancelled": 0,
            "tool_calls": 0,
        }

    @property
    def stats(self) -> dict:
        """运行统计快照（内存计数，重启清零）。"""
        return {**self._stats, "active_runs": len(self._active)}

    async def create_session(self) -> Session:
        session = Session(uuid4().hex, "新会话", datetime.now(UTC).isoformat())
        await self.repository.save(session)
        logger.debug("Session created: session=%s", session.id)
        return session

    async def delete_session(self, session_id: str) -> None:
        if session_id in self._active:
            raise ChatError("session_busy", "会话正在执行，请先停止生成")
        await self.repository.delete(session_id)
        logger.debug("Session deleted: session=%s", session_id)

    async def rename_session(self, session_id: str, title: str) -> Session:
        """重命名会话；标题去除首尾空白后须为 1~60 字符。

        Raises:
            ChatError: 会话不存在（session_not_found）或标题不合法（invalid_message）。
        """
        title = title.strip()
        if not title or len(title) > 60:
            raise ChatError("invalid_message", "标题不能为空，且不能超过 60 个字符")
        session = await self.repository.get(session_id)
        updated = replace(session, title=title)
        await self.repository.save(updated)
        logger.debug("Session renamed: session=%s", session_id)
        return updated

    def cancel(self, session_id: str) -> None:
        """取消会话当前执行中的 run。

        Raises:
            ChatError: 会话没有执行中的请求（session_not_running）。
        """
        task = self._active.get(session_id)
        if task is None or task.done():
            raise ChatError("session_not_running", "会话当前没有执行中的请求")
        task.cancel()

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
        session = await self.repository.get(session_id)
        user = Message("user", content)
        logger.info(
            "Agent user message: session=%s data=%s",
            session_id,
            {"content": content},
        )
        async with aclosing(
            self._drive(session_id, session.messages + (user,))
        ) as events:
            async for event in events:
                if event.type != "result":
                    yield event
                    continue
                result = event.data["content"]
                messages = (session.messages + (user, Message("assistant", result)))[
                    -self.max_history_messages :
                ]
                updated = replace(
                    session,
                    title=content[:28] if not session.messages else session.title,
                    messages=messages,
                )
                logger.info(
                    "Agent model response: session=%s data=%s",
                    session_id,
                    {"content": result},
                )
                # 先提交历史再向下游交付结果，保证失败时快照不污染
                await self.repository.save(updated)
                logger.debug(
                    "Agent history committed: session=%s messages=%d",
                    session_id,
                    len(messages),
                )
                yield Event("result", {"content": result, "session_id": session_id})

    async def run_stateless(self, messages: tuple[Message, ...]) -> AsyncIterator[Event]:
        """无会话执行一轮对话（供 OpenAI 兼容网关），不写入存储。

        历史由调用方携带，仅保留最近 max_history_messages 条；
        最后一条必须是不超长的用户消息。

        Raises:
            ChatError: 消息序列不合法（invalid_message）或执行不可用。
        """
        if not messages or messages[-1].role != "user":
            raise ChatError("invalid_message", "消息列表必须以一条用户消息结尾")
        self.validate_message(messages[-1].content)
        trimmed = messages[-self.max_history_messages :]
        for message in trimmed:
            if len(message.content) > self.max_input_chars:
                raise ChatError(
                    "invalid_message",
                    f"单条消息不能超过 {self.max_input_chars} 个字符",
                )
        run_id = f"stateless-{uuid4().hex[:12]}"
        async with aclosing(self._drive(run_id, trimmed)) as events:
            async for event in events:
                yield event

    async def _drive(
        self, run_id: str, messages: tuple[Message, ...]
    ) -> AsyncIterator[Event]:
        """执行核心：注册容量、创建 runner、驱动事件流并施加输出限额。

        以 result 事件结束（content 不带 session_id，由会话包装层补充）。
        """
        if run_id in self._active:
            raise ChatError("session_busy", "这个会话已有执行中的请求")
        if len(self._active) >= self.max_concurrent_runs:
            raise ChatError("capacity_exceeded", "当前执行数量已达上限，请稍后重试")
        self._active[run_id] = asyncio.current_task()
        self._stats["runs_started"] += 1
        runner = None
        started = perf_counter()
        tool_calls = 0
        completed = False
        logger.info("Agent run started: session=%s", run_id)
        try:
            logger.debug(
                "Agent context loaded: session=%s messages=%d",
                run_id,
                len(messages),
            )
            async with asyncio.timeout(self.timeout_seconds):
                runner = await self.runners.create()
                logger.debug("Agent runner created: session=%s", run_id)
                result = None
                output_size = 0
                async with aclosing(runner.stream(messages)) as events:
                    async for event in events:
                        if event.type == "tool_call":
                            tool_calls += 1
                            self._stats["tool_calls"] += 1
                            logger.debug(
                                "Agent tool call received: session=%s count=%d",
                                run_id,
                                tool_calls,
                            )
                        if event.type == "result":
                            result = event.data.get("content")
                        else:
                            output_size += len(str(event.data))
                            if output_size > self.max_event_chars:
                                raise ChatError(
                                    "output_limit", "模型输出超过单次执行限制"
                                )
                            if event.type == "tool_call":
                                logger.info(
                                    "Agent tool call: session=%s data=%s",
                                    run_id,
                                    event.data,
                                )
                            elif event.type == "tool_result":
                                logger.info(
                                    "Agent tool result: session=%s data=%s",
                                    run_id,
                                    event.data,
                                )
                            yield event
                if not isinstance(result, str) or not result.strip():
                    raise ChatError("runner_failed", "模型未返回有效回复")
                if len(result) > self.max_output_chars:
                    raise ChatError("output_limit", "模型回复超过长度限制")
                completed = True
                self._stats["runs_completed"] += 1
                logger.info(
                    "Agent run completed: session=%s elapsed_ms=%.0f output_chars=%d tool_calls=%d",
                    run_id,
                    (perf_counter() - started) * 1000,
                    len(result),
                    tool_calls,
                )
                yield Event("result", {"content": result})
        except asyncio.CancelledError:
            if not completed:
                self._stats["runs_cancelled"] += 1
                logger.info(
                    "Agent run cancelled: session=%s elapsed_ms=%.0f",
                    run_id,
                    (perf_counter() - started) * 1000,
                )
            raise
        except GeneratorExit:
            if not completed:
                self._stats["runs_cancelled"] += 1
                logger.info(
                    "Agent stream closed: session=%s elapsed_ms=%.0f",
                    run_id,
                    (perf_counter() - started) * 1000,
                )
            raise
        except TimeoutError as exc:
            self._stats["runs_failed"] += 1
            logger.warning(
                "Agent run timed out: session=%s timeout_seconds=%s",
                run_id,
                self.timeout_seconds,
            )
            raise ChatError("run_timeout", "执行超时，请稍后重试") from exc
        except ChatError as exc:
            self._stats["runs_failed"] += 1
            logger.warning("Agent run failed: session=%s code=%s", run_id, exc.code)
            raise
        except Exception as exc:
            self._stats["runs_failed"] += 1
            # SDK exception text may include upstream response bodies or credentials.
            logger.warning(
                "Agent execution failed: session=%s error=%s",
                run_id,
                type(exc).__name__,
            )
            raise ChatError(
                "runner_failed", "模型执行失败，请检查模型配置和服务状态"
            ) from exc
        finally:
            try:
                if runner is not None:
                    await self._dispose(runner)
            finally:
                self._active.pop(run_id, None)

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
