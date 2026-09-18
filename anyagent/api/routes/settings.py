"""Read and edit registered configuration forms."""

from urllib.parse import urlsplit

from fastapi import APIRouter, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from pydantic import BaseModel, ConfigDict, Field

from anyagent.configs.management import SettingsError
from anyagent.core.domain.chat import ChatError


class SettingsRoute(APIRoute):
    def get_route_handler(self):
        handler = super().get_route_handler()

        async def sanitized_handler(request: Request):
            try:
                return await handler(request)
            except RequestValidationError:
                # Validation diagnostics must never echo the submitted credential.
                return JSONResponse(
                    {
                        "detail": {
                            "message": "设置请求格式不正确，请重新载入页面后再保存"
                        }
                    },
                    status_code=422,
                )

        return sanitized_handler


router = APIRouter(
    prefix="/api/v1/settings", tags=["settings"], route_class=SettingsRoute
)


class SettingsInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    revision: str = Field(pattern=r"^[a-f0-9]{64}$")
    values: dict
    clear_api_key: bool = Field(default=False, strict=True)


def ensure_same_origin(request: Request) -> None:
    origin = request.headers.get("origin")
    if request.headers.get("sec-fetch-site") == "cross-site" or (
        origin and urlsplit(origin).netloc != request.headers.get("host")
    ):
        raise HTTPException(403, detail={"message": "请从当前服务的设置页面保存配置"})


@router.get("")
async def list_settings(request: Request) -> dict:
    try:
        return {"groups": request.app.state.configuration_manager.list()}
    except OSError:
        raise HTTPException(
            503, detail={"message": "无法读取设置，请检查配置目录的读写权限"}
        ) from None


@router.put("/{name}")
async def save_settings(name: str, body: SettingsInput, request: Request) -> dict:
    ensure_same_origin(request)
    try:
        return request.app.state.configuration_manager.save(
            name, body.values, body.revision, clear_api_key=body.clear_api_key
        )
    except SettingsError as error:
        raise HTTPException(
            error.status, detail={"message": error.message, "fields": error.fields}
        ) from None
    except OSError:
        raise HTTPException(
            503, detail={"message": "设置保存失败，原配置已保留，请检查目录读写权限"}
        ) from None


@router.post("/model_config/test")
async def test_model(request: Request) -> dict:
    ensure_same_origin(request)
    try:
        await request.app.state.test_model()
        return {"message": "模型连接正常，可以返回聊天页面开始使用"}
    except ChatError as error:
        raise HTTPException(503, detail={"message": error.message}) from None
