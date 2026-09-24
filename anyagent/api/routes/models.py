"""模型连接档案的增删查改与连接测试。

密钥安全：响应只回 has_api_key，永不回显真实密钥；
更新时 api_key 留空表示保持不变。
被 Runner 引用的模型连接不可删除，避免运行中档案失效。
"""

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from anyagent.api.routes.settings import ensure_same_origin
from anyagent.configs.model_profiles import ModelProfile, ModelProfileStore
from anyagent.core.domain.chat import ChatError
from anyagent.infrastructure.openai.client import OpenAIClient

router = APIRouter(prefix="/api/v1/models", tags=["models"])


class ModelInput(BaseModel):
    """创建/更新模型连接的输入；更新时 api_key 留空表示保持不变。"""

    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=40)
    base_url: str
    model: str = ""
    api_key: str = ""
    streaming: bool = Field(default=True, strict=True)
    timeout_seconds: int = Field(default=60, ge=1, le=600, strict=True)
    temperature: float = Field(default=0.7, ge=0, le=2)


def store(request: Request) -> ModelProfileStore:
    return request.app.state.model_store


def public(profile: ModelProfile, referenced_by: list[str]) -> dict:
    """模型连接的公开视图：不含真实密钥；附带引用它的 Runner 名称。"""
    return {
        "id": profile.id,
        "name": profile.name,
        "base_url": profile.base_url,
        "model": profile.model,
        "streaming": profile.streaming,
        "timeout_seconds": profile.timeout_seconds,
        "temperature": profile.temperature,
        "has_api_key": bool(profile.api_key.get_secret_value()),
        "referenced_by": referenced_by,
    }


def _references(request: Request) -> dict[str, list[str]]:
    """模型连接 id → 引用它的 Runner 名称列表。"""
    result: dict[str, list[str]] = {}
    for profile in request.app.state.profile_store.list():
        result.setdefault(profile.model_id, []).append(profile.name)
    return result


def validation_error(error: ValidationError) -> HTTPException:
    """校验失败返回 422；只提取字段与信息，不回显提交内容（含密钥）。"""
    first = error.errors()[0]
    field = ".".join(str(part) for part in first["loc"])
    message = first["msg"].removeprefix("Value error, ")
    return HTTPException(
        422, detail={"message": f"{field}: {message}" if field else message}
    )


def not_found(error: ChatError) -> HTTPException:
    return HTTPException(404, detail={"code": error.code, "message": error.message})


@router.get("")
async def list_models(request: Request) -> dict:
    references = _references(request)
    return {
        "models": [
            public(profile, references.get(profile.id, []))
            for profile in store(request).list()
        ]
    }


@router.post("", status_code=201)
async def create_model(body: ModelInput, request: Request) -> dict:
    ensure_same_origin(request)
    try:
        profile = ModelProfile(
            **body.model_dump(exclude={"api_key"}), api_key=body.api_key
        )
    except ValidationError as error:
        raise validation_error(error) from None
    store(request).create(profile)
    return public(profile, [])


@router.put("/{model_id}")
async def update_model(model_id: str, body: ModelInput, request: Request) -> dict:
    ensure_same_origin(request)
    model_store = store(request)
    try:
        existing = model_store.get(model_id)
    except ChatError as error:
        raise not_found(error) from None
    # 留空保持原密钥；填写则替换
    api_key = body.api_key or existing.api_key.get_secret_value()
    try:
        profile = ModelProfile(
            **body.model_dump(exclude={"api_key"}),
            id=existing.id,
            api_key=api_key,
        )
    except ValidationError as error:
        raise validation_error(error) from None
    model_store.update(profile)
    return public(profile, _references(request).get(model_id, []))


@router.delete("/{model_id}", status_code=204)
async def delete_model(model_id: str, request: Request) -> None:
    ensure_same_origin(request)
    referenced = _references(request).get(model_id, [])
    if referenced:
        raise HTTPException(
            409,
            detail={
                "code": "model_in_use",
                "message": f"该模型连接正被 Runner 使用：{'、'.join(referenced)}，请先修改或删除这些 Runner",
            },
        )
    try:
        store(request).delete(model_id)
    except ChatError as error:
        raise not_found(error) from None


@router.post("/{model_id}/test")
async def test_model_connection(model_id: str, request: Request) -> dict:
    """测试单个模型连接的连通性；未填写模型名称时无法测试。"""
    ensure_same_origin(request)
    try:
        profile = store(request).get(model_id)
    except ChatError as error:
        raise not_found(error) from None
    if not profile.model.strip():
        raise HTTPException(
            422,
            detail={
                "code": "model_incomplete",
                "message": "该模型连接未填写模型名称，请补全后再测试",
            },
        )
    client = OpenAIClient(profile.as_model_settings())
    try:
        await client.test()
    except ChatError as error:
        raise HTTPException(
            503, detail={"code": error.code, "message": error.message}
        ) from None
    finally:
        await client.aclose()
    return {"message": "模型连接正常"}
