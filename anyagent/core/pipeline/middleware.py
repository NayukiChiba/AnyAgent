"""洋葱中间件：经 call_next 包裹下游，在 finally 中管理清理。

中间件按声明顺序由外向内包裹；call_next 最多调用一次，
重复调用说明中间件实现有误，立即抛错暴露问题。
"""

from collections.abc import Awaitable, Callable, Sequence
from typing import Any, Protocol


class RunMiddleware(Protocol):
    """包裹下游链路的中间件；在 call_next 前后执行自身职责。"""

    async def __call__(
        self, ctx: Any, call_next: Callable[[], Awaitable[None]]
    ) -> None: ...


def compose(
    middlewares: Sequence[RunMiddleware],
    terminal: Callable[[Any], Awaitable[None]],
) -> Callable[[Any], Awaitable[None]]:
    """把中间件链与末端执行器组装为单个可调用。

    Args:
        middlewares: 中间件序列，首个在最外层。
        terminal: 链末端（通常是顺序阶段执行器）。

    Returns:
        可调用：接收执行上下文，驱动整条链。
    """

    async def run(ctx: Any) -> None:
        async def invoke(index: int) -> None:
            if index == len(middlewares):
                await terminal(ctx)
                return
            called = False

            async def call_next() -> None:
                nonlocal called
                if called:
                    raise RuntimeError("call_next 最多调用一次")
                called = True
                await invoke(index + 1)

            await middlewares[index](ctx, call_next)

        await invoke(0)

    return run
