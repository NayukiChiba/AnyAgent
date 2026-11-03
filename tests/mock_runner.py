"""可控 Mock Runner：按脚本产生事件，支撑 RunService 与后续契约测试。

script 为步骤序列：
- ("event", type, data)：产出一个事件
- ("sleep", 秒)：挂起指定时长
- ("wait", asyncio.Event)：等待外部放行
- ("raise", 异常)：抛出错误
- ("block",)：阻塞直到任务被取消
"""

import asyncio

from anyagent.core.domain.chat import Event


class MockRunner:
    def __init__(self, script=()):
        self.script = list(script)
        self.closed = False
        self.seen = ()

    async def stream(self, messages):
        self.seen = messages
        for step in self.script:
            kind = step[0]
            if kind == "event":
                yield Event(step[1], step[2])
            elif kind == "sleep":
                await asyncio.sleep(step[1])
            elif kind == "wait":
                await step[1].wait()
            elif kind == "raise":
                raise step[1]
            elif kind == "block":
                await asyncio.Event().wait()

    async def aclose(self):
        self.closed = True


class MockRunnerFactory:
    """每次 create 返回新的 MockRunner；created 记录所有实例。"""

    def __init__(self, script=()):
        self.script = script
        self.created = []

    async def create(self):
        runner = MockRunner(self.script)
        self.created.append(runner)
        return runner

    def describe(self):
        return {"profile_id": "mock", "profile_type": "mock"}
