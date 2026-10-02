"""企业微信加解密：签名、加解密往返、receive_id 校验。"""

import base64
import secrets

import pytest

from app.platforms.wecom import WeComCrypto

TOKEN = "testtoken"
CORP_ID = "wx_test_corp"
# 合法 43 位 EncodingAESKey（解码后 32 字节）
AES_KEY = base64.b64encode(secrets.token_bytes(32)).decode().rstrip("=")


def make_crypto() -> WeComCrypto:
    return WeComCrypto(TOKEN, AES_KEY, CORP_ID)


def test_aes_key_must_be_43_chars():
    with pytest.raises(ValueError, match="EncodingAESKey"):
        WeComCrypto(TOKEN, "tooshort", CORP_ID)


def test_encrypt_decrypt_roundtrip():
    crypto = make_crypto()
    xml = "<xml><Content>我想看流浪地球3</Content></xml>"
    cipher = crypto.encrypt(xml)
    plain, receive_id = crypto.decrypt(cipher)
    assert plain == xml
    assert receive_id == CORP_ID


def test_signature_is_stable_sha1_hex():
    sig = WeComCrypto.signature(TOKEN, "1409659813", "1372623149", "encrypted_data")
    assert len(sig) == 40  # sha1 hex
    assert sig == WeComCrypto.signature(TOKEN, "1409659813", "1372623149", "encrypted_data")


def test_each_encryption_uses_random_prefix():
    crypto = make_crypto()
    xml = "<xml><Content>same</Content></xml>"
    assert crypto.encrypt(xml) != crypto.encrypt(xml)


def test_unicode_content_survives():
    crypto = make_crypto()
    xml = "<xml><Content>抖音¥9.9优惠券 🎬</Content></xml>"
    plain, _ = crypto.decrypt(crypto.encrypt(xml))
    assert "🎬" in plain
