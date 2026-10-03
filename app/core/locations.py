"""每用户位置记忆：data/locations.json，按 平台:用户ID 存储。

来源三选一：
  - 用户聊天里说「我在XX市XX区」（LLM 调 set_my_location 工具保存）
  - 企业微信里直接发定位（回调里带经纬度和地址标签）
  - 高德地理编码把地址转成坐标（配了 AMAP_KEY 时）
"""

import json
import re
from datetime import datetime

from app.config import DATA_DIR

_CITY_RE = re.compile(r"([\u4e00-\u9fa5]{2,10}?(?:市|自治州|地区|盟))")


def _path():
    return DATA_DIR / "locations.json"


# 市 前一个字符命中这些时通常是「城市/超市/都市」等词而非行政区划
_NOT_CITY_CHARS = set("城都超县镇村省郡")


def parse_city(address: str) -> str:
    """从地址文本里粗提取城市名，如「北京市朝阳区望京」→「北京市」。"""
    if not address:
        return ""
    match = _CITY_RE.search(address)
    if not match:
        return ""
    found = match.group(1)
    if found[-1] == "市" and len(found) >= 2 and found[-2] in _NOT_CITY_CHARS:
        return ""
    return found


def load_all() -> dict:
    path = _path()
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return {}


def key(platform: str, user_id: str) -> str:
    return f"{platform}:{user_id}"


def get(platform: str, user_id: str) -> dict | None:
    return load_all().get(key(platform, user_id))


def set_location(platform: str, user_id: str, **fields) -> dict:
    """合并式保存；fields 可含 address/city/lat/lng。返回该用户的位置。"""
    data = load_all()
    entry = data.get(key(platform, user_id), {})
    entry.update({k: v for k, v in fields.items() if v not in (None, "")})
    address = entry.get("address", "")
    if not entry.get("city"):
        entry["city"] = parse_city(address)
    entry["updated"] = datetime.now().isoformat(timespec="seconds")
    data[key(platform, user_id)] = entry
    _path().parent.mkdir(parents=True, exist_ok=True)
    _path().write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    return entry
