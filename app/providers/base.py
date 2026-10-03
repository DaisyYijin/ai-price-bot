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
    """解析实际使用的数据源，优先级：浏览器登录态 > 联盟API > 模拟。

    - BROWSER_ENABLED 开且对应平台已扫码登录 → 浏览器真实抓取（实验）
    - 配了联盟密钥（大淘客/京东联盟）→ 官方 API 真实数据
    - 其余 → 模拟数据（结果中标注）
    """
    from app.browser import manager as bm

    browser_on = getattr(settings, "browser_enabled", False)
    providers: list[PriceProvider] = []
    for name in settings.enabled_provider_names():
        n = name.lower()

        # 1) 浏览器登录态（四平台）
        if browser_on:
            browser_cls = None
            if n == "meituan" and bm.is_logged_in("meituan"):
                from app.providers.browser_meituan import BrowserMeituanProvider

                browser_cls = BrowserMeituanProvider
            elif n == "douyin" and bm.is_logged_in("douyin"):
                from app.providers.browser_douyin import BrowserDouyinProvider

                browser_cls = BrowserDouyinProvider
            elif n == "taobao" and bm.is_logged_in("taobao"):
                from app.providers.browser_taobao_jd import BrowserTaobaoProvider

                browser_cls = BrowserTaobaoProvider
            elif n == "jd" and bm.is_logged_in("jd"):
                from app.providers.browser_taobao_jd import BrowserJdProvider

                browser_cls = BrowserJdProvider
            if browser_cls is not None:
                providers.append(browser_cls())
                continue

        # 2) 联盟 API
        real_choices: dict[str, tuple[str, str]] = {
            "taobao": ("dataoke_app_key", "dataoke_app_secret"),
            "jd": ("jd_union_app_key", "jd_union_secret_key"),
        }
        key_attr, secret_attr = real_choices.get(n, ("", ""))
        if key_attr and getattr(settings, key_attr) and getattr(settings, secret_attr):
            if n == "taobao":
                from app.providers.dataoke import DataokeProvider

                providers.append(DataokeProvider())
                continue
            if n == "jd":
                from app.providers.jd_union import JdUnionProvider

                providers.append(JdUnionProvider())
                continue

        # 3) 模拟兜底
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
