"""淘宝网页取数（实验性）：登录态下搜索商品抓价格。

淘宝网页版搜索未登录会跳登录页；管理后台扫码登录后可正常搜索。
"""

import logging
from urllib.parse import quote

from app.browser import manager as bm
from app.browser.extract import EXTRACT_JS
from app.core.models import Quote

logger = logging.getLogger(__name__)

_SEARCH_URL = "https://s.taobao.com/search?q={keyword}&imgfile=&js=1&stats_click=search_radio_all%3A1"


async def search_taobao(keyword: str) -> list[Quote]:
    if not bm.is_logged_in("taobao"):
        raise RuntimeError("淘宝未登录：请在管理后台「浏览器登录」点「淘宝扫码」")

    manager = bm.get_browser_manager()
    async with manager.lock:
        page = await manager.new_page()
        try:
            await page.goto(
                _SEARCH_URL.format(keyword=quote(keyword)),
                wait_until="domcontentloaded",
                timeout=30000,
            )
            await page.wait_for_timeout(5000)
            if "login" in page.url and "taobao" in page.url:
                raise RuntimeError("淘宝登录态已失效，请在管理后台重新扫码")

            # 滚动触发懒加载
            for _ in range(3):
                await page.mouse.wheel(0, 1200)
                await page.wait_for_timeout(1200)

            items = await page.evaluate(EXTRACT_JS)
            quotes: list[Quote] = []
            for item in items:
                price = float(item.get("price") or 0)
                if price <= 0:
                    continue
                quotes.append(
                    Quote(
                        platform="淘宝",
                        title=str(item.get("title") or keyword).strip(),
                        price=price,
                        url=None,
                        remark="真实抓取·实验",
                    )
                )
            if not quotes:
                raise RuntimeError("淘宝页面未解析到价格（登录态过期/风控/改版）")
            return quotes[:4]
        finally:
            await page.close()
