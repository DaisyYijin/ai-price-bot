"""抖音网页取数（实验性）：登录态下搜索并切「商品」tab 抓价格。

实测（2026-10）：未登录搜索被登录墙挡住（无价格数据）；网页登录二维码可达。
登录后能否稳定取到商品 tab 数据取决于账号与风控，失败会抛可读错误。
"""

import logging
from urllib.parse import quote

from app.browser import manager as bm
from app.browser.extract import EXTRACT_JS
from app.core.models import Quote

logger = logging.getLogger(__name__)

_SEARCH_URL = "https://www.douyin.com/search/{keyword}?type=goods&source=normal_search"


async def search_douyin(keyword: str) -> list[Quote]:
    if not bm.is_logged_in("douyin"):
        raise RuntimeError("抖音未登录：请在管理后台「浏览器登录」点「抖音扫码」")

    manager = bm.get_browser_manager()
    async with manager.lock:
        page = await manager.new_page()
        try:
            await page.goto(
                _SEARCH_URL.format(keyword=quote(keyword)),
                wait_until="domcontentloaded",
                timeout=30000,
            )
            await page.wait_for_timeout(4000)
            # 尽力关闭可能出现的登录弹窗（已登录时不出现）
            try:
                close = page.locator("[class*=modal] [class*=close], [class*=dy-account-close]").first
                if await close.is_visible():
                    await close.click(timeout=2000)
                    await page.wait_for_timeout(2000)
            except Exception:
                pass
            # 若页面还停在登录页，说明登录态失效
            if "/login" in page.url:
                raise RuntimeError("抖音登录态已失效，请在管理后台重新扫码")

            items = await page.evaluate(EXTRACT_JS)
            if not items:
                # 再尝试点击「商品」tab（有时 type=goods 参数未生效）
                try:
                    tab = page.locator("text=商品").first
                    if await tab.is_visible():
                        await tab.click(timeout=3000)
                        await page.wait_for_timeout(4000)
                        items = await page.evaluate(EXTRACT_JS)
                except Exception:
                    pass
            if not items:
                raise RuntimeError("抖音页面未解析到价格（可能登录态过期/风控/改版）")

            quotes: list[Quote] = []
            for item in items:
                price = float(item.get("price") or 0)
                if price <= 0:
                    continue
                quotes.append(
                    Quote(
                        platform="抖音",
                        title=str(item.get("title") or keyword).strip(),
                        price=price,
                        url=None,
                        remark="真实抓取·实验",
                    )
                )
            return quotes[:4]
        finally:
            await page.close()
