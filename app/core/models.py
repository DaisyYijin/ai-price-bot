"""统一消息模型：各平台消息进出都先规范化到这里的类型。"""

from typing import Any

from pydantic import BaseModel, Field


class Quote(BaseModel):
    """一条平台报价。真实联盟 API 接入后同样映射为该结构。"""

    platform: str  # 美团 / 淘宝 / 京东 / 抖音 ...
    title: str
    price: float = Field(description="当前成交价（券后）")
    original_price: float | None = None
    url: str | None = None
    remark: str | None = None

    @property
    def discount(self) -> float | None:
        """折扣（如 7.5 = 七五折）；无原价时为 None。"""
        if self.original_price and self.original_price > self.price > 0:
            return round(self.price / self.original_price * 10, 1)
        return None

    def format(self) -> str:
        orig = f"（原价¥{self.original_price:g}）" if self.original_price else ""
        remark = f" {self.remark}" if self.remark else ""
        return f"{self.platform}｜{self.title}｜¥{self.price:g}{orig}{remark}"


class InboundMessage(BaseModel):
    """平台适配器收到消息后统一转换的入站消息。"""

    platform: str  # wecom / dingtalk / qq / cli
    chat_id: str  # 平台内会话唯一标识（用户ID或群ID）
    user_id: str
    user_name: str = ""
    text: str
    is_group: bool = False
    raw: dict[str, Any] = Field(default_factory=dict)


class OutboundMessage(BaseModel):
    """出站消息，由平台适配器负责按各自协议发出。"""

    chat_id: str
    text: str
    user_id: str | None = None  # 供需要点对点发送的平台使用
    is_group: bool = False
    raw: dict[str, Any] = Field(default_factory=dict)
