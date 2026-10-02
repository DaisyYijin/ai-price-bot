"""FastAPI 应用入口：按 .env 开关装配各平台适配器。

启动: uvicorn app.main:app --host 0.0.0.0 --port 8000
健康检查: GET /healthz
"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.config import get_settings
from app.core.dispatcher import Dispatcher
from app.platforms.base import PlatformAdapter

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("app.main")


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


@asynccontextmanager
async def lifespan(app: FastAPI):
    dispatcher: Dispatcher = app.state.dispatcher
    started: list[PlatformAdapter] = []
    for adapter in app.state.adapters:
        try:
            await adapter.start()
            started.append(adapter)
            logger.info("平台 %s 已启动", adapter.platform)
        except Exception:
            logger.exception("平台 %s 启动失败（跳过）", adapter.platform)
    yield
    for adapter in started:
        stop = getattr(adapter, "stop", None)
        if stop:
            try:
                await stop()
            except Exception:
                logger.exception("平台 %s 停止异常", adapter.platform)


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title="AI 比价机器人助手", lifespan=lifespan)
    app.state.dispatcher = Dispatcher()
    app.state.adapters = _build_adapters(app.state.dispatcher)

    # 网页管理后台：配置填写、连通性测试、重启（始终可用，与平台开关无关）
    from app.admin.routes import create_admin_router

    app.include_router(create_admin_router(app.state.dispatcher))

    for adapter in app.state.adapters:
        adapter.register_routes(app)

    @app.get("/healthz")
    async def healthz() -> dict:
        return {
            "status": "ok",
            "platforms": [a.platform for a in app.state.adapters],
            "llm": settings.llm_model if settings.llm_api_key else "(未配置，仅规则模式)",
        }

    return app


app = create_app()
