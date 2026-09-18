"""Run isolated SDK-backed HTTP endpoints for browser acceptance tests."""

import json
from pathlib import Path
from tempfile import TemporaryDirectory

import uvicorn

from anyagent.configs import paths
from anyagent.runtime.bootstrap import create_app
from tests.model_fixture import open_model_endpoint


def main():
    with (
        TemporaryDirectory(prefix="anyagent-e2e-") as directory,
        open_model_endpoint() as (base_url, _),
    ):
        paths.DATA_DIR = Path(directory) / "data"
        paths.CONFIGS_DIR = paths.DATA_DIR / "configs"
        paths.get_configs_dir().mkdir(parents=True)
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
