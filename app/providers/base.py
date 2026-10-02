"""价格数据源抽象。

当前内置模拟数据源；之后接入真实联盟 API（京东联盟 / 大淘客 /
抖音精选联盟等）时，只需新建文件实现 PriceProvider 并用 @register
注册，核心流程零改动。
"""

from abc import ABC, abstractmethod

from app.config import Settings
from app.core.models import Quote

_REGISTRY: dict[str, type["PriceProvider"]] = {}


def register(cls: type["PriceProvider"]) -> type["PriceProvider"]:
    name = getattr(cls, "name", None)
    if not name:
        raise ValueError(f"{cls.__name__} 必须定义非空类属性 name")
    _REGISTRY[name.lower()] = cls
    return cls


def available_names() -> list[str]:
    return sorted(_REGISTRY)


def build_enabled(names: list[str]) -> list["PriceProvider"]:
    providers: list[PriceProvider] = []
    for name in names:
        cls = _REGISTRY.get(name.lower())
        if cls is None:
            raise ValueError(
                f"未知价格源 {name!r}，可用: {', '.join(available_names()) or '（无）'}"
            )
        providers.append(cls())
    return providers


def build_effective(settings: Settings) -> list["PriceProvider"]:
    """按配置解析实际使用的数据源：平台配了真实联盟密钥用真实 Provider，否则回落模拟源。"""
    real_choices: dict[str, tuple[str, str]] = {
        # 逻辑平台名 → (app_key属性, secret属性)；两个都配置才启用真实源
        "taobao": ("dataoke_app_key", "dataoke_app_secret"),
        "jd": ("jd_union_app_key", "jd_union_secret_key"),
    }
    providers: list[PriceProvider] = []
    for name in settings.enabled_provider_names():
        key_attr, secret_attr = real_choices.get(name.lower(), ("", ""))
        if key_attr and getattr(settings, key_attr) and getattr(settings, secret_attr):
            if name.lower() == "taobao":
                from app.providers.dataoke import DataokeProvider

                providers.append(DataokeProvider())
                continue
            if name.lower() == "jd":
                from app.providers.jd_union import JdUnionProvider

                providers.append(JdUnionProvider())
                continue
        providers.extend(build_enabled([name]))
    return providers


class PriceProvider(ABC):
    """一个平台报价源。实现要求：search 不抛异常以外的隐藏状态，可并发调用。"""

    name: str = ""  # 注册名（.env PRICE_PROVIDERS 使用）
    platform: str = ""  # 展示给用户的平台名
    is_mock: bool = False  # 模拟数据源标记（真实源 False），用于结果标注

    @abstractmethod
    async def search(self, keyword: str, category: str = "综合") -> list[Quote]:
        """按关键词查询该平台报价。category 如：电影票/数码/图书/外卖/综合。"""
