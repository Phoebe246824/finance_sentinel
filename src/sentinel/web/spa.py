"""前端 SPA 静态资源挂载与回退路由。"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles


def default_frontend_dist() -> Path:
    return Path(__file__).resolve().parents[3] / "frontend" / "dist"


def mount_spa(app: FastAPI, dist_dir: Path | None = None) -> None:
    dist = dist_dir or default_frontend_dist()
    assets_dir = dist / "assets"
    index_file = dist / "index.html"

    if assets_dir.exists():
        app.mount("/assets", StaticFiles(directory=assets_dir), name="frontend-assets")

    @app.get("/", response_class=HTMLResponse, include_in_schema=False)
    async def dashboard_home():
        if index_file.exists():
            return FileResponse(index_file)
        return HTMLResponse(
            "<!doctype html><html><head><title>Sentinel Dashboard</title></head>"
            '<body><main id="app">Sentinel Dashboard API is running.</main></body></html>'
        )

    @app.get("/{full_path:path}", include_in_schema=False)
    async def dashboard_spa_fallback(full_path: str):
        if full_path.startswith("api/"):
            raise HTTPException(status_code=404, detail="API route not found")
        if index_file.exists():
            return FileResponse(index_file)
        return HTMLResponse(
            "<!doctype html><html><head><title>Sentinel Dashboard</title></head>"
            '<body><main id="app">Build the frontend with pnpm build.</main></body></html>'
        )
