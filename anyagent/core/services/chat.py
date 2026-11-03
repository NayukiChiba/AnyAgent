"""Coordinate bounded sessions and commit only successful conversation turns.

ChatService 是 RunService 的兼容外观：既有会话端点内部经 Run 执行，
订阅断开时主动请求取消，保持"断连即取消"的既有连接语义；
RunService 本身不随订阅断开停止执行。
"""

import asyncio
from collections.abc import AsyncIterator
from contextlib import aclosing
from dataclasses import replace
from datetime import UTC, datetime
from uuid import uuid4

from anyagent.core.domain.chat import ChatError, Event, Message, Session
from anyagent.core.ports.chat import RunnerFactory, SessionRepository
from anyagent.core.ports.run import RunRepository
from anyagent.core.services.run import RunService
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
        run_repository: RunRepository | None = None,
    ):
        self.repository = repository
        self.max_input_chars = max_input_chars
        self._runs = RunService(
            repository,
            runners,
            timeout_seconds=timeout_seconds,
            max_concurrent_runs=max_concurrent_runs,
            max_history_messages=max_history_messages,
            max_input_chars=max_input_chars,
            max_output_chars=max_output_chars,
            max_event_chars=max_event_chars,
            cleanup_timeout_seconds=cleanup_timeout_seconds,
            run_repository=run_repository,
        )

    @property
    def stats(self) -> dict:
        """运行统计快照（内存计数，重启清零）。"""
        return self._runs.stats

    @property
    def runs(self) -> RunService:
        """Run 执行服务（Run API 等新接口直接使用；会话端点仍走本外观）。"""
        return self._runs

    @property
    def _active(self) -> dict:
        """兼容既有诊断与测试：执行中的任务表。"""
        return self._runs._active

    @property
    def _closing(self) -> set:
        """兼容既有诊断与测试：回收中的清理任务。"""
        return self._runs._closing

    async def create_session(self) -> Session:
        session = Session(uuid4().hex, "新会话", datetime.now(UTC).isoformat())
        await self.repository.save(session)
        logger.debug("Session created: session=%s", session.id)
        return session

    async def delete_session(self, session_id: str) -> None:
        if self._runs.has_active_session(session_id):
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
        self._runs.cancel_by_session(session_id)

    async def recover_interrupted(self) -> int:
        """启动时标记仓储中的残留非终态 Run 为 run_interrupted。"""
        return await self._runs.recover_interrupted()

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
        logger.info(
            "Agent user message: session=%s data=%s",
            session_id,
            {"content": content},
        )
        run = await self._runs.create_session_run(
            session_id=session_id, content=content
        )
        async for event in self._consume(run):
            if event.type == "result":
                # 结果事件补充会话标识，保持既有响应形状
                yield Event(
                    "result",
                    {"content": event.data["content"], "session_id": session_id},
                )
            else:
                yield event

    async def run_stateless(
        self, messages: tuple[Message, ...]
    ) -> AsyncIterator[Event]:
        """无会话执行一轮对话（供 OpenAI 兼容网关），不写入存储。

        历史由调用方携带，仅保留最近 max_history_messages 条；
        最后一条必须是不超长的用户消息。

        Raises:
            ChatError: 消息序列不合法（invalid_message）或执行不可用。
        """
        run = await self._runs.create_stateless_run(messages)
        async for event in self._consume(run):
            yield event

    async def _consume(self, run) -> AsyncIterator[Event]:
        """订阅 Run 事件并映射为既有 Event；断开时请求取消（既有连接语义）。

        正常结束（成功/失败/取消终态）或本侧断开触发取消时，等待执行
        收尾完成（清理有超时兜底），保证调用方看到结果时资源状态确定；
        Run 已终态后的断开立即传播，清理由 RunService 独立兜底。
        """
        wait = True
        try:
            async with aclosing(self._runs.subscribe(run.id)) as events:
                async for event in events:
                    if event.type == "status":
                        status = event.data["status"]
                        if status == "failed":
                            error = event.data.get("error") or {}
                            raise ChatError(
                                error.get("code", "runner_failed"),
                                error.get("message", "执行失败"),
                            )
                        if status == "cancelled":
                            raise ChatError("run_cancelled", "已停止生成")
                        if status == "succeeded":
                            break
                        # queued/running/cancelling 不向调用方暴露
                        continue
                    if event.type == "error":
                        raise ChatError(
                            event.data.get("code", "runner_failed"),
                            event.data.get("message", "执行失败"),
                        )
                    yield Event(event.type, event.data)
        except (GeneratorExit, asyncio.CancelledError):
            # 返回 False 表示 Run 已终态，收尾与调用方无关
            wait = self._runs.cancel_quietly(run.id)
            raise
        finally:
            if wait:
                await self._runs.wait_finished(run.id)

    def validate_message(self, content: str) -> str:
        content = content.strip()
        if not content or len(content) > self.max_input_chars:
            raise ChatError(
                "invalid_message",
                f"消息不能为空，且不能超过 {self.max_input_chars} 个字符",
            )
        return content

    async def shutdown(self) -> None:
        await self._runs.shutdown()
