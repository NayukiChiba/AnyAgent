"""Runner 档案的增删查改与启用切换。

档案只保存引擎类型与模型连接引用（model_id），连接信息在模型页面维护。
"""

from typing import Literal

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from anyagent.api.routes.settings import ensure_same_origin
from anyagent.configs.profiles import MODEL_REQUIRED_TYPES, ProfileStore, RunnerProfile
from anyagent.core.domain.chat import ChatError

router = APIRouter(prefix="/api/v1/profiles", tags=["profiles"])


class ProfileInput(BaseModel):
    """创建/更新档案的输入；model_id 必须指向已存在的模型连接。"""

    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=40)
    type: Literal["langchain", "langgraph", "loop", "dify", "coze", "pi", "deerflow"]
    model_id: str = Field(min_length=1)
    bot_id: str = ""


def store(request: Request) -> ProfileStore:
    return request.app.state.profile_store


def public(profile: RunnerProfile, active_id: str | None, request: Request) -> dict:
    """档案的公开视图：附带引用的模型连接摘要，供前端展示。"""
    model = None
    try:
        resolved = request.app.state.model_store.get(profile.model_id)
        model = {"id": resolved.id, "name": resolved.name, "model": resolved.model}
    except ChatError:
        model = None
    return {
        "id": profile.id,
        "name": profile.name,
        "type": profile.type,
        "model_id": profile.model_id,
        "model": model,
        "bot_id": profile.bot_id,
        "active": profile.id == active_id,
    }


def validation_error(error: ValidationError) -> HTTPException:
    """校验失败返回 422；只提取字段与信息，不回显提交内容。"""
    first = error.errors()[0]
    field = ".".join(str(part) for part in first["loc"])
    message = first["msg"].removeprefix("Value error, ")
    return HTTPException(
        422, detail={"message": f"{field}: {message}" if field else message}
    )


def not_found(error: ChatError) -> HTTPException:
    return HTTPException(404, detail={"code": error.code, "message": error.message})


def check_model_reference(body: ProfileInput, request: Request) -> None:
    """引用的模型连接必须存在；本地编排类引擎还要求其填写了模型名称。"""
    try:
        model = request.app.state.model_store.get(body.model_id)
    except ChatError:
        raise HTTPException(
            422, detail={"code": "model_missing", "message": "所选模型连接不存在"}
        ) from None
    if body.type in MODEL_REQUIRED_TYPES and not model.model.strip():
        raise HTTPException(
            422,
            detail={
                "code": "model_incomplete",
                "message": "该引擎要求所选模型填写模型名称，请先在模型页面补全",
            },
        )


@router.get("")
async def list_profiles(request: Request) -> dict:
    profile_store = store(request)
    active_id = profile_store.active_id()
    return {
        "active": active_id,
        "profiles": [
            public(profile, active_id, request) for profile in profile_store.list()
        ],
    }


@router.post("", status_code=201)
async def create_profile(body: ProfileInput, request: Request) -> dict:
    ensure_same_origin(request)
    try:
        profile = RunnerProfile(**body.model_dump())
    except ValidationError as error:
        raise validation_error(error) from None
    check_model_reference(body, request)
    profile_store = store(request)
    profile_store.create(profile)
    return public(profile, profile_store.active_id(), request)


@router.put("/{profile_id}")
async def update_profile(profile_id: str, body: ProfileInput, request: Request) -> dict:
    ensure_same_origin(request)
    profile_store = store(request)
    try:
        existing = profile_store.get(profile_id)
    except ChatError as error:
        raise not_found(error) from None
    try:
        profile = RunnerProfile(**body.model_dump(), id=existing.id)
    except ValidationError as error:
        raise validation_error(error) from None
    check_model_reference(body, request)
    profile_store.update(profile)
    return public(profile, profile_store.active_id(), request)


@router.delete("/{profile_id}", status_code=204)
async def delete_profile(profile_id: str, request: Request) -> None:
    ensure_same_origin(request)
    try:
        store(request).delete(profile_id)
    except ChatError as error:
        raise not_found(error) from None


@router.post("/{profile_id}/activate")
async def activate_profile(profile_id: str, request: Request) -> dict:
    """启用指定档案；下一次对话即生效，无需重启。"""
    ensure_same_origin(request)
    profile_store = store(request)
    try:
        profile_store.activate(profile_id)
    except ChatError as error:
        raise not_found(error) from None
    return {"message": "已切换 Runner", "active": profile_id}
