"""Source side of slice 2: ad-hoc destinations, in-flight tracking, retry, status token (#1303)."""

from __future__ import annotations

import json
import os
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import patch

import httpx
import mongomock
import pytest
from bson import ObjectId
from fastapi import BackgroundTasks, HTTPException

from depictio.api.v1.configs.config import settings
from depictio.api.v1.crypto import decrypt_secret
from depictio.api.v1.endpoints.migrate_endpoints import push_routes, routes, targets_routes
from depictio.api.v1.services import migration_push, outbound_http, project_bundle
from depictio.api.v1.services.outbound_http import TargetURLRejected, check_destination_domain
from depictio.models.timestamps import TIMESTAMP_FORMAT, utc_now

from .conftest import COLLECTIONS, FakeS3, make_db, seed_source_project

CODE = "7KQ2-M9XD-AB12-CD34-EF56-GH78"
URL = "https://target.serve.example.org"
TOKEN = "status-token-from-target"
DOMAIN = "serve.example.org"


class AdhocTarget:
    """A target reached with an invite code; status reads use the request token."""

    def __init__(self):
        self.calls: list[tuple[str, str, str, str]] = []
        self.remote_status = "importing"
        self.answer_token: str | None = TOKEN
        self.submitted: bytes | None = None

    def __call__(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path.split("/migrate/inbound")[1]
        header = next(
            h
            for h in (
                "X-Depictio-Invite-Code",
                "X-Depictio-Request-Token",
                "X-Depictio-Pairing-Key",
            )
            if h in request.headers
        )
        self.calls.append((request.method, path, header, request.headers[header]))
        if path == "/check":
            return httpx.Response(
                200,
                json={
                    "info": {"credential_type": "invite_code"},
                    "preflight": {"ok": True, "transfer_mode": "inline", "errors": []},
                    "probe": None,
                },
            )
        if path == "/requests" and request.method == "POST":
            self.submitted = request.read()
            body = {"request_id": "rq1", "status": "importing"}
            if self.answer_token:
                body["status_token"] = self.answer_token
            return httpx.Response(202, json=body)
        if path == "/requests/rq1":
            return httpx.Response(
                200,
                json={
                    "request_id": "rq1",
                    "status": self.remote_status,
                    "result": {"project_id": "p", "locked": True}
                    if self.remote_status == "imported"
                    else None,
                },
            )
        return httpx.Response(404, json={"detail": "nope"})


@pytest.fixture
def env(monkeypatch, tmp_path):
    db = make_db()
    ids = seed_source_project(db)
    s3 = FakeS3()
    s3.put("src-bucket", f"{ids['table_dc']}/part-0.parquet", b"rows")
    s3.put("src-bucket", f"{ids['table_dc']}/_delta_log/00000.json", b"{}")
    pushes = mongomock.MongoClient()["t"]["migration_pushes"]
    from depictio.api.v1 import db as dbmod

    patches = [
        patch.object(project_bundle, "_db", lambda: db),
        patch.object(routes, "_instance_s3_client", lambda: s3),
        patch.object(push_routes, "projects_collection", db.projects_collection),
        patch.object(push_routes, "migration_pushes_collection", pushes),
        patch.object(
            targets_routes, "migration_targets_collection", mongomock.MongoClient()["t"]["targets"]
        ),
        patch.object(dbmod, "projects_collection", db.projects_collection),
        patch.object(dbmod, "migration_pushes_collection", pushes),
        # The destination host must resolve to a public address for the SSRF guard.
        patch.object(
            outbound_http.socket,
            "getaddrinfo",
            lambda *a, **k: [(2, 1, 6, "", ("93.184.216.34", 443))],
        ),
    ]
    patches += [patch.object(routes, a, getattr(db, a)) for a in COLLECTIONS if hasattr(routes, a)]
    for p in patches:
        p.start()
    monkeypatch.setattr(settings.s3, "bucket", "src-bucket")
    monkeypatch.setattr(settings.migration, "spool_dir", str(tmp_path))
    monkeypatch.setattr(settings.migration, "destination_domains", [DOMAIN])
    monkeypatch.setattr(settings.migration, "ui_target_host_allowlist", [])
    fake = AdhocTarget()
    real = outbound_http.TargetClient

    def make(target):
        return real(target, transport=httpx.MockTransport(fake))

    monkeypatch.setattr(push_routes, "TargetClient", make)
    monkeypatch.setattr(outbound_http, "TargetClient", make)
    yield SimpleNamespace(db=db, ids=ids, pushes=pushes, fake=fake, tmp=tmp_path, real=real)
    for p in reversed(patches):
        p.stop()


def _owner(env):
    return SimpleNamespace(
        id=env.ids["owner_id"],
        email="author@source.org",
        is_admin=False,
        is_anonymous=False,
        is_temporary=False,
    )


def _adhoc_body(env, **over):
    fields = {
        "project_id": str(env.ids["project_id"]),
        "destination_url": URL,
        "invite_code": CODE,
    }
    return push_routes.PushRequest(**{**fields, **over})


def _start(env, **over):
    tasks = BackgroundTasks()
    out = push_routes.start_push(_adhoc_body(env, **over), tasks, current_user=_owner(env))
    return out, tasks


def _doc(env, push_id):
    return env.pushes.find_one({"_id": ObjectId(push_id)})


def _stamp(**minutes_ago) -> str:
    return (utc_now() - timedelta(**minutes_ago)).strftime(TIMESTAMP_FORMAT)


# ---------------------------------------------------------------------------
# check_destination_domain
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("url", "suffixes", "ok"),
    [
        ("https://serve.scilifelab.se", ["serve.scilifelab.se"], True),
        ("https://x.serve.scilifelab.se", ["serve.scilifelab.se"], True),
        ("https://a.b.serve.scilifelab.se/path?q=1", ["serve.scilifelab.se"], True),
        ("https://SERVE.SciLifeLab.se", ["serve.scilifelab.se"], True),
        ("https://serve.scilifelab.se.", ["serve.scilifelab.se"], True),
        ("https://x.serve.scilifelab.se", [".Serve.SciLifeLab.se."], True),
        ("https://evilserve.scilifelab.se", ["serve.scilifelab.se"], False),
        ("https://serve.scilifelab.se.evil.com", ["serve.scilifelab.se"], False),
        ("https://scilifelab.se", ["serve.scilifelab.se"], False),
        ("https://user@evil.com/serve.scilifelab.se", ["serve.scilifelab.se"], False),
        ("https://serve.scilifelab.se@evil.com", ["serve.scilifelab.se"], False),
        ("https://evil.com", ["a.org", "serve.scilifelab.se"], False),
        ("https://x.a.org", ["a.org", "serve.scilifelab.se"], True),
        ("https://anything.org", [], False),
        ("https://anything.org", [""], False),
        ("https://anything.org", ["."], False),
        ("not a url", ["serve.scilifelab.se"], False),
    ],
)
def test_check_destination_domain_matrix(url, suffixes, ok):
    if ok:
        check_destination_domain(url, suffixes)
    else:
        with pytest.raises(TargetURLRejected):
            check_destination_domain(url, suffixes)


def test_an_empty_list_says_the_feature_is_off():
    with pytest.raises(TargetURLRejected, match="not enabled"):
        check_destination_domain("https://serve.scilifelab.se", ())


def test_destination_domains_are_normalized_by_the_config():
    from depictio.api.v1.configs.settings_models import MigrationConfig

    cfg = MigrationConfig(destination_domains=[" .Serve.SciLifeLab.se. ", "", " . ", "a.org"])
    assert cfg.destination_domains == ["serve.scilifelab.se", "a.org"]


# ---------------------------------------------------------------------------
# _target_of / adhoc_target
# ---------------------------------------------------------------------------


def test_adhoc_target_carries_the_code_in_the_invite_header(env):
    target = push_routes._target_of(
        push_routes.PreflightRequest(
            project_id="p", destination_url=URL + "/", invite_code=f"  {CODE}  "
        )
    )
    assert target.id == push_routes.ADHOC and target.url == URL
    assert target.pairing_key == CODE and target.trusted is False
    assert target.credential_header == "X-Depictio-Invite-Code"
    assert target.domain_suffixes == (DOMAIN,) and target.name == "target.serve.example.org"
    assert CODE not in repr(target)


def test_a_target_id_wins_over_a_destination(env, monkeypatch):
    from depictio.api.v1.configs.settings_models import MigrationTargetConfig

    monkeypatch.setattr(
        settings.migration,
        "targets",
        [MigrationTargetConfig(name="pub", url="http://remote:8058", pairing_key="p" * 40)],
    )
    target = push_routes._target_of(
        push_routes.PreflightRequest(
            project_id="p", target_id="env:pub", destination_url=URL, invite_code=CODE
        )
    )
    assert target.id == "env:pub"


def test_destination_without_configured_domains_is_a_403(env, monkeypatch):
    monkeypatch.setattr(settings.migration, "destination_domains", [])
    with pytest.raises(HTTPException) as exc:
        push_routes._target_of(_adhoc_body(env))
    assert exc.value.status_code == 403


@pytest.mark.parametrize(
    "url",
    [
        "http://target.serve.example.org",  # http on a host that is not allowlisted
        "https://target.other.org",  # outside the domains
        "https://evilserve.example.org",  # look-alike suffix
        "https://u:p@target.serve.example.org",  # credentials in the URL
        "ftp://target.serve.example.org",
    ],
)
def test_a_disallowed_destination_is_a_400(env, url):
    with pytest.raises(HTTPException) as exc:
        push_routes._target_of(_adhoc_body(env, destination_url=url))
    assert exc.value.status_code == 400


def test_a_destination_resolving_to_a_private_address_is_a_400(env):
    with patch.object(
        outbound_http.socket,
        "getaddrinfo",
        lambda *a, **k: [(2, 1, 6, "", ("10.0.0.5", 443))],
    ):
        with pytest.raises(HTTPException) as exc:
            push_routes._target_of(_adhoc_body(env))
    assert exc.value.status_code == 400


@pytest.mark.parametrize(
    "kwargs",
    [
        {},
        {"destination_url": URL},
        {"invite_code": CODE},
        {"destination_url": URL, "invite_code": "   "},
        {"destination_url": URL, "invite_code": ""},
    ],
)
def test_neither_target_nor_url_and_code_is_a_422(env, kwargs):
    with pytest.raises(HTTPException) as exc:
        push_routes._target_of(push_routes.PreflightRequest(project_id="p", **kwargs))
    assert exc.value.status_code == 422


def test_the_client_rechecks_the_domain_before_every_call(env, monkeypatch):
    target = push_routes._target_of(_adhoc_body(env))
    monkeypatch.setattr(settings.migration, "destination_domains", ["elsewhere.org"])
    # The target still carries the suffixes it was resolved with, so re-resolve a stale one.
    stale = outbound_http.ResolvedTarget(
        id=target.id,
        name=target.name,
        url="https://target.other.org",
        pairing_key=CODE,
        trusted=False,
        credential_header=target.credential_header,
        domain_suffixes=(DOMAIN,),
    )
    with env.real(stale, transport=httpx.MockTransport(env.fake)) as client:
        with pytest.raises(outbound_http.RemoteError) as exc:
            client.check({})
    assert exc.value.status_code == 400 and env.fake.calls == []


# ---------------------------------------------------------------------------
# Starting an ad-hoc push
# ---------------------------------------------------------------------------


def test_preflight_by_url_asks_the_target_with_the_invite_code(env):
    out = push_routes.preflight(
        push_routes.PreflightRequest(
            project_id=str(env.ids["project_id"]), destination_url=URL, invite_code=CODE
        ),
        current_user=_owner(env),
    )
    assert out["can_push"] and out["target"]["url"] == URL and out["in_flight"] is False
    assert env.fake.calls == [("POST", "/check", "X-Depictio-Invite-Code", CODE)]


def test_start_push_records_the_url_but_never_the_code(env):
    out, tasks = _start(env)
    assert out["status"] == "building"
    doc = _doc(env, out["push_id"])
    assert doc["target_id"] == push_routes.ADHOC and doc["target_url"] == URL
    assert doc["credential_type"] == "invite_code" and doc["in_flight"] is True
    assert CODE not in json.dumps(doc, default=str)
    # The code travels to the job in memory only.
    assert [t.args for t in tasks.tasks] == [(out["push_id"], CODE)]
    assert tasks.tasks[0].func is migration_push.run_push


def test_a_registered_target_passes_no_credential_to_the_job(env, monkeypatch):
    from depictio.api.v1.configs.settings_models import MigrationTargetConfig

    key = "p" * 40
    monkeypatch.setattr(
        settings.migration,
        "targets",
        [MigrationTargetConfig(name="pub", url="http://remote:8058", pairing_key=key)],
    )

    def handler(request):
        path = request.url.path.split("/migrate/inbound")[1]
        if path == "/check":
            return httpx.Response(
                200, json={"info": {}, "preflight": {"ok": True, "transfer_mode": "inline"}}
            )
        return httpx.Response(404, json={"detail": "x"})

    real = env.real
    monkeypatch.setattr(
        push_routes, "TargetClient", lambda t: real(t, transport=httpx.MockTransport(handler))
    )
    tasks = BackgroundTasks()
    out = push_routes.start_push(
        push_routes.PushRequest(project_id=str(env.ids["project_id"]), target_id="env:pub"),
        tasks,
        current_user=_owner(env),
    )
    assert tasks.tasks[0].args == (out["push_id"], None)
    doc = _doc(env, out["push_id"])
    assert doc["credential_type"] == "pairing_key" and doc["target_url"] is None


@pytest.mark.parametrize("status", ["building", "uploading"])
def test_a_push_in_flight_blocks_another_with_a_409(env, status):
    env.pushes.insert_one(
        {"project_id": str(env.ids["project_id"]), "status": status, "in_flight": True}
    )
    with pytest.raises(HTTPException) as exc:
        _start(env)
    assert exc.value.status_code == 409
    assert env.pushes.count_documents({}) == 1
    assert env.fake.calls == [], "the target is not even asked"


def test_finished_pushes_do_not_block(env):
    for status in ("failed", "submitted"):
        env.pushes.insert_one(
            {"project_id": str(env.ids["project_id"]), "status": status, "in_flight": False}
        )
    out, _ = _start(env)
    assert out["status"] == "building"


def test_a_lost_race_on_the_unique_index_is_a_409(env, monkeypatch):
    from pymongo.errors import DuplicateKeyError

    def boom(*a, **k):
        raise DuplicateKeyError("dup")

    with patch.object(push_routes, "migration_pushes_collection") as col:
        col.find_one.return_value = None
        col.insert_one.side_effect = boom
        with pytest.raises(HTTPException) as exc:
            _start(env)
    assert exc.value.status_code == 409


def test_a_target_that_would_not_accept_the_project_is_a_422(env):
    def refuse(request):
        return httpx.Response(
            200,
            json={
                "info": {},
                "preflight": {"ok": False, "errors": ["bound to another"], "warnings": []},
            },
        )

    real = env.real
    with patch.object(
        push_routes, "TargetClient", lambda t: real(t, transport=httpx.MockTransport(refuse))
    ):
        with pytest.raises(HTTPException) as exc:
            _start(env)
    assert exc.value.status_code == 422 and "bound to another" in json.dumps(exc.value.detail)
    assert env.pushes.count_documents({}) == 0


# ---------------------------------------------------------------------------
# run_push
# ---------------------------------------------------------------------------


def test_run_push_stores_the_status_token_sealed_and_clears_in_flight(env):
    out, _ = _start(env)
    migration_push.run_push(out["push_id"], CODE)
    doc = _doc(env, out["push_id"])
    assert doc["status"] == "submitted" and doc["remote_request_id"] == "rq1"
    assert doc["in_flight"] is False
    enc = doc["status_token_enc"]
    assert enc and enc != TOKEN and TOKEN not in enc
    assert decrypt_secret(enc) == TOKEN
    blob = json.dumps(doc, default=str)
    assert TOKEN not in blob and CODE not in blob
    # The invite code reached the target, in its own header, on every call but never the key header.
    assert {c[2] for c in env.fake.calls} == {"X-Depictio-Invite-Code"}
    assert b'name="sha256"' in env.fake.submitted
    assert CODE.encode() not in env.fake.submitted
    assert not [f for f in os.listdir(env.tmp) if f.endswith(".zip")]


def test_run_push_without_a_token_in_the_answer_stores_none(env):
    env.fake.answer_token = None
    out, _ = _start(env)
    migration_push.run_push(out["push_id"], CODE)
    doc = _doc(env, out["push_id"])
    assert doc["status"] == "submitted" and "status_token_enc" not in doc


def test_run_push_for_adhoc_without_the_code_fails_and_clears_in_flight(env):
    out, _ = _start(env)
    migration_push.run_push(out["push_id"])
    doc = _doc(env, out["push_id"])
    assert doc["status"] == "failed" and "invite code is no longer available" in doc["error"]
    assert doc["in_flight"] is False


def test_run_push_fails_cleanly_when_the_destination_is_no_longer_allowed(env, monkeypatch):
    out, _ = _start(env)
    monkeypatch.setattr(settings.migration, "destination_domains", ["elsewhere.org"])
    migration_push.run_push(out["push_id"], CODE)
    doc = _doc(env, out["push_id"])
    assert doc["status"] == "failed" and doc["in_flight"] is False
    assert CODE not in json.dumps(doc, default=str)
    assert env.fake.calls[-1][1] != "/requests"


def test_a_refusal_by_the_target_never_echoes_the_code(env):
    def refuse(request):
        return httpx.Response(403, json={"detail": "This invite code is used"})

    out, _ = _start(env)
    real = env.real
    with patch.object(
        outbound_http, "TargetClient", lambda t: real(t, transport=httpx.MockTransport(refuse))
    ):
        migration_push.run_push(out["push_id"], CODE)
    doc = _doc(env, out["push_id"])
    assert doc["status"] == "failed" and "403" in doc["error"] and doc["in_flight"] is False
    assert CODE not in json.dumps(doc, default=str)


def test_set_push_only_clears_in_flight_on_a_final_status(env):
    pid = env.pushes.insert_one({"status": "building", "in_flight": True}).inserted_id
    migration_push._set_push(pid, status="uploading", bundle_bytes=3)
    assert env.pushes.find_one({"_id": pid})["in_flight"] is True
    migration_push._set_push(pid, status="submitted")
    assert env.pushes.find_one({"_id": pid})["in_flight"] is False
    other = env.pushes.insert_one({"status": "uploading", "in_flight": True}).inserted_id
    migration_push._set_push(other, status="failed", error="x")
    assert env.pushes.find_one({"_id": other})["in_flight"] is False


# ---------------------------------------------------------------------------
# Status read back with the token
# ---------------------------------------------------------------------------


def test_get_push_reads_the_remote_status_with_the_request_token(env):
    out, _ = _start(env)
    migration_push.run_push(out["push_id"], CODE)
    env.fake.remote_status = "imported"
    got = push_routes.get_push(out["push_id"], current_user=_owner(env))
    assert got["remote_status"] == "imported" and got["remote_result"]["locked"] is True
    method, path, header, value = env.fake.calls[-1]
    assert (method, path) == ("GET", "/requests/rq1")
    assert header == "X-Depictio-Request-Token" and value == TOKEN
    # Final: no further call.
    count = len(env.fake.calls)
    push_routes.get_push(out["push_id"], current_user=_owner(env))
    assert len(env.fake.calls) == count


def test_an_adhoc_push_without_a_token_cannot_be_followed(env):
    env.fake.answer_token = None
    out, _ = _start(env)
    migration_push.run_push(out["push_id"], CODE)
    count = len(env.fake.calls)
    got = push_routes.get_push(out["push_id"], current_user=_owner(env))
    assert got["remote_status"] == "importing" and len(env.fake.calls) == count


def test_a_status_target_outside_the_allowed_domains_is_not_dialled(env, monkeypatch):
    out, _ = _start(env)
    migration_push.run_push(out["push_id"], CODE)
    monkeypatch.setattr(settings.migration, "destination_domains", ["elsewhere.org"])
    count = len(env.fake.calls)
    got = push_routes.get_push(out["push_id"], current_user=_owner(env))
    assert got["status"] == "submitted" and len(env.fake.calls) == count


def test_the_serialized_push_exposes_neither_code_nor_token(env):
    out, _ = _start(env)
    migration_push.run_push(out["push_id"], CODE)
    listing = push_routes.list_pushes(None, current_user=_owner(env))
    blob = json.dumps(listing, default=str)
    assert CODE not in blob and TOKEN not in blob
    assert listing["pushes"][0]["target_url"] == URL


# ---------------------------------------------------------------------------
# retry_push
# ---------------------------------------------------------------------------


def _failed_adhoc(env):
    out, _ = _start(env)
    migration_push.run_push(out["push_id"])  # no code: fails
    assert _doc(env, out["push_id"])["status"] == "failed"
    return out["push_id"]


def test_retry_of_an_adhoc_push_needs_the_code_again(env):
    pid = _failed_adhoc(env)
    for body in (None, push_routes.RetryRequest(), push_routes.RetryRequest(invite_code="")):
        with pytest.raises(HTTPException) as exc:
            push_routes.retry_push(pid, BackgroundTasks(), body, current_user=_owner(env))
        assert exc.value.status_code == 422
    assert env.pushes.count_documents({}) == 1


def test_retry_with_the_code_starts_a_new_push(env):
    pid = _failed_adhoc(env)
    tasks = BackgroundTasks()
    out = push_routes.retry_push(
        pid, tasks, push_routes.RetryRequest(invite_code=CODE), current_user=_owner(env)
    )
    assert out["status"] == "building" and out["push_id"] != pid
    new = _doc(env, out["push_id"])
    assert new["retry_of"] == pid and new["target_url"] == URL and new["in_flight"] is True
    assert tasks.tasks[0].args == (out["push_id"], CODE)
    assert CODE not in json.dumps(new, default=str)


def test_retry_of_a_push_that_did_not_fail_is_a_409(env):
    for status in ("building", "uploading", "submitted"):
        pid = str(
            env.pushes.insert_one(
                {"status": status, "project_id": "x", "requested_by_id": str(env.ids["owner_id"])}
            ).inserted_id
        )
        with pytest.raises(HTTPException) as exc:
            push_routes.retry_push(
                pid,
                BackgroundTasks(),
                push_routes.RetryRequest(invite_code=CODE),
                current_user=_owner(env),
            )
        assert exc.value.status_code == 409


def test_retry_unknown_or_foreign_push(env):
    for bad in ("nope", str(ObjectId())):
        with pytest.raises(HTTPException) as exc:
            push_routes.retry_push(bad, BackgroundTasks(), None, current_user=_owner(env))
        assert exc.value.status_code == 404
    pid = _failed_adhoc(env)
    stranger = SimpleNamespace(
        id=ObjectId(), email="x@y.org", is_admin=False, is_anonymous=False, is_temporary=False
    )
    with pytest.raises(HTTPException) as exc:
        push_routes.retry_push(
            pid,
            BackgroundTasks(),
            push_routes.RetryRequest(invite_code=CODE),
            current_user=stranger,
        )
    assert exc.value.status_code == 403


def test_retry_while_another_push_is_in_flight_is_a_409(env):
    pid = _failed_adhoc(env)
    env.pushes.insert_one(
        {"project_id": str(env.ids["project_id"]), "status": "building", "in_flight": True}
    )
    with pytest.raises(HTTPException) as exc:
        push_routes.retry_push(
            pid,
            BackgroundTasks(),
            push_routes.RetryRequest(invite_code=CODE),
            current_user=_owner(env),
        )
    assert exc.value.status_code == 409


# ---------------------------------------------------------------------------
# /destinations
# ---------------------------------------------------------------------------


def test_destinations_lists_this_users_recent_urls_without_codes(env):
    me, other = str(env.ids["owner_id"]), str(ObjectId())

    def add(url, who, created, target_id=push_routes.ADHOC):
        env.pushes.insert_one(
            {
                "target_id": target_id,
                "target_url": url,
                "requested_by_id": who,
                "created_at": created,
                "invite_code": CODE,  # must never leak even if a stray field existed
            }
        )

    add("https://a.serve.example.org", me, "2026-01-01 00:00:00")
    add("https://b.serve.example.org", me, "2026-03-01 00:00:00")
    add("https://a.serve.example.org", me, "2026-02-01 00:00:00")  # duplicate
    add("https://x.serve.example.org", other, "2026-04-01 00:00:00")  # someone else's
    add("https://reg.example.org", me, "2026-05-01 00:00:00", target_id="env:pub")  # not adhoc

    out = push_routes.push_destinations(current_user=_owner(env))
    assert out["recent"] == ["https://b.serve.example.org", "https://a.serve.example.org"]
    assert out["enabled"] is True and out["domains"] == [DOMAIN]
    assert CODE not in json.dumps(out)


def test_destinations_when_disabled_and_empty(env, monkeypatch):
    monkeypatch.setattr(settings.migration, "destination_domains", [])
    out = push_routes.push_destinations(current_user=_owner(env))
    assert out == {"enabled": False, "domains": [], "recent": []}


def test_destinations_caps_the_list_at_ten(env):
    me = str(env.ids["owner_id"])
    for i in range(15):
        env.pushes.insert_one(
            {
                "target_id": push_routes.ADHOC,
                "target_url": f"https://h{i}.serve.example.org",
                "requested_by_id": me,
                "created_at": f"2026-01-{i + 1:02d} 00:00:00",
            }
        )
    out = push_routes.push_destinations(current_user=_owner(env))
    assert len(out["recent"]) == 10 and out["recent"][0] == "https://h14.serve.example.org"


def test_destinations_forbidden_to_visitors(env):
    visitor = _owner(env)
    visitor.is_anonymous = True
    with pytest.raises(HTTPException) as exc:
        push_routes.push_destinations(current_user=visitor)
    assert exc.value.status_code == 403


# ---------------------------------------------------------------------------
# Startup recovery of pushes
# ---------------------------------------------------------------------------


def test_recover_interrupted_pushes(env):
    old, recent = _stamp(minutes=61), _stamp(minutes=5)
    rows = {
        "old_building": {"status": "building", "in_flight": True, "updated_at": old},
        "old_uploading": {"status": "uploading", "in_flight": True, "updated_at": old},
        "recent_building": {"status": "building", "in_flight": True, "updated_at": recent},
        "recent_uploading": {"status": "uploading", "in_flight": True, "updated_at": recent},
        "old_submitted": {"status": "submitted", "in_flight": False, "updated_at": old},
        "old_failed": {"status": "failed", "in_flight": False, "updated_at": old, "error": "e"},
    }
    ids = {name: env.pushes.insert_one(doc).inserted_id for name, doc in rows.items()}

    assert migration_push.recover_interrupted_pushes() == 2

    def get(name):
        return env.pushes.find_one({"_id": ids[name]})

    for name in ("old_building", "old_uploading"):
        doc = get(name)
        assert doc["status"] == "failed" and doc["error"] == "interrupted by a restart"
        assert doc["in_flight"] is False and doc["updated_at"] > old
    for name in ("recent_building", "recent_uploading"):
        assert get(name)["status"] in ("building", "uploading") and get(name)["in_flight"]
    assert get("old_submitted")["status"] == "submitted"
    assert get("old_failed")["error"] == "e" and get("old_failed")["updated_at"] == old
    # Idempotent.
    assert migration_push.recover_interrupted_pushes() == 0


def test_the_recovery_window_follows_the_setting(env, monkeypatch):
    monkeypatch.setattr(settings.migration, "interrupted_after_minutes", 1)
    env.pushes.insert_one(
        {"status": "building", "in_flight": True, "updated_at": _stamp(minutes=2)}
    )
    assert migration_push.recover_interrupted_pushes() == 1


def test_a_recovered_push_frees_the_project_for_a_new_one(env):
    out, _ = _start(env)
    env.pushes.update_one(
        {"_id": ObjectId(out["push_id"])}, {"$set": {"updated_at": _stamp(hours=3)}}
    )
    with pytest.raises(HTTPException) as exc:
        _start(env)
    assert exc.value.status_code == 409
    assert migration_push.recover_interrupted_pushes() == 1
    again, _ = _start(env)
    assert again["push_id"] != out["push_id"]
