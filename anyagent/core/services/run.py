"""RunService：Run 生命周期的执行编排（内存态）。

执行与订阅解耦：Run 创建后在任务注册表中独立执行，客户端经订阅
接收事件；订阅断开不停止执行，慢订阅者被标记溢出而不阻塞 Runner。
终态唯一提交，提交完成后才发布终态 status 事件。

占用与容量在创建时原子登记；执行链路为洋葱中间件包裹顺序阶段：

    日志上下文 → 异常归一 → Runner 清理 → [上下文组装 → 执行 → 提交]
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import aclosing
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from time import perf_counter
from uuid import uuid4

from anyagent.core.domain.chat import ChatError, Message, Session
from anyagent.core.domain.run import (
    Run,
    RunError,
    RunEvent,
    is_terminal,
    prepare_input,
    transition,
)
from anyagent.core.pipeline.middleware import compose
from anyagent.core.pipeline.stages import run_stages
from anyagent.core.ports.chat import AgentRunner, RunnerFactory, SessionRepository
from anyagent.core.ports.run import RunRepository
from anyagent.utils.logger import get_logger, log_context

logger = get_logger(__name__)

# 每个 Run 的事件环形缓冲容量（超出后旧事件被丢弃，重放窗口前移）
RUN_EVENT_BUFFER_SIZE = 500
# 单个订阅者的待投递队列容量；消费不过来时标记溢出并终止该订阅
SUBSCRIBER_QUEUE_SIZE = 256
# 内存中保留的已终态 Run 上限，超出后清理最早的终态记录
MAX_RETAINED_TERMINAL_RUNS = 256


def _now() -> str:
    return datetime.now(UTC).isoformat()


class _Subscriber:
    """单个订阅者的投递队列；溢出时置 lagged 标记并终止该订阅。"""

    def __init__(self) -> None:
        self.queue: asyncio.Queue[RunEvent] = asyncio.Queue(SUBSCRIBER_QUEUE_SIZE)
        self.lagged = False


@dataclass
class _RunEntry:
    """运行期条目：最新 Run 快照、执行任务、事件缓冲与订阅者。"""

    run: Run
    task: asyncio.Task | None = None
    events: list[RunEvent] = field(default_factory=list)
    next_seq: int = 0
    subscribers: set[_Subscriber] = field(default_factory=set)
    terminal_published: bool = False
    done: asyncio.Event = field(default_factory=asyncio.Event)


@dataclass
class _RunContext:
    """pipeline 各阶段与中间件共享的执行上下文。"""

    service: RunService
    entry: _RunEntry
    session: Session | None
    started: float
    runner: AgentRunner | None = None
    result: str | None = None
    tool_calls: int = 0
    output_size: int = 0


class _LogContextMiddleware:
    """最外层：把 run 标识注入日志上下文，链路内日志自动携带。"""

    async def __call__(self, ctx: _RunContext, call_next) -> None:
        with log_context(run=ctx.entry.run.id):
            await call_next()


class _NormalizeErrorsMiddleware:
    """把执行异常归一为终态转移：取消/超时/业务错误/未知错误。"""

    async def __call__(self, ctx: _RunContext, call_next) -> None:
        service = ctx.service
        try:
            await call_next()
        except asyncio.CancelledError:
            # 取消优先：无论此前处于 running 还是 cancelling，终态都是 cancelled
            elapsed = (perf_counter() - ctx.started) * 1000
            logger.info("Agent run cancelled: elapsed_ms=%.0f", elapsed)
            service._finish_cancelled(ctx.entry)
            raise
        except TimeoutError:
            logger.warning(
                "Agent run timed out: timeout_seconds=%s", service.timeout_seconds
            )
            service._finish_failed(
                ctx.entry, ChatError("run_timeout", "执行超时，请稍后重试")
            )
        except ChatError as exc:
            logger.warning("Agent run failed: code=%s", exc.code)
            service._finish_failed(ctx.entry, exc)
        except Exception as exc:
            # SDK 异常文本可能携带上游响应或凭据，只记录类型名
            logger.warning("Agent execution failed: error=%s", type(exc).__name__)
            service._finish_failed(
                ctx.entry,
                ChatError("runner_failed", "模型执行失败，请检查模型配置和服务状态"),
            )


class _RunnerCleanupMiddleware:
    """最内层（阶段之外）：finally 中回收本 Run 创建的 Runner。"""

    async def __call__(self, ctx: _RunContext, call_next) -> None:
        try:
            await call_next()
        finally:
            if ctx.runner is not None:
                await ctx.service._dispose(ctx.runner)


class _ContextStage:
    """上下文组装：标记进入 running，记录上下文规模。"""

    async def __call__(self, ctx: _RunContext) -> None:
        service = ctx.service
        service._advance(ctx.entry, "running")
        logger.info("Agent run started")
        logger.debug(
            "Agent context loaded: messages=%d", len(ctx.entry.run.input.messages)
        )


class _ExecuteStage:
    """执行：创建 Runner、消费事件流并施加输出限额，捕获最终结果。

    事件流由本阶段消费并发布到 Run 缓冲，不逐 token 重跑下游阶段。
    """

    async def __call__(self, ctx: _RunContext) -> None:
        service = ctx.service
        async with asyncio.timeout(service.timeout_seconds):
            ctx.runner = await service.runners.create()
            logger.debug("Agent runner created")
            async with aclosing(
                ctx.runner.stream(ctx.entry.run.input.messages)
            ) as events:
                async for event in events:
                    if event.type == "tool_call":
                        ctx.tool_calls += 1
                        service._stats["tool_calls"] += 1
                        logger.debug(
                            "Agent tool call received: count=%d", ctx.tool_calls
                        )
                    if event.type == "result":
                        ctx.result = event.data.get("content")
                        continue
                    ctx.output_size += len(str(event.data))
                    if ctx.output_size > service.max_event_chars:
                        raise ChatError("output_limit", "模型输出超过单次执行限制")
                    if event.type == "tool_call":
                        logger.info("Agent tool call: data=%s", event.data)
                    elif event.type == "tool_result":
                        logger.info("Agent tool result: data=%s", event.data)
                    service._publish(ctx.entry, event.type, event.data)
            if not isinstance(ctx.result, str) or not ctx.result.strip():
                raise ChatError("runner_failed", "模型未返回有效回复")
            if len(ctx.result) > service.max_output_chars:
                raise ChatError("output_limit", "模型回复超过长度限制")


class _CommitStage:
    """提交：先落会话历史（会话 Run），再发布结果与终态事件。

    终态提交后才发布结束事件；失败或取消不进入本阶段，不提交半轮历史。
    """

    async def __call__(self, ctx: _RunContext) -> None:
        service = ctx.service
        entry = ctx.entry
        result = ctx.result
        assert result is not None  # 执行阶段已保证非空
        if ctx.session is not None:
            user = entry.run.input.messages[-1]
            messages = (ctx.session.messages + (user, Message("assistant", result)))[
                -service.max_history_messages :
            ]
            updated = replace(
                ctx.session,
                title=(
                    user.content[:28] if not ctx.session.messages else ctx.session.title
                ),
                messages=messages,
            )
            logger.info(
                "Agent model response: session=%s data=%s",
                ctx.session.id,
                {"content": result},
            )
            # 先提交历史再发布结果，保证失败时快照不污染
            await service.repository.save(updated)
            logger.debug(
                "Agent history committed: session=%s messages=%d",
                ctx.session.id,
                len(messages),
            )
        elapsed = (perf_counter() - ctx.started) * 1000
        logger.info(
            "Agent run completed: elapsed_ms=%.0f output_chars=%d tool_calls=%d",
            elapsed,
            len(result),
            ctx.tool_calls,
        )
        service._publish(entry, "result", {"content": result})
        service._advance(entry, "succeeded", at=_now(), result=result)


class RunService:
    """Run 的创建、执行编排、订阅与取消（内存注册表）。"""

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
        self.runners = runners
        # 执行记录仓储：可选；缺省时 Run 仅存活于内存（测试与隔离场景）
        self.run_repository = run_repository
        self.timeout_seconds = timeout_seconds
        self.max_concurrent_runs = max_concurrent_runs
        self.max_history_messages = max_history_messages // 2 * 2
        self.max_input_chars = max_input_chars
        self.max_output_chars = max_output_chars
        self.max_event_chars = max_event_chars
        self.cleanup_timeout_seconds = cleanup_timeout_seconds
        self._runs: dict[str, _RunEntry] = {}
        # 会话原子占用：session_id → run_id（仅执行中）
        self._by_session: dict[str, str] = {}
        # 执行中的任务（含清理中）：run_id → task
        self._active: dict[str, asyncio.Task] = {}
        self._closing: set[asyncio.Task] = set()
        self._persisting: set[asyncio.Task] = set()
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

    async def create_session_run(self, *, session_id: str, content: str) -> Run:
        """为既有会话创建 Run：校验输入、登记占用与容量、启动执行任务。

        Raises:
            ChatError: 输入不合法（invalid_message）、会话不存在
                （session_not_found）、会话执行中（session_busy）或
                全局并发已满（capacity_exceeded）。
        """
        # 先校验新输入（保持既有错误优先级），再取会话
        prepare_input(
            (Message("user", content),),
            max_input_chars=self.max_input_chars,
            max_history_messages=0,
        )
        session = await self.repository.get(session_id)
        if session_id in self._by_session:
            raise ChatError("session_busy", "这个会话已有执行中的请求")
        prepared = prepare_input(
            session.messages + (Message("user", content.strip()),),
            max_input_chars=self.max_input_chars,
            max_history_messages=self.max_history_messages,
        )
        return self._register(session=session, prepared=prepared)

    async def create_stateless_run(self, messages: tuple[Message, ...]) -> Run:
        """无会话执行一轮（供 OpenAI 兼容网关），不写入存储。

        历史由调用方携带，仅保留最近窗口；末条必须是不超长的用户消息。
        """
        prepared = prepare_input(
            messages,
            max_input_chars=self.max_input_chars,
            max_history_messages=self.max_history_messages,
        )
        return self._register(session=None, prepared=prepared)

    def _register(self, *, session: Session | None, prepared) -> Run:
        """原子登记容量与会话占用，创建执行任务（登记期间无 await）。"""
        if len(self._active) >= self.max_concurrent_runs:
            raise ChatError("capacity_exceeded", "当前执行数量已达上限，请稍后重试")
        snapshot = self._describe_factory()
        run = Run(
            id=uuid4().hex,
            profile_id=snapshot.get("profile_id", "unknown"),
            status="queued",
            input=prepared,
            config_snapshot=snapshot,
            created_at=_now(),
            session_id=session.id if session else None,
        )
        entry = _RunEntry(run=run)
        self._runs[run.id] = entry
        if session is not None:
            self._by_session[session.id] = run.id
        self._stats["runs_started"] += 1
        self._publish(entry, "status", {"status": "queued"})
        self._persist(run)
        task = asyncio.create_task(self._execute(entry, session))
        entry.task = task
        self._active[run.id] = task
        # 任务可能未启动就被取消：收尾统一由完成回调保证
        task.add_done_callback(lambda _t: self._finalize(entry))
        self._prune_terminal()
        return run

    def _describe_factory(self) -> dict:
        """读取工厂的配置快照（实现可选）；不可用时为空快照。"""
        describe = getattr(self.runners, "describe", None)
        if not callable(describe):
            return {}
        try:
            return dict(describe())
        except Exception as exc:
            logger.warning("Runner describe failed: %s", type(exc).__name__)
            return {}

    async def get_run(self, run_id: str) -> Run:
        """查询 Run 最新快照；内存未命中时回源仓储（重启后的历史 Run）。

        Raises:
            ChatError: 执行不存在或已被清理（run_not_found）。
        """
        entry = self._runs.get(run_id)
        if entry is not None:
            return entry.run
        if self.run_repository is not None:
            return await self.run_repository.get(run_id)
        raise ChatError("run_not_found", "执行不存在或已被清理")

    def has_active_session(self, session_id: str) -> bool:
        return session_id in self._by_session

    async def subscribe(
        self, run_id: str, *, since_seq: int = -1
    ) -> AsyncIterator[RunEvent]:
        """订阅 Run 事件：先重放 since_seq 之后的缓冲，再转入实时投递。

        慢订阅者消费不过来时被标记溢出：收到 subscription_lagged 错误
        事件后订阅终止，调用方可带更大的 since_seq 重订或查询终态。
        订阅断开不影响执行。

        Raises:
            ChatError: 执行不存在（run_not_found）。
        """
        entry = self._runs.get(run_id)
        if entry is None:
            if self.run_repository is None:
                raise ChatError("run_not_found", "执行不存在或已被清理")
            # 重启后的历史 Run：无实时事件，按存档合成结果与终态
            stored = await self.run_repository.get(run_id)
            seq = 0
            if stored.result is not None:
                yield RunEvent(seq=seq, type="result", data={"content": stored.result})
                seq += 1
            yield RunEvent(
                seq=seq,
                type="status",
                data={"status": stored.status},
            )
            return
        # 重放缓冲内未交付的事件（事件循环内无 await，重放到注册订阅者之间原子）
        for event in list(entry.events):
            if event.seq > since_seq:
                yield event
        if entry.terminal_published:
            return
        subscriber = _Subscriber()
        entry.subscribers.add(subscriber)
        try:
            while True:
                if subscriber.lagged:
                    yield RunEvent(
                        seq=entry.next_seq,
                        type="error",
                        data={
                            "code": "subscription_lagged",
                            "message": "事件消费过慢导致缓冲溢出，请重新订阅或查询执行结果",
                        },
                    )
                    return
                event = await subscriber.queue.get()
                yield event
                if event.type == "status" and is_terminal(event.data["status"]):
                    return
        finally:
            entry.subscribers.discard(subscriber)

    def request_cancel(self, run_id: str) -> Run:
        """请求取消：queued 直接终态，running 转 cancelling 并取消任务。

        Raises:
            ChatError: 执行不存在（run_not_found）或已终态（invalid_state）。
        """
        entry = self._runs.get(run_id)
        if entry is None:
            raise ChatError("run_not_found", "执行不存在或已被清理")
        if is_terminal(entry.run.status):
            raise ChatError("invalid_state", "执行已结束，无法取消")
        self._cancel_entry(entry)
        return entry.run

    def cancel_quietly(self, run_id: str) -> bool:
        """断开连接等场景的幂等取消；返回是否真正触发了取消。

        已终态时静默忽略并返回 False（调用方可据此决定是否等待收尾）。
        """
        entry = self._runs.get(run_id)
        if entry is None or is_terminal(entry.run.status):
            return False
        self._cancel_entry(entry)
        return True

    def cancel_by_session(self, session_id: str) -> None:
        """取消会话当前执行中的 Run（既有 cancel 语义）。

        Raises:
            ChatError: 会话没有执行中的请求（session_not_running）。
        """
        run_id = self._by_session.get(session_id)
        if run_id is None:
            raise ChatError("session_not_running", "会话当前没有执行中的请求")
        self.request_cancel(run_id)

    def _cancel_entry(self, entry: _RunEntry) -> None:
        """同步推进取消终态并取消执行任务；清理在执行任务的收尾中完成。"""
        if entry.run.status == "running":
            self._advance(entry, "cancelling")
        self._advance(entry, "cancelled", at=_now())
        if entry.task is not None and not entry.task.done():
            entry.task.cancel()

    async def wait_finished(self, run_id: str) -> None:
        """等待执行任务完全收尾（含 Runner 清理）。

        等待者自身被取消时立即传播，执行侧继续独立收尾。
        """
        entry = self._runs.get(run_id)
        if entry is None:
            return
        await asyncio.shield(entry.done.wait())

    async def _execute(self, entry: _RunEntry, session: Session | None) -> None:
        ctx = _RunContext(
            service=self, entry=entry, session=session, started=perf_counter()
        )
        chain = compose(
            [
                _LogContextMiddleware(),
                _NormalizeErrorsMiddleware(),
                _RunnerCleanupMiddleware(),
            ],
            lambda ctx: run_stages(
                [_ContextStage(), _ExecuteStage(), _CommitStage()], ctx
            ),
        )
        await chain(ctx)

    def _finalize(self, entry: _RunEntry) -> None:
        """任务完成（含未启动即取消）后的统一收尾：置完成标志。

        占用与容量槽位在终态转移时已释放（见 _advance），清理工作由
        执行任务的中间件 finally 与关闭流程兜底。
        """
        entry.done.set()

    def _publish(self, entry: _RunEntry, type_: str, data: dict) -> None:
        """分配单调序号，写入环形缓冲并向各订阅者非阻塞投递。"""
        event = RunEvent(seq=entry.next_seq, type=type_, data=data)
        entry.next_seq += 1
        entry.events.append(event)
        if len(entry.events) > RUN_EVENT_BUFFER_SIZE:
            del entry.events[: len(entry.events) - RUN_EVENT_BUFFER_SIZE]
        for subscriber in tuple(entry.subscribers):
            try:
                subscriber.queue.put_nowait(event)
            except asyncio.QueueFull:
                subscriber.lagged = True

    def _advance(self, entry: _RunEntry, to, **kwargs) -> None:
        """推进状态机并发布 status 事件；终态更新统计并同步释放占用。

        占用与容量槽位在终态落定即释放（清理仍有超时兜底），使取消后
        立刻重开等行为不依赖执行任务的事件循环调度。
        """
        entry.run = transition(entry.run, to, **kwargs)
        data: dict = {"status": entry.run.status}
        if entry.run.error is not None:
            data["error"] = {
                "code": entry.run.error.code,
                "message": entry.run.error.message,
            }
        self._publish(entry, "status", data)
        if is_terminal(entry.run.status):
            entry.terminal_published = True
            key = {
                "succeeded": "runs_completed",
                "failed": "runs_failed",
                "cancelled": "runs_cancelled",
            }[entry.run.status]
            self._stats[key] += 1
            if entry.run.session_id is not None:
                self._by_session.pop(entry.run.session_id, None)
            self._active.pop(entry.run.id, None)
            self._persist(entry.run)

    def _persist(self, run: Run) -> None:
        """后台落库：输入/终态。持久化失败只记日志，不影响执行链路。"""

        async def save():
            try:
                await self.run_repository.save(run)
            except Exception as exc:
                logger.error(
                    "Run persistence failed: run=%s error=%s",
                    run.id,
                    type(exc).__name__,
                )

        if self.run_repository is None:
            return
        task = asyncio.create_task(save())
        self._persisting.add(task)
        task.add_done_callback(self._persisting.discard)

    async def recover_interrupted(self) -> int:
        """启动时把仓储中的残留非终态 Run 标记为 run_interrupted。

        未知执行状态不自动重跑；返回标记数量。
        """
        if self.run_repository is None:
            return 0
        count = 0
        for run in await self.run_repository.list_nonterminal():
            marked = transition(
                run,
                "failed",
                at=_now(),
                error=RunError("run_interrupted", "服务重启，执行被中断"),
            )
            await self.run_repository.save(marked)
            count += 1
        if count:
            logger.warning("服务重启，标记中断的执行: count=%d", count)
        return count

    def _finish_failed(self, entry: _RunEntry, error: ChatError) -> None:
        """异常归一后的失败终态；已终态（如取消竞态）时不重复提交。"""
        if is_terminal(entry.run.status):
            return
        if entry.run.status == "cancelling":
            # 取消竞态：取消优先，错误作为诊断信息保留
            self._advance(
                entry,
                "cancelled",
                at=_now(),
                error=RunError(error.code, error.message),
            )
            return
        self._advance(
            entry, "failed", at=_now(), error=RunError(error.code, error.message)
        )

    def _finish_cancelled(self, entry: _RunEntry) -> None:
        """取消终态；取消请求通常已推进终态，此处幂等兜底（如关闭取消）。"""
        if is_terminal(entry.run.status):
            return
        if entry.run.status == "running":
            self._advance(entry, "cancelling")
        self._advance(entry, "cancelled", at=_now())

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
        # 断开连接的取消不得中断归属连接的回收
        await asyncio.shield(task)

    def _prune_terminal(self) -> None:
        """清理最早的终态记录，避免长时运行内存增长。"""
        terminal = [
            entry for entry in self._runs.values() if is_terminal(entry.run.status)
        ]
        excess = len(terminal) - MAX_RETAINED_TERMINAL_RUNS
        if excess <= 0:
            return
        terminal.sort(key=lambda entry: entry.run.created_at)
        for entry in terminal[:excess]:
            self._runs.pop(entry.run.id, None)

    async def shutdown(self) -> None:
        tasks = set(self._active.values()) - {asyncio.current_task()}
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        if self._closing:
            await asyncio.gather(*tuple(self._closing), return_exceptions=True)
        if self._persisting:
            await asyncio.gather(*tuple(self._persisting), return_exceptions=True)
