"""Tests for per-project storage configuration (RFC remote-data §5.3, issue 383).

Covers the encryption primitive (first encrypt-at-rest in the codebase), the
owner-only CRUD contract with write-only secrets, endpoint gating, and the
threading of project credentials into the manifest re-ingest path.
"""

from unittest.mock import patch

import mongomock
import pytest
from bson import ObjectId
from fastapi import HTTPException

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
    monkeypatch.setenv("DEPICTIO_KEYS_DIR", str(tmp_path))
    yield tmp_path


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


# ── Crypto primitive ────────────────────────────────────────────────────────


def test_encrypt_decrypt_roundtrip(keys_dir):
    from depictio.api.v1.crypto import decrypt_secret, encrypt_secret

    ciphertext = encrypt_secret("s3cr3t")
    assert ciphertext != "s3cr3t"
    assert decrypt_secret(ciphertext) == "s3cr3t"
    # The symmetric key is persisted alongside the JWT keypair location.
    assert (keys_dir / "secrets_key.bin").is_file()


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


# ── Read-side resolver ──────────────────────────────────────────────────────


def test_storage_options_for_project_decrypts(mock_db):
    user = _user()
    doc = _project_doc(user.id)
    mock_db["projects"].insert_one(doc)
    _put(str(doc["_id"]), user)

    options = storage_config.storage_options_for_project(doc["_id"])

    assert options is not None
    assert options["endpoint_url"] == "https://s3.example.org"
    assert options["aws_access_key_id"] == "AKIA123"
    assert options["aws_secret_access_key"] == "s3cr3t"
    assert options["use_ssl"] == "true"


def test_storage_options_none_without_config(mock_db):
    assert storage_config.storage_options_for_project(ObjectId()) is None


def test_storage_options_none_on_undecryptable_secret(mock_db):
    user = _user()
    doc = _project_doc(user.id)
    mock_db["projects"].insert_one(doc)
    _put(str(doc["_id"]), user)
    # Simulate a rotated/lost keys dir: ciphertext no longer decryptable.
    mock_db["storage"].update_one(
        {"project_id": doc["_id"]}, {"$set": {"secret_encrypted": "gAAAAA-not-a-token"}}
    )
    assert storage_config.storage_options_for_project(doc["_id"]) is None


# ── Threading into re-ingestion ─────────────────────────────────────────────


def test_refresh_threads_project_storage_into_ingest(mock_db, monkeypatch):
    from depictio.api.v1.endpoints.projects_endpoints import manifest_ingest

    monkeypatch.setenv("DEPICTIO_REMOTE_URL_ALLOWLIST", "s3.example.org,example.org")
    user = _user()
    # Raw project dict with a manifest-mode DC — _run_dc_ingest is mocked so
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
