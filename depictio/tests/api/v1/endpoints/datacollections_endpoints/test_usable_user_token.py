"""Which stored token the in-process CLI calls sign with (`_usable_user_token`).

The oldest token on file is usually a one-hour login token: long expired, it
made every upload of the web UI fail with 401 "Invalid token". An unexpired
one must be used, or a new one minted when there is none.
"""

import asyncio
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, patch

import mongomock
import pytest
from bson import ObjectId

from depictio.api.v1.endpoints.datacollections_endpoints import utils as dc_utils
from depictio.models.models.users import UserBase

ADD_TOKEN = "depictio.api.v1.endpoints.user_endpoints.core_functions._add_token"


@pytest.fixture()
def db():
    database = mongomock.MongoClient()["depictio_test"]
    with (
        patch.object(dc_utils, "projects_collection", database["projects"]),
        patch.object(dc_utils, "tokens_collection", database["tokens"]),
    ):
        yield database


@pytest.fixture()
def user():
    return UserBase(id=ObjectId(), email="learner@example.com", is_admin=False)


def _token(db, user, name, expires_in, lifetime="short-lived"):
    expire = datetime.now() + expires_in
    db["tokens"].insert_one(
        {
            "user_id": user.id,
            "name": name,
            "token_lifetime": lifetime,
            "access_token": f"{name}.a.b",
            "refresh_token": f"{name}.r.r",
            "expire_datetime": expire,
            "refresh_expire_datetime": expire + timedelta(days=7),
        }
    )


def _owned_project(db, user) -> str:
    project_id = ObjectId()
    db["projects"].insert_one(
        {"_id": project_id, "permissions": {"owners": [{"_id": user.id}]}, "workflows": []}
    )
    return str(project_id)


def test_expired_oldest_token_is_skipped_for_a_valid_newer_one(db, user):
    _token(db, user, "morning-login", timedelta(hours=-8))
    _token(db, user, "current-login", timedelta(minutes=50))

    assert dc_utils._usable_user_token(user.id)["name"] == "current-login"
    _, full_token = dc_utils._editable_project_and_token(_owned_project(db, user), user)
    assert full_token["name"] == "current-login"
    assert dc_utils._build_cli_config_for_user(user).user.token.access_token == "current-login.a.b"


def test_long_lived_token_preferred_over_a_newer_login_token(db, user):
    _token(db, user, "cli", timedelta(days=300), lifetime="long-lived")
    _token(db, user, "current-login", timedelta(minutes=50))

    assert dc_utils._usable_user_token(user.id)["name"] == "cli"


def test_only_expired_tokens_mints_a_new_one(db, user):
    _token(db, user, "morning-login", timedelta(hours=-8))
    _token(db, user, "noon-login", timedelta(hours=-2))

    assert dc_utils._usable_user_token(user.id) is None
    with patch(ADD_TOKEN, new_callable=AsyncMock) as add_token:
        asyncio.run(dc_utils._ensure_user_cli_token(user))
    add_token.assert_awaited_once()
    minted = add_token.await_args.args[0]
    assert minted.token_lifetime == "long-lived"
    assert str(minted.sub) == str(user.id)


def test_no_tokens_mints_a_new_one(db, user):
    with patch(ADD_TOKEN, new_callable=AsyncMock) as add_token:
        asyncio.run(dc_utils._ensure_user_cli_token(user))
    add_token.assert_awaited_once()


def test_a_valid_token_mints_nothing(db, user):
    _token(db, user, "morning-login", timedelta(hours=-8))
    _token(db, user, "current-login", timedelta(minutes=50))
    with patch(ADD_TOKEN, new_callable=AsyncMock) as add_token:
        asyncio.run(dc_utils._ensure_user_cli_token(user))
    add_token.assert_not_awaited()


def test_only_expired_tokens_refuse_the_in_process_config(db, user):
    _token(db, user, "morning-login", timedelta(hours=-8))
    with pytest.raises(dc_utils.HTTPException) as exc:
        dc_utils._editable_project_and_token(_owned_project(db, user), user)
    assert exc.value.status_code == 401
