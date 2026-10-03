"""淘宝/京东浏览器真实数据 Provider（实验性）。"""

from app.browser import manager as bm
from app.browser.jd import search_jd
from app.browser.taobao import search_taobao
from app.core.models import Quote
from app.providers.base import PriceProvider


class BrowserTaobaoProvider(PriceProvider):
    name = "taobao_browser"
    platform = "淘宝"
    is_mock = False

    async def search(self, keyword: str, category: str = "综合") -> list[Quote]:
        if not bm.is_logged_in("taobao"):
            raise RuntimeError("淘宝未登录：请在管理后台「浏览器登录」扫码")
        return await search_taobao(keyword)


class BrowserJdProvider(PriceProvider):
    name = "jd_browser"
    platform = "京东"
    is_mock = False

    async def search(self, keyword: str, category: str = "综合") -> list[Quote]:
        if not bm.is_logged_in("jd"):
            raise RuntimeError("京东未登录：请在管理后台「浏览器登录」扫码")
        return await search_jd(keyword)
