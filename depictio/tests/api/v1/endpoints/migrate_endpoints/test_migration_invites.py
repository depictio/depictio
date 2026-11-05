"""Invite codes: lifecycle, storage, authentication and the admin routes (#1303 slice 2)."""

from __future__ import annotations

import json
from datetime import timedelta
from unittest.mock import patch

import pytest
from bson import ObjectId
from fastapi import HTTPException

from depictio.api.v1.configs.config import settings
from depictio.api.v1.endpoints.migrate_endpoints import (
    inbound_auth,
    inbound_routes,
    invites_routes,
)
from depictio.api.v1.services import migration_invites
from depictio.models.timestamps import TIMESTAMP_FORMAT, utc_now

from .invite_helpers import (
    admin_user,
    bare_target,
    make_invite,
    plain_user,
    source_for,
)


@pytest.fixture
def target(monkeypatch, target_db):
    return bare_target(monkeypatch, target_db)


def _stored(target, doc):
    return target.db.migration_invites_collection.find_one({"_id": doc["_id"]})


def _past() -> str:
    return (utc_now() - timedelta(hours=1)).strftime(TIMESTAMP_FORMAT)


# ---------------------------------------------------------------------------
# Codes
# ---------------------------------------------------------------------------


def test_generated_codes_have_six_groups_and_validate():
    code = migration_invites.generate_code()
    groups = code.split("-")
    assert len(groups) == 6 and all(len(g) == 4 for g in groups)
    assert migration_invites.normalize_code(code) == "".join(groups)
    assert migration_invites.generate_code() != code


def test_normalize_accepts_lowercase_spaces_and_no_dashes():
    code = migration_invites.generate_code()
    flat = code.replace("-", "")
    expected = flat
    assert migration_invites.normalize_code(code.lower()) == expected
    assert migration_invites.normalize_code(flat.lower()) == expected
    assert migration_invites.normalize_code(f"  {code.replace('-', ' ')}  ") == expected
    assert migration_invites.normalize_code(f"\t{code}\n") == expected


@pytest.mark.parametrize(
    "bad",
    [None, "", "   ", "abc", "A" * 23, "A" * 25, "I" * 24, "O" * 24, "U" * 24, "L" * 24, 12345],
)
def test_malformed_codes_normalize_to_none(bad):
    assert migration_invites.normalize_code(bad) is None


def test_hash_is_sha256_hex_of_the_normalized_code():
    import hashlib

    assert migration_invites.hash_code("ABC") == hashlib.sha256(b"ABC").hexdigest()


# ---------------------------------------------------------------------------
# Creation and storage
# ---------------------------------------------------------------------------


def test_create_returns_the_code_and_stores_only_its_hash(target):
    doc, code = make_invite(note="for the lab")
    stored = _stored(target, doc)
    normalized = migration_invites.normalize_code(code)
    assert stored["code_sha256"] == migration_invites.hash_code(normalized)
    assert stored["code_hint"] == normalized[-4:]
    assert "code" not in stored
    blob = json.dumps(stored, default=str).lower()
    assert code.lower() not in blob and normalized.lower() not in blob
    # The returned document is the stored one: it must not carry the code either.
    assert code.lower() not in json.dumps(doc, default=str).lower()
    assert normalized.lower() not in json.dumps(doc, default=str).lower()


def test_public_invite_never_exposes_the_code_or_the_hash(target):
    doc, code = make_invite()
    public = migration_invites.public_invite(_stored(target, doc))
    blob = json.dumps(public, default=str)
    assert code not in blob and migration_invites.normalize_code(code) not in blob
    assert doc["code_sha256"] not in blob
    assert "code_sha256" not in public and "code" not in public
    assert public["code_hint"] == migration_invites.normalize_code(code)[-4:]
    assert public["state"] == "active" and public["use_count"] == 0


def test_default_ttl_follows_the_setting(target, monkeypatch):
    monkeypatch.setattr(settings.migration, "invite_ttl_days", 3)
    doc, _ = make_invite()
    from datetime import datetime

    now = utc_now().replace(tzinfo=None)
    left = datetime.strptime(doc["expires_at"], TIMESTAMP_FORMAT) - now
    assert timedelta(days=2, hours=23) < left <= timedelta(days=3, seconds=5)
    assert migration_invites.default_ttl() == timedelta(days=3)


def test_the_note_is_trimmed_and_clipped(target):
    doc, _ = make_invite(note="  " + "x" * 900 + "  ")
    assert len(doc["note"]) == 500
    blank, _ = make_invite(note="   ")
    assert blank["note"] is None


def test_a_ttl_over_the_maximum_is_refused(target, monkeypatch):
    monkeypatch.setattr(settings.migration, "invite_max_ttl_days", 2)
    with pytest.raises(ValueError):
        make_invite(hours=2 * 24 + 1)
    make_invite(hours=48)  # exactly the maximum is fine


# ---------------------------------------------------------------------------
# find_invite and states
# ---------------------------------------------------------------------------


def test_find_invite_accepts_any_spelling_of_the_code(target):
    doc, code = make_invite()
    for spelled in (code, code.lower(), code.replace("-", ""), code.replace("-", " ").lower()):
        found = migration_invites.find_invite(spelled)
        assert found is not None and found["_id"] == doc["_id"]


@pytest.mark.parametrize("bad", [None, "", "nonsense", "A" * 24, "!" * 100])
def test_find_invite_returns_none_for_unknown_or_malformed(target, bad):
    make_invite()
    assert migration_invites.find_invite(bad) is None


def test_a_random_valid_looking_code_is_unknown(target):
    make_invite()
    assert migration_invites.find_invite(migration_invites.generate_code()) is None


def test_find_invite_looks_up_by_hash_then_compares_in_constant_time(target):
    doc, code = make_invite()
    queries = []
    real_col = migration_invites._col()

    class Spy:
        def find_one(self, query, *a, **kw):
            queries.append(query)
            return real_col.find_one(query, *a, **kw)

    real = migration_invites.hmac.compare_digest
    with (
        patch.object(migration_invites, "_col", lambda: Spy()),
        patch.object(migration_invites.hmac, "compare_digest", side_effect=real) as spy,
    ):
        assert migration_invites.find_invite(code)["_id"] == doc["_id"]
    assert queries == [{"code_sha256": doc["code_sha256"]}], "the lookup never carries the code"
    assert spy.call_count == 1


def test_find_invite_does_not_compare_when_nothing_matches(target):
    make_invite()
    with patch.object(migration_invites.hmac, "compare_digest") as spy:
        assert migration_invites.find_invite(migration_invites.generate_code()) is None
    spy.assert_not_called()


def test_a_hash_collision_without_a_real_match_is_rejected(target):
    """If the constant-time comparison disagrees with the lookup, the invite is refused."""
    _, code = make_invite()
    with patch.object(migration_invites.hmac, "compare_digest", return_value=False):
        assert migration_invites.find_invite(code) is None


def test_invite_states(target):
    doc, _ = make_invite()
    assert migration_invites.invite_state(doc) == "active"
    assert migration_invites.invite_state({**doc, "expires_at": _past()}) == "expired"
    # There is no "used" state: a code that has imported stays active until it expires.
    used = {**doc, "used_at": "2026-01-01 00:00:00", "use_count": 1, "project_id": "p1"}
    assert migration_invites.invite_state(used) == "active"
    # Revoked wins over everything else.
    both = {**doc, "used_at": "x", "revoked_at": "2026-01-01 00:00:00", "expires_at": _past()}
    assert migration_invites.invite_state(both) == "revoked"
    assert migration_invites.invite_state({**doc, "expires_at": _past()}, now="1999-01-01") == (
        "active"
    )


# ---------------------------------------------------------------------------
# Claim and binding
# ---------------------------------------------------------------------------


def test_a_claim_binds_the_code_and_does_not_spend_it(target):
    doc, _ = make_invite()
    first = migration_invites.claim_invite(
        doc["_id"], project_id="p1", project_name="P", request_id=ObjectId()
    )
    assert first is not None
    again = migration_invites.claim_invite(
        doc["_id"], project_id="p1", project_name="P", request_id=ObjectId()
    )
    assert again is not None
    stored = _stored(target, doc)
    assert stored["use_count"] == 2 and stored["used_at"] and len(stored["request_ids"]) == 2
    assert migration_invites.invite_state(stored) == "active"


def test_claim_of_an_unknown_expired_or_revoked_invite_fails(target):
    assert (
        migration_invites.claim_invite(
            ObjectId(), project_id="p", project_name=None, request_id=ObjectId()
        )
        is None
    )
    expired, _ = make_invite()
    target.db.migration_invites_collection.update_one(
        {"_id": expired["_id"]}, {"$set": {"expires_at": _past()}}
    )
    revoked, _ = make_invite()
    migration_invites.revoke_invite(revoked["_id"], "admin")
    for d in (expired, revoked):
        assert (
            migration_invites.claim_invite(
                d["_id"], project_id="p", project_name=None, request_id=ObjectId()
            )
            is None
        )


def test_a_code_binds_to_the_first_project_and_accepts_it_again(target):
    doc, _ = make_invite()
    claim = migration_invites.claim_invite
    assert claim(doc["_id"], project_id="p1", project_name="One", request_id=ObjectId())
    assert claim(doc["_id"], project_id="p1", project_name="One", request_id=ObjectId())
    assert claim(doc["_id"], project_id="p2", project_name="Two", request_id=ObjectId()) is None
    stored = _stored(target, doc)
    assert stored["project_id"] == "p1" and stored["use_count"] == 2
    assert stored["project_name"] == "One"
    assert migration_invites.invite_state(stored) == "active"


def test_bound_error_only_for_a_bound_invite(target):
    unbound, _ = make_invite()
    assert migration_invites.bound_error(unbound, "p1") is None
    bound = {**unbound, "project_id": "p1", "project_name": "One"}
    assert migration_invites.bound_error(bound, "p1") is None
    assert migration_invites.bound_error({**bound, "project_id": ObjectId()}, "p1")
    err = migration_invites.bound_error(bound, "p2")
    assert err and "this code already brought the project 'One'" in err
    assert "Ask for a new code to send another project" in err


def test_revoke_is_idempotent_in_effect(target):
    doc, _ = make_invite()
    assert migration_invites.revoke_invite(doc["_id"], "a1") is not None
    assert migration_invites.revoke_invite(doc["_id"], "a2") is None
    stored = _stored(target, doc)
    assert stored["revoked_by_id"] == "a1" and migration_invites.invite_state(stored) == "revoked"


# ---------------------------------------------------------------------------
# Authentication dependencies
# ---------------------------------------------------------------------------


def test_an_invite_authenticates_as_an_invite_source(target):
    doc, code = make_invite(lock=False)
    src = source_for(code.lower())
    assert isinstance(src, inbound_auth.InviteSource)
    assert src.name == f"invite:{doc['_id']}" and src.invite_id == str(doc["_id"])
    assert src.allowed_source_buckets == [], "an invite never gets a server-side copy"
    assert src.invite["lock_on_import"] is False
    assert src.max_per_day == inbound_auth.INVITE_MAX_PER_DAY


def test_pairing_key_comes_first_and_a_wrong_key_is_not_rescued_by_a_code(target):
    _, code = make_invite()
    from .invite_helpers import KEY

    assert inbound_auth.require_inbound_source(KEY, code).name == "lab"
    with pytest.raises(HTTPException) as exc:
        inbound_auth.require_inbound_source("w" * 40, code)
    assert exc.value.status_code == 403


@pytest.mark.parametrize("which", ["expired", "revoked"])
def test_an_expired_or_revoked_invite_cannot_upload(target, which):
    doc, code = make_invite()
    col = target.db.migration_invites_collection
    patch_ = {
        "expired": {"expires_at": _past()},
        "revoked": {"revoked_at": "2026-01-01 00:00:00"},
    }[which]
    col.update_one({"_id": doc["_id"]}, {"$set": patch_})
    with pytest.raises(HTTPException) as exc:
        source_for(code)
    assert exc.value.status_code == 403 and which in exc.value.detail


def test_readers_accept_expired_invites_but_not_revoked_ones(target):
    col = target.db.migration_invites_collection
    for field, value, allowed in (
        ("expires_at", _past(), True),
        ("revoked_at", "2026-01-01 00:00:00", False),
    ):
        doc, code = make_invite()
        col.update_one({"_id": doc["_id"]}, {"$set": {field: value}})
        if allowed:
            assert inbound_auth.require_inbound_reader(None, code, None).invite_id == str(
                doc["_id"]
            )
        else:
            with pytest.raises(HTTPException) as exc:
                inbound_auth.require_inbound_reader(None, code, None)
            assert exc.value.status_code == 403


def test_a_bare_request_token_is_returned_as_a_string(target):
    assert inbound_auth.require_inbound_reader(None, None, "tok") == "tok"
    # Any other credential alongside it is authenticated normally instead.
    with pytest.raises(HTTPException) as exc:
        inbound_auth.require_inbound_reader("w" * 40, None, "tok")
    assert exc.value.status_code == 403


def test_request_token_matches_compares_the_hash(target):
    doc = {"status_token_sha256": inbound_auth.hash_request_token("secret")}
    assert inbound_auth.request_token_matches(doc, "secret")
    assert not inbound_auth.request_token_matches(doc, "Secret")
    assert not inbound_auth.request_token_matches({}, "")
    assert not inbound_auth.request_token_matches({"status_token_sha256": ""}, "")


def test_request_token_comparison_is_constant_time(target):
    doc = {"status_token_sha256": inbound_auth.hash_request_token("secret")}
    real = inbound_auth.hmac.compare_digest
    with patch.object(inbound_auth.hmac, "compare_digest", side_effect=real) as spy:
        assert inbound_auth.request_token_matches(doc, "secret")
    assert spy.call_count == 1


# ---------------------------------------------------------------------------
# Inbound off / on with nothing configured
# ---------------------------------------------------------------------------


def test_with_inbound_disabled_every_credential_is_a_404(target, monkeypatch):
    _, code = make_invite()
    monkeypatch.setattr(settings.migration, "inbound_enabled", False)
    from .invite_helpers import KEY

    calls = [
        lambda: inbound_auth.require_inbound_source(None, code),
        lambda: inbound_auth.require_inbound_source(KEY, None),
        lambda: inbound_auth.require_inbound_reader(None, code, None),
        lambda: inbound_auth.require_inbound_reader(None, None, "tok"),
        lambda: inbound_auth.require_inbound_reader(KEY, None, None),
    ]
    for call in calls:
        with pytest.raises(HTTPException) as exc:
            call()
        assert exc.value.status_code == 404


def test_every_inbound_route_is_behind_an_authenticating_dependency():
    allowed = {inbound_auth.require_inbound_source, inbound_auth.require_inbound_reader}
    routes = [r for r in inbound_routes.inbound_router.routes if hasattr(r, "dependant")]
    assert {r.path for r in routes} >= {
        "/info",
        "/preflight",
        "/probe",
        "/check",
        "/requests",
        "/requests/{request_id}",
    }
    for route in routes:
        calls = {d.call for d in route.dependant.dependencies}
        assert calls & allowed, f"{route.path} is not authenticated"


def test_enabled_with_no_sources_and_no_invites_accepts_nothing(target, monkeypatch):
    monkeypatch.setattr(settings.migration, "inbound_sources", [])
    for args in (
        (None, None),
        ("", ""),
        ("w" * 40, None),
        (None, migration_invites.generate_code()),
        (None, "not-a-code"),
        ("w" * 40, migration_invites.generate_code()),
    ):
        with pytest.raises(HTTPException) as exc:
            inbound_auth.require_inbound_source(*args)
        assert exc.value.status_code == 403, args
    for args in ((None, None, None), (None, migration_invites.generate_code(), None)):
        with pytest.raises(HTTPException) as exc:
            inbound_auth.require_inbound_reader(*args)
        assert exc.value.status_code == 403


def test_the_unfilled_header_default_is_not_taken_for_a_credential(target):
    """Called directly, an omitted Header() is a Header object, not None."""
    from fastapi import Header

    with pytest.raises(HTTPException) as exc:
        inbound_auth.require_inbound_source(Header(default=None), Header(default=None))
    assert exc.value.status_code == 403


# ---------------------------------------------------------------------------
# Admin routes
# ---------------------------------------------------------------------------


def _create(**over):
    return invites_routes.create_invite(
        invites_routes.InviteCreate(**over), current_user=admin_user()
    )


def test_create_route_returns_the_code_once(target):
    out = _create(lock_on_import=False, note="n")
    code = out["code"]
    assert migration_invites.find_invite(code) is not None
    assert "policy" not in out and out["lock_on_import"] is False
    assert out["state"] == "active" and out["created_by_email"] == "admin@target.org"
    listing = invites_routes.list_invites(current_user=admin_user())
    blob = json.dumps(listing, default=str)
    assert code not in blob and migration_invites.normalize_code(code) not in blob
    assert out["id"] in blob and "code_sha256" not in blob
    assert listing["inbound_enabled"] is True
    assert listing["defaults"]["max_ttl_days"] == settings.migration.invite_max_ttl_days
    assert listing["defaults"]["ttl_days"] == settings.migration.invite_ttl_days
    assert set(listing["defaults"]) == {"ttl_days", "max_ttl_days", "lock_on_import"}
    assert all("code" not in row for row in listing["invites"])


def test_list_is_newest_first(target):
    first = _create()
    target.db.migration_invites_collection.update_one(
        {"_id": ObjectId(first["id"])}, {"$set": {"created_at": "2000-01-01 00:00:00"}}
    )
    second = _create()
    ids = [r["id"] for r in invites_routes.list_invites(current_user=admin_user())["invites"]]
    assert ids == [second["id"], first["id"]]


def test_create_over_the_max_ttl_is_a_422(target, monkeypatch):
    monkeypatch.setattr(settings.migration, "invite_max_ttl_days", 1)
    with pytest.raises(HTTPException) as exc:
        _create(expires_in_hours=25)
    assert exc.value.status_code == 422 and "at most 1 days" in exc.value.detail
    assert target.db.migration_invites_collection.count_documents({}) == 0


def test_create_validates_the_body():
    with pytest.raises(ValueError):
        invites_routes.InviteCreate(expires_in_hours=0)
    with pytest.raises(ValueError):
        invites_routes.InviteCreate(note="x" * 501)


def test_non_admins_are_forbidden_everywhere(target):
    doc, _ = make_invite()
    user = plain_user()
    for call in (
        lambda: invites_routes.list_invites(current_user=user),
        lambda: invites_routes.create_invite(invites_routes.InviteCreate(), current_user=user),
        lambda: invites_routes.revoke_invite(str(doc["_id"]), current_user=user),
        lambda: invites_routes.list_invites(current_user=None),
    ):
        with pytest.raises(HTTPException) as exc:
            call()
        assert exc.value.status_code == 403
    assert migration_invites.invite_state(_stored(target, doc)) == "active"


def test_create_while_inbound_is_disabled_is_a_409(target, monkeypatch):
    monkeypatch.setattr(settings.migration, "inbound_enabled", False)
    with pytest.raises(HTTPException) as exc:
        _create()
    assert exc.value.status_code == 409
    assert target.db.migration_invites_collection.count_documents({}) == 0
    # Listing still works, and says why nothing can be used.
    assert invites_routes.list_invites(current_user=admin_user())["inbound_enabled"] is False


def test_revoke_route(target):
    out = _create()
    revoked = invites_routes.revoke_invite(out["id"], current_user=admin_user())
    assert revoked["state"] == "revoked" and revoked["revoked_at"]
    with pytest.raises(HTTPException) as exc:
        source_for(out["code"])
    assert exc.value.status_code == 403
    with pytest.raises(HTTPException) as exc:
        invites_routes.revoke_invite(out["id"], current_user=admin_user())
    assert exc.value.status_code == 409
    for bad in ("nope", str(ObjectId())):
        with pytest.raises(HTTPException) as exc:
            invites_routes.revoke_invite(bad, current_user=admin_user())
        assert exc.value.status_code == 404


def test_a_fresh_code_for_a_project_already_here_says_what_to_do():
    """The refusal names the rule, not an internal invite id."""
    from depictio.api.v1.services import project_bundle

    msg = project_bundle.foreign_project_error("p1", "invite:abc")
    assert "only the code that first brought it" in msg and "invite:abc" not in msg
    assert "'lab'" in project_bundle.foreign_project_error("p1", "lab")
