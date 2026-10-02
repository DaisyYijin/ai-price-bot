"""平台登录中继：后台浏览器代填/展示登录页，前端轮询截图 + 登录态。

美团：管理后台输入手机号+密码 → 代填提交；若出现短信验证码，前端补填。
抖音：网页版有标准「扫码登录」，直接轮询截图等用户扫。
"""

import asyncio
import time

from app.browser import manager as bm

LOGIN_TARGETS: dict[str, dict] = {
    "meituan": {
        "url": "https://passport.meituan.com/account/unitivelogin",
        "success_cookies": ("token", "u", "n", "lt", "userid"),
        "label": "美团",
        "mode": "password",  # 代填账号密码（可附短信验证码）
    },
    "douyin": {
        "url": "https://www.douyin.com/login",
        "success_cookies": ("sessionid", "sessionid_ss", "LOGIN_STATUS"),
        "label": "抖音",
        "mode": "qrcode",  # 截图里直接扫码
    },
}

LOGIN_TIMEOUT_SECONDS = 180
_SMS_INPUT = "input[placeholder*='验证码'], input[maxlength='6'], input[name*='code'], input[name*='sms']"
_PHONE_INPUT = "input[type='tel'], input[placeholder*='手机号'], input[placeholder*='手机']"
_PASSWORD_INPUT = "input[type='password']"
_LOGIN_BUTTON = "button:has-text('登录'), a:has-text('登录'), button:has-text('登 录')"


class LoginRelay:
    """同一时刻只允许一个登录流程；frame 保存最新截图供前端轮询。"""

    def __init__(self) -> None:
        self.platform: str | None = None
        self.state: str = "idle"  # idle / waiting / need_sms / logged_in / timeout / error
        self.message: str = ""
        self.frame_png: bytes = b""
        self._task: asyncio.Task | None = None
        self._sms_code: str | None = None
        self._sms_event = asyncio.Event()

    async def start(self, platform: str, phone: str = "", password: str = "") -> bool:
        target = LOGIN_TARGETS.get(platform)
        if not target:
            return False
        if target["mode"] == "password" and not (phone and password):
            self.message = "美团登录需要手机号和密码"
            return False
        if self._task and not self._task.done():
            await self._cancel_task()
        self.platform = platform
        self.state = "waiting"
        self.message = "抖音请直接扫码" if target["mode"] == "qrcode" else "正在代填登录…"
        self.frame_png = b""
        self._sms_code = None
        self._task = asyncio.create_task(self._run(platform, phone, password))
        return True

    async def submit_sms(self, code: str) -> bool:
        if self.state != "need_sms" or not code:
            return False
        self._sms_code = code.strip()
        self._sms_event.set()
        return True

    async def _cancel_task(self) -> None:
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):
                pass
            self._task = None

    async def _run(self, platform: str, phone: str = "", password: str = "") -> None:
        manager = bm.get_browser_manager()
        target = LOGIN_TARGETS[platform]
        try:
            async with manager.lock:
                page = await manager.new_page()
                try:
                    await page.goto(target["url"], wait_until="domcontentloaded", timeout=30000)
                    await page.wait_for_timeout(2500)
                    if target["mode"] == "password":
                        await self._autofill(page, phone, password)

                    deadline = time.time() + LOGIN_TIMEOUT_SECONDS
                    while time.time() < deadline:
                        await page.wait_for_timeout(2000)
                        try:
                            self.frame_png = await page.screenshot(type="png")
                        except Exception:
                            pass
                        if await manager.cookies_contain(*target["success_cookies"]):
                            bm.mark_logged_in(platform)
                            self.state = "logged_in"
                            self.message = f"{target['label']}登录成功，登录态已保存"
                            return
                        if target["mode"] == "password" and await page.locator(_SMS_INPUT).count():
                            if self.state != "need_sms":
                                self.state = "need_sms"
                                self.message = "需要短信验证码：请在下方输入收到的验证码"
                            self._sms_event.clear()
                            try:
                                await asyncio.wait_for(self._sms_event.wait(), timeout=10)
                                await self._fill_sms(page, self._sms_code or "")
                                self.state = "waiting"
                                self.message = "已提交验证码，等待结果…"
                            except asyncio.TimeoutError:
                                pass  # 继续轮询，等待用户补填
                    self.state = "timeout"
                    self.message = "超时未完成登录，可重新发起"
                finally:
                    await page.close()
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            self.state = "error"
            self.message = f"{type(exc).__name__}: {exc}"

    async def _autofill(self, page, phone: str, password: str) -> None:
        try:
            await page.locator(_PHONE_INPUT).first.fill(phone, timeout=8000)
            await page.locator(_PASSWORD_INPUT).first.fill(password, timeout=8000)
            # 勾选可能存在的协议复选框
            for checkbox in await page.locator("input[type='checkbox']").all():
                try:
                    if await checkbox.is_visible() and not await checkbox.is_checked():
                        await checkbox.check(timeout=1000)
                except Exception:
                    continue
            await page.locator(_LOGIN_BUTTON).first.click(timeout=8000)
        except Exception as exc:
            raise RuntimeError(f"代填登录失败（页面结构可能已变化）: {exc}") from exc

    async def _fill_sms(self, page, code: str) -> None:
        await page.locator(_SMS_INPUT).first.fill(code, timeout=8000)
        try:
            await page.locator(_LOGIN_BUTTON).first.click(timeout=5000)
        except Exception:
            pass  # 部分页面验证码填完自动提交


_relay: LoginRelay | None = None


def get_login_relay() -> LoginRelay:
    global _relay
    if _relay is None:
        _relay = LoginRelay()
    return _relay
