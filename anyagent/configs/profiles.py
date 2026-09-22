"""Runner 档案：每个执行引擎独立配置、增删查改、实时切换。

存储于 data/configs/runner_profiles.json：

    {"active": "<profile-id>", "profiles": [RunnerProfile, ...]}

旧版兼容：档案文件不存在时，从模型连接配置派生唯一的活动档案
（保持按次重读的热更新行为）；首次写操作创建文件并脱离兼容模式，
派生档案会以 id=legacy 正式落盘，已有的连接配置不会丢失。
"""

import json
import time
from pathlib import Path
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, Field, SecretStr, field_validator, model_validator

from anyagent.configs import paths
from anyagent.configs.agent import ModelSettings, validate_http_base_url
from anyagent.configs.load import load_langchain_config, load_model_config
from anyagent.core.domain.chat import ChatError
from anyagent.utils.logger import get_logger

logger = get_logger(__name__)

RUNNER_TYPES = ("langchain", "langgraph", "loop", "dify", "coze", "pi", "deerflow")
# 本地编排引擎与 Pi 直接调用模型 API，必须填写模型名称
MODEL_REQUIRED_TYPES = ("langchain", "langgraph", "loop", "pi")
LEGACY_PROFILE_ID = "legacy"


class RunnerProfile(BaseModel):
    """一个 runner 的自包含配置：标识 + 类型 + 连接信息。"""

    id: str = Field(default_factory=lambda: uuid4().hex[:12])
    name: str = Field(min_length=1, max_length=40)
    type: Literal["langchain", "langgraph", "loop", "dify", "coze", "pi", "deerflow"]
    base_url: str
    model: str = ""
    api_key: SecretStr = SecretStr("")
    streaming: bool = Field(default=True, strict=True)
    timeout_seconds: int = Field(default=60, ge=1, le=600, strict=True)
    temperature: float = Field(default=0.7, ge=0, le=2)
    bot_id: str = ""

    @field_validator("name")
    @classmethod
    def strip_name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("名称不能为空")
        return value

    @field_validator("base_url")
    @classmethod
    def check_base_url(cls, value: str) -> str:
        return validate_http_base_url(value)

    @model_validator(mode="after")
    def check_required_fields(self) -> "RunnerProfile":
        if self.type in MODEL_REQUIRED_TYPES and not self.model.strip():
            raise ValueError("该引擎需要填写模型名称")
        if self.type == "coze" and not self.bot_id.strip():
            raise ValueError("Coze 引擎需要填写 Bot ID")
        if not self.api_key.get_secret_value().strip():
            raise ValueError("请填写 API Key（无需认证的本地服务可填 local）")
        return self

    def as_model_settings(self) -> ModelSettings:
        """转换为模型连接配置，供既有 runner 工厂复用。"""
        return ModelSettings(
            enabled=True,
            streaming=self.streaming,
            base_url=self.base_url,
            # 平台引擎不使用模型名称，以类型名占位满足连接校验
            model=self.model.strip() or self.type,
            api_key=self.api_key,
            temperature=self.temperature,
            timeout_seconds=self.timeout_seconds,
        )


class ProfileStore:
    """Runner 档案的读写与启用切换。

    旧版兼容模式：档案文件不存在时，从模型连接配置派生活动档案；
    任何写操作都会创建档案文件并脱离兼容模式。
    """

    def __init__(self, path: Path | None = None):
        self._path = path or paths.get_config_path("runner_profiles")

    @property
    def legacy_mode(self) -> bool:
        return not self._path.is_file()

    def list(self) -> list[RunnerProfile]:
        data = self._read()
        if data is None:
            legacy = self._legacy_profile()
            return [legacy] if legacy is not None else []
        return [RunnerProfile.model_validate(item) for item in data.get("profiles", [])]

    def active_id(self) -> str | None:
        data = self._read()
        if data is None:
            legacy = self._legacy_profile()
            return legacy.id if legacy is not None else None
        return data.get("active")

    def active(self) -> RunnerProfile | None:
        data = self._read()
        if data is None:
            return self._legacy_profile()
        active_id = data.get("active")
        for profile in self.list():
            if profile.id == active_id:
                return profile
        return None

    def get(self, profile_id: str) -> RunnerProfile:
        for profile in self.list():
            if profile.id == profile_id:
                return profile
        raise ChatError("profile_not_found", "Runner 档案不存在")

    def create(self, profile: RunnerProfile) -> RunnerProfile:
        stored = self.list()
        stored.append(profile)
        active = self.active_id() or profile.id
        self._write({"active": active, "profiles": [self._dump(p) for p in stored]})
        logger.info("Runner profile created: id=%s type=%s", profile.id, profile.type)
        return profile

    def update(self, profile: RunnerProfile) -> RunnerProfile:
        stored = self.list()
        if all(p.id != profile.id for p in stored):
            raise ChatError("profile_not_found", "Runner 档案不存在")
        stored = [profile if p.id == profile.id else p for p in stored]
        self._write(
            {"active": self.active_id(), "profiles": [self._dump(p) for p in stored]}
        )
        logger.info("Runner profile updated: id=%s", profile.id)
        return profile

    def delete(self, profile_id: str) -> None:
        stored = self.list()
        if all(p.id != profile_id for p in stored):
            raise ChatError("profile_not_found", "Runner 档案不存在")
        stored = [p for p in stored if p.id != profile_id]
        active = self.active_id()
        if active == profile_id:
            # 活动档案被删除时回落到剩余的第一个，避免服务立即不可用
            active = stored[0].id if stored else None
        self._write({"active": active, "profiles": [self._dump(p) for p in stored]})
        logger.info("Runner profile deleted: id=%s", profile_id)

    def activate(self, profile_id: str) -> None:
        self.get(profile_id)
        self._write(
            {
                "active": profile_id,
                "profiles": [self._dump(p) for p in self.list()],
            }
        )
        logger.info("Runner profile activated: id=%s", profile_id)

    def _legacy_profile(self) -> RunnerProfile | None:
        """从旧的模型连接配置派生活动档案；未启用模型时返回 None。"""
        connection = load_model_config()
        if not connection.enabled:
            return None
        behavior = load_langchain_config()
        return RunnerProfile(
            id=LEGACY_PROFILE_ID,
            name="默认连接（旧版迁移）",
            type=behavior.runner,
            base_url=connection.base_url,
            model=connection.model,
            api_key=connection.api_key,
            streaming=connection.streaming,
            timeout_seconds=connection.timeout_seconds,
            temperature=connection.temperature,
            bot_id=behavior.coze_bot_id,
        )

    def _read(self) -> dict | None:
        """读取档案文件；不存在返回 None，损坏时备份后按不存在处理。"""
        try:
            with self._path.open(encoding="utf-8-sig") as file:
                data = json.load(file)
            if not isinstance(data, dict):
                raise ValueError("runner profiles must be an object")
            return data
        except FileNotFoundError:
            return None
        except ValueError:
            backup = self._path.with_suffix(f".broken-{time.time_ns()}.json")
            self._path.rename(backup)
            logger.warning("Runner profiles backed up to %s", backup)
            return None

    def _write(self, data: dict) -> None:
        """原子写入：先写临时文件再替换，避免中途断电留下半个文件。"""
        self._path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self._path.with_name(f"{self._path.stem}.{time.time_ns()}.tmp")
        try:
            with temporary.open("x", encoding="utf-8") as file:
                json.dump(data, file, ensure_ascii=False, indent=2)
                file.write("\n")
            temporary.replace(self._path)
        finally:
            temporary.unlink(missing_ok=True)

    @staticmethod
    def _dump(profile: RunnerProfile) -> dict:
        """序列化为存储字典；model_dump 会遮蔽密钥，需显式取回真实值。"""
        data = profile.model_dump()
        data["api_key"] = profile.api_key.get_secret_value()
        return data
