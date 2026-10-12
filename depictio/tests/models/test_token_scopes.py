"""Scoped tokens: scope resolution and (de)serialization of the token models."""

from datetime import datetime, timedelta
from typing import cast

import pytest
from beanie import PydanticObjectId, init_beanie
from mongomock_motor import AsyncMongoMockClient
from pydantic import ValidationError
from pymongo.asynchronous.database import AsyncDatabase

from depictio.models.models.base import PyObjectId
from depictio.models.models.users import (
    ALL_TOKEN_SCOPES,
    TokenBase,
    TokenBeanie,
    TokenData,
    effective_scopes,
)


class TestEffectiveScopes:
    def test_none_keeps_full_access(self):
        assert effective_scopes(None) == ALL_TOKEN_SCOPES

    def test_all_scopes_listed(self):
        assert ALL_TOKEN_SCOPES == {"read", "annotate", "report", "edit_dashboard", "ingest"}

    def test_explicit_list_implies_read(self):
        assert effective_scopes(["annotate"]) == {"annotate", "read"}

    def test_read_only(self):
        assert effective_scopes(["read"]) == {"read"}

    def test_empty_list_is_read_only(self):
        assert effective_scopes([]) == {"read"}

    def test_agent_preset(self):
        assert effective_scopes(["read", "annotate", "report"]) == {"read", "annotate", "report"}


def _token_base(**overrides) -> TokenBase:
    now = datetime.now()
    fields = {
        "user_id": PydanticObjectId(),
        "access_token": "access",
        "refresh_token": "refresh",
        "expire_datetime": now + timedelta(days=1),
        "refresh_expire_datetime": now + timedelta(days=7),
        **overrides,
    }
    return TokenBase(**fields)


class TestTokenModels:
    def test_token_data_defaults_to_unscoped(self):
        data = TokenData(sub=PyObjectId(str(PydanticObjectId())))
        assert data.scopes is None
        assert data.model_dump()["scopes"] is None

    def test_token_data_scopes_dump_as_strings(self):
        data = TokenData(sub=PyObjectId(str(PydanticObjectId())), scopes=["read", "annotate"])
        assert data.model_dump()["scopes"] == ["read", "annotate"]

    def test_token_data_rejects_unknown_scope(self):
        with pytest.raises(ValidationError):
            TokenData(sub=PyObjectId(str(PydanticObjectId())), scopes=["admin"])  # type: ignore[invalid-argument-type]

    def test_token_base_round_trip(self):
        token = _token_base(scopes=["read", "report"])
        dumped = token.model_dump()
        assert dumped["scopes"] == ["read", "report"]
        assert TokenBase.model_validate(token.model_dump()).scopes == ["read", "report"]

    def test_token_base_legacy_doc_has_no_scopes(self):
        token = _token_base()
        assert token.scopes is None
        assert "scopes" in token.model_dump_json()

    def test_token_base_rejects_unknown_scope(self):
        with pytest.raises(ValidationError):
            _token_base(scopes=["delete_everything"])

    @pytest.mark.asyncio
    async def test_beanie_persists_scopes(self):
        client = AsyncMongoMockClient()
        await init_beanie(
            database=cast(AsyncDatabase, client.test_db), document_models=[TokenBeanie]
        )
        now = datetime.now()
        token = TokenBeanie(
            user_id=PydanticObjectId(),
            access_token="scoped-access",
            refresh_token="scoped-refresh",
            expire_datetime=now + timedelta(days=1),
            refresh_expire_datetime=now + timedelta(days=7),
            scopes=["annotate"],
        )
        await token.save()
        legacy = TokenBeanie(
            user_id=PydanticObjectId(),
            access_token="legacy-access",
            refresh_token="legacy-refresh",
            expire_datetime=now + timedelta(days=1),
            refresh_expire_datetime=now + timedelta(days=7),
        )
        await legacy.save()

        found = await TokenBeanie.find_one({"access_token": "scoped-access"})
        assert found is not None and found.scopes == ["annotate"]
        found_legacy = await TokenBeanie.find_one({"access_token": "legacy-access"})
        assert found_legacy is not None and found_legacy.scopes is None
