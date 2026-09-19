"""Verify automatic frontend preparation for source-based startup."""

import subprocess
from pathlib import Path

from anyagent.configs import paths
from anyagent.runtime.frontend import ensure_frontend_build


def create_frontend_files(frontend_dir: Path) -> None:
    frontend_dir.mkdir()
    (frontend_dir / "package.json").write_text("{}", encoding="utf-8")
    (frontend_dir / "package-lock.json").write_text("{}", encoding="utf-8")


def test_existing_frontend_build_skips_npm(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "PROJECT_ROOT", tmp_path)
    index_path = tmp_path / "frontend/dist/index.html"
    index_path.parent.mkdir(parents=True)
    index_path.write_text("ready", encoding="utf-8")

    def unexpected_which(command):
        raise AssertionError(command)

    monkeypatch.setattr("anyagent.runtime.frontend.shutil.which", unexpected_which)

    assert ensure_frontend_build()


def test_missing_dependencies_are_installed_before_build(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "PROJECT_ROOT", tmp_path)
    frontend_dir = tmp_path / "frontend"
    create_frontend_files(frontend_dir)
    commands = []

    def run(command, *, cwd, check):
        commands.append((command, cwd, check))
        if command[-2:] == ["run", "build"]:
            index_path = frontend_dir / "dist/index.html"
            index_path.parent.mkdir(parents=True)
            index_path.write_text("built", encoding="utf-8")

    monkeypatch.setattr("anyagent.runtime.frontend.shutil.which", lambda _: "npm")
    monkeypatch.setattr("anyagent.runtime.frontend.subprocess.run", run)

    assert ensure_frontend_build()
    assert commands == [
        (["npm", "ci"], frontend_dir, True),
        (["npm", "run", "build"], frontend_dir, True),
    ]


def test_existing_dependencies_only_trigger_build(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "PROJECT_ROOT", tmp_path)
    frontend_dir = tmp_path / "frontend"
    create_frontend_files(frontend_dir)
    (frontend_dir / "node_modules").mkdir()
    commands = []

    def run(command, *, cwd, check):
        commands.append(command)
        index_path = frontend_dir / "dist/index.html"
        index_path.parent.mkdir(parents=True)
        index_path.write_text("built", encoding="utf-8")

    monkeypatch.setattr("anyagent.runtime.frontend.shutil.which", lambda _: "npm")
    monkeypatch.setattr("anyagent.runtime.frontend.subprocess.run", run)

    assert ensure_frontend_build()
    assert commands == [["npm", "run", "build"]]


def test_build_failure_keeps_frontend_unavailable(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "PROJECT_ROOT", tmp_path)
    frontend_dir = tmp_path / "frontend"
    create_frontend_files(frontend_dir)
    (frontend_dir / "node_modules").mkdir()
    monkeypatch.setattr("anyagent.runtime.frontend.shutil.which", lambda _: "npm")

    def fail(*args, **kwargs):
        raise subprocess.CalledProcessError(1, args[0])

    monkeypatch.setattr("anyagent.runtime.frontend.subprocess.run", fail)

    assert not ensure_frontend_build()


def test_missing_npm_keeps_frontend_unavailable(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "PROJECT_ROOT", tmp_path)
    create_frontend_files(tmp_path / "frontend")
    monkeypatch.setattr("anyagent.runtime.frontend.shutil.which", lambda _: None)

    assert not ensure_frontend_build()
