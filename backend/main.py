import os
import sys
from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

ROOT = Path(__file__).resolve().parent.parent
FRONTEND = ROOT / "frontend"
DIST = FRONTEND / "dist"
load_dotenv(ROOT / ".env")

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.database import SessionLocal, init_db, uses_mysql  # noqa: E402
from backend.routers.admin import router as admin_router  # noqa: E402
from backend.routers.admin_events import router as admin_events_router  # noqa: E402
from backend.routers.agent_public import router as agent_public_router  # noqa: E402
from backend.routers.api import router as api_router  # noqa: E402
from backend.routers.auth import router as auth_router  # noqa: E402
from backend.routers.feedback import router as feedback_router  # noqa: E402
from backend.seed import seed_if_empty  # noqa: E402
from backend.services.auth_service import ensure_default_admin  # noqa: E402


def _should_seed_on_start() -> bool:
    """Work package 1: shared MySQL never auto-seeds demo data."""
    if uses_mysql():
        return False
    return os.getenv("SEED_DEMO_ON_START", "false").lower() in ("1", "true", "yes")


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    db = SessionLocal()
    try:
        ensure_default_admin(db)
        db.commit()
    finally:
        db.close()
    if _should_seed_on_start():
        db = SessionLocal()
        try:
            seed_if_empty(db)
        finally:
            db.close()
    yield


app = FastAPI(title="Campus AI Agent", lifespan=lifespan)
app.include_router(auth_router, prefix="/api")
app.include_router(admin_router, prefix="/api")
app.include_router(agent_public_router, prefix="/api")
app.include_router(admin_events_router, prefix="/api")
app.include_router(feedback_router, prefix="/api")
app.include_router(api_router, prefix="/api")


@app.api_route(
    "/api/{path:path}",
    methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
)
def api_not_found(path: str):
    return JSONResponse(
        status_code=404,
        content={"code": 404, "message": f"API not found: /api/{path}", "data": None},
    )


@app.get("/health")
def health():
    return {"status": "ok"}


# ── 前端静态资源托管 ──
# 优先使用 dist/（Vite 构建产物），回退到 frontend/（开发源码）
_static_dir = DIST if DIST.is_dir() else FRONTEND
_assets_dir = _static_dir / "assets"

if _assets_dir.is_dir():
    # /assets/* → dist/assets/*  或  frontend/assets/*
    app.mount("/assets", StaticFiles(directory=_assets_dir), name="assets")

if _static_dir.is_dir():
    # 其他静态文件（favicon 等）
    app.mount("/static", StaticFiles(directory=_static_dir), name="static")


@app.get("/")
@app.get("/{path:path}")
def serve_spa(request: Request, path: str = ""):
    """SPA fallback：已知静态文件直接返回，其余都返回 index.html（交给 Vue Router 处理）"""
    # 如果请求的就是真实存在的文件（如 /assets/xxx.js），StaticFiles mount 已处理
    # 这里只处理 HTML 页面路由和 SPA fallback
    html = _static_dir / "index.html"
    if html.is_file():
        return FileResponse(html)
    return {"detail": "Frontend not found. Run 'cd frontend && npm run build' first."}


if __name__ == "__main__":
    import uvicorn

    host = os.getenv("APP_HOST", "127.0.0.1")
    port = int(os.getenv("APP_PORT", "9000"))
    uvicorn.run(app, host=host, port=port)
