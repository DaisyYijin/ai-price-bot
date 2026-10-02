"""平台适配器抽象：对上暴露统一的消息入口与发送出口。"""

import logging
from abc import ABC, abstractmethod

from fastapi import FastAPI

from app.core.dispatcher import Dispatcher
from app.core.models import InboundMessage, OutboundMessage


class PlatformAdapter(ABC):
    platform: str

    def __init__(self, dispatcher: Dispatcher):
        self.dispatcher = dispatcher
        self.logger = logging.getLogger(f"app.platforms.{self.platform}")

    @abstractmethod
    async def start(self) -> None:
        """启动长连接（钉钉 Stream / QQ WebSocket 等）；纯 Webhook 平台可为空实现。"""

    @abstractmethod
    async def send(self, msg: OutboundMessage) -> None:
        """把出站消息按平台协议发出。"""

    def register_routes(self, app: FastAPI) -> None:
        """需要接收 Webhook 回调的平台在此注册路由。"""

    async def dispatch(self, msg: InboundMessage) -> str:
        return await self.dispatcher.handle(msg)
