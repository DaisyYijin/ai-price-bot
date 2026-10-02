"""价格数据源抽象。

当前内置模拟数据源；之后接入真实联盟 API（京东联盟 / 大淘客 /
抖音精选联盟等）时，只需新建文件实现 PriceProvider 并用 @register
注册，核心流程零改动。
"""

from abc import ABC, abstractmethod

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


class PriceProvider(ABC):
    """一个平台报价源。实现要求：search 不抛异常以外的隐藏状态，可并发调用。"""

    name: str = ""  # 注册名（.env PRICE_PROVIDERS 使用）
    platform: str = ""  # 展示给用户的平台名

    @abstractmethod
    async def search(self, keyword: str, category: str = "综合") -> list[Quote]:
        """按关键词查询该平台报价。category 如：电影票/数码/图书/外卖/综合。"""
