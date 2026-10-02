"""管理后台存储层：密码哈希、配置文件读写合并、会话签名。"""

from app.admin import store


def test_credentials_roundtrip(tmp_path):
    assert not store.credentials_are_set(tmp_path)
    store.set_credentials("boss", "s3cret-密码", tmp_path)
    assert store.credentials_are_set(tmp_path)
    assert store.verify_credentials("boss", "s3cret-密码", tmp_path)
    assert not store.verify_credentials("someone-else", "s3cret-密码", tmp_path)  # 账号错
    assert not store.verify_credentials("boss", "wrong", tmp_path)  # 密码错
    # 密码哈希落盘不含明文；账号明文单独存
    stored = (tmp_path / "admin_password").read_text(encoding="utf-8")
    assert "s3cret-密码" not in stored
    assert "$" in stored  # salt$digest
    assert (tmp_path / "admin_user").read_text(encoding="utf-8") == "boss"


def test_env_credentials_default_username(monkeypatch):
    monkeypatch.setenv("ADMIN_PASSWORD", "env-pass-9")
    assert store.env_admin_username() == "admin"  # 未设 ADMIN_USERNAME 时默认
    assert store.verify_credentials("admin", "env-pass-9")
    assert not store.verify_credentials("other", "env-pass-9")


def test_config_roundtrip_and_merge(tmp_path):
    assert store.read_config(tmp_path) == {}
    merged = store.merge_config({"LLM_API_KEY": "sk-abc", "QQ_ENABLED": "true"}, tmp_path)
    assert merged == {"LLM_API_KEY": "sk-abc", "QQ_ENABLED": "true"}

    # 值里带 '=' 与引号
    merged = store.merge_config({"LLM_BASE_URL": "https://x/y?a=1"}, tmp_path)
    assert merged["LLM_BASE_URL"] == "https://x/y?a=1"

    # 合并不丢旧键；空值删除键
    merged = store.merge_config({"LLM_API_KEY": ""}, tmp_path)
    assert "LLM_API_KEY" not in merged
    assert merged.get("QQ_ENABLED") == "true"


def test_session_token(tmp_path):
    token = store.create_session(tmp_path)
    assert store.verify_session(token, tmp_path)
    assert not store.verify_session(None, tmp_path)
    assert not store.verify_session("9999999999999.deadbeef", tmp_path)  # 过期+伪造
    assert not store.verify_session(token.split(".")[0] + ".tampered", tmp_path)
    # 会话密钥持久化：换实例仍可验证
    assert store.verify_session(token, tmp_path)
