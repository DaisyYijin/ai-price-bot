"""管理后台 API：登录鉴权、配置读写、连通性测试、服务重启。

所有路由挂在 /admin 下；前端是单文件静态页（static/admin.html）。
"""

import asyncio
import os
import time
from pathlib import Path

import httpx
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse

from app.admin import store
from app.config import get_settings, reload_settings
from app.core.dispatcher import Dispatcher

COOKIE_NAME = "pb_admin"
_PAGE_PATH = Path(__file__).parent / "static" / "admin.html"

# (env键, settings属性, 标签, 分区, 类型)；secret 字段永不回传浏览器
FIELDS: list[tuple[str, str, str, str, str]] = [
    ("LLM_BASE_URL", "llm_base_url", "API 地址", "llm", "text"),
    ("LLM_MODEL", "llm_model", "模型名称", "llm", "text"),
    ("LLM_API_KEY", "llm_api_key", "API Key", "llm", "password"),
    ("WECOM_ENABLED", "wecom_enabled", "启用企业微信", "wecom", "checkbox"),
    ("WECOM_CORP_ID", "wecom_corp_id", "Corp ID", "wecom", "text"),
    ("WECOM_AGENT_ID", "wecom_agent_id", "Agent ID（数字）", "wecom", "text"),
    ("WECOM_SECRET", "wecom_secret", "应用 Secret", "wecom", "password"),
    ("WECOM_TOKEN", "wecom_token", "回调 Token", "wecom", "text"),
    ("WECOM_ENCODING_AES_KEY", "wecom_encoding_aes_key", "EncodingAESKey", "wecom", "password"),
    ("DINGTALK_ENABLED", "dingtalk_enabled", "启用钉钉", "dingtalk", "checkbox"),
    ("DINGTALK_CLIENT_ID", "dingtalk_client_id", "Client ID", "dingtalk", "text"),
    ("DINGTALK_CLIENT_SECRET", "dingtalk_client_secret", "Client Secret", "dingtalk", "password"),
    ("QQ_ENABLED", "qq_enabled", "启用 QQ 机器人", "qq", "checkbox"),
    ("QQ_APP_ID", "qq_app_id", "App ID", "qq", "text"),
    ("QQ_CLIENT_SECRET", "qq_client_secret", "Client Secret", "qq", "password"),
    ("PRICE_PROVIDERS", "price_providers", "价格源（逗号分隔）", "general", "text"),
    ("HISTORY_ROUNDS", "history_rounds", "会话保留轮数", "general", "text"),
]

SECTION_LABELS = {
    "llm": "AI 大模型",
    "wecom": "企业微信",
    "dingtalk": "钉钉",
    "qq": "QQ 机器人",
    "general": "比价与会话",
}

# 登录失败锁定：IP → (连续失败数, 锁定截止时间)
_login_failures: dict[str, tuple[int, float]] = {}
_MAX_FAILS = 5
_LOCK_SECONDS = 60


def _unauthorized() -> JSONResponse:
    return JSONResponse({"detail": "未登录"}, status_code=401)


def _authed(request: Request) -> bool:
    return store.verify_session(request.cookies.get(COOKIE_NAME))


def _client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def create_admin_router(dispatcher: Dispatcher) -> APIRouter:
    router = APIRouter(prefix="/admin")

    @router.get("", response_class=HTMLResponse, include_in_schema=False)
    @router.get("/", response_class=HTMLResponse, include_in_schema=False)
    async def page() -> HTMLResponse:
        return HTMLResponse(_PAGE_PATH.read_text(encoding="utf-8"))

    # ------------------------------------------------ 鉴权
    @router.get("/api/state")
    async def state(request: Request) -> dict:
        return {
            "credentials_set": store.credentials_are_set(),
            "authenticated": _authed(request),
        }

    @router.post("/api/setup")
    async def setup(request: Request) -> JSONResponse:
        if store.env_admin_password():
            return JSONResponse(
                {"detail": "账号密码已由环境变量 ADMIN_USERNAME / ADMIN_PASSWORD 指定，直接登录即可"},
                status_code=400,
            )
        if store.credentials_are_set():
            return JSONResponse({"detail": "账号密码已设置，请直接登录"}, status_code=400)
        body = await request.json()
        username = str(body.get("username") or "").strip() or store.DEFAULT_ADMIN_USERNAME
        password = str(body.get("password") or "")
        if len(password) < 6:
            return JSONResponse({"detail": "密码至少 6 位"}, status_code=400)
        store.set_credentials(username, password)
        response = JSONResponse({"ok": True})
        response.set_cookie(COOKIE_NAME, store.create_session(), httponly=True, samesite="lax")
        return response

    @router.post("/api/login")
    async def login(request: Request) -> JSONResponse:
        ip = _client_ip(request)
        fails, locked_until = _login_failures.get(ip, (0, 0.0))
        if time.time() < locked_until:
            remain = int(locked_until - time.time()) + 1
            return JSONResponse({"detail": f"失败次数过多，{remain} 秒后再试"}, status_code=429)
        if not store.credentials_are_set():
            return JSONResponse({"detail": "尚未设置账号密码，请先初始化"}, status_code=400)
        body = await request.json()
        username = str(body.get("username") or "")
        password = str(body.get("password") or "")
        if not store.verify_credentials(username, password):
            _login_failures[ip] = (fails + 1, time.time() + _LOCK_SECONDS if fails + 1 >= _MAX_FAILS else 0.0)
            return JSONResponse({"detail": "账号或密码错误"}, status_code=401)
        _login_failures.pop(ip, None)
        response = JSONResponse({"ok": True})
        response.set_cookie(COOKIE_NAME, store.create_session(), httponly=True, samesite="lax")
        return response

    @router.post("/api/logout")
    async def logout() -> JSONResponse:
        response = JSONResponse({"ok": True})
        response.delete_cookie(COOKIE_NAME)
        return response

    # ------------------------------------------------ 配置
    @router.get("/api/config")
    async def get_config(request: Request) -> JSONResponse:
        if not _authed(request):
            return _unauthorized()
        settings = get_settings()
        saved = store.read_config()  # 面板管理的值以落盘文件为准
        fields = []
        for env_key, attr, label, section, kind in FIELDS:
            if kind == "password":
                is_set = bool(saved.get(env_key) or getattr(settings, attr))
                fields.append({"key": env_key, "label": label, "section": section,
                               "type": kind, "value": "", "set": is_set})
                continue
            raw = saved.get(env_key)
            if raw is None:
                current = getattr(settings, attr)
                value = bool(current) if kind == "checkbox" else (
                    "" if current in (0, None) else str(current)
                )
            elif kind == "checkbox":
                value = raw.strip().lower() == "true"
            else:
                value = raw
            fields.append({"key": env_key, "label": label, "section": section,
                           "type": kind, "value": value})
        return {"fields": fields, "sections": SECTION_LABELS}

    @router.post("/api/config")
    async def save_config(request: Request) -> JSONResponse:
        if not _authed(request):
            return _unauthorized()
        body = await request.json()
        payload: dict[str, str] = body.get("values") or {}

        allowed = {env_key: kind for env_key, _, _, _, kind in FIELDS}
        updates: dict[str, str] = {}
        for key, raw in payload.items():
            if key not in allowed:
                continue
            if isinstance(raw, bool):
                updates[key] = "true" if raw else "false"
            else:
                updates[key] = str(raw).strip()

        error = _validate(updates)
        if error:
            return JSONResponse({"detail": error}, status_code=400)

        before = store.read_config()
        merged = store.merge_config(updates)
        reload_settings()

        # LLM 与价格源是按次读取配置的，热重建客户端即可立即生效
        old_llm = dispatcher.llm
        from app.llm.client import LLMClient

        dispatcher.llm = LLMClient()
        close = getattr(old_llm, "aclose", None)
        if close:
            asyncio.create_task(close())

        # 平台适配器在启动时读取配置，相关键的值发生变化才需要重启
        platform_changed = any(
            merged.get(key, "") != before.get(key, "")
            and key.startswith(("WECOM_", "DINGTALK_", "QQ_"))
            for key in set(merged) | set(before)
        )
        return {"saved": True, "restart_required": platform_changed}

    # ------------------------------------------------ 连通性测试
    @router.post("/api/test")
    async def test_connectivity(request: Request) -> JSONResponse:
        if not _authed(request):
            return _unauthorized()
        body = await request.json()
        target = str(body.get("target") or "")
        effective = _effective_values(body.get("values") or {})
        try:
            ok, detail = await _run_test(target, effective)
            return {"ok": ok, "detail": detail}
        except Exception as exc:  # noqa: BLE001 — 测试结果直接回显给用户
            return {"ok": False, "detail": f"{type(exc).__name__}: {exc}"}

    # ------------------------------------------------ 重启
    @router.post("/api/restart")
    async def restart(request: Request) -> JSONResponse:
        if not _authed(request):
            return _unauthorized()

        async def _die() -> None:
            await asyncio.sleep(1.0)  # 等响应发出去再退出，容器由 restart 策略拉起
            os._exit(137)

        asyncio.create_task(_die())
        return JSONResponse({"restarting": True})

    return router


def _validate(updates: dict[str, str]) -> str | None:
    if rounds := updates.get("HISTORY_ROUNDS"):
        if not rounds.isdigit() or not 1 <= int(rounds) <= 100:
            return "会话保留轮数需为 1~100 的整数"
    if agent := updates.get("WECOM_AGENT_ID"):
        if not agent.isdigit():
            return "企业微信 Agent ID 需为数字"
    if providers := updates.get("PRICE_PROVIDERS"):
        names = [n.strip() for n in providers.split(",") if n.strip()]
        from app.providers import base as provider_base

        unknown = [n for n in names if n.lower() not in provider_base.available_names()
                   and not n.lower().startswith("mock")]
        if unknown:
            return f"未知价格源: {', '.join(unknown)}，可用: {', '.join(provider_base.available_names())}"
    return None


def _effective_values(payload_values: dict) -> dict[str, str]:
    """表单值优先（用户当场输入的密钥），空密钥回落到已保存的 config.env。"""
    saved = store.read_config()
    effective: dict[str, str] = {}
    for env_key, attr, _, _, kind in FIELDS:
        raw = payload_values.get(env_key)
        if isinstance(raw, bool):
            effective[env_key] = "true" if raw else "false"
        elif raw is not None and str(raw).strip() != "":
            effective[env_key] = str(raw).strip()
        elif env_key in saved:
            effective[env_key] = saved[env_key]
        else:
            current = getattr(get_settings(), attr)
            if isinstance(current, bool):
                effective[env_key] = "true" if current else "false"
            elif current not in (0, "", None):
                effective[env_key] = str(current)
            else:
                effective[env_key] = ""
    return effective


async def _run_test(target: str, v: dict[str, str]) -> tuple[bool, str]:
    if target == "llm":
        if not v.get("LLM_API_KEY"):
            return False, "请先填写 API Key"
        from openai import AsyncOpenAI

        client = AsyncOpenAI(base_url=v.get("LLM_BASE_URL") or "https://api.deepseek.com",
                             api_key=v["LLM_API_KEY"], timeout=20)
        response = await client.chat.completions.create(
            model=v.get("LLM_MODEL") or "deepseek-chat",
            messages=[{"role": "user", "content": "回复两个字：正常"}],
            max_tokens=8,
        )
        return True, f"模型已响应：{(response.choices[0].message.content or '').strip()[:20]}"

    if target == "wecom":
        if not (v.get("WECOM_CORP_ID") and v.get("WECOM_SECRET")):
            return False, "请先填写 Corp ID 与 Secret"
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get("https://qyapi.weixin.qq.com/cgi-bin/gettoken",
                                    params={"corpid": v["WECOM_CORP_ID"], "corpsecret": v["WECOM_SECRET"]})
            data = resp.json()
        if data.get("errcode") == 0:
            return True, "access_token 获取成功"
        return False, f"errcode={data.get('errcode')}: {data.get('errmsg')}"

    if target == "dingtalk":
        if not (v.get("DINGTALK_CLIENT_ID") and v.get("DINGTALK_CLIENT_SECRET")):
            return False, "请先填写 Client ID 与 Secret"
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post("https://api.dingtalk.com/v1.0/oauth2/accessToken",
                                     json={"clientId": v["DINGTALK_CLIENT_ID"],
                                           "clientSecret": v["DINGTALK_CLIENT_SECRET"]})
            data = resp.json()
        if data.get("accessToken"):
            return True, "accessToken 获取成功"
        return False, str(data)[:200]

    if target == "qq":
        if not (v.get("QQ_APP_ID") and v.get("QQ_CLIENT_SECRET")):
            return False, "请先填写 App ID 与 Client Secret"
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get("https://bots.qq.com/app/getAppAccessToken",
                                    params={"appId": v["QQ_APP_ID"], "clientSecret": v["QQ_CLIENT_SECRET"]})
            data = resp.json()
        if data.get("access_token"):
            return True, "access_token 获取成功"
        return False, str(data)[:200]

    return False, f"未知测试目标：{target}"
