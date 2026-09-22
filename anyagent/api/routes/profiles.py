"""Runner 档案的增删查改与启用切换。

密钥安全：响应只回 has_api_key，永不回显真实密钥；
更新时 api_key 留空表示保持不变。
"""

from typing import Literal

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from anyagent.api.routes.settings import ensure_same_origin
from anyagent.configs.profiles import ProfileStore, RunnerProfile
from anyagent.core.domain.chat import ChatError

router = APIRouter(prefix="/api/v1/profiles", tags=["profiles"])


class ProfileInput(BaseModel):
    """创建/更新档案的输入；更新时 api_key 留空表示保持不变。"""

    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=40)
    type: Literal["langchain", "langgraph", "loop", "dify", "coze", "pi", "deerflow"]
    base_url: str
    model: str = ""
    api_key: str = ""
    streaming: bool = Field(default=True, strict=True)
    timeout_seconds: int = Field(default=60, ge=1, le=600, strict=True)
    temperature: float = Field(default=0.7, ge=0, le=2)
    bot_id: str = ""


def store(request: Request) -> ProfileStore:
    return request.app.state.profile_store


def public(profile: RunnerProfile, active_id: str | None) -> dict:
    """档案的公开视图：不含真实密钥。"""
    return {
        "id": profile.id,
        "name": profile.name,
        "type": profile.type,
        "base_url": profile.base_url,
        "model": profile.model,
        "streaming": profile.streaming,
        "timeout_seconds": profile.timeout_seconds,
        "temperature": profile.temperature,
        "bot_id": profile.bot_id,
        "has_api_key": bool(profile.api_key.get_secret_value()),
        "active": profile.id == active_id,
    }


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
async def list_profiles(request: Request) -> dict:
    profile_store = store(request)
    active_id = profile_store.active_id()
    return {
        "active": active_id,
        "profiles": [public(profile, active_id) for profile in profile_store.list()],
    }


@router.post("", status_code=201)
async def create_profile(body: ProfileInput, request: Request) -> dict:
    ensure_same_origin(request)
    try:
        profile = RunnerProfile(
            **body.model_dump(exclude={"api_key"}), api_key=body.api_key
        )
    except ValidationError as error:
        raise validation_error(error) from None
    profile_store = store(request)
    profile_store.create(profile)
    return public(profile, profile_store.active_id())


@router.put("/{profile_id}")
async def update_profile(profile_id: str, body: ProfileInput, request: Request) -> dict:
    ensure_same_origin(request)
    profile_store = store(request)
    try:
        existing = profile_store.get(profile_id)
    except ChatError as error:
        raise not_found(error) from None
    # 留空保持原密钥；填写则替换
    api_key = body.api_key or existing.api_key.get_secret_value()
    try:
        profile = RunnerProfile(
            **body.model_dump(exclude={"api_key"}),
            id=existing.id,
            api_key=api_key,
        )
    except ValidationError as error:
        raise validation_error(error) from None
    profile_store.update(profile)
    return public(profile, profile_store.active_id())


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
