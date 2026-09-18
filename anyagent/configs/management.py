"""Validated configuration editing with masked credentials and revision checks."""

import hashlib
import json

from pydantic import ValidationError

from anyagent.configs import paths
from anyagent.configs.catalog import APPLY_NOTICES, GROUPS, defaults_for, form_fields
from anyagent.configs.default import DEFAULT_CONFIGS
from anyagent.configs.load import _fill_defaults, _save_update, load_config


class SettingsError(Exception):
    def __init__(self, message: str, *, status: int = 422, fields: dict | None = None):
        super().__init__(message)
        self.message = message
        self.status = status
        self.fields = fields or {}


class ConfigurationManager:
    def __init__(self):
        self.initial_revisions = {name: self._read(name)[1] for name in GROUPS}

    def _read(self, name: str) -> tuple[dict, str]:
        if name not in GROUPS:
            raise SettingsError("没有找到这类设置", status=404)
        group = GROUPS[name]
        load_config(name, group.schema, DEFAULT_CONFIGS[name])
        raw = paths.get_config_path(name).read_bytes()
        values = json.loads(raw.decode("utf-8-sig"))
        group.schema.model_validate(values)
        return values, hashlib.sha256(raw).hexdigest()

    def get(self, name: str) -> dict:
        values, revision = self._read(name)
        group = GROUPS[name]
        has_key = bool(values.get("api_key"))
        if "api_key" in values:
            values["api_key"] = ""
        return {
            "name": name,
            "title": group.title,
            "description": group.description,
            "apply_mode": group.apply_mode,
            "apply_notice": APPLY_NOTICES[group.apply_mode],
            "restart_required": group.apply_mode == "restart"
            and revision != self.initial_revisions[name],
            "fields": form_fields(group),
            "values": values,
            "defaults": defaults_for(name),
            "has_api_key": has_key,
            "revision": revision,
        }

    def list(self) -> list[dict]:
        return [self.get(name) for name in GROUPS]

    def save(
        self, name: str, values: dict, revision: str, *, clear_api_key: bool = False
    ) -> dict:
        """Validate and atomically save one registered configuration group.

        Args:
            name: Registered group name; never an arbitrary filename.
            values: Edited configuration fields, merged with the current values.
            revision: Revision loaded by the caller, used to reject stale writes.
            clear_api_key: Explicit action to remove the stored model credential.

        Returns:
            The refreshed public form without credential contents.

        Raises:
            SettingsError: The edit is invalid or its revision is stale.
            OSError: The configuration file cannot be written.
        """
        current, latest = self._read(name)
        if latest != revision:
            raise SettingsError("设置已被其他页面修改，请重新载入后再保存", status=409)
        if clear_api_key and name != "model_config":
            raise SettingsError("这类设置不包含模型密钥")
        candidate = _fill_defaults(values, current)
        if name == "model_config":
            if "api_key" in values and not isinstance(values["api_key"], str):
                raise SettingsError(
                    "请填写有效的 API Key", fields={"api_key": "密钥必须是文本"}
                )
            candidate["api_key"] = (
                "" if clear_api_key else (values.get("api_key") or current["api_key"])
            )
        group = GROUPS[name]
        try:
            validated = group.schema.model_validate(candidate)
        except ValidationError as exc:
            fields = {}
            for error in exc.errors(
                include_input=False, include_context=False, include_url=False
            ):
                path = ".".join(str(part) for part in error["loc"])
                label = group.fields.get(path, ("配置",))[0]
                if error["type"] in {
                    "greater_than_equal",
                    "less_than_equal",
                    "greater_than",
                    "less_than",
                }:
                    fields[path] = f"{label}超出允许范围，请参考输入框提示"
                elif error["type"] == "extra_forbidden":
                    fields[path] = "包含无法识别的设置项，请重新载入页面"
                elif path in {"paths.data_dir", "file_path"}:
                    fields[path] = (
                        f"{label}必须位于指定的数据目录内，且目录不能当作文件、文件不能当作目录"
                        + (
                            "；数据库须使用 .db、.sqlite 或 .sqlite3 扩展名"
                            if name == "database_config"
                            else ""
                        )
                    )
                elif path == "base_url":
                    fields[path] = (
                        "请填写有效的 HTTP 或 HTTPS 接口前缀，不包含密钥、查询参数或片段"
                    )
                elif not path and name == "model_config":
                    for field in ("model", "api_key"):
                        if not str(candidate.get(field, "")).strip():
                            fields[field] = "启用模型前，请填写此项"
                else:
                    fields[path] = f"请填写有效的{label}"
            raise SettingsError(
                "请检查标出的设置，原配置尚未修改", fields=fields
            ) from None
        stored = validated.model_dump(mode="json")
        if name == "model_config":
            stored["api_key"] = validated.api_key.get_secret_value()
        elif name == "cmd_config":
            stored["paths"]["data_dir"] = paths.as_project_relative(
                validated.paths.data_dir
            )
        elif name in {"logging_config", "database_config"}:
            stored["file_path"] = paths.as_project_relative(validated.file_path)
        if name == "model_config" and stored["base_url"].endswith("/chat/completions"):
            raise SettingsError(
                "接口地址请填写前缀，移除结尾的 /chat/completions",
                fields={"base_url": "例如 https://api.openai.com/v1"},
            )
        if stored != current:
            _save_update(paths.get_config_path(name), stored)
        return self.get(name)
