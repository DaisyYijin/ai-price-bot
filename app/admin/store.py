"""管理后台的文件存储：配置文件、密码哈希、会话密钥。

不引入数据库，分目录落盘（Docker 里各自挂载独立卷）：
  config/config.env   管理后台写入的配置（优先级高于项目根的 .env）
  data/admin_password 管理密码（盐 + PBKDF2-SHA256，十六进制）
  data/session.key    会话签名密钥（首次自动生成）
"""

import hashlib
import hmac
import os
import secrets
import time
from pathlib import Path

from app.config import CONFIG_DIR, DATA_DIR

SESSION_TTL_SECONDS = 7 * 24 * 3600

DEFAULT_ADMIN_USERNAME = "admin"


def env_admin_username() -> str:
    """容器环境变量 ADMIN_USERNAME（未设置时默认 admin）。"""
    return os.environ.get("ADMIN_USERNAME", "").strip() or DEFAULT_ADMIN_USERNAME


def env_admin_password() -> str:
    """容器环境变量 ADMIN_PASSWORD 指定的管理密码（优先于文件凭据）。"""
    return os.environ.get("ADMIN_PASSWORD", "").strip()


# ---------------------------------------------------------------- 配置文件
def config_path(config_dir: Path | None = None) -> Path:
    return (config_dir or CONFIG_DIR) / "config.env"


def read_config(config_dir: Path | None = None) -> dict[str, str]:
    """解析 KEY=VALUE；忽略注释与空行，值里允许出现 '='。"""
    path = config_path(config_dir)
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


def write_config(values: dict[str, str], config_dir: Path | None = None) -> None:
    """整表写回 config/config.env；空值不落盘（让默认值生效）。"""
    path = config_path(config_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = ["# 由网页管理后台生成，可手工编辑；改完重启容器生效规则同面板保存。"]
    for key, value in values.items():
        if value == "":
            continue
        lines.append(f"{key}={value}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def merge_config(updates: dict[str, str], config_dir: Path | None = None) -> dict[str, str]:
    """合并更新并写盘，返回合并后的全量值；置空表示删除该键（回落默认值）。"""
    merged = read_config(config_dir)
    for key, value in updates.items():
        if value == "":
            merged.pop(key, None)
        else:
            merged[key] = value
    write_config(merged, config_dir)
    return merged


# ---------------------------------------------------------------- 管理凭据
def _password_path(data_dir: Path | None = None) -> Path:
    return (data_dir or DATA_DIR) / "admin_password"


def _username_path(data_dir: Path | None = None) -> Path:
    return (data_dir or DATA_DIR) / "admin_user"


def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 120_000).hex()
    return f"{salt}${digest}"


def credentials_are_set(data_dir: Path | None = None) -> bool:
    return bool(env_admin_password()) or _password_path(data_dir).exists()


def set_credentials(username: str, password: str, data_dir: Path | None = None) -> None:
    username = username.strip() or DEFAULT_ADMIN_USERNAME
    user_path = _username_path(data_dir)
    user_path.parent.mkdir(parents=True, exist_ok=True)
    user_path.write_text(username, encoding="utf-8")
    _password_path(data_dir).write_text(hash_password(password), encoding="utf-8")


def verify_credentials(username: str, password: str, data_dir: Path | None = None) -> bool:
    username = username.strip()
    env_password = env_admin_password()
    if env_password:  # 环境变量指定凭据时直接比对，不读文件
        user_ok = hmac.compare_digest(username.encode(), env_admin_username().encode())
        password_ok = hmac.compare_digest(password.encode(), env_password.encode())
        return user_ok and password_ok
    user_path = _username_path(data_dir)
    expected_user = user_path.read_text(encoding="utf-8").strip() if user_path.exists() else ""
    if not expected_user or not hmac.compare_digest(username.encode(), expected_user.encode()):
        return False
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
