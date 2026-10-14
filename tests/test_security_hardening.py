"""Regression checks for security boundaries introduced in v1.5.9."""
import concurrent.futures
import threading

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app import auth
from app.http_security import admit_webhook_request, permitted_host, permitted_origin
from app.settings import settings


def test_rebinding_host_rejected_and_lan_access_allowed(monkeypatch):
    monkeypatch.setattr(settings, "admin_allowed_hosts", "dashboard.example.net")
    for host in ("localhost:8090", "127.0.0.1:8090", "192.168.31.10:8090", "[::1]:8090", "my-hass.local", "ha.home.arpa", "dashboard.example.net"):
        assert permitted_host(host), host
    for host in ("evil.example.com", "attacker.example.org:8090", "8.8.8.8:8090", "evil.example.net@localhost", "localhost/path", "localhost\\evil", "evil,localhost", "invalid host"):
        assert not permitted_host(host), host


def test_same_origin_write_and_browser_cross_site_blocked():
    assert permitted_origin("localhost:8090", "http://localhost:8090", "same-origin")
    assert permitted_origin("dashboard.example.net", "https://dashboard.example.net", "same-origin")
    assert permitted_origin("127.0.0.1:8090", None, None)  # CLI/API clients
    assert not permitted_origin("localhost:8090", "http://evil.local:8090", "cross-site")
    assert not permitted_origin("localhost:8090", "null", "cross-site")
    assert not permitted_origin("localhost:8090", None, "cross-site")
    assert not permitted_origin("localhost:8090", "http://localhost:9999", "same-site")


def test_webhook_rate_limits_repeated_replays():
    for _ in range(120):
        assert admit_webhook_request("rate-test-ip-1")
    assert not admit_webhook_request("rate-test-ip-1")
    assert admit_webhook_request("rate-test-ip-2")


def test_auth_workload_bound_per_ip_and_global():
    with auth._auth_slot("rate-test-ip"):
        with auth._auth_slot("rate-test-ip"):
            with pytest.raises(HTTPException) as exc:
                with auth._auth_slot("rate-test-ip"):
                    pass
            assert exc.value.status_code == 429
    assert len(auth._auth_ip_slots) < 10  # idle semaphores are weakly referenced


def test_auth_failure_key_map_capped(monkeypatch):
    monkeypatch.setattr(auth, "_RATE_MAX_KEYS", 5)
    with auth._rate_lock:
        auth._rate_events.clear()
    try:
        for n in range(100):
            auth._record_rate_failure(f"malicious-user-{n}")
        assert len(auth._rate_events) == 5
        assert auth._rate_limited("new-unknown-user", 5, 900)
    finally:
        with auth._rate_lock:
            auth._rate_events.clear()


def test_secret_write_uses_random_private_temp_and_replaces_symlink(monkeypatch, tmp_path):
    root = tmp_path / "secrets"
    root.mkdir()
    monkeypatch.setattr(settings, "runtime_secret_dir", str(root))
    outside = tmp_path / "outside.txt"
    outside.write_text("never touched", encoding="utf-8")
    (root / "hassmind_api_token").symlink_to(outside)
    target = settings.write_runtime_secret("hassmind_api_token", "new-strong-token")
    assert target.read_text(encoding="utf-8") == "new-strong-token"
    assert not target.is_symlink()
    assert outside.read_text(encoding="utf-8") == "never touched"
    assert target.stat().st_mode & 0o777 == 0o600
    assert not list(root.glob(".secret-*"))
    for name in ("../escape", "bad/name", "CAPITAL", ""):
        with pytest.raises(ValueError):
            settings.write_runtime_secret(name, "token")


def test_http_middleware_access_controls(monkeypatch):
    # Integration test is executed in a fully installed production/test environment.
    pytest.importorskip("openai")
    pytest.importorskip("mcp")
    from app.main import app

    monkeypatch.setattr(settings, "admin_allowed_networks", "")
    client = TestClient(app, client=("127.0.0.1", 50000))
    try:
        assert client.get("/login", headers={"Host": "attacker.example.com"}).status_code == 400
        assert client.post("/api/auth/login", headers={"Origin": "http://attacker.example.com"}, json={"username": "x", "password": "y"}).status_code == 403
        assert client.post("/api/auth/login", headers={"Content-Length": "5000000"}, content=b"{}").status_code == 413
    finally:
        client.close()


def test_telegram_is_deny_by_default_and_group_needs_sender_allowlist(monkeypatch):
    import time
    from app.telegram import telegram_message_allowed

    private = {"chat": {"id": 123, "type": "private"}, "from": {"id": 123}, "date": int(time.time()), "text": "turn on lights"}
    group = {"chat": {"id": -10055, "type": "supergroup"}, "from": {"id": 123}, "date": int(time.time()), "text": "turn on lights"}
    monkeypatch.setattr(settings, "telegram_allowed_chat_ids", "")
    monkeypatch.setattr(settings, "telegram_allowed_user_ids", "")
    assert telegram_message_allowed(private)[0] is False
    monkeypatch.setattr(settings, "telegram_allowed_chat_ids", "123,-10055")
    assert telegram_message_allowed(private)[0] is True
    assert telegram_message_allowed(group)[0] is False
    monkeypatch.setattr(settings, "telegram_allowed_user_ids", "123")
    assert telegram_message_allowed(group)[0] is True
    assert telegram_message_allowed({**group, "from": {"id": 999}})[0] is False
    assert telegram_message_allowed({**group, "sender_chat": {"id": -10055}})[0] is False
    assert telegram_message_allowed({**group, "date": int(time.time() - 10000)})[0] is False
    assert telegram_message_allowed({**private, "date": None})[0] is False
