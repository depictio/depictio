"""The push-target registry and its SSRF guard (#1303)."""

from __future__ import annotations

import hashlib
import socket
from types import SimpleNamespace

import mongomock
import pytest
from bson import ObjectId
from fastapi import HTTPException

from depictio.api.v1.configs.config import settings
from depictio.api.v1.configs.settings_models import MigrationTargetConfig
from depictio.api.v1.endpoints.migrate_endpoints import targets_routes
from depictio.api.v1.services import outbound_http
from depictio.api.v1.services.outbound_http import TargetURLRejected, check_target_url

KEY = "k" * 40


def _user(admin=True):
    return SimpleNamespace(id=ObjectId(), email="a@x.org", is_admin=admin)


@pytest.fixture
def registry(monkeypatch, tmp_path):
    coll = mongomock.MongoClient()["t"]["migration_targets"]
    monkeypatch.setattr(targets_routes, "migration_targets_collection", coll)
    monkeypatch.setattr(settings.auth, "keys_dir", str(tmp_path))
    monkeypatch.setattr(settings.migration, "allow_ui_targets", True)
    monkeypatch.setattr(settings.migration, "ui_target_host_allowlist", [])
    monkeypatch.setattr(settings.migration, "targets", [])
    return coll


def _resolving(monkeypatch, address):
    family = socket.AF_INET6 if ":" in address else socket.AF_INET
    monkeypatch.setattr(
        socket, "getaddrinfo", lambda *a, **k: [(family, socket.SOCK_STREAM, 6, "", (address, 443))]
    )


def test_create_never_returns_key_and_encrypts_at_rest(registry, monkeypatch):
    _resolving(monkeypatch, "93.184.216.34")
    body = targets_routes.TargetCreate(name="prod", url="https://prod.example.org", pairing_key=KEY)
    created = targets_routes.create_target(body, current_user=_user())
    listed = targets_routes.get_targets(current_user=_user())
    for payload in (created, listed):
        assert KEY not in repr(payload)
    assert created["key_fingerprint"] == hashlib.sha256(KEY.encode()).hexdigest()[:8]
    stored = registry.find_one({})
    assert stored["pairing_key_enc"] != KEY and KEY not in repr(stored)
    resolved = targets_routes.resolve_target(created["id"])
    assert resolved.pairing_key == KEY and resolved.trusted is False
    assert KEY not in repr(resolved)


def test_post_forbidden_when_ui_targets_disabled(registry, monkeypatch):
    monkeypatch.setattr(settings.migration, "allow_ui_targets", False)
    body = targets_routes.TargetCreate(name="p", url="https://p.example.org", pairing_key=KEY)
    with pytest.raises(HTTPException) as exc:
        targets_routes.create_target(body, current_user=_user())
    assert exc.value.status_code == 403


def test_non_admin_forbidden(registry):
    with pytest.raises(HTTPException) as exc:
        targets_routes.get_targets(current_user=_user(admin=False))
    assert exc.value.status_code == 403


def test_name_unique_across_env_and_ui(registry, monkeypatch):
    _resolving(monkeypatch, "93.184.216.34")
    monkeypatch.setattr(
        settings.migration,
        "targets",
        [MigrationTargetConfig(name="envt", url="http://lan:8058", pairing_key=KEY)],
    )
    body = targets_routes.TargetCreate(name="envt", url="https://p.example.org", pairing_key=KEY)
    with pytest.raises(HTTPException) as exc:
        targets_routes.create_target(body, current_user=_user())
    assert exc.value.status_code == 409
    listed = targets_routes.get_targets(current_user=_user())["targets"]
    assert listed[0]["id"] == "env:envt" and listed[0]["source"] == "env"


def test_env_target_delete_is_400_and_ui_delete_works(registry, monkeypatch):
    _resolving(monkeypatch, "93.184.216.34")
    with pytest.raises(HTTPException) as exc:
        targets_routes.delete_target("env:x", current_user=_user())
    assert exc.value.status_code == 400
    body = targets_routes.TargetCreate(name="p", url="https://p.example.org", pairing_key=KEY)
    created = targets_routes.create_target(body, current_user=_user())
    assert targets_routes.delete_target(created["id"], current_user=_user()) == {"deleted": True}
    assert registry.count_documents({}) == 0


def test_short_key_rejected():
    with pytest.raises(ValueError):
        targets_routes.TargetCreate(name="p", url="https://p.example.org", pairing_key="short")


@pytest.mark.parametrize(
    "url, address",
    [
        ("http://prod.example.org", "93.184.216.34"),
        ("https://localhost", "127.0.0.1"),
        ("https://a.example.org", "10.1.2.3"),
        ("https://b.example.org", "169.254.169.254"),
        ("https://c.example.org", "100.64.1.1"),
        ("https://d.example.org", "::1"),
        ("https://e.example.org", "fd00:ec2::254"),
        ("https://f.example.org", "::ffff:127.0.0.1"),
        ("https://g.example.org", "0.0.0.0"),
        ("https://h.example.org", "224.0.0.1"),
    ],
)
def test_ssrf_refusals(monkeypatch, url, address):
    _resolving(monkeypatch, address)
    with pytest.raises(TargetURLRejected):
        check_target_url(url, trusted=False, host_allowlist=[])


def test_any_bad_address_among_several_refuses(monkeypatch):
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *a, **k: [
            (socket.AF_INET, 1, 6, "", ("93.184.216.34", 443)),
            (socket.AF_INET, 1, 6, "", ("10.0.0.1", 443)),
        ],
    )
    with pytest.raises(TargetURLRejected):
        check_target_url("https://x.example.org", trusted=False, host_allowlist=[])


def test_public_https_allowed(monkeypatch):
    _resolving(monkeypatch, "93.184.216.34")
    check_target_url("https://ok.example.org", trusted=False, host_allowlist=[])


def test_allowlisted_lan_host_over_http(monkeypatch):
    _resolving(monkeypatch, "192.168.1.10")
    check_target_url("http://depictio.lan:8058", trusted=False, host_allowlist=["depictio.lan"])


def test_trusted_skips_guard():
    check_target_url("http://127.0.0.1:8058", trusted=True, host_allowlist=[])


def test_post_refuses_private_target(registry, monkeypatch):
    _resolving(monkeypatch, "10.0.0.5")
    body = targets_routes.TargetCreate(name="p", url="https://p.example.org", pairing_key=KEY)
    with pytest.raises(HTTPException) as exc:
        targets_routes.create_target(body, current_user=_user())
    assert exc.value.status_code == 400


def test_client_rechecks_url_on_every_call(monkeypatch):
    """A host that resolves publicly when saved and privately later is refused."""
    import httpx

    _resolving(monkeypatch, "93.184.216.34")
    target = outbound_http.ResolvedTarget("1", "t", "https://rebind.example.org", KEY, False)
    transport = httpx.MockTransport(lambda r: httpx.Response(200, json={"ok": True}))
    with outbound_http.TargetClient(target, transport=transport) as client:
        assert client.info() == {"ok": True}
        _resolving(monkeypatch, "127.0.0.1")
        with pytest.raises(outbound_http.RemoteError):
            client.info()


def test_json_answer_size_capped():
    import httpx

    target = outbound_http.ResolvedTarget("1", "t", "http://x", KEY, True)
    big = httpx.MockTransport(lambda r: httpx.Response(200, content=b"{" + b" " * 2_000_000))
    with outbound_http.TargetClient(target, transport=big) as client:
        with pytest.raises(outbound_http.RemoteError) as exc:
            client.info()
    assert "too large" in exc.value.detail


def test_remote_error_detail_has_no_key():
    import httpx

    target = outbound_http.ResolvedTarget("1", "t", "http://x", KEY, True)
    seen = {}

    def handler(request):
        seen["key"] = request.headers["X-Depictio-Pairing-Key"]
        return httpx.Response(403, json={"detail": "Invalid pairing key"})

    with outbound_http.TargetClient(target, transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(outbound_http.RemoteError) as exc:
            client.info()
    assert seen["key"] == KEY and exc.value.status_code == 403 and KEY not in str(exc.value)
