"""京东网页取数（实验性）：登录态下 search.jd.com 搜索抓价格。

实测（2026-10）：京东搜索未登录会被重定向到 passport.jd.com 登录页，
需先在管理后台扫码登录。价格元素为滚动懒加载，取数前会滚动触发。
"""

import logging
from urllib.parse import quote

from app.browser import manager as bm
from app.browser.extract import EXTRACT_JS
from app.core.models import Quote

logger = logging.getLogger(__name__)

_SEARCH_URL = "https://search.jd.com/Search?keyword={keyword}&enc=utf-8"


async def search_jd(keyword: str) -> list[Quote]:
    if not bm.is_logged_in("jd"):
        raise RuntimeError("京东未登录：请在管理后台「浏览器登录」点「京东扫码」")

    manager = bm.get_browser_manager()
    async with manager.lock:
        page = await manager.new_page()
        try:
            await page.goto(
                _SEARCH_URL.format(keyword=quote(keyword)),
                wait_until="domcontentloaded",
                timeout=30000,
            )
            await page.wait_for_timeout(3000)
            if "passport.jd.com" in page.url:
                raise RuntimeError("京东登录态已失效，请在管理后台重新扫码")

            # 京东价格是滚动懒加载的，滚动两屏触发渲染
            for _ in range(3):
                await page.mouse.wheel(0, 1500)
                await page.wait_for_timeout(1500)

            items = await page.evaluate(EXTRACT_JS)
            quotes: list[Quote] = []
            for item in items:
                price = float(item.get("price") or 0)
                if price <= 0:
                    continue
                quotes.append(
                    Quote(
                        platform="京东",
                        title=str(item.get("title") or keyword).strip(),
                        price=price,
                        original_price=float(item.get("original") or 0) or None,
                        url=None,
                        remark="真实抓取·实验",
                    )
                )
            if not quotes:
                raise RuntimeError("京东页面未解析到价格（改版或被风控）")
            return quotes[:4]
        finally:
            await page.close()
