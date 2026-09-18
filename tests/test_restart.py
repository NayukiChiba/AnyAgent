"""Verify restart negotiation and replacement of a real isolated server process."""

import json
import os
import shutil
import signal
import socket
import subprocess
import sys
import time
from urllib.error import URLError
from urllib.request import Request, urlopen

import pytest
from fastapi.testclient import TestClient

from anyagent.configs import paths
from anyagent.runtime.bootstrap import create_app
from anyagent.runtime.restart import RestartController


def test_restart_api_requires_explicit_lifecycle_and_same_origin():
    calls = []
    controller = RestartController(lambda: calls.append("stop"), port_override=8123)
    with TestClient(create_app(restart_controller=controller)) as client:
        status = client.get("/api/v1/system")
        assert status.headers["access-control-allow-origin"] == "*"
        assert status.json()["restart_available"]
        assert (
            client.post(
                "/api/v1/system/restart", headers={"Origin": "https://other.invalid"}
            ).status_code
            == 403
        )
        assert not calls
        response = client.post("/api/v1/system/restart")
        assert response.status_code == 202
        assert response.json()["port"] == 8123
        assert response.json()["instance_id"] == controller.instance_id
        assert calls == ["stop"]
        assert client.get("/api/v1/system").json()["restarting"]
        assert client.post("/api/v1/system/restart").status_code == 409
        assert calls == ["stop"]
    with TestClient(create_app()) as client:
        assert not client.get("/api/v1/system").json()["restart_available"]
        assert client.post("/api/v1/system/restart").status_code == 503


def free_port():
    with socket.socket() as server:
        server.bind(("127.0.0.1", 0))
        return server.getsockname()[1]


def http(port, path, *, method="GET", payload=None):
    request = Request(
        f"http://127.0.0.1:{port}{path}",
        method=method,
        headers={"Content-Type": "application/json"},
        data=json.dumps(payload).encode() if payload is not None else None,
    )
    with urlopen(request, timeout=1) as response:
        return json.load(response)


def wait_instance(process, port, previous=None):
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        assert process.poll() is None, "Server exited instead of restarting"
        try:
            status = http(port, "/api/v1/system")
            if status["ready"] and status["instance_id"] != previous:
                return status
        except (URLError, TimeoutError, ConnectionError):
            pass
        time.sleep(0.05)
    raise AssertionError("Replacement server did not become ready")


@pytest.mark.parametrize("override", [False, True])
def test_main_replaces_process_reloads_settings_and_preserves_cli(tmp_path, override):
    shutil.copytree(
        paths.get_project_root() / "anyagent",
        tmp_path / "anyagent",
        ignore=shutil.ignore_patterns("__pycache__"),
    )
    shutil.copy(paths.get_main_path(), tmp_path / "main.py")
    config_dir = tmp_path / "data/configs"
    config_dir.mkdir(parents=True)
    port, next_port = free_port(), free_port()
    (config_dir / "cmd_config.json").write_text(
        json.dumps(
            {
                "paths": {"data_dir": "data"},
                "server": {"host": "127.0.0.1", "port": port},
            }
        )
    )
    command = [sys.executable, str(tmp_path / "main.py")]
    if override:
        command.extend(["--port", str(port)])
    with (tmp_path / "server-output.txt").open("w+") as output:
        process = subprocess.Popen(
            command, cwd=tmp_path, stdout=output, stderr=subprocess.STDOUT
        )
        try:
            initial = wait_instance(process, port)
            http(port, "/api/v1/sessions", method="POST")
            groups = http(port, "/api/v1/settings")["groups"]
            agent = next(
                group for group in groups if group["name"] == "langchain_config"
            )
            http(
                port,
                "/api/v1/settings/langchain_config",
                method="PUT",
                payload={
                    "revision": agent["revision"],
                    "values": {"max_input_chars": 3},
                },
            )
            cmd = next(group for group in groups if group["name"] == "cmd_config")
            http(
                port,
                "/api/v1/settings/cmd_config",
                method="PUT",
                payload={
                    "revision": cmd["revision"],
                    "values": {"server": {"port": next_port}},
                },
            )
            response = http(port, "/api/v1/system/restart", method="POST")
            effective_port = port if override else next_port
            assert response["port"] == effective_port
            replaced = wait_instance(process, effective_port, initial["instance_id"])
            assert replaced["restart_available"] and not replaced["restarting"]
            assert http(effective_port, "/api/v1/sessions") == []
            assert (
                http(effective_port, "/api/v1/agent")["limits"]["max_input_chars"] == 3
            )
            assert not any(
                group["restart_required"]
                for group in http(effective_port, "/api/v1/settings")["groups"]
            )
            assert (tmp_path / "data/logs/anyagent.log").is_file()
        finally:
            if process.poll() is None:
                process.send_signal(
                    signal.SIGINT if os.name != "nt" else signal.SIGTERM
                )
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
            if process.returncode != 0:
                output.seek(0)
                pytest.fail(output.read())
