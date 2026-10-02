"""QQ 官方机器人适配器（QQ 开放平台，个人可注册）。

自实现轻量单分片 WebSocket 客户端，无第三方 SDK 依赖：
  1. getAppAccessToken 获取 access_token（缓存自动续期）
  2. /websocket 获取网关地址，建立 WSS 连接
  3. Identify(鉴权) → READY；期间按 Hello 下发的间隔发送心跳
  4. 消费 GROUP_AT_MESSAGE_CREATE / C2C_MESSAGE_CREATE 事件
  5. 断线后带 session_id + seq Resume 续 session

回复走 REST v2 被动消息（携带 msg_id），不占用主动消息额度。
群内使用方式：@机器人 消息。
"""

import asyncio
import json
import re
import time

import httpx
import websockets

from app.config import get_settings
from app.core.models import InboundMessage, OutboundMessage
from app.platforms.base import PlatformAdapter

_TOKEN_URL = "https://bots.qq.com/app/getAppAccessToken"
_GATEWAY_URL = "https://api.sgroup.qq.com/websocket"
_API_BASE = "https://api.sgroup.qq.com"

_INTENT_GROUP_AND_C2C = 1 << 25
_MENTION_RE = re.compile(r"^<@![^>]+>\s*")


class QQOfficialAdapter(PlatformAdapter):
    platform = "qq"

    def __init__(self, dispatcher):
        super().__init__(dispatcher)
        settings = get_settings()
        if not (settings.qq_app_id and settings.qq_client_secret):
            raise RuntimeError("QQ 已启用但缺少 QQ_APP_ID / QQ_CLIENT_SECRET")
        self.settings = settings
        self._http = httpx.AsyncClient(timeout=30)
        self._token = ""
        self._token_expire_at = 0.0
        self._session_id: str | None = None
        self._seq: int | None = None
        self._closing = False

    # ---------------------------------------------------------- 生命周期
    async def start(self) -> None:
        asyncio.create_task(self._run_forever())

    async def stop(self) -> None:
        self._closing = True
        await self._http.aclose()

    async def _run_forever(self) -> None:
        backoff = 3
        while not self._closing:
            try:
                await self._run_session()
                backoff = 3
            except asyncio.CancelledError:
                raise
            except Exception:
                self.logger.exception("QQ WebSocket 会话异常，%s 秒后重连", backoff)
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 60)

    async def _run_session(self) -> None:
        gateway = await self._fetch_gateway()
        heartbeat_interval = 41_250  # Hello 下发前的兜底值
        async with websockets.connect(gateway, max_size=2**22) as ws:
            hello = json.loads(await ws.recv())
            if hello.get("op") != 10:
                raise RuntimeError(f"网关首包不是 Hello: {hello}")
            heartbeat_interval = (hello.get("d") or {}).get("heartbeat_interval", heartbeat_interval)

            token = await self._access_token()
            if self._session_id and self._seq is not None:
                await ws.send(json.dumps({
                    "op": 6,
                    "d": {"token": f"QQBot {token}", "session_id": self._session_id, "seq": self._seq},
                }))
            else:
                await ws.send(json.dumps({
                    "op": 2,
                    "d": {
                        "token": f"QQBot {token}",
                        "intents": _INTENT_GROUP_AND_C2C,
                        "shard": [0, 1],
                        "properties": {"$os": "docker", "$browser": "price-bot", "$device": "price-bot"},
                    },
                }))

            heartbeat = asyncio.create_task(self._heartbeat_loop(ws, heartbeat_interval))
            try:
                async for raw in ws:
                    await self._on_packet(json.loads(raw))
            finally:
                heartbeat.cancel()

    async def _heartbeat_loop(self, ws, interval_ms: int) -> None:
        interval = max(interval_ms / 1000, 5)
        while True:
            await asyncio.sleep(interval)
            await ws.send(json.dumps({"op": 1, "d": self._seq}))

    # ---------------------------------------------------------- 协议处理
    async def _on_packet(self, packet: dict) -> None:
        op = packet.get("op")
        if op == 0:
            self._seq = packet.get("s", self._seq)
            event = packet.get("t")
            data = packet.get("d") or {}
            if event == "READY":
                self._session_id = data.get("session_id")
                self.logger.info("QQ 机器人已就绪: %s", (data.get("user") or {}).get("username"))
            elif event == "RESUMED":
                self.logger.info("QQ 会话已恢复")
            elif event in ("GROUP_AT_MESSAGE_CREATE", "C2C_MESSAGE_CREATE"):
                asyncio.create_task(self._on_chat_event(event, data))
            elif event is not None:
                self.logger.debug("忽略事件 %s", event)
        elif op == 11:
            pass  # 心跳 ACK
        elif op == 9:  # 连接数受限/鉴权失败
            self.logger.error("QQ 网关拒绝连接(invalid op/intents): %s", packet)

    async def _on_chat_event(self, event: str, data: dict) -> None:
        text = _MENTION_RE.sub("", data.get("content") or "").strip()
        if not text:
            return
        author = data.get("author") or {}
        is_group = event == "GROUP_AT_MESSAGE_CREATE"
        msg = InboundMessage(
            platform=self.platform,
            chat_id=data.get("group_openid") or author.get("user_openid") or "",
            user_id=author.get("member_openid") or author.get("user_openid") or "",
            user_name="",
            text=text,
            is_group=is_group,
            raw={"msg_id": data.get("id")},
        )
        try:
            reply = await self.dispatch(msg)
            await self.send(
                OutboundMessage(chat_id=msg.chat_id, text=reply, is_group=is_group, raw=msg.raw)
            )
        except Exception:
            self.logger.exception("QQ 消息处理失败")

    # ---------------------------------------------------------- 网络
    async def _access_token(self) -> str:
        if self._token and time.time() < self._token_expire_at:
            return self._token
        resp = await self._http.get(
            _TOKEN_URL, params={"appId": self.settings.qq_app_id, "clientSecret": self.settings.qq_client_secret}
        )
        data = resp.json()
        if "access_token" not in data:
            raise RuntimeError(f"获取 QQ access_token 失败: {data}")
        self._token = data["access_token"]
        self._token_expire_at = time.time() + int(data.get("expires_in", 7000)) - 300
        return self._token

    async def _fetch_gateway(self) -> str:
        resp = await self._http.get(_GATEWAY_URL)
        data = resp.json()
        url = data.get("url")
        if not url:
            raise RuntimeError(f"获取 QQ 网关地址失败: {data}")
        return url

    async def _api_headers(self) -> dict:
        token = await self._access_token()
        return {"Authorization": f"QQBot {token}", "Content-Type": "application/json"}

    async def send(self, msg: OutboundMessage) -> None:
        headers = await self._api_headers()
        body = {
            "msg_type": 0,  # 文本
            "content": msg.text,
            "msg_id": (msg.raw or {}).get("msg_id"),
            "msg_seq": 0,
        }
        if msg.is_group:
            url = f"{_API_BASE}/v2/groups/{msg.chat_id}/messages"
        else:
            url = f"{_API_BASE}/v2/users/{msg.chat_id}/messages"
        resp = await self._http.post(url, headers=headers, json=body)
        if resp.status_code not in (200, 201, 204):
            self.logger.error("QQ 发送失败: %s %s", resp.status_code, resp.text[:300])
