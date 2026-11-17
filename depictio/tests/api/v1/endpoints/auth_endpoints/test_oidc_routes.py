"""The ``/auth/oidc`` routes, end to end against a fake provider and mongomock."""

from collections.abc import Callable
from datetime import timedelta
from typing import Any
from urllib.parse import parse_qs, quote, urlsplit

import httpx
import pytest
from fastapi import FastAPI

from depictio.api.v1.configs.config import settings
from depictio.api.v1.endpoints.auth_endpoints import oidc_routes
from depictio.api.v1.endpoints.auth_endpoints.oidc_routes import oidc_router
from depictio.models.models.oauth_state import OAuthStateBeanie
from depictio.models.models.users import GroupBeanie, MagicLinkTicketBeanie, UserBeanie
from depictio.models.timestamps import utc_now_naive
from depictio.tests.api.v1.endpoints.auth_endpoints.fake_idp import (
    CLIENT_ID,
    ISSUER,
    FakeIdP,
    make_provider,
)
from depictio.tests.api.v1.endpoints.user_endpoints.conftest import beanie_setup

MODELS = [UserBeanie, GroupBeanie, OAuthStateBeanie, MagicLinkTicketBeanie]
REDIRECT_URI = "https://depictio.example.org/depictio/api/v1/auth/oidc/kc/callback"


def viewer() -> str:
    return settings.viewer.external_url.rstrip("/")


@pytest.fixture
def providers(monkeypatch) -> Callable[..., None]:
    """Install providers on ``settings.auth`` and return a setter."""

    def install(*items: Any) -> None:
        monkeypatch.setattr(settings.auth, "oidc_providers", list(items))

    install(make_provider(redirect_uri=REDIRECT_URI))
    monkeypatch.setattr(settings.auth, "registration_disabled", False)
    return install


@pytest.fixture
def app() -> FastAPI:
    application = FastAPI()
    application.include_router(oidc_router, prefix="/auth/oidc")
    return application


@pytest.fixture
def client(app):
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://api.test", follow_redirects=False
    )


def query(location: str) -> dict[str, str]:
    return {k: v[0] for k, v in parse_qs(urlsplit(location).query).items()}


def fragment(location: str) -> dict[str, str]:
    return {k: v[0] for k, v in parse_qs(urlsplit(location).fragment).items()}


async def start_login(client, provider_id="kc", next_path: str | None = None):
    params = {"next": next_path} if next_path is not None else {}
    response = await client.get(f"/auth/oidc/{provider_id}/login", params=params)
    return response


def serve_tokens(idp: FakeIdP, **claim_overrides: Any) -> list[dict[str, str]]:
    """Make the token endpoint answer with an id_token for the login in flight.

    The nonce is read from the form-less authorization step, so tests pass it
    through ``claim_overrides`` or ``idp.pending_nonce``. Returns the list of
    token-request forms received.
    """
    seen: list[dict[str, str]] = []

    def handler(form: dict[str, str]) -> dict[str, Any]:
        seen.append(form)
        claims = idp.claims(nonce=idp.pending_nonce, **claim_overrides)
        return {"id_token": idp.sign(claims), "access_token": "at", "token_type": "Bearer"}

    idp.token_handler = handler
    return seen


@pytest.fixture(autouse=True)
def _pending_nonce(idp):
    idp.pending_nonce = "unset"  # type: ignore[attr-defined]


async def full_login(client, idp, *, next_path=None, **claim_overrides):
    """Run /login then /callback; return (login_response, callback_response, token_forms)."""
    forms = serve_tokens(idp, **claim_overrides)
    login = await start_login(client, next_path=next_path)
    assert login.status_code == 302, login.text
    params = query(login.headers["location"])
    idp.pending_nonce = params["nonce"]  # type: ignore[attr-defined]
    callback = await client.get(
        "/auth/oidc/kc/callback", params={"code": "auth-code", "state": params["state"]}
    )
    return login, callback, forms


def error_of(response) -> str | None:
    location = response.headers["location"]
    assert location.startswith(f"{viewer()}/auth?error="), location
    return location.split("error=", 1)[1]


# ------------------------------------------------------
# /providers
# ------------------------------------------------------


class TestProvidersList:
    @pytest.mark.asyncio
    async def test_lists_only_enabled_configured_providers_with_id_and_label(
        self, client, providers
    ):
        providers(
            make_provider(id="kc", label="Sign in with Keycloak"),
            make_provider(id="off", enabled=False),
            make_provider(id="nosecret", client_secret=None),
            make_provider(id="noid", client_id=None),
            make_provider(id="noissuer", issuer=None),
            make_provider(id="pub", client_secret=None, token_endpoint_auth_method="none"),
        )

        response = await client.get("/auth/oidc/providers")

        assert response.status_code == 200
        assert response.json() == [
            {"id": "kc", "label": "Sign in with Keycloak"},
            {"id": "pub", "label": "Sign in with pub"},
        ]

    @pytest.mark.asyncio
    async def test_never_exposes_secrets_or_internal_settings(self, client, providers):
        providers(make_provider(client_secret="very-secret-value"))

        body = (await client.get("/auth/oidc/providers")).text

        for leaked in ("very-secret-value", CLIENT_ID, ISSUER, "claims", "client_secret"):
            assert leaked not in body

    @pytest.mark.asyncio
    async def test_empty_when_none_is_configured(self, client, providers):
        providers()
        response = await client.get("/auth/oidc/providers")
        assert response.status_code == 200
        assert response.json() == []

    @pytest.mark.asyncio
    async def test_is_public(self, client, providers):
        # No Authorization header at all.
        assert (await client.get("/auth/oidc/providers")).status_code == 200


# ------------------------------------------------------
# /login
# ------------------------------------------------------


class TestLogin:
    @pytest.mark.asyncio
    @beanie_setup(models=MODELS)
    async def test_redirects_to_the_authorization_endpoint_and_stores_the_state(
        self, client, providers, idp
    ):
        response = await start_login(client, next_path="/dashboard/abc?version=1")

        assert response.status_code == 302
        location = response.headers["location"]
        assert location.startswith(idp.discovery["authorization_endpoint"] + "?")
        params = query(location)
        assert params["response_type"] == "code"
        assert params["client_id"] == CLIENT_ID
        assert params["redirect_uri"] == REDIRECT_URI
        assert params["code_challenge_method"] == "S256"
        assert params["scope"] == "openid email profile"
        stored = await OAuthStateBeanie.find_one({"state": params["state"]})
        assert stored is not None
        assert stored.provider == "kc"
        assert stored.nonce == params["nonce"]
        assert stored.return_to == "/dashboard/abc?version=1"
        assert stored.code_verifier
        assert stored.code_verifier not in location  # only the challenge leaves the server
        assert stored.nonce != params["state"]

    @pytest.mark.asyncio
    @beanie_setup(models=MODELS)
    async def test_challenge_matches_the_stored_verifier(self, client, providers, idp):
        import base64
        import hashlib

        response = await start_login(client)
        params = query(response.headers["location"])
        stored = await OAuthStateBeanie.find_one({"state": params["state"]})
        assert stored is not None and stored.code_verifier is not None
        digest = hashlib.sha256(stored.code_verifier.encode()).digest()
        assert params["code_challenge"] == base64.urlsafe_b64encode(digest).rstrip(b"=").decode()

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "next_path",
        ["//evil.example.org", "https://evil.example.org", "/\\evil.example.org", "javascript:1"],
    )
    @beanie_setup(models=MODELS)
    async def test_open_redirect_in_next_is_sanitised(self, client, providers, idp, next_path):
        response = await start_login(client, next_path=next_path)

        params = query(response.headers["location"])
        stored = await OAuthStateBeanie.find_one({"state": params["state"]})
        assert stored is not None
        assert stored.return_to == "/dashboards"

    @pytest.mark.asyncio
    @beanie_setup(models=MODELS)
    async def test_missing_next_lands_on_the_dashboards(self, client, providers, idp):
        params = query((await start_login(client)).headers["location"])
        stored = await OAuthStateBeanie.find_one({"state": params["state"]})
        assert stored is not None and stored.return_to == "/dashboards"

    @pytest.mark.asyncio
    @beanie_setup(models=MODELS)
    async def test_each_login_gets_fresh_state_nonce_and_challenge(self, client, providers, idp):
        first = query((await start_login(client)).headers["location"])
        second = query((await start_login(client)).headers["location"])
        for key in ("state", "nonce", "code_challenge"):
            assert first[key] != second[key]

    @pytest.mark.asyncio
    @pytest.mark.parametrize("provider_id", ["unknown", "off", "nosecret"])
    @beanie_setup(models=MODELS)
    async def test_unknown_disabled_or_unconfigured_provider_redirects_to_the_sign_in_page(
        self, client, providers, idp, provider_id
    ):
        providers(
            make_provider(id="kc"),
            make_provider(id="off", enabled=False),
            make_provider(id="nosecret", client_secret=None),
        )

        response = await start_login(client, provider_id)

        assert response.status_code == 303
        assert response.headers["location"] == f"{viewer()}/auth?error=sso_unavailable"
        assert await OAuthStateBeanie.find({}).count() == 0

    @pytest.mark.asyncio
    @beanie_setup(models=MODELS)
    async def test_discovery_failure_redirects_without_storing_a_state(
        self, client, providers, idp
    ):
        idp.discovery["issuer"] = "https://evil.example.org"

        response = await start_login(client)

        assert error_of(response) == "sso_unavailable"
        assert await OAuthStateBeanie.find({}).count() == 0


# ------------------------------------------------------
# /callback
# ------------------------------------------------------


class TestCallbackSuccess:
    @pytest.mark.asyncio
    @beanie_setup(models=MODELS)
    async def test_success_hands_off_a_ticket_in_the_fragment(self, client, providers, idp):
        _, response, _ = await full_login(client, idp, next_path="/dashboard/abc?x=1")

        assert response.status_code == 303
        location = response.headers["location"]
        assert location.startswith(f"{viewer()}/auth/magic#ticket=")
        assert "?" not in location.split("#", 1)[0]  # nothing sensitive in the query
        frag = fragment(location)
        assert frag["next"] == "/dashboard/abc?x=1"
        user = await UserBeanie.find_one({"email": "jane@example.com"})
        assert user is not None
        ticket = await MagicLinkTicketBeanie.find_one({"ticket": frag["ticket"]})
        assert ticket is not None
        assert str(ticket.user_id) == str(user.id)

    @pytest.mark.asyncio
    @beanie_setup(models=MODELS)
    async def test_creates_a_verified_user_stamped_with_the_provider(self, client, providers, idp):
        await full_login(client, idp, email="Jane@Example.com")

        user = await UserBeanie.find_one({"email": "jane@example.com"})
        assert user is not None
        assert user.is_verified is True
        assert user.sso_provider == "kc"
        assert user.is_admin is False

    @pytest.mark.asyncio
    @beanie_setup(models=MODELS)
    async def test_existing_user_is_reused(self, client, providers, idp):
        existing = UserBeanie(
            email="jane@example.com", password="$2b$12$x", is_active=True, is_verified=True
        )
        await existing.save()

        _, response, _ = await full_login(client, idp)

        assert response.headers["location"].startswith(f"{viewer()}/auth/magic#ticket=")
        assert await UserBeanie.find({}).count() == 1

    @pytest.mark.asyncio
    @beanie_setup(models=MODELS)
    async def test_token_request_carries_the_stored_pkce_verifier(self, client, providers, idp):
        forms = serve_tokens(idp)
        login = await start_login(client)
        params = query(login.headers["location"])
        idp.pending_nonce = params["nonce"]  # type: ignore[attr-defined]
        stored = await OAuthStateBeanie.find_one({"state": params["state"]})
        assert stored is not None

        await client.get(
            "/auth/oidc/kc/callback", params={"code": "the-code", "state": params["state"]}
        )

        assert len(forms) == 1
        assert forms[0]["code_verifier"] == stored.code_verifier
        assert forms[0]["code"] == "the-code"
        assert forms[0]["grant_type"] == "authorization_code"
        assert forms[0]["redirect_uri"] == REDIRECT_URI

    @pytest.mark.asyncio
    @beanie_setup(models=MODELS)
    async def test_userinfo_claims_fill_in_what_the_token_lacks(self, client, providers, idp):
        providers(make_provider(redirect_uri=REDIRECT_URI, claims={"display_name": "name"}))
        idp.userinfo = {"sub": "user-1", "name": "Jane Doe"}

        await full_login(client, idp)

        user = await UserBeanie.find_one({"email": "jane@example.com"})
        assert user is not None and user.display_name == "Jane Doe"

    @pytest.mark.asyncio
    @beanie_setup(models=MODELS)
    async def test_userinfo_with_a_different_sub_is_ignored(self, client, providers, idp):
        providers(make_provider(redirect_uri=REDIRECT_URI, claims={"display_name": "name"}))
        idp.userinfo = {
            "sub": "someone-else",
            "email": "attacker@example.com",
            "email_verified": True,
            "name": "Attacker",
        }

        _, response, _ = await full_login(client, idp)

        assert response.headers["location"].startswith(f"{viewer()}/auth/magic#ticket=")
        assert await UserBeanie.find_one({"email": "attacker@example.com"}) is None
        user = await UserBeanie.find_one({"email": "jane@example.com"})
        assert user is not None and user.display_name is None

    @pytest.mark.asyncio
    @beanie_setup(models=MODELS)
    async def test_the_signed_token_wins_over_userinfo(self, client, providers, idp):
        idp.userinfo = {"sub": "user-1", "email": "other@example.com", "email_verified": True}

        await full_login(client, idp)

        assert await UserBeanie.find_one({"email": "jane@example.com"}) is not None
        assert await UserBeanie.find_one({"email": "other@example.com"}) is None

    @pytest.mark.asyncio
    @beanie_setup(models=MODELS)
    async def test_userinfo_is_not_requested_when_disabled(self, client, providers, idp):
        providers(make_provider(redirect_uri=REDIRECT_URI, fetch_userinfo=False))
        idp.userinfo = {"sub": "user-1"}

        await full_login(client, idp)

        assert idp.count("userinfo") == 0


class TestCallbackRejections:
    @pytest.mark.asyncio
    @beanie_setup(models=MODELS)
    async def test_state_replay_is_rejected(self, client, providers, idp):
        serve_tokens(idp)
        params = query((await start_login(client)).headers["location"])
        idp.pending_nonce = params["nonce"]  # type: ignore[attr-defined]
        query_params = {"code": "c", "state": params["state"]}

        first = await client.get("/auth/oidc/kc/callback", params=query_params)
        assert first.headers["location"].startswith(f"{viewer()}/auth/magic#ticket=")
        tickets = await MagicLinkTicketBeanie.find({}).count()

        replay = await client.get("/auth/oidc/kc/callback", params=query_params)

        assert error_of(replay) == "sso_failed"
        assert await MagicLinkTicketBeanie.find({}).count() == tickets
        assert idp.count("token", "POST") == 1

    @pytest.mark.asyncio
    @pytest.mark.parametrize("state", [None, "", "never-issued"])
    @beanie_setup(models=MODELS)
    async def test_missing_or_unknown_state_is_rejected(self, client, providers, idp, state):
        serve_tokens(idp)
        params = {"code": "c"}
        if state is not None:
            params["state"] = state

        response = await client.get("/auth/oidc/kc/callback", params=params)

        assert error_of(response) == "sso_failed"
        assert idp.count("token", "POST") == 0
        assert await UserBeanie.find({}).count() == 0

    @pytest.mark.asyncio
    @beanie_setup(models=MODELS)
    async def test_state_issued_for_another_provider_is_rejected(self, client, providers, idp):
        providers(
            make_provider(id="kc", redirect_uri=REDIRECT_URI),
            make_provider(id="other", redirect_uri=REDIRECT_URI.replace("/kc/", "/other/")),
        )
        serve_tokens(idp)
        login = await start_login(client, "kc")
        params = query(login.headers["location"])
        idp.pending_nonce = params["nonce"]  # type: ignore[attr-defined]

        response = await client.get(
            "/auth/oidc/other/callback", params={"code": "c", "state": params["state"]}
        )

        assert error_of(response) == "sso_failed"
        assert idp.count("token", "POST") == 0
        assert await UserBeanie.find({}).count() == 0
        # The state is burned: it cannot be tried again on the right provider.
        retry = await client.get(
            "/auth/oidc/kc/callback", params={"code": "c", "state": params["state"]}
        )
        assert error_of(retry) == "sso_failed"

    @pytest.mark.asyncio
    @beanie_setup(models=MODELS)
    async def test_access_denied_is_a_cancellation_and_burns_the_state(
        self, client, providers, idp
    ):
        params = query((await start_login(client)).headers["location"])

        response = await client.get(
            "/auth/oidc/kc/callback", params={"error": "access_denied", "state": params["state"]}
        )

        assert error_of(response) == "sso_cancelled"
        assert await OAuthStateBeanie.find({"state": params["state"]}).count() == 0

    @pytest.mark.asyncio
    @beanie_setup(models=MODELS)
    async def test_other_provider_errors_are_failures_and_burn_the_state(
        self, client, providers, idp
    ):
        params = query((await start_login(client)).headers["location"])

        response = await client.get(
            "/auth/oidc/kc/callback",
            params={
                "error": "server_error",
                "error_description": "<script>",
                "state": params["state"],
            },
        )

        assert error_of(response) == "sso_failed"
        assert "script" not in response.headers["location"]
        assert await OAuthStateBeanie.find({}).count() == 0

    @pytest.mark.asyncio
    @beanie_setup(models=MODELS)
    async def test_expired_state_is_rejected(self, client, providers, idp):
        serve_tokens(idp)
        params = query((await start_login(client)).headers["location"])
        await OAuthStateBeanie.find_one({"state": params["state"]}).update(
            {"$set": {"expire_datetime": utc_now_naive() - timedelta(seconds=1)}}
        )

        response = await client.get(
            "/auth/oidc/kc/callback", params={"code": "c", "state": params["state"]}
        )

        assert error_of(response) == "sso_failed"
        assert idp.count("token", "POST") == 0
        assert await OAuthStateBeanie.find({}).count() == 0

    @pytest.mark.asyncio
    @beanie_setup(models=MODELS)
    async def test_missing_code_is_rejected(self, client, providers, idp):
        serve_tokens(idp)
        params = query((await start_login(client)).headers["location"])

        response = await client.get("/auth/oidc/kc/callback", params={"state": params["state"]})

        assert error_of(response) == "sso_failed"

    @pytest.mark.asyncio
    @pytest.mark.parametrize("provider_id", ["unknown", "off"])
    @beanie_setup(models=MODELS)
    async def test_unknown_provider_callback_is_unavailable(
        self, client, providers, idp, provider_id
    ):
        providers(make_provider(id="kc"), make_provider(id="off", enabled=False))
        response = await client.get(
            f"/auth/oidc/{provider_id}/callback", params={"code": "c", "state": "s"}
        )
        assert error_of(response) == "sso_unavailable"

    @pytest.mark.asyncio
    @beanie_setup(models=MODELS)
    async def test_token_endpoint_failure_is_sso_failed(self, client, providers, idp):
        params = query((await start_login(client)).headers["location"])
        idp.token_handler = None  # token endpoint answers 400

        response = await client.get(
            "/auth/oidc/kc/callback", params={"code": "c", "state": params["state"]}
        )

        assert error_of(response) == "sso_failed"
        assert await UserBeanie.find({}).count() == 0

    @pytest.mark.asyncio
    @beanie_setup(models=MODELS)
    async def test_wrong_nonce_in_the_token_is_rejected(self, client, providers, idp):
        serve_tokens(idp)
        idp.pending_nonce = "a-nonce-from-another-login"  # type: ignore[attr-defined]
        params = query((await start_login(client)).headers["location"])

        response = await client.get(
            "/auth/oidc/kc/callback", params={"code": "c", "state": params["state"]}
        )

        assert error_of(response) == "sso_failed"
        assert await UserBeanie.find({}).count() == 0

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "overrides",
        [{"aud": "someone-else"}, {"iss": "https://evil.example.org"}, {"exp": 1}],
    )
    @beanie_setup(models=MODELS)
    async def test_invalid_token_claims_are_rejected(self, client, providers, idp, overrides):
        _, response, _ = await full_login(client, idp, **overrides)

        assert error_of(response) == "sso_failed"
        assert await UserBeanie.find({}).count() == 0
        assert await MagicLinkTicketBeanie.find({}).count() == 0

    @pytest.mark.asyncio
    @beanie_setup(models=MODELS)
    async def test_token_signed_by_an_unknown_key_is_rejected(self, client, providers, idp):
        from depictio.tests.api.v1.endpoints.auth_endpoints.fake_idp import make_key

        forged = make_key("k1")
        forms = []

        def handler(form):
            forms.append(form)
            return {"id_token": idp.sign(idp.claims(nonce=idp.pending_nonce), key=forged)}

        idp.token_handler = handler
        params = query((await start_login(client)).headers["location"])
        idp.pending_nonce = params["nonce"]  # type: ignore[attr-defined]

        response = await client.get(
            "/auth/oidc/kc/callback", params={"code": "c", "state": params["state"]}
        )

        assert error_of(response) == "sso_failed"
        assert await UserBeanie.find({}).count() == 0

    @pytest.mark.asyncio
    @beanie_setup(models=MODELS)
    async def test_registration_disabled_rejects_an_unknown_email(
        self, client, providers, idp, monkeypatch
    ):
        monkeypatch.setattr(settings.auth, "registration_disabled", True)

        _, response, _ = await full_login(client, idp)

        assert error_of(response) == "registration_disabled"
        assert await UserBeanie.find({}).count() == 0
        assert await MagicLinkTicketBeanie.find({}).count() == 0

    @pytest.mark.asyncio
    @beanie_setup(models=MODELS)
    async def test_registration_disabled_still_logs_in_a_known_user(
        self, client, providers, idp, monkeypatch
    ):
        monkeypatch.setattr(settings.auth, "registration_disabled", True)
        await UserBeanie(
            email="jane@example.com", password="$2b$12$x", is_active=True, is_verified=True
        ).save()

        _, response, _ = await full_login(client, idp)

        assert response.headers["location"].startswith(f"{viewer()}/auth/magic#ticket=")

    @pytest.mark.asyncio
    @beanie_setup(models=MODELS)
    async def test_unverified_email_is_rejected(self, client, providers, idp):
        _, response, _ = await full_login(client, idp, email_verified=False)

        assert error_of(response) == "email_not_verified"
        assert await UserBeanie.find({}).count() == 0

    @pytest.mark.asyncio
    @beanie_setup(models=MODELS)
    async def test_missing_email_is_sso_failed(self, client, providers, idp):
        _, response, _ = await full_login(client, idp, email="")

        assert error_of(response) == "sso_failed"

    @pytest.mark.asyncio
    @beanie_setup(models=MODELS)
    async def test_error_redirects_never_leak_details(self, client, providers, idp):
        _, response, _ = await full_login(client, idp, email_verified=False)

        location = response.headers["location"]
        assert location == f"{viewer()}/auth?error=email_not_verified"
        assert "jane" not in location

    def test_module_redirect_helper_quotes_codes(self):
        response = oidc_routes._error_redirect("a b&c")
        assert response.headers["location"].endswith(f"?error={quote('a b&c')}")
