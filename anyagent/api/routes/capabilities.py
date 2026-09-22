"""工具清单与执行引擎元数据的只读接口。"""

from fastapi import APIRouter, Request

from anyagent.configs.catalog import CHOICE_LABELS, RUNNER_INFO

router = APIRouter(prefix="/api/v1", tags=["capabilities"])


@router.get("/tools")
async def list_tools(request: Request) -> list[dict]:
    """列出已注册工具的名称、描述与参数 schema。"""
    return [
        {
            "name": tool.name,
            "description": tool.description,
            "parameters": tool.parameters,
        }
        for tool in request.app.state.tool_set.tools
    ]


@router.get("/runners")
async def list_runners(request: Request) -> dict:
    """列出全部执行引擎的元数据与当前启用的引擎。"""
    return {
        "current": request.app.state.agent_info()["runner"],
        "runners": [
            {
                "id": runner_id,
                "label": CHOICE_LABELS.get(runner_id, runner_id),
                **info,
            }
            for runner_id, info in RUNNER_INFO.items()
        ],
    }
