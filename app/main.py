"""应用工厂：单进程内两个 FastAPI 服务，共享 Dispatcher/浏览器/位置数据。

  管理服务（默认 2048）：管理后台 /admin、平台回调（企微 webhook）与适配器长连接、/healthz
  前台服务（默认 2222）：前台首页 /、网页聊天 /chat、/healthz

启动入口: python -m app.serve（本模块末尾的 admin_app/public_app 供 uvicorn 引用）
"""

import logging
from contextlib import asynccontextmanager
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse, RedirectResponse

from app.config import LOG_DIR, get_settings
from app.core.dispatcher import Dispatcher
from app.platforms.base import PlatformAdapter


def _setup_logging() -> None:
    """stdout + logs/app.log 双路输出，日志按天轮转保留 14 天。"""
    handlers: list[logging.Handler] = [logging.StreamHandler()]
    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        handlers.append(
            TimedRotatingFileHandler(
                LOG_DIR / "app.log", when="midnight", backupCount=14, encoding="utf-8"
            )
        )
    except OSError:  # 只读文件系统等异常场景下退回仅 stdout
        pass
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=handlers,
    )


logger = logging.getLogger("app.main")

# 进程级共享状态：两个服务用同一个 Dispatcher（会话历史/数据源/浏览器互通）
_runtime: dict = {}


def _state() -> dict:
    if "dispatcher" not in _runtime:
        _runtime["dispatcher"] = Dispatcher()
    if "adapters" not in _runtime:
        _runtime["adapters"] = _build_adapters(_runtime["dispatcher"])
    return _runtime


def _build_adapters(dispatcher: Dispatcher) -> list[PlatformAdapter]:
    settings = get_settings()
    adapters: list[PlatformAdapter] = []

    if settings.wecom_enabled:
        from app.platforms.wecom import WecomAdapter

        adapters.append(WecomAdapter(dispatcher))
    if settings.dingtalk_enabled:
        from app.platforms.dingtalk import DingtalkAdapter

        adapters.append(DingtalkAdapter(dispatcher))
    if settings.qq_enabled:
        from app.platforms.qq_official import QQOfficialAdapter

        adapters.append(QQOfficialAdapter(dispatcher))
    return adapters


async def _stop_shared() -> None:
    for adapter in _state().get("adapters", []):
        stop = getattr(adapter, "stop", None)
        if stop:
            try:
                await stop()
            except Exception:
                logger.exception("平台 %s 停止异常", adapter.platform)
    try:  # 关闭无头浏览器
        from app.browser.manager import get_browser_manager

        await get_browser_manager().aclose()
    except Exception:
        logger.exception("浏览器关闭异常")


@asynccontextmanager
async def _admin_lifespan(app: FastAPI):
    started: list[PlatformAdapter] = []
    for adapter in app.state.adapters:
        try:
            await adapter.start()
            started.append(adapter)
            logger.info("平台 %s 已启动", adapter.platform)
        except Exception:
            logger.exception("平台 %s 启动失败（跳过）", adapter.platform)
    yield
    await _stop_shared()


@asynccontextmanager
async def _public_lifespan(app: FastAPI):
    yield  # 前台无平台适配器；共享资源的关闭由管理服务负责
    await _stop_shared()


def create_admin_app() -> FastAPI:
    state = _state()
    app = FastAPI(title="AI 比价机器人助手 · 管理", lifespan=_admin_lifespan)
    app.state.dispatcher = state["dispatcher"]
    app.state.adapters = state["adapters"]

    from app.admin.routes import create_admin_router

    app.include_router(create_admin_router(app.state.dispatcher))
    for adapter in app.state.adapters:
        adapter.register_routes(app)

    @app.get("/", include_in_schema=False)
    async def root() -> RedirectResponse:
        return RedirectResponse(url="/admin")

    @app.get("/healthz")
    async def healthz() -> dict:
        settings = get_settings()
        return {
            "status": "ok",
            "service": "admin",
            "platforms": [a.platform for a in app.state.adapters],
            "llm": settings.llm_model if settings.llm_api_key else "(未配置，仅规则模式)",
        }

    return app


def create_public_app() -> FastAPI:
    state = _state()
    app = FastAPI(title="AI 比价机器人助手 · 前台", lifespan=_public_lifespan)
    app.state.dispatcher = state["dispatcher"]

    from app.webchat.routes import create_webchat_router

    app.include_router(create_webchat_router(app.state.dispatcher))

    _landing = Path(__file__).parent / "webchat" / "static" / "index.html"

    @app.get("/", include_in_schema=False)
    async def home() -> FileResponse:
        return FileResponse(_landing, media_type="text/html")

    @app.get("/healthz")
    async def healthz() -> dict:
        return {"status": "ok", "service": "public"}

    return app


def create_app() -> FastAPI:
    """兼容旧入口：返回管理服务应用。"""
    return create_admin_app()


# 供 uvicorn 字符串引用（app.main:admin_app / app.main:public_app）
admin_app = create_admin_app()
public_app = create_public_app()
