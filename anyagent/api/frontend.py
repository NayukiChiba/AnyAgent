"""Serve the built Vue application using paths supplied by runtime."""

from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles


def install_frontend(app: FastAPI, *, index_file: Path, assets_dir: Path) -> None:
    app.mount(
        "/assets",
        StaticFiles(directory=assets_dir, check_dir=False),
        name="frontend-assets",
    )

    @app.get("/settings", include_in_schema=False, response_model=None)
    @app.get("/runners", include_in_schema=False, response_model=None)
    @app.get("/models", include_in_schema=False, response_model=None)
    @app.get("/logs", include_in_schema=False, response_model=None)
    @app.get("/", include_in_schema=False, response_model=None)
    async def frontend():
        if not index_file.is_file():
            return JSONResponse(
                {
                    "detail": "前端尚未构建，请在 frontend 目录运行 npm ci 和 npm run build。"
                },
                status_code=503,
            )
        return FileResponse(index_file, headers={"Cache-Control": "no-cache"})
