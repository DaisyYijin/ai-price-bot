"""Playwright 浏览器管理：持久化登录态、串行化操作、基础反自动化检测处理。

登录态保存在 DATA_DIR/browser_profile（Docker 挂载 ./data 即持久），
登录成功的标记写在 DATA_DIR/login_{platform}.ok。
"""

import asyncio
import logging
from pathlib import Path

from app.config import DATA_DIR

logger = logging.getLogger(__name__)

UA_DESKTOP = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)


def login_marker(platform: str) -> Path:
    return DATA_DIR / f"login_{platform}.ok"


def is_logged_in(platform: str) -> bool:
    return login_marker(platform).exists()


def mark_logged_in(platform: str, value: bool = True) -> None:
    path = login_marker(platform)
    if value:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("ok", encoding="utf-8")
    else:
        path.unlink(missing_ok=True)


class BrowserManager:
    """单例浏览器：所有页面操作必须 async with manager.lock 串行执行。"""

    def __init__(self) -> None:
        self.lock = asyncio.Lock()
        self._pw = None
        self._context = None
        self.profile_dir = DATA_DIR / "browser_profile"

    @property
    def running(self) -> bool:
        return self._context is not None

    async def _ensure(self) -> None:
        if self._context is not None:
            return
        from playwright.async_api import async_playwright

        self._pw = await async_playwright().start()
        browser = await self._pw.chromium.launch(
            headless=True,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--disable-dev-shm-usage",
            ],
        )
        self._context = await browser.new_context(
            user_agent=UA_DESKTOP,
            locale="zh-CN",
            viewport={"width": 1440, "height": 900},
        )
        await self._context.add_init_script(
            "Object.defineProperty(navigator,'webdriver',{get:()=>undefined})"
        )
        logger.info("浏览器已启动（profile: %s）", self.profile_dir)

    async def new_page(self):
        await self._ensure()
        return await self._context.new_page()

    async def cookies_contain(self, *names: str) -> bool:
        """判断当前会话是否出现任一指定 cookie（登录态检测）。"""
        if self._context is None:
            return False
        cookies = await self._context.cookies()
        present = {c["name"] for c in cookies}
        return any(n in present for n in names)

    async def aclose(self) -> None:
        if self._context is not None:
            try:
                await self._context.close()
            except Exception:
                pass
            self._context = None
        if self._pw is not None:
            try:
                await self._pw.stop()
            except Exception:
                pass
            self._pw = None


_manager: BrowserManager | None = None


def get_browser_manager() -> BrowserManager:
    global _manager
    if _manager is None:
        _manager = BrowserManager()
    return _manager
