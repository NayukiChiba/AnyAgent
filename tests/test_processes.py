"""Verify runtime-owned subprocess cleanup."""

from unittest.mock import Mock

from anyagent.runtime.processes import terminate_child_processes


def test_child_processes_are_terminated_and_survivors_are_killed(monkeypatch):
    stopped = Mock(pid=101)
    survivor = Mock(pid=102)
    parent = Mock()
    parent.children.return_value = [stopped, survivor]
    wait_results = [([stopped], [survivor]), ([survivor], [])]

    monkeypatch.setattr("anyagent.runtime.processes.os.getpid", lambda: 100)
    process = Mock(return_value=parent)
    monkeypatch.setattr("anyagent.runtime.processes.psutil.Process", process)
    wait_procs = Mock(side_effect=wait_results)
    monkeypatch.setattr("anyagent.runtime.processes.psutil.wait_procs", wait_procs)

    terminate_child_processes(timeout_seconds=0.5)

    process.assert_called_once_with(100)
    parent.children.assert_called_once_with(recursive=True)
    stopped.terminate.assert_called_once_with()
    survivor.terminate.assert_called_once_with()
    stopped.kill.assert_not_called()
    survivor.kill.assert_called_once_with()
    assert wait_procs.call_args_list[0].args == ([stopped, survivor],)
    assert wait_procs.call_args_list[0].kwargs == {"timeout": 0.5}
    assert wait_procs.call_args_list[1].args == ([survivor],)
    assert wait_procs.call_args_list[1].kwargs == {"timeout": 0.5}


def test_no_child_processes_require_no_wait(monkeypatch):
    parent = Mock()
    parent.children.return_value = []
    monkeypatch.setattr(
        "anyagent.runtime.processes.psutil.Process", Mock(return_value=parent)
    )
    wait_procs = Mock()
    monkeypatch.setattr("anyagent.runtime.processes.psutil.wait_procs", wait_procs)

    terminate_child_processes()

    wait_procs.assert_not_called()
