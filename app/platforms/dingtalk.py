"""钉钉适配器：企业内部应用 · Stream 模式（出站 WebSocket，无需公网 IP）。

依赖官方 dingtalk-stream SDK。机器人收到群内 @ 消息后，通过事件里的
sessionWebhook 直接回复（文本消息）。
"""

import asyncio
import threading

import httpx

from app.config import get_settings
from app.core.models import InboundMessage, OutboundMessage
from app.platforms.base import PlatformAdapter

BOT_TOPIC = "/v1.0/im/bot/messages/get"


class DingtalkAdapter(PlatformAdapter):
    platform = "dingtalk"

    def __init__(self, dispatcher):
        super().__init__(dispatcher)
        settings = get_settings()
        if not (settings.dingtalk_client_id and settings.dingtalk_client_secret):
            raise RuntimeError("钉钉已启用但缺少 DINGTALK_CLIENT_ID / DINGTALK_CLIENT_SECRET")
        self.settings = settings
        self._http = httpx.AsyncClient(timeout=30)

    async def start(self) -> None:
        # dingtalk-stream 的 start_forever 是阻塞式（内部自带重连），
        # 放到独立线程用自己的事件循环运行。
        thread = threading.Thread(target=self._run_stream_forever, name="dingtalk-stream", daemon=True)
        thread.start()

    async def stop(self) -> None:
        await self._http.aclose()

    def _run_stream_forever(self) -> None:
        asyncio.run(self._run_stream())

    async def _run_stream(self) -> None:
        import dingtalk_stream

        adapter = self

        class BotHandler(dingtalk_stream.CallbackHandler):
            async def process(self, callback: dingtalk_stream.CallbackMessage):
                await adapter._on_message(callback.data or {})
                return dingtalk_stream.AckMessage.STATUS_OK, "OK"

        credential = dingtalk_stream.Credential(
            self.settings.dingtalk_client_id, self.settings.dingtalk_client_secret
        )
        client = dingtalk_stream.DingTalkStreamClient(credential)
        client.register_callback_handler(BOT_TOPIC, BotHandler())
        client.start_forever()

    async def _on_message(self, data: dict) -> None:
        text = ((data.get("text") or {}).get("content") or "").strip()
        sender_id = data.get("senderStaffId") or data.get("senderId") or ""
        webhook = data.get("sessionWebhook")
        if not text:
            return
        msg = InboundMessage(
            platform=self.platform,
            chat_id=data.get("conversationId") or sender_id,
            user_id=sender_id,
            user_name=data.get("senderNick") or "",
            text=text,
            is_group=(data.get("conversationType") == "1"),
            raw={"sessionWebhook": webhook},
        )
        try:
            reply = await self.dispatch(msg)
            await self.send(
                OutboundMessage(
                    chat_id=msg.chat_id,
                    text=reply,
                    user_id=sender_id,
                    is_group=msg.is_group,
                    raw={"sessionWebhook": webhook, "senderStaffId": sender_id},
                )
            )
        except Exception:
            self.logger.exception("钉钉消息处理失败")

    async def send(self, msg: OutboundMessage) -> None:
        webhook = (msg.raw or {}).get("sessionWebhook")
        if not webhook:
            self.logger.error("钉钉发送失败：缺少 sessionWebhook")
            return
        payload: dict = {"msgtype": "text", "text": {"content": msg.text}}
        if msg.is_group and (msg.raw or {}).get("senderStaffId"):
            payload["at"] = {"atUserIds": [msg.raw["senderStaffId"]]}
        resp = await self._http.post(webhook, json=payload)
        if resp.status_code != 200 or resp.json().get("errcode") not in (0, None):
            self.logger.error("钉钉回复失败: %s %s", resp.status_code, resp.text[:200])
