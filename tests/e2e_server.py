"""Run isolated SDK-backed HTTP endpoints for browser acceptance tests."""

import json
from pathlib import Path
from tempfile import TemporaryDirectory

import uvicorn

from anyagent.configs import load_logging_config, paths
from anyagent.runtime.bootstrap import create_app
from anyagent.utils.logger import LogManager
from tests.model_fixture import open_model_endpoint


def main():
    with (
        TemporaryDirectory(prefix="anyagent-e2e-") as directory,
        open_model_endpoint() as (base_url, _),
    ):
        index = paths.get_frontend_index_path()
        assets = paths.get_frontend_assets_dir()
        paths.get_frontend_index_path = lambda: index
        paths.get_frontend_assets_dir = lambda: assets
        paths.PROJECT_ROOT = Path(directory)
        paths.DATA_DIR = Path(directory) / "data"
        paths.CONFIGS_DIR = paths.DATA_DIR / "configs"
        paths.LOGS_DIR = paths.DATA_DIR / "logs"
        paths.LEGACY_CONFIG_FILE = paths.DATA_DIR / "config.json"
        paths.get_configs_dir().mkdir(parents=True)
        # 与正式入口一致：配置日志后实时日志接口才有内容
        LogManager.configure(load_logging_config())
        paths.get_config_path("model_config").write_text(
            json.dumps(
                {
                    "enabled": True,
                    "base_url": base_url,
                    "model": "browser-fixture",
                    "api_key": "browser-local-key",
                }
            )
        )
        uvicorn.run(create_app(), host="127.0.0.1", port=18765, log_level="warning")


if __name__ == "__main__":
    main()
