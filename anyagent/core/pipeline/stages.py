"""顺序阶段：按声明顺序执行，阶段抛错即中止后续阶段。

阶段通过共享的上下文对象交换数据（如准备后的输入、创建的 Runner、
最终结果）；中止语义由异常表达，不为正常路径引入隐式状态。
"""

from collections.abc import Sequence
from typing import Any, Protocol


class RunStage(Protocol):
    """执行链路的单个顺序阶段；抛出异常即中止后续阶段。"""

    async def __call__(self, ctx: Any) -> None: ...


async def run_stages(stages: Sequence[RunStage], ctx: Any) -> None:
    """按顺序执行各阶段。

    Args:
        stages: 阶段序列，按列表顺序执行。
        ctx: 阶段间共享的执行上下文。
    """
    for stage in stages:
        await stage(ctx)
