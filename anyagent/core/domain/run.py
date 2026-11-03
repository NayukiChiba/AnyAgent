"""Run 领域模型：执行生命周期的一等公民表达。

Run 属于一个会话（session_id 为空表示无会话执行），状态机约束
转移合法性，终态唯一且不可再转移：

    queued → running → succeeded | failed | cancelled
                  └── cancelling → cancelled
    queued → cancelled（启动前取消）

取消请求被接受后进入 cancelling，清理完成落到 cancelled；
cancelling 期间发生的执行错误仅作为诊断信息保留，不改变取消终态。
"""

from dataclasses import dataclass, field, replace
from typing import Any, Literal

from anyagent.core.domain.chat import ChatError, Message

type RunStatus = Literal[
    "queued", "running", "cancelling", "succeeded", "failed", "cancelled"
]

type RunEventType = Literal[
    "delta", "tool_call", "tool_result", "result", "status", "error"
]

type ExecutionKind = Literal["builtin", "sdk", "http", "subprocess"]

type ConversationMode = Literal["stateless", "framework_state"]

# 终态：不可再转移，终态唯一由状态机（终态无出边）与仓储写事务共同保证
TERMINAL_STATUSES: frozenset[RunStatus] = frozenset(
    {"succeeded", "failed", "cancelled"}
)

# 合法状态转移表；未列出的边一律拒绝
_TRANSITIONS: dict[RunStatus, frozenset[RunStatus]] = {
    "queued": frozenset({"running", "cancelled"}),
    "running": frozenset({"succeeded", "failed", "cancelling"}),
    "cancelling": frozenset({"cancelled"}),
    "succeeded": frozenset(),
    "failed": frozenset(),
    "cancelled": frozenset(),
}


def is_terminal(status: RunStatus) -> bool:
    """判断状态是否为终态。"""
    return status in TERMINAL_STATUSES


@dataclass(frozen=True)
class RunError:
    """终态失败/取消的错误信息，code 对齐 ChatError.code。"""

    code: str
    message: str


@dataclass(frozen=True)
class RunEvent:
    """带单调序号的执行事件；seq 由执行方分配，用于订阅重放去重。"""

    seq: int
    type: RunEventType
    data: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.seq < 0:
            raise ValueError("事件序号必须是非负整数")


@dataclass(frozen=True)
class PreparedInput:
    """校验并完成窗口截断的执行输入。"""

    messages: tuple[Message, ...]
    truncated: bool = False


@dataclass(frozen=True)
class RunnerCapabilities:
    """Runner 能力声明。

    M1 阶段只声明、不强制校验工具能力（工具授权属 M2 ToolExecutor）；
    M3 适配各 SDK 时按真实能力回填。
    """

    execution_kind: ExecutionKind
    conversation_mode: ConversationMode = "stateless"
    streaming: bool = True
    tools: bool = False


@dataclass(frozen=True)
class Run:
    """一次执行的完整记录；不可变，状态推进经 transition 产生新实例。"""

    id: str
    profile_id: str
    status: RunStatus
    input: PreparedInput
    config_snapshot: dict[str, Any]
    created_at: str
    session_id: str | None = None
    result: str | None = None
    error: RunError | None = None
    finished_at: str | None = None


def prepare_input(
    messages: tuple[Message, ...],
    *,
    max_input_chars: int,
    max_history_messages: int,
) -> PreparedInput:
    """校验消息序列并按历史窗口截断。

    规则：序列非空且末条为用户消息；逐条长度不超过 max_input_chars；
    末条用户消息去首尾空白后非空。max_history_messages <= 0 表示不限制窗口。

    Args:
        messages: 完整消息序列（含本次用户消息）。
        max_input_chars: 单条消息字符上限。
        max_history_messages: 历史窗口大小（条数）。

    Returns:
        PreparedInput: 截断后的消息序列与是否发生截断的标记。

    Raises:
        ChatError: 序列不合法（invalid_message）。
    """
    if not messages or messages[-1].role != "user":
        raise ChatError("invalid_message", "消息列表必须以一条用户消息结尾")
    for message in messages:
        if len(message.content) > max_input_chars:
            raise ChatError(
                "invalid_message", f"单条消息不能超过 {max_input_chars} 个字符"
            )
    last = messages[-1]
    content = last.content.strip()
    if not content:
        raise ChatError("invalid_message", "消息不能为空")
    # 末条消息统一为去空白后的内容，与执行口径一致
    normalized = messages[:-1] + (replace(last, content=content),)
    if max_history_messages > 0:
        windowed = normalized[-max_history_messages:]
    else:
        windowed = normalized
    return PreparedInput(windowed, truncated=len(windowed) != len(normalized))


def transition(
    run: Run,
    to: RunStatus,
    *,
    at: str | None = None,
    result: str | None = None,
    error: RunError | None = None,
) -> Run:
    """推进 Run 状态，返回新实例。

    Args:
        run: 当前 Run。
        to: 目标状态。
        at: 完成时间（ISO 字符串）；进入终态时必填。
        result: 最终回复；succeeded 必填且非空。
        error: 错误信息；failed 必填，cancelled 可选（诊断用途）。

    Returns:
        Run: 状态推进后的新实例。

    Raises:
        ChatError: 非法状态转移或终态语义不满足（invalid_state）。
    """
    if to not in _TRANSITIONS[run.status]:
        raise ChatError("invalid_state", f"执行状态不能从 {run.status} 变为 {to}")
    updates: dict[str, Any] = {"status": to}
    if is_terminal(to):
        if at is None:
            raise ChatError("invalid_state", "进入终态必须提供完成时间")
        updates["finished_at"] = at
    if to == "succeeded":
        if not result or not result.strip():
            raise ChatError("invalid_state", "成功终态必须携带非空结果")
        updates["result"] = result
    if to == "failed":
        if error is None:
            raise ChatError("invalid_state", "失败终态必须携带错误信息")
        updates["error"] = error
    if to == "cancelled" and error is not None:
        # cancelling 期间的执行错误作为诊断信息保留，不改变取消终态
        updates["error"] = error
    return replace(run, **updates)
