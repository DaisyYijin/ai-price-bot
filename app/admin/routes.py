"""管理后台 API：登录鉴权、配置读写、连通性测试、服务重启。

所有路由挂在 /admin 下；前端是单文件静态页（static/admin.html）。
"""

import asyncio
import json
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
    ("DATAOKE_APP_KEY", "dataoke_app_key", "AppKey", "dataoke", "text"),
    ("DATAOKE_APP_SECRET", "dataoke_app_secret", "AppSecret", "dataoke", "password"),
    ("JD_UNION_APP_KEY", "jd_union_app_key", "AppKey", "jdunion", "text"),
    ("JD_UNION_SECRET_KEY", "jd_union_secret_key", "AppSecretKey", "jdunion", "password"),
    ("BROWSER_ENABLED", "browser_enabled", "启用浏览器真实数据（美团，实验）", "browser", "checkbox"),
    ("AMAP_KEY", "amap_key", "Web服务 Key", "amap", "password"),
]

SECTION_LABELS = {
    "llm": "AI 大模型",
    "wecom": "企业微信",
    "dingtalk": "钉钉",
    "qq": "QQ 机器人",
    "general": "比价与会话",
    "dataoke": "淘宝真实数据（大淘客）",
    "jdunion": "京东真实数据（京东联盟）",
    "browser": "浏览器真实数据（实验）",
    "amap": "高德地图（附近搜索）",
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

    # ------------------------------------------------ 模型列表
    @router.post("/api/models")
    async def list_models(request: Request) -> JSONResponse:
        """按用户填写的 base_url + key 在线拉取 OpenAI 兼容的 /models 列表。"""
        if not _authed(request):
            return _unauthorized()
        body = await request.json()
        effective = _effective_values(body.get("values") or {})
        base_url = effective.get("LLM_BASE_URL") or "https://api.deepseek.com"
        api_key = effective.get("LLM_API_KEY")
        if not api_key:
            return JSONResponse({"detail": "请先填写 API Key"}, status_code=400)
        try:
            models = await _fetch_models(base_url, api_key)
        except Exception as exc:  # noqa: BLE001 — 失败原因直接回显给用户
            return JSONResponse({"ok": False, "detail": f"获取失败：{exc}"})
        if not models:
            return JSONResponse({"ok": False, "detail": "接口未返回任何模型，请手动填写模型名"})
        return {"ok": True, "models": models, "detail": f"获取到 {len(models)} 个模型，点击模型输入框选择"}

    # ------------------------------------------------ 默认位置
    @router.get("/api/location")
    async def get_default_location(request: Request):
        if not _authed(request):
            return _unauthorized()
        from app.core import locations

        return {"location": locations.get_default()}

    @router.post("/api/location")
    async def set_default_location(request: Request) -> JSONResponse:
        if not _authed(request):
            return _unauthorized()
        from app.core import locations
        from app.tools import nearby

        body = await request.json()
        lat, lng = body.get("lat"), body.get("lng")
        address = str(body.get("address") or "").strip()
        fields: dict = {}
        try:
            if lat is not None and lng is not None:
                if not nearby.amap_configured():
                    return JSONResponse({"detail": "坐标定位需要配置高德Key"}, status_code=400)
                formatted = await nearby.regeo(str(lng), str(lat))
                fields = {"lat": str(lat), "lng": str(lng), "address": formatted}
            elif address:
                if nearby.amap_configured():
                    try:
                        formatted, g_lng, g_lat = await nearby.geocode(address)
                        fields = {"address": formatted, "lng": g_lng, "lat": g_lat}
                    except Exception:
                        fields = {"address": address}  # 解析失败仍保存文本
                else:
                    fields = {"address": address}
            else:
                return JSONResponse({"detail": "缺少 lat/lng 或 address"}, status_code=400)
        except Exception as exc:  # noqa: BLE001
            return JSONResponse({"detail": f"位置解析失败：{exc}"}, status_code=400)
        entry = locations.set_default(**fields)
        return {"ok": True, "location": entry}

    # ------------------------------------------------ 浏览器扫码登录
    @router.post("/api/browser-login/start")
    async def browser_login_start(request: Request) -> JSONResponse:
        if not _authed(request):
            return _unauthorized()
        from app.browser import login_relay

        body = await request.json()
        relay = login_relay.get_login_relay()
        ok = await relay.start(
            str(body.get("platform") or ""),
            phone=str(body.get("phone") or ""),
            password=str(body.get("password") or ""),
        )
        if not ok:
            return JSONResponse({"detail": relay.message or "不支持的平台/参数缺失"}, status_code=400)
        return {"ok": True, "state": relay.state, "message": relay.message}

    @router.post("/api/browser-login/code")
    async def browser_login_code(request: Request) -> JSONResponse:
        if not _authed(request):
            return _unauthorized()
        from app.browser import login_relay

        body = await request.json()
        relay = login_relay.get_login_relay()
        if not await relay.submit_sms(str(body.get("code") or "")):
            return JSONResponse({"detail": "当前不在等待验证码状态"}, status_code=400)
        return {"ok": True}

    @router.get("/api/browser-login/frame")
    async def browser_login_frame(request: Request):
        from fastapi.responses import Response

        from app.browser import login_relay

        if not _authed(request):
            return _unauthorized()
        relay = login_relay.get_login_relay()
        return Response(
            content=relay.frame_png or b"",
            media_type="image/png",
            headers={"Cache-Control": "no-store"},
        )

    @router.get("/api/browser-login/status")
    async def browser_login_status(request: Request):
        if not _authed(request):
            return _unauthorized()
        from app.browser import manager as bm
        from app.browser import login_relay

        relay = login_relay.get_login_relay()
        return {
            "state": relay.state,
            "message": relay.message,
            "logged": {name: bm.is_logged_in(name) for name in login_relay.LOGIN_TARGETS},
        }

    # ------------------------------------------------ 模型自动识别
    @router.post("/api/detect-llm")
    async def detect_llm(request: Request) -> JSONResponse:
        """只填 API Key 时自动识别厂商：逐个探测候选厂商的 /models 接口。"""
        if not _authed(request):
            return _unauthorized()
        body = await request.json()
        api_key = str(body.get("api_key") or "").strip()
        base_url = str(body.get("base_url") or "").strip()
        if not api_key:
            return JSONResponse({"detail": "请先填写 API Key"}, status_code=400)

        candidates = [(base_url, "自定义", "")] if base_url else [
            ("https://api.deepseek.com", "DeepSeek", "deepseek-chat"),
            ("https://api.moonshot.cn/v1", "Kimi", ""),
            ("https://open.bigmodel.cn/api/paas/v4", "智谱 GLM", ""),
            ("https://dashscope.aliyuncs.com/compatible-mode/v1", "通义千问", ""),
            ("https://api.openai.com/v1", "OpenAI", ""),
        ]
        for url, provider, preferred in candidates:
            try:
                models = await _fetch_models(url, api_key)
            except Exception:
                continue
            if not models:
                continue
            return {
                "ok": True,
                "provider": provider,
                "base_url": url,
                "models": models,
                "recommended": preferred if preferred in models else _recommend_model(provider, models),
                "detail": f"识别为 {provider}，可用模型 {len(models)} 个",
            }
        return JSONResponse(
            {"ok": False, "detail": "未识别出厂商：Key 无效或不在支持列表（DeepSeek/Kimi/智谱/通义/OpenAI），可手动填 API 地址"},
        )

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


def _recommend_model(provider: str, models: list[str]) -> str:
    """从模型列表里挑一个默认推荐：优先常见主力型号关键词，再取字典序首个。"""
    preferences = {
        "DeepSeek": ("deepseek-chat", "deepseek-reasoner"),
        "Kimi": ("moonshot-v1-8k", "kimi"),
        "智谱 GLM": ("glm-4", "glm-3"),
        "通义千问": ("qwen-plus", "qwen-turbo", "qwen-max"),
        "OpenAI": ("gpt-4o-mini", "gpt-4o", "gpt-4.1-mini"),
    }.get(provider, ())
    for preferred in preferences:
        for model in models:
            if model == preferred or preferred in model:
                return model
    return sorted(models)[0]


async def _fetch_models(base_url: str, api_key: str) -> list[str]:
    """调用 OpenAI 兼容的 GET {base_url}/models，返回模型 id 列表。"""
    base = base_url.rstrip("/")
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.get(f"{base}/models", headers={"Authorization": f"Bearer {api_key}"})
    resp.raise_for_status()
    data = resp.json()
    return sorted(
        item["id"] for item in data.get("data", []) if isinstance(item, dict) and item.get("id")
    )


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

    if target == "dataoke":
        if not (v.get("DATAOKE_APP_KEY") and v.get("DATAOKE_APP_SECRET")):
            return False, "请先填写大淘客 AppKey 与 AppSecret"
        from app.providers.dataoke import _GOODS_LIST_URL, dataoke_sign

        params = {
            "appKey": v["DATAOKE_APP_KEY"],
            "version": "v1.2.4",
            "keyWords": "手机",
            "pageId": "1",
            "pageSize": "1",
        }
        params["sign"] = dataoke_sign(params, v["DATAOKE_APP_SECRET"])
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(_GOODS_LIST_URL, params=params)
            data = resp.json()
        if data.get("code") == 0:
            count = len((data.get("data") or {}).get("list") or [])
            return True, f"接口可用，返回 {count} 条商品"
        return False, str(data.get("msg") or data)[:200]

    if target == "jdunion":
        if not (v.get("JD_UNION_APP_KEY") and v.get("JD_UNION_SECRET_KEY")):
            return False, "请先填写京东联盟 AppKey 与 AppSecretKey"
        from app.providers.jd_union import _post_json, _ROUTER_URL, jd_union_sign

        payload = {
            "method": "jd.union.open.goods.query",
            "app_key": v["JD_UNION_APP_KEY"],
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
            "format": "json",
            "v": "1.0",
            "sign_method": "md5",
            "360buy_param_json": '{"goodsReqDTO":{"keyword":"手机","pageIndex":1,"pageSize":1}}',
        }
        payload["sign"] = jd_union_sign(payload, v["JD_UNION_SECRET_KEY"])
        data = await _post_json(_ROUTER_URL, payload)
        envelope = data.get("jd_union_open_goods_query_responce") or {}
        result = envelope.get("queryResult")
        inner = json.loads(result) if isinstance(result, str) else (result or {})
        if inner.get("code") == 0:
            count = len((inner.get("data") or {}).get("list") or [])
            return True, f"接口可用，返回 {count} 条商品"
        return False, str(inner.get("message") or data)[:200]

    if target == "amap":
        if not v.get("AMAP_KEY"):
            return False, "请先填写高德 Web服务 Key"
        from app.tools.nearby import _GEOCODE_URL

        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(_GEOCODE_URL, params={"address": "北京市朝阳区", "key": v["AMAP_KEY"]})
            data = resp.json()
        if data.get("status") == "1" and data.get("geocodes"):
            formatted = (data["geocodes"][0] or {}).get("formatted_address", "")
            return True, f"Key 可用，示例解析：{formatted}"
        return False, str(data.get("info") or data)[:200]

    if target == "browser":
        from app.browser import manager as bm

        try:
            import playwright  # noqa: F401

            playwright_ok = True
        except ImportError:
            playwright_ok = False
        logged = [p for p in ("meituan", "douyin") if bm.is_logged_in(p)]
        if not playwright_ok:
            return False, "服务器未安装 Playwright/Chromium（镜像需包含浏览器）"
        if not logged:
            return False, "尚未扫码登录任何平台：在「浏览器登录」卡片发起美团扫码"
        return True, f"已登录: {', '.join(logged)}（查询时用登录态浏览器抓取真实数据）"

    return False, f"未知测试目标：{target}"
