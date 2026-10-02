"""美团浏览器真实数据 Provider（实验性）：依赖管理后台扫码登录。"""

from app.browser import manager as bm
from app.browser.meituan import search_meituan
from app.core.models import Quote
from app.providers.base import PriceProvider


class BrowserMeituanProvider(PriceProvider):
    name = "meituan_browser"
    platform = "美团"
    is_mock = False

    async def search(self, keyword: str, category: str = "综合") -> list[Quote]:
        if not bm.is_logged_in("meituan"):
            raise RuntimeError("美团未登录：请在管理后台「浏览器登录」扫码")
        return await search_meituan(keyword)
