"""Run 持久化契约：输入、结果与终态的存取边界。

实现方负责序列化与短事务；进行中状态（事件流、订阅者）不属于本契约，
仍由 RunService 在内存中管理。
"""

from typing import Protocol

from anyagent.core.domain.run import Run


class RunRepository(Protocol):
    async def save(self, run: Run) -> None:
        """按 run.id 新增或覆盖记录（调用方保证终态唯一）。"""
        ...

    async def get(self, run_id: str) -> Run:
        """查询 Run 记录；不存在时抛 ChatError（run_not_found）。"""
        ...

    async def list_nonterminal(self) -> tuple[Run, ...]:
        """列出所有非终态 Run（启动时的残留扫描用）。"""
        ...
