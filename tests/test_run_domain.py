"""Run 领域模型：状态机转移矩阵、终态语义与输入准备。"""

import pytest

from anyagent.core.domain.chat import ChatError, Message
from anyagent.core.domain.run import (
    TERMINAL_STATUSES,
    PreparedInput,
    Run,
    RunError,
    RunEvent,
    is_terminal,
    prepare_input,
    transition,
)

TS = "2026-11-03T00:00:00+00:00"

ALL_STATUSES = ["queued", "running", "cancelling", "succeeded", "failed", "cancelled"]

ALLOWED_EDGES = {
    ("queued", "running"),
    ("queued", "cancelled"),
    ("queued", "failed"),
    ("running", "succeeded"),
    ("running", "failed"),
    ("running", "cancelling"),
    ("cancelling", "cancelled"),
    ("cancelling", "failed"),
}


def _input(text="你好"):
    return PreparedInput((Message("user", text),))


def _make_run(status="queued") -> Run:
    """构造指定状态的 Run（沿合法路径推进）。"""
    run = Run(
        id="r-1",
        profile_id="default",
        status="queued",
        input=_input(),
        config_snapshot={},
        created_at=TS,
    )
    if status == "queued":
        return run
    run = transition(run, "running")
    if status == "running":
        return run
    if status == "cancelling":
        return transition(run, "cancelling")
    if status == "succeeded":
        return transition(run, "succeeded", at=TS, result="好的")
    if status == "failed":
        return transition(run, "failed", at=TS, error=RunError("runner_failed", "失败"))
    if status == "cancelled":
        return transition(transition(run, "cancelling"), "cancelled", at=TS)
    raise AssertionError(f"未知状态: {status}")


@pytest.mark.parametrize("source", ALL_STATUSES)
@pytest.mark.parametrize("target", ALL_STATUSES)
def test_transition_matrix_allows_only_declared_edges(source, target):
    """全枚举 36 条边：仅转移表内的边合法，其余一律拒绝。"""
    run = _make_run(source)
    # 提供全部终态语义材料，本用例只考察转移合法性
    kwargs = {"at": TS, "result": "好的", "error": RunError("x", "y")}
    if (source, target) in ALLOWED_EDGES:
        assert transition(run, target, **kwargs).status == target
    else:
        with pytest.raises(ChatError) as excinfo:
            transition(run, target, **kwargs)
        assert excinfo.value.code == "invalid_state"


@pytest.mark.parametrize("status", sorted(TERMINAL_STATUSES))
def test_terminal_states_have_no_outgoing_edges(status):
    """终态唯一：终态不存在任何出边，不可再转移。"""
    run = _make_run(status)
    assert is_terminal(run.status)
    for target in ALL_STATUSES:
        with pytest.raises(ChatError):
            transition(run, target, at=TS, result="好的", error=RunError("x", "y"))


def test_terminal_transition_requires_finished_at():
    run = _make_run("running")
    with pytest.raises(ChatError, match="完成时间"):
        transition(run, "failed", error=RunError("runner_failed", "失败"))


def test_succeeded_requires_non_empty_result():
    run = _make_run("running")
    with pytest.raises(ChatError, match="非空结果"):
        transition(run, "succeeded", at=TS, result="  ")
    done = transition(run, "succeeded", at=TS, result="好的")
    assert done.result == "好的" and done.finished_at == TS


def test_failed_requires_error():
    run = _make_run("running")
    with pytest.raises(ChatError, match="错误信息"):
        transition(run, "failed", at=TS)
    done = transition(run, "failed", at=TS, error=RunError("run_timeout", "超时"))
    assert done.error.code == "run_timeout"


def test_cancelling_preserves_diagnostic_error_but_ends_cancelled():
    """cancelling 期间的执行错误保留为诊断信息，终态仍是 cancelled。"""
    run = transition(_make_run("running"), "cancelling")
    done = transition(
        run, "cancelled", at=TS, error=RunError("runner_failed", "清理前报错")
    )
    assert done.status == "cancelled"
    assert done.error.code == "runner_failed"


def test_queued_can_be_cancelled_before_start():
    done = transition(_make_run("queued"), "cancelled", at=TS)
    assert done.status == "cancelled" and done.finished_at == TS


def test_run_event_rejects_negative_seq():
    with pytest.raises(ValueError, match="非负整数"):
        RunEvent(seq=-1, type="delta", data={})
    assert RunEvent(seq=0, type="status", data={"status": "queued"}).seq == 0


def test_prepare_input_requires_user_message_at_end():
    with pytest.raises(ChatError, match="用户消息"):
        prepare_input((), max_input_chars=100, max_history_messages=40)
    with pytest.raises(ChatError, match="用户消息"):
        prepare_input(
            (Message("assistant", "答"),),
            max_input_chars=100,
            max_history_messages=100,
        )


def test_prepare_input_enforces_message_length_limit():
    messages = (Message("user", "x" * 101),)
    with pytest.raises(ChatError, match="不能超过"):
        prepare_input(messages, max_input_chars=100, max_history_messages=100)


def test_prepare_input_strips_and_rejects_blank_last_message():
    with pytest.raises(ChatError, match="不能为空"):
        prepare_input(
            (Message("user", "   "),),
            max_input_chars=100,
            max_history_messages=100,
        )
    prepared = prepare_input(
        (Message("user", "  你好  "),),
        max_input_chars=100,
        max_history_messages=100,
    )
    assert prepared.messages[-1].content == "你好"
    assert not prepared.truncated


def test_prepare_input_applies_history_window_and_marks_truncation():
    messages = tuple(Message("user", f"第{i}条") for i in range(5))
    prepared = prepare_input(messages, max_input_chars=100, max_history_messages=2)
    assert [m.content for m in prepared.messages] == ["第3条", "第4条"]
    assert prepared.truncated


def test_prepare_input_nonpositive_window_means_unlimited():
    messages = tuple(Message("user", f"第{i}条") for i in range(5))
    prepared = prepare_input(messages, max_input_chars=100, max_history_messages=0)
    assert len(prepared.messages) == 5
    assert not prepared.truncated
