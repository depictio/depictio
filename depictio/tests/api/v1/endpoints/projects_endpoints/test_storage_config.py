"""Tests for per-project storage configuration (RFC remote-data §5.3, issue 383).

Covers the encryption primitive (first encrypt-at-rest in the codebase), the
owner-only CRUD contract with write-only secrets, endpoint gating at write and
read time, the read-side failure contract (unusable config raises, it never
degrades to the instance credentials), the unique index, and the threading of
project credentials into the manifest re-ingest path.
"""

from unittest.mock import patch

import mongomock
import pytest
from bson import ObjectId
from fastapi import HTTPException
from pymongo.errors import DuplicateKeyError

from depictio.api.v1.configs.config import settings
from depictio.api.v1.endpoints.projects_endpoints import storage_config
from depictio.models.models.users import UserBase


def _user(is_admin: bool = False) -> UserBase:
    return UserBase(id=ObjectId(), email="owner@example.com", is_admin=is_admin)


def _project_doc(owner_id: ObjectId) -> dict:
    return {
        "_id": ObjectId(),
        "name": "storage-project",
        "permissions": {"owners": [{"_id": owner_id}], "editors": [], "viewers": []},
        "workflows": [],
    }


@pytest.fixture()
def keys_dir(tmp_path, monkeypatch):
    """Point the app's keys directory (the JWT keypair location) at a temp dir.

    The secrets key must follow ``settings.auth.keys_dir`` (DEPICTIO_AUTH_KEYS_DIR),
    the one directory backend and worker share, and nothing else. The
    directory does not exist yet: creation must be lazy (first use), never at
    import.
    """
    target = tmp_path / "keys"
    monkeypatch.setattr(settings.auth, "keys_dir", target)
    yield target


@pytest.fixture()
def mock_db(monkeypatch, keys_dir):
    monkeypatch.setenv("DEPICTIO_REMOTE_URL_ALLOWLIST", "s3.example.org")
    client = mongomock.MongoClient()
    database = client["depictio_test"]
    with (
        patch.object(storage_config, "projects_collection", database["projects"]),
        patch.object(storage_config, "project_storage_collection", database["storage"]),
    ):
        yield database


def _put(project_id: str, user, **overrides):
    fields = {
        "endpoint_url": "https://s3.example.org",
        "bucket": "private-bucket",
        "access_key_id": "AKIA123",
        "secret_access_key": "s3cr3t",
        **overrides,
    }
    payload = storage_config.ProjectStorageConfigIn(**fields)
    return storage_config._set_project_storage(project_id, payload, user)


def _stored_project(mock_db, user=None):
    user = user or _user()
    doc = _project_doc(user.id)
    mock_db["projects"].insert_one(doc)
    _put(str(doc["_id"]), user)
    return doc, user


# ── Crypto primitive ────────────────────────────────────────────────────────


def test_encrypt_decrypt_roundtrip_creates_key_lazily_under_keys_dir(keys_dir):
    from depictio.api.v1.crypto import decrypt_secret, encrypt_secret, secrets_key_path

    assert not keys_dir.exists()  # importing the module touched nothing
    assert secrets_key_path() == keys_dir / "secrets_key.bin"

    ciphertext = encrypt_secret("s3cr3t")

    assert ciphertext != "s3cr3t"
    assert decrypt_secret(ciphertext) == "s3cr3t"
    key_file = keys_dir / "secrets_key.bin"
    assert key_file.is_file()  # persisted next to the JWT keypair location
    assert key_file.stat().st_mode & 0o777 == 0o600


def test_key_is_reused_not_regenerated(keys_dir):
    from depictio.api.v1.crypto import decrypt_secret, encrypt_secret

    first = encrypt_secret("one")
    key_bytes = (keys_dir / "secrets_key.bin").read_bytes()
    encrypt_secret("two")
    assert (keys_dir / "secrets_key.bin").read_bytes() == key_bytes
    assert decrypt_secret(first) == "one"


# ── CRUD contract ───────────────────────────────────────────────────────────


def test_put_encrypts_secret_and_never_echoes_it(mock_db):
    user = _user()
    doc = _project_doc(user.id)
    mock_db["projects"].insert_one(doc)

    out = _put(str(doc["_id"]), user)

    assert out.has_secret is True
    assert not hasattr(out, "secret_access_key")
    stored = mock_db["storage"].find_one({"project_id": doc["_id"]})
    assert stored["secret_encrypted"] != "s3cr3t"
    assert "s3cr3t" not in str(stored)


def test_put_without_secret_keeps_stored_one(mock_db):
    user = _user()
    doc = _project_doc(user.id)
    mock_db["projects"].insert_one(doc)

    _put(str(doc["_id"]), user)
    before = mock_db["storage"].find_one({"project_id": doc["_id"]})["secret_encrypted"]

    out = _put(str(doc["_id"]), user, secret_access_key=None, bucket="renamed")
    after = mock_db["storage"].find_one({"project_id": doc["_id"]})

    assert out.has_secret is True
    assert after["secret_encrypted"] == before  # write-only: omitted keeps stored
    assert after["bucket"] == "renamed"


def test_owner_only(mock_db):
    owner = _user()
    doc = _project_doc(owner.id)
    mock_db["projects"].insert_one(doc)

    with pytest.raises(HTTPException) as exc:
        _put(str(doc["_id"]), _user())  # not an owner
    assert exc.value.status_code == 403

    # Admins pass the gate.
    out = _put(str(doc["_id"]), _user(is_admin=True))
    assert out.has_secret is True


def test_private_endpoint_rejected(mock_db):
    user = _user()
    doc = _project_doc(user.id)
    mock_db["projects"].insert_one(doc)

    with pytest.raises(HTTPException) as exc:
        _put(str(doc["_id"]), user, endpoint_url="https://192.168.1.10:9000")
    assert exc.value.status_code == 400


def test_get_masks_and_delete_removes(mock_db):
    user = _user()
    doc = _project_doc(user.id)
    mock_db["projects"].insert_one(doc)

    with pytest.raises(HTTPException) as exc:
        storage_config._get_project_storage(str(doc["_id"]), user)
    assert exc.value.status_code == 404

    _put(str(doc["_id"]), user)
    out = storage_config._get_project_storage(str(doc["_id"]), user)
    assert out.endpoint_url == "https://s3.example.org"
    assert out.has_secret is True

    assert storage_config._delete_project_storage(str(doc["_id"]), user) == {"deleted": True}
    assert mock_db["storage"].find_one({"project_id": doc["_id"]}) is None


# ── Unique index ────────────────────────────────────────────────────────────


def test_unique_project_id_index_is_created_and_enforced(mock_db):
    from depictio.api.v1.db import ensure_project_storage_indexes

    ensure_project_storage_indexes(mock_db["storage"])

    info = mock_db["storage"].index_information()
    assert info["project_id_unique"]["key"] == [("project_id", 1)]
    assert info["project_id_unique"]["unique"] is True

    project_id = ObjectId()
    mock_db["storage"].insert_one({"project_id": project_id})
    with pytest.raises(DuplicateKeyError):
        mock_db["storage"].insert_one({"project_id": project_id})


def test_writes_ensure_the_index_and_upsert_one_document(mock_db):
    """The first storage write in a process ensures the index (upgraded
    instances never ran the db_init call) and repeated writes upsert."""
    doc, user = _stored_project(mock_db)
    assert "project_id_unique" in mock_db["storage"].index_information()

    _put(str(doc["_id"]), user, bucket="other")
    assert mock_db["storage"].count_documents({"project_id": doc["_id"]}) == 1


# ── Read-side resolver ──────────────────────────────────────────────────────


def test_storage_options_for_project_decrypts(mock_db):
    doc, _ = _stored_project(mock_db)

    options = storage_config.storage_options_for_project(doc["_id"])

    assert options is not None
    assert options["endpoint_url"] == "https://s3.example.org"
    assert options["aws_access_key_id"] == "AKIA123"
    assert options["aws_secret_access_key"] == "s3cr3t"
    assert options["use_ssl"] == "true"


def test_storage_options_none_without_config(mock_db):
    assert storage_config.storage_options_for_project(ObjectId()) is None


def test_storage_options_invalid_project_id_raises(mock_db):
    with pytest.raises(ValueError):
        storage_config.storage_options_for_project("not-an-object-id")


def test_storage_options_raise_on_undecryptable_secret(mock_db, keys_dir):
    """A key mismatch must never fall back to the instance credentials."""
    doc, _ = _stored_project(mock_db)
    # Simulate a rotated/lost keys dir: ciphertext no longer decryptable.
    mock_db["storage"].update_one(
        {"project_id": doc["_id"]}, {"$set": {"secret_encrypted": "gAAAAA-not-a-token"}}
    )

    with pytest.raises(storage_config.StorageSecretUnreadable) as exc:
        storage_config.storage_options_for_project(doc["_id"])

    err = exc.value
    assert isinstance(err, storage_config.ProjectStorageUnusable)
    assert err.status_code == 500
    assert err.project_id == str(doc["_id"])
    # Client-safe detail names the project and the fix; the operator hint
    # (filesystem path) is only in the logged str().
    assert str(doc["_id"]) in err.detail
    assert "re-enter" in err.detail.lower()
    assert str(keys_dir) not in err.detail
    assert str(keys_dir / "secrets_key.bin") in str(err)
    assert "DEPICTIO_AUTH_KEYS_DIR" in str(err)


def test_storage_options_raise_when_another_key_encrypted_the_secret(
    mock_db, tmp_path, monkeypatch
):
    """Backend and worker with different keys dirs: the reader must fail loudly."""
    doc, _ = _stored_project(mock_db)  # encrypted with the fixture's key

    monkeypatch.setattr(settings.auth, "keys_dir", tmp_path / "worker-keys")
    with pytest.raises(storage_config.StorageSecretUnreadable):
        storage_config.storage_options_for_project(doc["_id"])


def test_storage_options_regate_endpoint_at_read_time(mock_db, monkeypatch):
    """A config written before the allowlist was tightened must stop working."""
    doc, _ = _stored_project(mock_db)  # written while s3.example.org was allowlisted

    monkeypatch.setenv("DEPICTIO_REMOTE_URL_ALLOWLIST", "other.example.org")
    with pytest.raises(storage_config.StorageEndpointRejected) as exc:
        storage_config.storage_options_for_project(doc["_id"])

    assert exc.value.status_code == 409
    assert "s3.example.org" in exc.value.detail
    assert "not in the administrator allowlist" in exc.value.detail


def test_test_endpoint_reports_unusable_config_without_raising(mock_db):
    doc, user = _stored_project(mock_db)
    mock_db["storage"].update_one(
        {"project_id": doc["_id"]}, {"$set": {"secret_encrypted": "gAAAAA-not-a-token"}}
    )

    result = storage_config._test_project_storage(str(doc["_id"]), user)

    assert result.success is False
    assert str(doc["_id"]) in result.message
    assert "secrets_key.bin" not in result.message


# ── Threading into re-ingestion ─────────────────────────────────────────────


def test_refresh_threads_project_storage_into_ingest(mock_db, monkeypatch):
    from depictio.api.v1.endpoints.projects_endpoints import manifest_ingest

    monkeypatch.setenv("DEPICTIO_REMOTE_URL_ALLOWLIST", "s3.example.org,example.org")
    user = _user()
    # Raw project dict with a manifest-mode DC; _run_dc_ingest is mocked so
    # the workflow never needs to parse as a full model.
    doc = {
        "_id": ObjectId(),
        "name": "storage-project",
        "permissions": {"owners": [{"_id": user.id}]},
        "workflows": [
            {
                "data_collections": [
                    {
                        "_id": ObjectId(),
                        "data_collection_tag": "counts",
                        "config": {
                            "scan": {
                                "mode": "manifest",
                                "scan_parameters": {
                                    "manifest_url": "https://example.org/manifest.json",
                                    "manifest_type": "counts",
                                },
                            }
                        },
                    }
                ]
            }
        ],
    }
    mock_db["projects"].insert_one(doc)

    manifest_json = '[{"id": "s1", "type": "counts", "url": "https://example.org/s1.csv"}]'

    def _fake_download(url, dest_path, max_bytes=None, timeout_s=30.0):
        with open(dest_path, "w") as fh:
            fh.write(manifest_json)
        return len(manifest_json)

    resolved = {"endpoint_url": "https://s3.example.org", "aws_access_key_id": "AKIA123"}
    with (
        patch.object(manifest_ingest, "projects_collection", mock_db["projects"]),
        patch.object(manifest_ingest, "bounded_download", side_effect=_fake_download),
        patch.object(storage_config, "storage_options_for_project", return_value=resolved),
        patch.object(manifest_ingest, "_run_dc_ingest", return_value=(True, None)) as ingest,
    ):
        report = manifest_ingest._refresh_manifest_in_project(
            project_id=str(doc["_id"]), current_user=user
        )

    assert report.success is True
    assert ingest.call_args.kwargs.get("remote_storage_options") == resolved


# ── Surfacing through the API and the worker ────────────────────────────────


@pytest.mark.asyncio
async def test_routes_turn_unusable_storage_into_a_clean_http_error(mock_db):
    from depictio.api.v1.endpoints.projects_endpoints import routes

    project_id = ObjectId()

    def _boom(**kwargs):
        raise storage_config.StorageSecretUnreadable(project_id, "/keys")

    with pytest.raises(HTTPException) as exc:
        await routes._run_ingest_off_loop(_boom, project_id=str(project_id))

    assert exc.value.status_code == 500
    assert str(project_id) in exc.value.detail
    assert "/keys" not in exc.value.detail


def test_worker_marks_the_dc_step_failed_on_unusable_storage(mock_db):
    from depictio.api.v1 import celery_tasks

    doc, _ = _stored_project(mock_db)
    mock_db["storage"].update_one(
        {"project_id": doc["_id"]}, {"$set": {"secret_encrypted": "gAAAAA-not-a-token"}}
    )
    # The task indexes the workflow before resolving credentials.
    mock_db["projects"].update_one(
        {"_id": doc["_id"]}, {"$set": {"workflows": [{"data_collections": []}]}}
    )
    payload = {
        "run_id": "run-1",
        "project_id": str(doc["_id"]),
        "wf_index": 0,
        "dc_id": str(ObjectId()),
        "dc_tag": "counts",
        "user": {"id": str(ObjectId()), "email": "owner@example.com"},
    }
    steps: list[dict] = []
    with (
        patch("depictio.api.v1.db.projects_collection", mock_db["projects"]),
        patch(
            "depictio.api.v1.monitoring.store.set_ingestion_step",
            side_effect=lambda run_id, step, current_step=None: steps.append(step),
        ),
        patch.object(celery_tasks, "_finalize_manifest_refresh_run"),
        patch(
            "depictio.api.v1.endpoints.projects_endpoints.manifest_ingest._run_dc_ingest"
        ) as ingest,
    ):
        result = celery_tasks.manifest_refresh_dc_task.run(payload)

    ingest.assert_not_called()  # never read with the wrong credentials
    assert result["ok"] is False
    assert str(doc["_id"]) in result["message"]
    assert "secrets_key.bin" not in result["message"]
    assert steps[-1] == {"name": "counts", "status": "failed", "detail": result["message"]}
