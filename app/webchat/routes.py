"""网页聊天接口：手机浏览器直接和机器人对话 + GPS 精确定位。

复用管理后台的登录会话（同一密码）；设备身份存浏览器 localStorage，
每台设备独立记忆位置。页面在 static/chat.html。
"""

import json
import re
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse

from app.admin import store
from app.config import get_settings

_PAGE = Path(__file__).parent / "static" / "chat.html"
_COOKIE_NAME = "pb_admin"
_UID_RE = re.compile(r"^[\w-]{1,64}$")


def _authed(request: Request) -> bool:
    return store.verify_session(request.cookies.get(_COOKIE_NAME))


def _clean_uid(uid: str) -> str:
    return uid if _UID_RE.match(uid) else ""


def create_webchat_router(dispatcher) -> APIRouter:
    router = APIRouter(prefix="/chat")

    @router.get("", response_class=HTMLResponse, include_in_schema=False)
    @router.get("/", response_class=HTMLResponse, include_in_schema=False)
    async def page() -> HTMLResponse:
        return HTMLResponse(_PAGE.read_text(encoding="utf-8"))

    @router.get("/api/state")
    async def state(request: Request):
        location = None
        uid = request.query_params.get("uid", "")
        if _authed(request) and _clean_uid(uid):
            from app.core import locations

            entry = locations.get("web", _clean_uid(uid))
            location = {"address": entry.get("address", "")} if entry else None
        return {"authenticated": _authed(request), "location": location,
                "amap": bool(get_settings().amap_key)}

    @router.post("/api/login")
    async def chat_login(request: Request) -> JSONResponse:
        """前台独立登录口：与管理后台同一套账号密码，cookie 在本端口生效。"""
        body = await request.json()
        username = str(body.get("username") or "")
        password = str(body.get("password") or "")
        if not store.credentials_are_set():
            return JSONResponse({"detail": "尚未初始化账号：请先打开管理后台(2048端口)完成设置"}, status_code=400)
        if not store.verify_credentials(username, password):
            return JSONResponse({"detail": "账号或密码错误"}, status_code=401)
        response = JSONResponse({"ok": True})
        response.set_cookie(_COOKIE_NAME, store.create_session(), httponly=True, samesite="lax")
        return response

    @router.post("/api/message")
    async def send_message(request: Request) -> JSONResponse:
        if not _authed(request):
            return JSONResponse({"detail": "未登录"}, status_code=401)
        body = await request.json()
        uid = _clean_uid(str(body.get("uid") or ""))
        text = str(body.get("text") or "").strip()
        if not uid:
            return JSONResponse({"detail": "缺少设备标识"}, status_code=400)
        if not text or len(text) > 500:
            return JSONResponse({"detail": "消息为空或过长"}, status_code=400)

        from app.core.models import InboundMessage

        msg = InboundMessage(
            platform="web",
            chat_id=f"web:{uid}",
            user_id=uid,
            user_name="网页用户",
            text=text,
        )
        reply = await dispatcher.handle(msg)
        return {"reply": reply}

    @router.post("/api/location")
    async def set_location(request: Request) -> JSONResponse:
        if not _authed(request):
            return JSONResponse({"detail": "未登录"}, status_code=401)
        body = await request.json()
        uid = _clean_uid(str(body.get("uid") or ""))
        try:
            lat = float(body.get("lat"))
            lng = float(body.get("lng"))
        except (TypeError, ValueError):
            return JSONResponse({"detail": "坐标不合法"}, status_code=400)
        if not uid or not (0 < lat < 90 and 0 < lng < 180):
            return JSONResponse({"detail": "缺少设备标识或坐标越界"}, status_code=400)

        from app.core import locations
        from app.tools import nearby

        address = ""
        resolved = False
        if nearby.amap_configured():
            try:
                address = await nearby.regeo(f"{lng:g}", f"{lat:g}")
                resolved = bool(address)
            except Exception:
                address = ""
        locations.set_location("web", uid, address=address, lat=f"{lat:g}", lng=f"{lng:g}")
        return {"ok": True, "address": address, "resolved": resolved}

    return router
