"""企业微信（自建应用）适配器。

收消息：公网回调 URL（GET 验签 + POST 加密消息，AES-256-CBC）。
发消息：主动调用 message/send API（access_token 自动缓存续期）。

本地开发无公网时可用 frp / 云服务器反代，README 有说明。
"""

import asyncio
import base64
import hashlib
import os
import secrets
import struct
import time
import xml.etree.ElementTree as ET
from collections import deque
from typing import Optional

import httpx
from Crypto.Cipher import AES
from fastapi import FastAPI, Query, Request
from fastapi.responses import PlainTextResponse

from app.config import get_settings
from app.core.models import InboundMessage, OutboundMessage
from app.platforms.base import PlatformAdapter

_API_BASE = "https://qyapi.weixin.qq.com/cgi-bin"


# ---------------------------------------------------------------- 加解密
class WeComCrypto:
    """企业微信消息加解密（官方 WXBizMsgCrypt 协议的精简实现）。"""

    def __init__(self, token: str, encoding_aes_key: str, receive_id: str):
        self.token = token
        self.receive_id = receive_id
        self.key = base64.b64decode(encoding_aes_key + "=")
        if len(self.key) != 32:
            raise ValueError("EncodingAESKey 非法（解码后应为 32 字节）")

    @staticmethod
    def signature(token: str, timestamp: str, nonce: str, encrypt: str) -> str:
        raw = "".join(sorted([token, timestamp, nonce, encrypt]))
        return hashlib.sha1(raw.encode("utf-8")).hexdigest()

    def _pkcs7_pad(self, data: bytes) -> bytes:
        block = 32
        amount = block - len(data) % block
        return data + bytes([amount]) * amount

    @staticmethod
    def _pkcs7_unpad(data: bytes) -> bytes:
        return data[: -data[-1]]

    def decrypt(self, encrypt_b64: str) -> tuple[str, str]:
        """返回 (明文XML, receive_id)。"""
        cipher = AES.new(self.key, AES.MODE_CBC, self.key[:16])
        plain = self._pkcs7_unpad(cipher.decrypt(base64.b64decode(encrypt_b64)))
        msg_len = struct.unpack(">I", plain[16:20])[0]
        msg = plain[20 : 20 + msg_len].decode("utf-8")
        receive_id = plain[20 + msg_len :].decode("utf-8")
        return msg, receive_id

    def encrypt(self, plain_xml: str) -> str:
        data = (
            secrets.token_bytes(16)
            + struct.pack(">I", len(plain_xml.encode("utf-8")))
            + plain_xml.encode("utf-8")
            + self.receive_id.encode("utf-8")
        )
        cipher = AES.new(self.key, AES.MODE_CBC, self.key[:16])
        return base64.b64encode(cipher.encrypt(self._pkcs7_pad(data))).decode()


# ---------------------------------------------------------------- 适配器
class WecomAdapter(PlatformAdapter):
    platform = "wecom"

    def __init__(self, dispatcher):
        super().__init__(dispatcher)
        settings = get_settings()
        self.settings = settings
        self.crypto = WeComCrypto(
            settings.wecom_token, settings.wecom_encoding_aes_key, settings.wecom_corp_id
        )
        self._token: Optional[str] = None
        self._token_expire_at = 0.0
        self._http = httpx.AsyncClient(timeout=30)
        # 企业微信 5 秒未收到响应会重试，同一 msgid 去重避免重复触发 LLM
        self._seen_msgids: deque[str] = deque(maxlen=256)
        self._seen_set: set[str] = set()

    async def start(self) -> None:
        required = ("wecom_corp_id", "wecom_agent_id", "wecom_secret", "wecom_token", "wecom_encoding_aes_key")
        missing = [f for f in required if not getattr(self.settings, f)]
        if missing:
            raise RuntimeError(f"企业微信已启用但缺少配置: {', '.join(missing)}")

    async def stop(self) -> None:
        await self._http.aclose()

    def register_routes(self, app: FastAPI) -> None:
        app.add_api_route(
            "/webhook/wecom", self._verify_url, methods=["GET"], include_in_schema=False
        )
        app.add_api_route(
            "/webhook/wecom", self._receive_message, methods=["POST"], include_in_schema=False
        )

    # ---- Webhook ----
    async def _verify_url(
        self,
        msg_signature: str = Query(...),
        timestamp: str = Query(...),
        nonce: str = Query(...),
        echostr: str = Query(...),
    ) -> PlainTextResponse:
        if self.crypto.signature(self.crypto.token, timestamp, nonce, echostr) != msg_signature:
            return PlainTextResponse("signature mismatch", status_code=403)
        plain, _ = self.crypto.decrypt(echostr)
        return PlainTextResponse(plain)

    async def _receive_message(self, request: Request) -> PlainTextResponse:
        query = request.query_params
        body = await request.body()
        try:
            root = ET.fromstring(body)
            encrypt = root.findtext("Encrypt") or ""
            if self.crypto.signature(
                self.crypto.token, query["timestamp"], query["nonce"], encrypt
            ) != query["msg_signature"]:
                return PlainTextResponse("signature mismatch", status_code=403)
            plain_xml, receive_id = self.crypto.decrypt(encrypt)
        except Exception:
            self.logger.exception("企业微信回调解析失败")
            return PlainTextResponse("bad request", status_code=400)
        if receive_id != self.settings.wecom_corp_id:
            self.logger.warning("receive_id 不匹配: %s", receive_id)

        xml = ET.fromstring(plain_xml)
        msg_type = xml.findtext("MsgType") or ""
        msg_id = xml.findtext("MsgId") or secrets.token_hex(8)
        if self._is_duplicate(msg_id):
            return PlainTextResponse("")
        from_user = xml.findtext("FromUserName") or ""

        if msg_type == "location":
            # 用户直接发定位：记为该用户的位置（附近查询的基础）
            from app.core import locations

            try:
                lat = float(xml.findtext("Location_X") or 0)
                lng = float(xml.findtext("Location_Y") or 0)
            except ValueError:
                lat = lng = 0.0
            label = xml.findtext("Label") or ""
            entry = locations.set_location("wecom", from_user, address=label, lat=lat, lng=lng)
            where = entry.get("address") or label or "当前定位"
            city = f"（{entry['city']}）" if entry.get("city") else ""
            asyncio.get_running_loop().create_task(
                self._send_text(from_user, f"已记住你的位置：{where}{city}。可以问我「附近哪家影院优惠最大」了～")
            )
            return PlainTextResponse("")

        if msg_type != "text":
            self.logger.info("忽略非文本消息: %s", msg_type)
            return PlainTextResponse("")

        msg = InboundMessage(
            platform=self.platform,
            chat_id=from_user,
            user_id=from_user,
            user_name="",
            text=(xml.findtext("Content") or "").strip(),
            raw={"msg_id": msg_id},
        )
        # 先应答再处理：LLM 响应通常超过企业微信 5 秒被动回复窗口，
        # 回复改由 message/send 主动发送。
        asyncio.get_running_loop().create_task(self._reply_later(msg))
        return PlainTextResponse("")

    def _is_duplicate(self, msg_id: str) -> bool:
        if msg_id in self._seen_set:
            return True
        if self._seen_msgids.maxlen and len(self._seen_msgids) == self._seen_msgids.maxlen:
            self._seen_set.discard(self._seen_msgids[0])
        self._seen_msgids.append(msg_id)
        self._seen_set.add(msg_id)
        return False

    async def _reply_later(self, msg: InboundMessage) -> None:
        try:
            reply = await self.dispatch(msg)
            await self.send(OutboundMessage(chat_id=msg.chat_id, text=reply, user_id=msg.user_id))
        except Exception:
            self.logger.exception("企业微信回复失败")

    # ---- 主动发送 ----
    async def _access_token(self) -> str:
        if self._token and time.time() < self._token_expire_at:
            return self._token
        resp = await self._http.get(
            f"{_API_BASE}/gettoken",
            params={"corpid": self.settings.wecom_corp_id, "corpsecret": self.settings.wecom_secret},
        )
        data = resp.json()
        if data.get("errcode") != 0:
            raise RuntimeError(f"获取企业微信 access_token 失败: {data}")
        self._token = data["access_token"]
        self._token_expire_at = time.time() + int(data.get("expires_in", 7200)) - 300
        return self._token

    async def _send_text(self, user_id: str, text: str) -> None:
        token = await self._access_token()
        resp = await self._http.post(
            f"{_API_BASE}/message/send",
            params={"access_token": token},
            json={
                "touser": user_id,
                "msgtype": "text",
                "agentid": self.settings.wecom_agent_id,
                "text": {"content": text},
            },
        )
        data = resp.json()
        if data.get("errcode") != 0:
            self.logger.error("企业微信发送失败: %s", data)

    async def send(self, msg: OutboundMessage) -> None:
        await self._send_text(msg.user_id or msg.chat_id, msg.text)
