"""管理后台存储层：密码哈希、配置文件读写合并、会话签名。"""

from app.admin import store


def test_password_roundtrip(tmp_path):
    assert not store.password_is_set(tmp_path)
    store.set_password("s3cret-密码", tmp_path)
    assert store.password_is_set(tmp_path)
    assert store.verify_password("s3cret-密码", tmp_path)
    assert not store.verify_password("wrong", tmp_path)
    # 哈希落盘，不含明文
    stored = (tmp_path / "admin_password").read_text(encoding="utf-8")
    assert "s3cret-密码" not in stored
    assert "$" in stored  # salt$digest


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
