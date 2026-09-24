"""Runner 档案：每个执行引擎独立配置、增删查改、实时切换。

存储于 data/configs/runner_profiles.json：

    {"active": "<profile-id>", "profiles": [RunnerProfile, ...]}

档案只保存引擎类型与模型连接引用（model_id），连接信息统一由
模型连接档案（model_profiles.json）维护，多个 Runner 可共用同一连接。

旧版兼容：档案文件不存在时，从模型连接配置派生唯一的活动档案
（保持按次重读的热更新行为）；首次写操作创建文件并脱离兼容模式，
派生档案会以 id=legacy 正式落盘，已有的连接配置不会丢失。

数据迁移：读取时若发现旧版档案内联了连接信息（含 base_url 字段），
自动拆分为模型连接档案 + 引用，并落盘为新格式。
"""

from pathlib import Path
from uuid import uuid4

from pydantic import BaseModel, Field, field_validator, model_validator

from anyagent.configs import paths
from anyagent.configs.json_store import JsonDocumentStore, dump_profile
from anyagent.configs.load import load_langchain_config, load_model_config
from anyagent.configs.model_profiles import (
    LEGACY_MODEL_ID,
    ModelProfile,
    ModelProfileStore,
)
from anyagent.core.domain.chat import ChatError
from anyagent.utils.logger import get_logger

logger = get_logger(__name__)

RUNNER_TYPES = ("langchain", "langgraph", "loop", "dify", "coze", "pi", "deerflow")
# 本地编排引擎与 Pi 直接调用模型 API，引用的模型连接必须填写模型名称
MODEL_REQUIRED_TYPES = ("langchain", "langgraph", "loop", "pi")
LEGACY_PROFILE_ID = "legacy"


class RunnerProfile(BaseModel):
    """一个 runner 的自包含配置：标识 + 类型 + 模型连接引用。"""

    id: str = Field(default_factory=lambda: uuid4().hex[:12])
    name: str = Field(min_length=1, max_length=40)
    type: str = Field(pattern="^(langchain|langgraph|loop|dify|coze|pi|deerflow)$")
    model_id: str = Field(min_length=1)
    bot_id: str = ""

    @field_validator("name")
    @classmethod
    def strip_name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("名称不能为空")
        return value

    @model_validator(mode="after")
    def check_required_fields(self) -> "RunnerProfile":
        if self.type == "coze" and not self.bot_id.strip():
            raise ValueError("Coze 引擎需要填写 Bot ID")
        return self


class ProfileStore(JsonDocumentStore):
    """Runner 档案的读写与启用切换。

    旧版兼容模式：档案文件不存在时，从模型连接配置派生活动档案；
    任何写操作都会创建档案文件并脱离兼容模式。
    """

    def __init__(self, path: Path | None = None, *, model_store: ModelProfileStore):
        super().__init__(path or paths.get_config_path("runner_profiles"))
        self._model_store = model_store

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
        self._write({"active": active, "profiles": [dump_profile(p) for p in stored]})
        logger.info("Runner profile created: id=%s type=%s", profile.id, profile.type)
        return profile

    def update(self, profile: RunnerProfile) -> RunnerProfile:
        stored = self.list()
        if all(p.id != profile.id for p in stored):
            raise ChatError("profile_not_found", "Runner 档案不存在")
        stored = [profile if p.id == profile.id else p for p in stored]
        self._write(
            {"active": self.active_id(), "profiles": [dump_profile(p) for p in stored]}
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
        self._write({"active": active, "profiles": [dump_profile(p) for p in stored]})
        logger.info("Runner profile deleted: id=%s", profile_id)

    def activate(self, profile_id: str) -> None:
        self.get(profile_id)
        self._write(
            {
                "active": profile_id,
                "profiles": [dump_profile(p) for p in self.list()],
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
            model_id=LEGACY_MODEL_ID,
            bot_id=behavior.coze_bot_id,
        )

    def _read(self) -> dict | None:
        data = super()._read()
        if data is None:
            return None
        profiles = data.get("profiles", [])
        if not any("base_url" in item for item in profiles if isinstance(item, dict)):
            return data
        return self._migrate_inline_connections(data, profiles)

    def _migrate_inline_connections(self, data: dict, profiles: list) -> dict:
        """拆分旧版内联连接为模型连接档案 + 引用，并落盘为新格式。"""
        migrated = []
        for item in profiles:
            if not isinstance(item, dict) or "base_url" not in item:
                migrated.append(item)
                continue
            model = ModelProfile(
                name=f"{item.get('name', '未命名')} 的连接",
                base_url=item["base_url"],
                model=item.get("model", ""),
                api_key=item.get("api_key", ""),
                streaming=item.get("streaming", True),
                timeout_seconds=item.get("timeout_seconds", 60),
                temperature=item.get("temperature", 0.7),
            )
            self._model_store.create(model)
            migrated.append(
                {
                    "id": item["id"],
                    "name": item.get("name", "未命名"),
                    "type": item.get("type", "langchain"),
                    "model_id": model.id,
                    "bot_id": item.get("bot_id", ""),
                }
            )
        result = {"active": data.get("active"), "profiles": migrated}
        self._write(result)
        logger.info(
            "Runner profiles migrated: %d inline connections moved to model profiles",
            sum(
                1 for item in profiles if isinstance(item, dict) and "base_url" in item
            ),
        )
        return result
