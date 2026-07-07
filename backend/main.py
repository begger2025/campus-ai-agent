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
from backend.logging_setup import setup_logging  # noqa: E402
from backend.routers.admin import router as admin_router  # noqa: E402
from backend.routers.admin_events import router as admin_events_router  # noqa: E402
from backend.routers.agent_public import router as agent_public_router  # noqa: E402
from backend.routers.api import router as api_router  # noqa: E402
from backend.routers.auth import router as auth_router  # noqa: E402
from backend.routers.feedback import router as feedback_router  # noqa: E402
from backend.seed import seed_if_empty  # noqa: E402
from backend.services.auth_service import ensure_default_admin, ensure_default_demo_user  # noqa: E402
from backend.services.log_service import write_system_log  # noqa: E402

logger = setup_logging()


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
        ensure_default_demo_user(db)
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


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    """兜底：未捕获异常返回统一 JSON，不向前端泄露堆栈；同时写日志与 system_logs。"""

    logger.exception("unhandled error on %s %s", request.method, request.url.path)
    db = None
    try:
        db = SessionLocal()
        write_system_log(
            db,
            level="error",
            module="api",
            message=f"{type(exc).__name__}: {exc}",
            detail={"path": str(request.url.path), "method": request.method},
        )
        db.commit()
    except Exception:  # 落库失败不能掩盖原始错误响应
        logger.exception("failed to persist system log for unhandled error")
        if db is not None:
            db.rollback()
    finally:
        if db is not None:
            db.close()
    return JSONResponse(
        status_code=500,
        content={"code": 500, "message": "服务器内部错误，请稍后重试", "data": None},
    )
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
