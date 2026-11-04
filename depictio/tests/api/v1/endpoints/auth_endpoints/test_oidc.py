"""OpenID Connect helpers: discovery, JWKS, PKCE, authorization URL, token exchange, id_token."""

import base64
import hashlib
import time
from urllib.parse import parse_qs, urlsplit

import pytest

from depictio.api.v1.endpoints.auth_endpoints import oidc
from depictio.api.v1.endpoints.auth_endpoints.oidc import OIDCError
from depictio.tests.api.v1.endpoints.auth_endpoints.fake_idp import (
    CLIENT_ID,
    CLIENT_SECRET,
    ISSUER,
    MISSING,
    hs256_token,
    make_key,
    make_provider,
    unsigned_token,
)

pytestmark = pytest.mark.asyncio


async def _verify(idp, token, *, nonce="nonce-1", provider=None, now=None):
    provider = provider or make_provider()
    metadata = await oidc.get_provider_metadata(provider)
    return await oidc.verify_id_token(provider, metadata, token, nonce=nonce, now=now)


# ------------------------------------------------------
# Discovery
# ------------------------------------------------------


class TestProviderMetadata:
    async def test_reads_the_discovery_document_from_the_issuer(self, idp):
        metadata = await oidc.get_provider_metadata(make_provider())

        assert metadata["token_endpoint"] == idp.discovery["token_endpoint"]
        assert idp.requests[0].url == f"{ISSUER}/.well-known/openid-configuration"

    async def test_explicit_discovery_url_is_used(self, idp):
        provider = make_provider(
            issuer=None,
            discovery_url="https://other.example.org/x/.well-known/openid-configuration",
        )
        # Served by the same fake (suffix match), but the issuer is not pinned.
        metadata = await oidc.get_provider_metadata(provider)
        assert metadata["issuer"] == ISSUER
        assert idp.requests[0].url.startswith("https://other.example.org/x/")

    async def test_document_is_cached(self, idp):
        provider = make_provider()
        await oidc.get_provider_metadata(provider)
        await oidc.get_provider_metadata(provider)
        assert idp.count("openid-configuration") == 1

        await oidc.get_provider_metadata(provider, force_refresh=True)
        assert idp.count("openid-configuration") == 2

    async def test_cache_expires(self, idp, monkeypatch):
        provider = make_provider()
        await oidc.get_provider_metadata(provider)
        for entry in oidc._metadata_cache.values():
            entry.fetched_at -= oidc.METADATA_TTL_SECONDS + 1

        await oidc.get_provider_metadata(provider)

        assert idp.count("openid-configuration") == 2

    async def test_issuer_mismatch_is_rejected(self, idp):
        idp.discovery["issuer"] = "https://evil.example.org/realms/example"
        with pytest.raises(OIDCError, match="does not match"):
            await oidc.get_provider_metadata(make_provider())

    async def test_issuer_trailing_slash_is_tolerated(self, idp):
        idp.discovery["issuer"] = ISSUER + "/"
        metadata = await oidc.get_provider_metadata(make_provider())
        assert metadata["issuer"] == ISSUER + "/"

    async def test_a_rejected_document_is_not_cached(self, idp):
        idp.discovery["issuer"] = "https://evil.example.org"
        with pytest.raises(OIDCError):
            await oidc.get_provider_metadata(make_provider())
        idp.discovery["issuer"] = ISSUER
        assert (await oidc.get_provider_metadata(make_provider()))["issuer"] == ISSUER

    @pytest.mark.parametrize(
        "missing", ["issuer", "authorization_endpoint", "token_endpoint", "jwks_uri"]
    )
    async def test_missing_required_fields_are_rejected(self, idp, missing):
        del idp.discovery[missing]
        with pytest.raises(OIDCError, match=missing):
            await oidc.get_provider_metadata(make_provider())

    async def test_provider_without_issuer_or_discovery_url_is_rejected(self, idp):
        with pytest.raises(OIDCError, match="no issuer"):
            await oidc.get_provider_metadata(make_provider(issuer=None))

    async def test_http_error_is_an_oidc_error(self, idp):
        provider = make_provider(issuer=None, discovery_url="https://idp.example.org/nope")
        with pytest.raises(OIDCError, match="404"):
            await oidc.get_provider_metadata(provider)


# ------------------------------------------------------
# Pure helpers
# ------------------------------------------------------


class TestPkce:
    def test_s256_challenge_is_base64url_sha256_without_padding(self):
        verifier, challenge = oidc.new_pkce_pair()

        digest = hashlib.sha256(verifier.encode("ascii")).digest()
        expected = base64.urlsafe_b64encode(digest).rstrip(b"=").decode()
        assert challenge == expected
        assert "=" not in challenge

    def test_verifier_length_and_alphabet(self):
        verifier, _ = oidc.new_pkce_pair()
        assert 43 <= len(verifier) <= 128
        assert set(verifier) <= set(
            "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-._~"
        )

    def test_pairs_are_unique(self):
        assert len({oidc.new_pkce_pair()[0] for _ in range(20)}) == 20

    def test_rfc7636_appendix_b_vector(self):
        from authlib.oauth2.rfc7636 import create_s256_code_challenge

        assert (
            create_s256_code_challenge("dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk")
            == "E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM"
        )


class TestSafeReturnPath:
    @pytest.mark.parametrize(
        "path",
        ["/x?y", "/dashboards", "/dashboard/123?version=abc#frag", "/a/b/c", "/"],
    )
    def test_same_origin_paths_are_kept(self, path):
        assert oidc.safe_return_path(path) == path

    @pytest.mark.parametrize(
        "path",
        [
            "//evil.example.org",
            "//evil.example.org/x",
            "/\\evil.example.org",
            "/\\\\evil.example.org",
            "https://evil.example.org",
            "http://evil.example.org/x",
            "javascript:alert(1)",
            "data:text/html,x",
            " /x",
            "/x ",
            "/x\ny",
            "/x\ty",
            "/x\r\nSet-Cookie: a=b",
            "/x\x00",
            "/x\x7f",
            "x/y",
            "",
            None,
            "/" + "a" * 2100,
        ],
    )
    def test_anything_else_falls_back_to_the_default(self, path):
        assert oidc.safe_return_path(path) == "/dashboards"


class TestRedirectUri:
    def test_configured_value_wins(self):
        provider = make_provider(redirect_uri="https://depictio.example.org/cb")
        assert oidc.redirect_uri_for(provider) == "https://depictio.example.org/cb"

    def test_default_is_the_api_callback_for_the_provider_id(self):
        uri = oidc.redirect_uri_for(make_provider(id="my-idp"))
        assert uri.endswith("/depictio/api/v1/auth/oidc/my-idp/callback")

    def test_constant_time_equals(self):
        assert oidc.constant_time_equals("a", "a")
        assert not oidc.constant_time_equals("a", "b")
        assert not oidc.constant_time_equals(None, "a")
        assert not oidc.constant_time_equals("a", 1)  # type: ignore[arg-type]


# ------------------------------------------------------
# Authorization URL
# ------------------------------------------------------


class TestAuthorizationUrl:
    META = {"authorization_endpoint": f"{ISSUER}/protocol/openid-connect/auth"}

    def _params(self, url: str) -> dict[str, str]:
        return {k: v[0] for k, v in parse_qs(urlsplit(url).query).items()}

    def test_carries_the_code_flow_with_pkce(self):
        provider = make_provider(redirect_uri="https://depictio.example.org/cb")
        url = oidc.build_authorization_url(
            provider, self.META, state="st", nonce="no", code_challenge="ch"
        )

        assert url.startswith(f"{self.META['authorization_endpoint']}?")
        params = self._params(url)
        assert params == {
            "response_type": "code",
            "client_id": CLIENT_ID,
            "redirect_uri": "https://depictio.example.org/cb",
            "scope": "openid email profile",
            "state": "st",
            "nonce": "no",
            "code_challenge": "ch",
            "code_challenge_method": "S256",
        }

    def test_configured_extras_are_added_but_cannot_override_protocol_parameters(self):
        provider = make_provider(
            redirect_uri="https://depictio.example.org/cb",
            authorize_params={
                "prompt": "select_account",
                "hd": "example.org",
                "redirect_uri": "https://evil.example.org/cb",
                "state": "forced",
                "code_challenge_method": "plain",
                "response_type": "token",
                "client_id": "other",
                "nonce": "forced",
                "scope": "admin",
                "code_challenge": "forced",
            },
        )
        params = self._params(
            oidc.build_authorization_url(
                provider, self.META, state="st", nonce="no", code_challenge="ch"
            )
        )

        assert params["prompt"] == "select_account"
        assert params["hd"] == "example.org"
        assert params["redirect_uri"] == "https://depictio.example.org/cb"
        assert params["state"] == "st"
        assert params["nonce"] == "no"
        assert params["code_challenge"] == "ch"
        assert params["code_challenge_method"] == "S256"
        assert params["response_type"] == "code"
        assert params["client_id"] == CLIENT_ID
        assert params["scope"] == "openid email profile"

    def test_endpoint_with_a_query_gets_an_ampersand(self):
        url = oidc.build_authorization_url(
            make_provider(),
            {"authorization_endpoint": "https://idp.example.org/auth?tenant=t"},
            state="st",
            nonce="no",
            code_challenge="ch",
        )
        assert url.startswith("https://idp.example.org/auth?tenant=t&response_type=code")

    def test_custom_scopes(self):
        provider = make_provider(scopes="email groups")
        params = self._params(
            oidc.build_authorization_url(
                provider, self.META, state="s", nonce="n", code_challenge="c"
            )
        )
        assert params["scope"] == "openid email groups"


# ------------------------------------------------------
# Token endpoint
# ------------------------------------------------------


class TestExchangeCode:
    async def _exchange(self, idp, provider, **kwargs):
        idp.token_handler = lambda form: {"id_token": "a.b.c", "access_token": "at"}
        metadata = await oidc.get_provider_metadata(provider)
        body = await oidc.exchange_code(provider, metadata, code="the-code", code_verifier="ver")
        return body, [r for r in idp.requests if r.method == "POST"][-1]

    async def test_sends_the_verifier_grant_and_redirect_uri(self, idp):
        provider = make_provider(redirect_uri="https://depictio.example.org/cb")
        body, request = await self._exchange(idp, provider)

        assert body["id_token"] == "a.b.c"
        assert request.url == idp.discovery["token_endpoint"]
        assert request.form["grant_type"] == "authorization_code"
        assert request.form["code"] == "the-code"
        assert request.form["code_verifier"] == "ver"
        assert request.form["redirect_uri"] == "https://depictio.example.org/cb"

    async def test_basic_auth_by_default(self, idp):
        _, request = await self._exchange(idp, make_provider())

        header = request.headers["authorization"]
        assert header.startswith("Basic ")
        decoded = base64.b64decode(header.split(" ", 1)[1]).decode()
        assert decoded == f"{CLIENT_ID}:{CLIENT_SECRET}"
        assert "client_secret" not in request.form
        assert "client_id" not in request.form

    async def test_post_auth_puts_credentials_in_the_body(self, idp):
        provider = make_provider(token_endpoint_auth_method="client_secret_post")
        _, request = await self._exchange(idp, provider)

        assert "authorization" not in request.headers
        assert request.form["client_id"] == CLIENT_ID
        assert request.form["client_secret"] == CLIENT_SECRET

    async def test_public_client_sends_only_the_client_id(self, idp):
        provider = make_provider(token_endpoint_auth_method="none", client_secret=None)
        _, request = await self._exchange(idp, provider)

        assert "authorization" not in request.headers
        assert request.form["client_id"] == CLIENT_ID
        assert "client_secret" not in request.form
        assert request.form["code_verifier"] == "ver"

    async def test_error_status_is_an_oidc_error(self, idp):
        provider = make_provider()
        metadata = await oidc.get_provider_metadata(provider)
        idp.token_handler = None  # answers 400
        with pytest.raises(OIDCError, match="400"):
            await oidc.exchange_code(provider, metadata, code="c", code_verifier="v")

    @pytest.mark.parametrize("body", [{}, {"access_token": "x"}, {"id_token": 5}, ["list"]])
    async def test_response_without_an_id_token_is_rejected(self, idp, body):
        provider = make_provider()
        metadata = await oidc.get_provider_metadata(provider)
        idp.token_handler = lambda form: body
        with pytest.raises(OIDCError, match="id_token"):
            await oidc.exchange_code(provider, metadata, code="c", code_verifier="v")


# ------------------------------------------------------
# id_token
# ------------------------------------------------------


class TestVerifyIdToken:
    async def test_valid_token_returns_its_claims(self, idp):
        claims = await _verify(idp, idp.sign(name="Jane"))

        assert claims["sub"] == "user-1"
        assert claims["email"] == "jane@example.com"
        assert claims["name"] == "Jane"

    @pytest.mark.parametrize("alg", ["RS256", "RS384", "RS512", "PS256"])
    async def test_asymmetric_algorithms_are_accepted(self, idp, alg):
        assert (await _verify(idp, idp.sign(alg=alg)))["sub"] == "user-1"

    async def test_bad_signature_with_the_right_kid_is_rejected(self, idp):
        forged_key = make_key("k1")  # same kid, different key
        with pytest.raises(OIDCError, match="signature"):
            await _verify(idp, idp.sign(key=forged_key))

    async def test_tampered_payload_is_rejected(self, idp):
        header, payload, signature = idp.sign().split(".")
        forged = idp.claims(sub="admin")
        import json

        body = base64.urlsafe_b64encode(json.dumps(forged).encode()).rstrip(b"=").decode()
        with pytest.raises(OIDCError):
            await _verify(idp, f"{header}.{body}.{signature}")

    @pytest.mark.parametrize("aud", ["someone-else", ["a", "b"], []])
    async def test_wrong_audience_is_rejected(self, idp, aud):
        with pytest.raises(OIDCError, match="claims rejected"):
            await _verify(idp, idp.sign(aud=aud))

    async def test_missing_audience_is_rejected(self, idp):
        with pytest.raises(OIDCError):
            await _verify(idp, idp.sign(aud=MISSING))

    async def test_wrong_issuer_is_rejected(self, idp):
        with pytest.raises(OIDCError, match="claims rejected"):
            await _verify(idp, idp.sign(iss="https://evil.example.org/realms/example"))

    async def test_missing_issuer_is_rejected(self, idp):
        with pytest.raises(OIDCError):
            await _verify(idp, idp.sign(iss=MISSING))

    async def test_expired_beyond_the_leeway_is_rejected(self, idp):
        now = int(time.time())
        token = idp.sign(exp=now - oidc.CLOCK_SKEW_SECONDS - 60, iat=now - 600)
        with pytest.raises(OIDCError, match="claims rejected"):
            await _verify(idp, token)

    async def test_expired_within_the_leeway_is_accepted(self, idp):
        now = int(time.time())
        token = idp.sign(exp=now - 10, iat=now - 600)
        assert (await _verify(idp, token))["sub"] == "user-1"

    async def test_missing_expiry_is_rejected(self, idp):
        with pytest.raises(OIDCError):
            await _verify(idp, idp.sign(exp=MISSING))

    async def test_iat_in_the_future_is_rejected(self, idp):
        now = int(time.time())
        with pytest.raises(OIDCError):
            await _verify(idp, idp.sign(iat=now + oidc.CLOCK_SKEW_SECONDS + 120, exp=now + 900))

    async def test_iat_within_the_leeway_is_accepted(self, idp):
        now = int(time.time())
        assert (await _verify(idp, idp.sign(iat=now + 20)))["sub"] == "user-1"

    async def test_missing_iat_is_rejected(self, idp):
        with pytest.raises(OIDCError):
            await _verify(idp, idp.sign(iat=MISSING))

    async def test_missing_sub_is_rejected(self, idp):
        with pytest.raises(OIDCError):
            await _verify(idp, idp.sign(sub=MISSING))

    async def test_nonce_mismatch_is_rejected(self, idp):
        with pytest.raises(OIDCError, match="nonce"):
            await _verify(idp, idp.sign(nonce="other"), nonce="nonce-1")

    async def test_missing_nonce_is_rejected(self, idp):
        with pytest.raises(OIDCError, match="nonce"):
            await _verify(idp, idp.sign(nonce=MISSING))

    async def test_alg_none_is_rejected(self, idp):
        with pytest.raises(OIDCError, match="alg"):
            await _verify(idp, unsigned_token(idp.claims()))

    async def test_hs256_signed_with_the_client_secret_is_rejected(self, idp):
        token = hs256_token(idp.claims(), CLIENT_SECRET)
        with pytest.raises(OIDCError, match="alg"):
            await _verify(idp, token)

    async def test_hs256_signed_with_the_public_key_material_is_rejected(self, idp):
        public_n = idp.keys["k1"].as_dict(private=False)["n"]
        with pytest.raises(OIDCError, match="alg"):
            await _verify(idp, hs256_token(idp.claims(), public_n * 2))

    @pytest.mark.parametrize("token", ["", "garbage", "a.b", "....", "e30.e30.e30", "%%%.x.y"])
    async def test_malformed_tokens_are_oidc_errors(self, idp, token):
        with pytest.raises(OIDCError):
            await _verify(idp, token)

    async def test_several_audiences_without_azp_are_rejected(self, idp):
        with pytest.raises(OIDCError, match="azp"):
            await _verify(idp, idp.sign(aud=[CLIENT_ID, "other-api"]))

    async def test_several_audiences_with_the_right_azp_are_accepted(self, idp):
        claims = await _verify(idp, idp.sign(aud=[CLIENT_ID, "other-api"], azp=CLIENT_ID))
        assert claims["sub"] == "user-1"

    async def test_several_audiences_with_a_foreign_azp_are_rejected(self, idp):
        with pytest.raises(OIDCError, match="azp"):
            await _verify(idp, idp.sign(aud=[CLIENT_ID, "other-api"], azp="other-api"))

    async def test_single_audience_with_a_foreign_azp_is_rejected(self, idp):
        with pytest.raises(OIDCError, match="azp"):
            await _verify(idp, idp.sign(azp="other-client"))

    async def test_single_audience_list_is_accepted(self, idp):
        assert (await _verify(idp, idp.sign(aud=[CLIENT_ID])))["sub"] == "user-1"

    async def test_explicit_now_drives_the_time_checks(self, idp):
        token = idp.sign()
        far_future = int(time.time()) + 10_000
        with pytest.raises(OIDCError):
            await _verify(idp, token, now=far_future)


class TestJwksHandling:
    async def test_keys_are_fetched_once_and_reused(self, idp):
        await _verify(idp, idp.sign())
        await _verify(idp, idp.sign())
        assert idp.count("/certs") == 1

    async def test_unknown_kid_refetches_the_key_set_once_and_is_then_accepted(self, idp):
        await _verify(idp, idp.sign())  # populates the cache with k1
        assert idp.count("/certs") == 1
        idp.add_key("k2")  # the provider rotates
        # Age the cached set past the refresh floor.
        for entry in oidc.jwks_cache._entries.values():
            entry.fetched_at -= oidc.JWKS_MIN_REFRESH_SECONDS + 5

        claims = await _verify(idp, idp.sign(kid="k2"))

        assert claims["sub"] == "user-1"
        assert idp.count("/certs") == 2
        await _verify(idp, idp.sign(kid="k2"))
        assert idp.count("/certs") == 2  # now cached

    async def test_a_second_unknown_kid_within_the_floor_does_not_refetch(self, idp):
        await _verify(idp, idp.sign())
        for entry in oidc.jwks_cache._entries.values():
            entry.fetched_at -= oidc.JWKS_MIN_REFRESH_SECONDS + 5
        idp.add_key("k3", publish=False)  # signed with, but never published
        with pytest.raises(OIDCError, match="key id"):
            await _verify(idp, idp.sign(kid="k3"))
        assert idp.count("/certs") == 2  # refetched once, kid still unknown

        with pytest.raises(OIDCError, match="key id"):
            await _verify(idp, idp.sign(kid="k3"))
        with pytest.raises(OIDCError, match="key id"):
            await _verify(idp, idp.sign(kid="k4-never-seen", key=idp.keys["k1"]))

        assert idp.count("/certs") == 2  # no stream of requests to the provider

    async def test_unknown_kid_on_a_cold_cache_fetches_and_rejects(self, idp):
        idp.add_key("rogue", publish=False)
        with pytest.raises(OIDCError, match="key id"):
            await _verify(idp, idp.sign(kid="rogue"))
        assert idp.count("/certs") == 1

    async def test_key_set_expires(self, idp):
        await _verify(idp, idp.sign())
        for entry in oidc.jwks_cache._entries.values():
            entry.fetched_at -= oidc.JWKS_TTL_SECONDS + 1
        await _verify(idp, idp.sign())
        assert idp.count("/certs") == 2

    async def test_no_kid_with_a_single_key_is_accepted(self, idp):
        assert (await _verify(idp, idp.sign(kid=None, key=idp.keys["k1"])))["sub"] == "user-1"

    async def test_no_kid_with_several_keys_is_rejected(self, idp):
        idp.add_key("k2")
        with pytest.raises(OIDCError, match="several keys"):
            await _verify(idp, idp.sign(kid=None, key=idp.keys["k1"]))

    async def test_encryption_keys_are_ignored(self, idp):
        enc = make_key("enc")
        idp.keys["enc"] = enc
        original = idp.handle

        def handle(request):
            response = original(request)
            if str(request.url) == idp.jwks_uri:
                import json

                import httpx

                body = json.loads(response.content)
                body["keys"].append({**enc.as_dict(private=False), "use": "enc"})
                return httpx.Response(200, json=body)
            return response

        idp.handle = handle  # type: ignore[method-assign]
        # Same shape as before: one signature key, so a token without kid works.
        assert (await _verify(idp, idp.sign(kid=None, key=idp.keys["k1"])))["sub"] == "user-1"

    async def test_jwks_without_keys_list_is_an_oidc_error(self, idp):
        idp.published.clear()
        original = idp.handle

        def handle(request):
            import httpx

            if str(request.url) == idp.jwks_uri:
                return httpx.Response(200, json={"nokeys": True})
            return original(request)

        idp.handle = handle  # type: ignore[method-assign]
        with pytest.raises(OIDCError, match="keys"):
            await _verify(idp, idp.sign())

    async def test_clear_caches_forgets_everything(self, idp):
        await _verify(idp, idp.sign())
        oidc.clear_caches()
        await _verify(idp, idp.sign())
        assert idp.count("openid-configuration") == 2
        assert idp.count("/certs") == 2


# ------------------------------------------------------
# Userinfo
# ------------------------------------------------------


class TestFetchUserinfo:
    async def test_returns_claims_for_the_same_subject(self, idp):
        idp.userinfo = {"sub": "user-1", "name": "Jane"}
        metadata = await oidc.get_provider_metadata(make_provider())

        info = await oidc.fetch_userinfo(metadata, "at", expected_sub="user-1")

        assert info["name"] == "Jane"
        request = [r for r in idp.requests if "userinfo" in r.url][0]
        assert request.headers["authorization"] == "Bearer at"

    async def test_a_different_subject_is_ignored(self, idp):
        idp.userinfo = {"sub": "someone-else", "email": "attacker@example.com"}
        metadata = await oidc.get_provider_metadata(make_provider())
        assert await oidc.fetch_userinfo(metadata, "at", expected_sub="user-1") == {}

    async def test_missing_sub_is_ignored(self, idp):
        idp.userinfo = {"email": "attacker@example.com"}
        metadata = await oidc.get_provider_metadata(make_provider())
        assert await oidc.fetch_userinfo(metadata, "at", expected_sub="user-1") == {}

    async def test_provider_without_endpoint_or_token_yields_nothing(self, idp):
        del idp.discovery["userinfo_endpoint"]
        metadata = await oidc.get_provider_metadata(make_provider())
        assert await oidc.fetch_userinfo(metadata, "at", expected_sub="user-1") == {}
        assert await oidc.fetch_userinfo({"userinfo_endpoint": "x"}, "", expected_sub="u") == {}

    async def test_a_failing_endpoint_does_not_fail_the_login(self, idp):
        idp.userinfo = {"sub": "user-1"}
        idp.userinfo_status = 500
        metadata = await oidc.get_provider_metadata(make_provider())
        assert await oidc.fetch_userinfo(metadata, "at", expected_sub="user-1") == {}
