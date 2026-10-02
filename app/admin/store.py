"""管理后台的文件存储：配置文件、密码哈希、会话密钥。

不引入数据库——所有状态落在 DATA_DIR（Docker 里挂载 ./data 卷即可持久化）：
  data/config.env       管理后台写入的配置（优先级高于项目根的 .env）
  data/admin_password   管理密码（盐 + PBKDF2-SHA256，十六进制）
  data/session.key      会话签名密钥（首次自动生成）
"""

import hashlib
import hmac
import secrets
import time
from pathlib import Path

from app.config import DATA_DIR

SESSION_TTL_SECONDS = 7 * 24 * 3600


# ---------------------------------------------------------------- 配置文件
def config_path(data_dir: Path | None = None) -> Path:
    return (data_dir or DATA_DIR) / "config.env"


def read_config(data_dir: Path | None = None) -> dict[str, str]:
    """解析 KEY=VALUE；忽略注释与空行，值里允许出现 '='。"""
    path = config_path(data_dir)
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def write_config(values: dict[str, str], data_dir: Path | None = None) -> None:
    """整表写回 data/config.env；空值不落盘（让默认值生效）。"""
    path = config_path(data_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = ["# 由网页管理后台生成，可手工编辑；改完重启容器生效规则同面板保存。"]
    for key, value in values.items():
        if value == "":
            continue
        lines.append(f"{key}={value}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def merge_config(updates: dict[str, str], data_dir: Path | None = None) -> dict[str, str]:
    """合并更新并写盘，返回合并后的全量值；置空表示删除该键（回落默认值）。"""
    merged = read_config(data_dir)
    for key, value in updates.items():
        if value == "":
            merged.pop(key, None)
        else:
            merged[key] = value
    write_config(merged, data_dir)
    return merged


# ---------------------------------------------------------------- 管理密码
def _password_path(data_dir: Path | None = None) -> Path:
    return (data_dir or DATA_DIR) / "admin_password"


def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 120_000).hex()
    return f"{salt}${digest}"


def password_is_set(data_dir: Path | None = None) -> bool:
    return _password_path(data_dir).exists()


def set_password(password: str, data_dir: Path | None = None) -> None:
    path = _password_path(data_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(hash_password(password), encoding="utf-8")


def verify_password(password: str, data_dir: Path | None = None) -> bool:
    path = _password_path(data_dir)
    if not path.exists():
        return False
    stored = path.read_text(encoding="utf-8").strip()
    salt, _, digest = stored.partition("$")
    if not salt or not digest:
        return False
    expect = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 120_000).hex()
    return hmac.compare_digest(expect, digest)


# ---------------------------------------------------------------- 会话
def _secret_path(data_dir: Path | None = None) -> Path:
    return (data_dir or DATA_DIR) / "session.key"


def _server_secret(data_dir: Path | None = None) -> bytes:
    path = _secret_path(data_dir)
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(secrets.token_hex(32), encoding="utf-8")
    return bytes.fromhex(path.read_text(encoding="utf-8").strip())


def create_session(data_dir: Path | None = None) -> str:
    expires = str(int(time.time()) + SESSION_TTL_SECONDS)
    signature = hmac.new(_server_secret(data_dir), expires.encode(), hashlib.sha256).hexdigest()
    return f"{expires}.{signature}"


def verify_session(token: str | None, data_dir: Path | None = None) -> bool:
    if not token or "." not in token:
        return False
    expires, _, signature = token.partition(".")
    if not expires.isdigit() or not signature:
        return False
    if int(expires) < time.time():
        return False
    expect = hmac.new(_server_secret(data_dir), expires.encode(), hashlib.sha256).hexdigest()
    return hmac.compare_digest(expect, signature)
