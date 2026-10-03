"""美团网页取数（实验性）。

实测（2026-10）：美团 H5/点评在未登录时会弹 verify.meituan.com 人机验证，
登录后是否放行取决于账号与环境风控，无法离线保证。本模块失败时抛出
可读错误，比价结果会如实显示「查询失败」，绝不伪造数据。
"""

import logging

from app.browser import manager as bm
from app.browser.extract import EXTRACT_JS
from app.core.models import Quote

logger = logging.getLogger(__name__)

_ENTRY_URL = "https://i.meituan.com/"


async def search_meituan(keyword: str) -> list[Quote]:
    if not bm.is_logged_in("meituan"):
        raise RuntimeError("美团未登录：请在管理后台「浏览器登录」填写账号")

    manager = bm.get_browser_manager()
    async with manager.lock:
        page = await manager.new_page()
        try:
            await page.goto(_ENTRY_URL, wait_until="domcontentloaded", timeout=30000)
            await page.wait_for_timeout(3000)
            if "verify.meituan.com" in page.url:
                raise RuntimeError("触发美团人机验证：登录态可能已过期或被风控，请在管理后台重新登录")

            # H5 首页有搜索框；没有则靠页面默认内容解析
            try:
                box = page.locator("input[type=search], input[placeholder*=搜索]").first
                await box.click(timeout=5000)
                await box.fill(keyword)
                await box.press("Enter")
                await page.wait_for_timeout(4000)
            except Exception:
                logger.info("美团搜索框未找到，按默认页面解析")

            items = await page.evaluate(EXTRACT_JS)
            quotes: list[Quote] = []
            for item in items:
                price = float(item.get("price") or 0)
                if price <= 0:
                    continue
                quotes.append(
                    Quote(
                        platform="美团",
                        title=str(item.get("title") or keyword).strip(),
                        price=price,
                        original_price=float(item.get("original") or 0) or None,
                        url=None,
                        remark="真实抓取·实验",
                    )
                )
            if not quotes:
                raise RuntimeError("页面未解析到价格（美团改版或页面未渲染完成）")
            return quotes[:4]
        finally:
            await page.close()
