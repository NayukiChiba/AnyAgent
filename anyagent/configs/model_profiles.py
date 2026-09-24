"""模型连接档案：可复用的地址、模型名与密钥组合，供 Runner 档案引用。

存储于 data/configs/model_profiles.json：

    {"profiles": [ModelProfile, ...]}

旧版兼容：档案文件不存在时，从模型连接配置（model_config）派生唯一的
档案（保持按次重读的热更新行为）；首次写操作创建文件并脱离兼容模式，
派生档案会以 id=legacy 正式落盘，已有的连接配置不会丢失。
"""

from pathlib import Path
from uuid import uuid4

from pydantic import BaseModel, Field, SecretStr, field_validator, model_validator

from anyagent.configs import paths
from anyagent.configs.agent import ModelSettings, validate_http_base_url
from anyagent.configs.json_store import JsonDocumentStore, dump_profile
from anyagent.configs.load import load_model_config
from anyagent.core.domain.chat import ChatError

LEGACY_MODEL_ID = "legacy"


class ModelProfile(BaseModel):
    """一个可复用的模型连接：标识 + 地址 + 模型名 + 密钥。"""

    id: str = Field(default_factory=lambda: uuid4().hex[:12])
    name: str = Field(min_length=1, max_length=40)
    base_url: str
    model: str = ""
    api_key: SecretStr = SecretStr("")
    streaming: bool = Field(default=True, strict=True)
    timeout_seconds: int = Field(default=60, ge=1, le=600, strict=True)
    temperature: float = Field(default=0.7, ge=0, le=2)

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
    def check_required_fields(self) -> "ModelProfile":
        if not self.api_key.get_secret_value().strip():
            raise ValueError("请填写 API Key（无需认证的本地服务可填 local）")
        return self

    def as_model_settings(self, fallback_model: str = "") -> ModelSettings:
        """转换为模型连接配置，供既有 runner 工厂复用。

        远端平台引擎不使用模型名称，调用方以引擎类型名占位满足连接校验。
        """
        return ModelSettings(
            enabled=True,
            streaming=self.streaming,
            base_url=self.base_url,
            model=self.model.strip() or fallback_model,
            api_key=self.api_key,
            temperature=self.temperature,
            timeout_seconds=self.timeout_seconds,
        )


class ModelProfileStore(JsonDocumentStore):
    """模型连接档案的读写。

    旧版兼容模式：档案文件不存在时，从模型连接配置派生档案；
    任何写操作都会创建档案文件并脱离兼容模式。
    """

    def __init__(self, path: Path | None = None):
        super().__init__(path or paths.get_config_path("model_profiles"))

    def list(self) -> list[ModelProfile]:
        data = self._read()
        if data is None:
            legacy = self._legacy_model()
            return [legacy] if legacy is not None else []
        return [ModelProfile.model_validate(item) for item in data.get("profiles", [])]

    def get(self, model_id: str) -> ModelProfile:
        for profile in self.list():
            if profile.id == model_id:
                return profile
        raise ChatError("model_profile_not_found", "模型连接不存在")

    def create(self, profile: ModelProfile) -> ModelProfile:
        stored = self.list()
        stored.append(profile)
        self._write({"profiles": [dump_profile(item) for item in stored]})
        return profile

    def update(self, profile: ModelProfile) -> ModelProfile:
        stored = self.list()
        if all(item.id != profile.id for item in stored):
            raise ChatError("model_profile_not_found", "模型连接不存在")
        stored = [profile if item.id == profile.id else item for item in stored]
        self._write({"profiles": [dump_profile(item) for item in stored]})
        return profile

    def delete(self, model_id: str) -> None:
        stored = self.list()
        if all(item.id != model_id for item in stored):
            raise ChatError("model_profile_not_found", "模型连接不存在")
        stored = [item for item in stored if item.id != model_id]
        self._write({"profiles": [dump_profile(item) for item in stored]})

    def _legacy_model(self) -> ModelProfile | None:
        """从旧的模型连接配置派生档案；未启用模型时返回 None。"""
        connection = load_model_config()
        if not connection.enabled:
            return None
        return ModelProfile(
            id=LEGACY_MODEL_ID,
            name="默认模型（旧版迁移）",
            base_url=connection.base_url,
            model=connection.model,
            api_key=connection.api_key,
            streaming=connection.streaming,
            timeout_seconds=connection.timeout_seconds,
            temperature=connection.temperature,
        )
