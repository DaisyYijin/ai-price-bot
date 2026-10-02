"""管理后台 API 流程：初始化密码 → 登录 → 配置读取/保存（脱敏、合并、校验）。"""

import pytest
from fastapi.testclient import TestClient

from app.admin import store
from app.main import create_app


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "DATA_DIR", tmp_path)
    return TestClient(create_app())


def _login(client, password="admin-pass-1"):
    return client.post("/admin/api/login", json={"password": password})


def test_full_flow(client, tmp_path):
    # 未初始化：state 显示无密码，受保护接口 401
    assert client.get("/admin/api/state").json() == {"password_set": False, "authenticated": False}
    assert client.get("/admin/api/config").status_code == 401
    assert _login(client).status_code == 400

    # 初始化密码（过短的拒绝）
    assert client.post("/admin/api/setup", json={"password": "123"}).status_code == 400
    resp = client.post("/admin/api/setup", json={"password": "admin-pass-1"})
    assert resp.status_code == 200

    # 已登录：能读配置；密钥不回传，只返回 set 标志
    config = client.get("/admin/api/config").json()
    fields = {f["key"]: f for f in config["fields"]}
    assert fields["LLM_BASE_URL"]["value"] == "https://api.deepseek.com"
    assert fields["LLM_API_KEY"]["type"] == "password"
    assert fields["LLM_API_KEY"]["value"] == ""
    assert fields["LLM_API_KEY"]["set"] is False

    # 保存：平台开关变化 → 提示重启；文件落盘
    resp = client.post(
        "/admin/api/config",
        json={"values": {"LLM_API_KEY": "sk-test-123", "WECOM_ENABLED": True}},
    ).json()
    assert resp == {"saved": True, "restart_required": True}
    saved = store.read_config(tmp_path)
    assert saved["LLM_API_KEY"] == "sk-test-123"
    assert saved["WECOM_ENABLED"] == "true"

    # 再读：密钥仍不回传但 set=True；未改平台配置再保存 → 不要求重启
    fields = {f["key"]: f for f in client.get("/admin/api/config").json()["fields"]}
    assert fields["LLM_API_KEY"]["set"] is True and fields["LLM_API_KEY"]["value"] == ""
    resp = client.post("/admin/api/config", json={"values": {"LLM_MODEL": "deepseek-reasoner"}}).json()
    assert resp == {"saved": True, "restart_required": False}
    # 密钥留空保存不会丢
    assert store.read_config(tmp_path)["LLM_API_KEY"] == "sk-test-123"
    assert store.read_config(tmp_path)["LLM_MODEL"] == "deepseek-reasoner"


def test_save_validation(client):
    client.post("/admin/api/setup", json={"password": "admin-pass-1"})
    assert client.post("/admin/api/config", json={"values": {"HISTORY_ROUNDS": "abc"}}).status_code == 400
    resp = client.post("/admin/api/config", json={"values": {"PRICE_PROVIDERS": "pdd,taobao"}})
    assert resp.status_code == 400
    assert "未知价格源" in resp.json()["detail"]


def test_logout_requires_relogin(client):
    client.post("/admin/api/setup", json={"password": "admin-pass-1"})
    client.post("/admin/api/logout")
    assert client.get("/admin/api/config").status_code == 401
    assert _login(client, "wrong-pass").status_code == 401
    assert client.get("/admin/api/config").status_code == 401


def test_unknown_fields_ignored(client):
    client.post("/admin/api/setup", json={"password": "admin-pass-1"})
    resp = client.post("/admin/api/config", json={"values": {"EVIL_KEY": "x", "LLM_MODEL": "m"}})
    assert resp.status_code == 200
    assert "EVIL_KEY" not in store.read_config()


def test_login_lockout_after_five_failures(client):
    client.post("/admin/api/setup", json={"password": "admin-pass-1"})
    for _ in range(5):
        client.post("/admin/api/login", json={"password": "nope"})
    resp = _login(client, "admin-pass-1")  # 正确密码也被锁定拦截
    assert resp.status_code == 429
