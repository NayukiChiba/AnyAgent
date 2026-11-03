"""In-memory run storage for isolated unit and connection tests."""

from anyagent.core.domain.chat import ChatError
from anyagent.core.domain.run import Run, is_terminal


class InMemoryRunRepository:
    """字典承载的 Run 仓储；进程退出即丢失，仅供测试与隔离场景。"""

    def __init__(self) -> None:
        self._runs: dict[str, Run] = {}

    async def save(self, run: Run) -> None:
        self._runs[run.id] = run

    async def get(self, run_id: str) -> Run:
        try:
            return self._runs[run_id]
        except KeyError:
            raise ChatError("run_not_found", "执行不存在或已被清理") from None

    async def list_nonterminal(self) -> tuple[Run, ...]:
        return tuple(run for run in self._runs.values() if not is_terminal(run.status))
