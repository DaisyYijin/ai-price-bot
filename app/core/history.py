"""会话历史：内存存储，按 平台+会话ID 隔离，保留最近 N 轮。

数据量不大时内存已够用；将来需要多实例部署再换 Redis，接口不变。
"""

from collections import defaultdict, deque

from app.config import get_settings


class ConversationHistory:
    def __init__(self) -> None:
        self._store: dict[str, deque[dict]] = defaultdict(
            lambda: deque(maxlen=get_settings().history_rounds * 2)
        )

    @staticmethod
    def key(platform: str, chat_id: str) -> str:
        return f"{platform}:{chat_id}"

    def append(self, platform: str, chat_id: str, role: str, content: str) -> None:
        self._store[self.key(platform, chat_id)].append({"role": role, "content": content})

    def messages(self, platform: str, chat_id: str) -> list[dict]:
        return list(self._store[self.key(platform, chat_id)])

    def clear(self, platform: str, chat_id: str) -> None:
        self._store.pop(self.key(platform, chat_id), None)
