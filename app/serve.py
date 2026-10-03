"""双端口启动：管理服务 + 前台服务（单进程，共享 Dispatcher/浏览器/位置）。

  ADMIN_PORT  默认 2048：管理后台、平台回调
  PUBLIC_PORT 默认 2222：前台首页、网页聊天
"""

import asyncio
import os
import signal

import uvicorn

ADMIN_PORT = int(os.environ.get("ADMIN_PORT", "2048"))
PUBLIC_PORT = int(os.environ.get("PUBLIC_PORT", "2222"))


async def main() -> None:
    servers = [
        uvicorn.Server(
            uvicorn.Config("app.main:admin_app", host="0.0.0.0", port=ADMIN_PORT, log_level="info")
        ),
        uvicorn.Server(
            uvicorn.Config("app.main:public_app", host="0.0.0.0", port=PUBLIC_PORT, log_level="info")
        ),
    ]
    tasks = [asyncio.create_task(server.serve()) for server in servers]

    # uvicorn 各自启动时会抢占信号处理器（后者覆盖前者），两个服务都起来后
    # 重装统一的退出处理器，保证 Ctrl+C / docker stop 能同时停掉两个端口。
    async def _install_shared_handler() -> None:
        await asyncio.sleep(1.0)

        def _stop(*_) -> None:
            for server in servers:
                server.should_exit = True

        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                signal.signal(sig, _stop)
            except ValueError:  # 非主线程等场景
                pass

    asyncio.create_task(_install_shared_handler())
    await asyncio.gather(*tasks)


if __name__ == "__main__":
    asyncio.run(main())
