"""JSON 文档存储的共享基类：原子写入与损坏自动备份。"""

import json
import time
from pathlib import Path

from pydantic import BaseModel

from anyagent.utils.logger import get_logger

logger = get_logger(__name__)


class JsonDocumentStore:
    """单个 JSON 文档的读写；文件不存在返回 None（由子类决定旧版兼容行为）。"""

    def __init__(self, path: Path):
        self._path = path

    @property
    def legacy_mode(self) -> bool:
        return not self._path.is_file()

    def _read(self) -> dict | None:
        """读取文档；不存在返回 None，损坏时备份后按不存在处理。"""
        try:
            with self._path.open(encoding="utf-8-sig") as file:
                data = json.load(file)
            if not isinstance(data, dict):
                raise ValueError("json document must be an object")
            return data
        except FileNotFoundError:
            return None
        except ValueError:
            backup = self._path.with_suffix(f".broken-{time.time_ns()}.json")
            self._path.rename(backup)
            logger.warning("Config document backed up to %s", backup)
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


def dump_profile(profile: BaseModel) -> dict:
    """序列化档案为存储字典；model_dump 会遮蔽密钥，需显式取回真实值。"""
    data = profile.model_dump()
    if hasattr(profile, "api_key"):
        data["api_key"] = profile.api_key.get_secret_value()
    return data
