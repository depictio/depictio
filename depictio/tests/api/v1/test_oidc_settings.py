"""OIDC provider configuration: env parsing, credential overrides, legacy mappings."""

import json
from unittest.mock import MagicMock

import pytest
from pydantic import SecretStr, ValidationError

from depictio.api.v1.configs.settings_models import (
    GOOGLE_OIDC_DISCOVERY_URL,
    AuthConfig,
    OIDCClaimMapping,
    OIDCProviderConfig,
)
from depictio.api.v1.endpoints.auth_endpoints import oidc

ISSUER = "https://idp.example.org/realms/example"


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    """No OIDC, Google or SAML variable from the host leaks into a test."""
    import os

    for name in list(os.environ):
        upper = name.upper()
        if upper.startswith(
            (
                "DEPICTIO_AUTH_OIDC_",
                "DEPICTIO_AUTH_GOOGLE_OAUTH_",
                "DEPICTIO_AUTH_SAML_",
                "DEPICTIO_AUTH_PASSWORD_LOGIN_DISABLED",
            )
        ):
            monkeypatch.delenv(name, raising=False)


def providers_env(monkeypatch, *items: dict) -> None:
    monkeypatch.setenv("DEPICTIO_AUTH_OIDC_PROVIDERS", json.dumps(list(items)))


def kc(**extra) -> dict:
    return {"id": "kc", "issuer": ISSUER, "client_id": "depictio", "client_secret": "s", **extra}


class TestProviderParsing:
    def test_json_list_in_the_environment_is_parsed(self, monkeypatch):
        providers_env(
            monkeypatch,
            kc(
                label="Sign in with Keycloak",
                scopes="openid email groups",
                claims={"groups": "realm_access.roles", "login": "preferred_username"},
                authorize_params={"prompt": "login"},
                sso_provider="keycloak",
            ),
            {
                "id": "second",
                "discovery_url": "https://i.example.org/.well-known/x",
                "enabled": False,
            },
        )

        auth = AuthConfig()

        assert [p.id for p in auth.oidc_providers] == ["kc", "second"]
        first = auth.oidc_providers[0]
        assert first.label == "Sign in with Keycloak"
        assert first.issuer == ISSUER
        assert first.client_secret is not None
        assert first.client_secret.get_secret_value() == "s"
        assert first.claims.groups == "realm_access.roles"
        assert first.claims.email == "email"
        assert first.authorize_params == {"prompt": "login"}
        assert first.stored_provider_name == "keycloak"
        assert auth.oidc_providers[1].enabled is False

    def test_defaults(self):
        provider = OIDCProviderConfig(id="kc", issuer=ISSUER)

        assert provider.enabled is True
        assert provider.scopes == ["openid", "email", "profile"]
        assert provider.token_endpoint_auth_method == "client_secret_basic"
        assert provider.assume_email_verified is False
        assert provider.fetch_userinfo is True
        assert provider.authorize_params == {}
        assert provider.claims == OIDCClaimMapping()
        assert provider.claims.picture == "picture"
        assert provider.claims.groups is None
        assert provider.redirect_uri is None
        assert provider.display_label == "Sign in with kc"
        assert provider.stored_provider_name == "kc"
        assert provider.resolved_discovery_url == f"{ISSUER}/.well-known/openid-configuration"

    def test_discovery_url_override_and_trailing_slash(self):
        assert (
            OIDCProviderConfig(id="a", issuer=ISSUER + "/").resolved_discovery_url
            == f"{ISSUER}/.well-known/openid-configuration"
        )
        assert (
            OIDCProviderConfig(
                id="a", issuer=ISSUER, discovery_url="https://x.example.org/d"
            ).resolved_discovery_url
            == "https://x.example.org/d"
        )
        assert OIDCProviderConfig(id="a").resolved_discovery_url is None

    def test_no_provider_by_default(self):
        auth = AuthConfig()
        assert auth.oidc_providers == []
        assert auth.enabled_oidc_providers == []
        assert auth.sso_enabled is False

    def test_empty_strings_from_helm_are_unset(self):
        provider = OIDCProviderConfig(
            id="kc",
            issuer=ISSUER,
            label="",
            client_id="",
            client_secret="",
            sso_provider="",
            redirect_uri="  ",
            claims={"groups": "", "login": " ", "title": "", "display_name": "", "picture": ""},
        )
        assert provider.label is None
        assert provider.client_id is None
        assert provider.client_secret is None
        assert provider.sso_provider is None
        assert provider.redirect_uri is None
        assert provider.claims.groups is None
        assert provider.claims.login is None
        assert provider.claims.title is None
        assert provider.claims.display_name is None
        assert provider.claims.picture is None

    def test_client_secret_is_not_shown_in_repr(self):
        provider = OIDCProviderConfig(id="kc", issuer=ISSUER, client_secret="hunter2-secret")
        assert "hunter2-secret" not in repr(provider)
        assert "hunter2-secret" not in provider.model_dump_json()

    def test_unknown_keys_are_rejected(self):
        with pytest.raises(ValidationError):
            OIDCProviderConfig(id="kc", unknown_key=1)  # type: ignore[call-arg]
        with pytest.raises(ValidationError):
            OIDCClaimMapping(nope="x")  # type: ignore[call-arg]

    def test_invalid_auth_method_is_rejected(self):
        with pytest.raises(ValidationError):
            OIDCProviderConfig(id="kc", token_endpoint_auth_method="private_key_jwt")  # type: ignore[arg-type]


class TestProviderIds:
    @pytest.mark.parametrize("good", ["kc", "my-idp", "a_b", "0idp", "a" * 32, "x"])
    def test_valid_ids(self, good):
        assert OIDCProviderConfig(id=good).id == good

    def test_ids_are_lowercased_and_stripped(self):
        assert OIDCProviderConfig(id="  KeyCloak ").id == "keycloak"

    @pytest.mark.parametrize(
        "bad", ["", "-kc", "_kc", "a b", "a/b", "a.b", "a" * 33, "é", "kc?x=1", "../x", "a#b"]
    )
    def test_invalid_ids_are_rejected(self, bad):
        with pytest.raises(ValidationError):
            OIDCProviderConfig(id=bad)

    def test_duplicate_ids_are_rejected(self):
        with pytest.raises(ValidationError, match="unique"):
            AuthConfig(oidc_providers=[{"id": "kc"}, {"id": "kc"}])

    def test_duplicate_ids_in_the_environment_are_rejected(self, monkeypatch):
        providers_env(monkeypatch, kc(), kc(label="again"))
        with pytest.raises(ValidationError):
            AuthConfig()

    def test_ids_differing_only_in_case_are_duplicates(self):
        with pytest.raises(ValidationError, match="unique"):
            AuthConfig(oidc_providers=[{"id": "KC"}, {"id": "kc"}])

    def test_invalid_id_in_the_environment_is_rejected(self, monkeypatch):
        providers_env(monkeypatch, kc(id="bad id"))
        with pytest.raises(ValidationError):
            AuthConfig()


class TestScopes:
    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("email profile", ["openid", "email", "profile"]),
            ("openid email", ["openid", "email"]),
            ("email,profile", ["openid", "email", "profile"]),
            ("  email   groups ", ["openid", "email", "groups"]),
            (["email"], ["openid", "email"]),
            (["openid", "email"], ["openid", "email"]),
            ("", ["openid"]),
            ([], ["openid"]),
        ],
    )
    def test_scopes_are_split_and_openid_is_always_present(self, raw, expected):
        assert OIDCProviderConfig(id="kc", scopes=raw).scopes == expected


class TestCredentialEnvOverrides:
    def test_client_id_and_secret_come_from_the_environment(self, monkeypatch):
        providers_env(monkeypatch, {"id": "kc", "issuer": ISSUER})
        monkeypatch.setenv("DEPICTIO_AUTH_OIDC_KC_CLIENT_ID", "from-env")
        monkeypatch.setenv("DEPICTIO_AUTH_OIDC_KC_CLIENT_SECRET", "env-secret")

        provider = AuthConfig().oidc_providers[0]

        assert provider.client_id == "from-env"
        assert provider.client_secret is not None
        assert provider.client_secret.get_secret_value() == "env-secret"
        assert [p.id for p in AuthConfig().enabled_oidc_providers] == ["kc"]

    def test_environment_wins_over_the_json_values(self, monkeypatch):
        providers_env(monkeypatch, kc())
        monkeypatch.setenv("DEPICTIO_AUTH_OIDC_KC_CLIENT_ID", "from-env")

        provider = AuthConfig().oidc_providers[0]

        assert provider.client_id == "from-env"
        assert provider.client_secret is not None
        assert provider.client_secret.get_secret_value() == "s"  # only the id was overridden

    def test_id_with_a_dash_maps_to_an_underscore(self, monkeypatch):
        providers_env(monkeypatch, {"id": "my-idp", "issuer": ISSUER})
        monkeypatch.setenv("DEPICTIO_AUTH_OIDC_MY_IDP_CLIENT_ID", "dash-id")
        monkeypatch.setenv("DEPICTIO_AUTH_OIDC_MY_IDP_CLIENT_SECRET", "dash-secret")

        provider = AuthConfig().oidc_providers[0]

        assert provider.env_prefix == "DEPICTIO_AUTH_OIDC_MY_IDP_"
        assert provider.client_id == "dash-id"
        assert provider.client_secret == SecretStr("dash-secret")

    def test_one_providers_variables_do_not_touch_another(self, monkeypatch):
        providers_env(monkeypatch, kc(), kc(id="other", client_id="x"))
        monkeypatch.setenv("DEPICTIO_AUTH_OIDC_OTHER_CLIENT_ID", "other-env")

        by_id = {p.id: p for p in AuthConfig().oidc_providers}

        assert by_id["kc"].client_id == "depictio"
        assert by_id["other"].client_id == "other-env"

    def test_blank_environment_values_do_not_erase_the_json_ones(self, monkeypatch):
        providers_env(monkeypatch, kc())
        monkeypatch.setenv("DEPICTIO_AUTH_OIDC_KC_CLIENT_ID", "  ")
        monkeypatch.setenv("DEPICTIO_AUTH_OIDC_KC_CLIENT_SECRET", "")

        provider = AuthConfig().oidc_providers[0]

        assert provider.client_id == "depictio"
        assert provider.client_secret is not None
        assert provider.client_secret.get_secret_value() == "s"


class TestEnabledProviders:
    def test_only_enabled_and_fully_configured_providers_are_listed(self):
        auth = AuthConfig(
            oidc_providers=[
                {"id": "ok", "issuer": ISSUER, "client_id": "c", "client_secret": "s"},
                {
                    "id": "off",
                    "issuer": ISSUER,
                    "client_id": "c",
                    "client_secret": "s",
                    "enabled": False,
                },
                {"id": "noid", "issuer": ISSUER, "client_secret": "s"},
                {"id": "nosecret", "issuer": ISSUER, "client_id": "c"},
                {"id": "noissuer", "client_id": "c", "client_secret": "s"},
                {
                    "id": "pub",
                    "issuer": ISSUER,
                    "client_id": "c",
                    "token_endpoint_auth_method": "none",
                },
                {
                    "id": "disc",
                    "discovery_url": "https://i.example.org/d",
                    "client_id": "c",
                    "client_secret": "s",
                },
            ]
        )

        assert [p.id for p in auth.enabled_oidc_providers] == ["ok", "pub", "disc"]
        assert auth.get_oidc_provider("ok") is not None
        assert auth.get_oidc_provider("off") is None
        assert auth.get_oidc_provider("noid") is None
        assert auth.get_oidc_provider("missing") is None
        assert auth.sso_enabled is True

    def test_missing_settings_names_what_is_lacking(self):
        assert OIDCProviderConfig(id="kc").missing_settings() == [
            "client_id",
            "issuer or discovery_url",
            "client_secret",
        ]
        assert (
            OIDCProviderConfig(
                id="kc", issuer=ISSUER, client_id="c", token_endpoint_auth_method="none"
            ).missing_settings()
            == []
        )

    def test_provider_missing_client_id_is_not_enabled(self, monkeypatch):
        providers_env(monkeypatch, {"id": "kc", "issuer": ISSUER, "client_secret": "s"})
        auth = AuthConfig()
        assert len(auth.oidc_providers) == 1
        assert auth.enabled_oidc_providers == []
        assert auth.sso_enabled is False


class TestPasswordLoginDisabled:
    def test_flag_alone_is_ignored(self):
        assert AuthConfig(password_login_disabled=True).is_password_login_disabled is False

    def test_flag_with_an_unconfigured_provider_is_ignored(self):
        auth = AuthConfig(password_login_disabled=True, oidc_providers=[{"id": "kc"}])
        assert auth.is_password_login_disabled is False

    def test_flag_with_a_disabled_provider_is_ignored(self):
        auth = AuthConfig(
            password_login_disabled=True,
            oidc_providers=[
                {
                    "id": "kc",
                    "issuer": ISSUER,
                    "client_id": "c",
                    "client_secret": "s",
                    "enabled": False,
                }
            ],
        )
        assert auth.is_password_login_disabled is False

    def test_flag_with_an_enabled_configured_provider_applies(self):
        auth = AuthConfig(
            password_login_disabled=True,
            oidc_providers=[{"id": "kc", "issuer": ISSUER, "client_id": "c", "client_secret": "s"}],
        )
        assert auth.is_password_login_disabled is True

    def test_provider_without_the_flag_keeps_passwords_on(self):
        auth = AuthConfig(
            oidc_providers=[{"id": "kc", "issuer": ISSUER, "client_id": "c", "client_secret": "s"}]
        )
        assert auth.is_password_login_disabled is False

    def test_flag_from_the_environment(self, monkeypatch):
        providers_env(monkeypatch, kc())
        monkeypatch.setenv("DEPICTIO_AUTH_PASSWORD_LOGIN_DISABLED", "true")
        assert AuthConfig().is_password_login_disabled is True


class TestLegacyGoogleMapping:
    def _google(self, monkeypatch, **extra: str) -> None:
        monkeypatch.setenv("DEPICTIO_AUTH_GOOGLE_OAUTH_ENABLED", "true")
        monkeypatch.setenv("DEPICTIO_AUTH_GOOGLE_OAUTH_CLIENT_ID", "gid.apps.example.org")
        monkeypatch.setenv("DEPICTIO_AUTH_GOOGLE_OAUTH_CLIENT_SECRET", "gsecret")
        for key, value in extra.items():
            monkeypatch.setenv(f"DEPICTIO_AUTH_GOOGLE_OAUTH_{key}", value)

    def test_legacy_variables_become_a_google_provider(self, monkeypatch):
        self._google(monkeypatch, REDIRECT_URI="https://depictio.example.org/auth/google/callback")

        auth = AuthConfig()

        assert [p.id for p in auth.oidc_providers] == ["google"]
        google = auth.oidc_providers[0]
        assert google.label == "Sign in with Google"
        assert google.display_label == "Sign in with Google"
        assert google.discovery_url == GOOGLE_OIDC_DISCOVERY_URL
        assert google.resolved_discovery_url == GOOGLE_OIDC_DISCOVERY_URL
        assert google.issuer == "https://accounts.google.com"
        assert google.client_id == "gid.apps.example.org"
        assert google.client_secret is not None
        assert google.client_secret.get_secret_value() == "gsecret"
        # Kept as configured: it is the one registered at the provider.
        assert google.redirect_uri == "https://depictio.example.org/auth/google/callback"
        assert google.sso_provider == "google"
        assert google.stored_provider_name == "google"
        assert auth.enabled_oidc_providers == [google]
        assert auth.sso_enabled is True

    def test_redirect_uri_is_optional(self, monkeypatch):
        self._google(monkeypatch)
        assert AuthConfig().oidc_providers[0].redirect_uri is None

    def test_disabled_flag_adds_nothing(self, monkeypatch):
        self._google(monkeypatch, ENABLED="false")
        assert AuthConfig().oidc_providers == []

    def test_enabled_without_credentials_is_not_usable(self, monkeypatch):
        monkeypatch.setenv("DEPICTIO_AUTH_GOOGLE_OAUTH_ENABLED", "true")
        auth = AuthConfig()
        assert [p.id for p in auth.oidc_providers] == ["google"]
        assert auth.enabled_oidc_providers == []

    def test_explicit_google_entry_wins(self, monkeypatch):
        self._google(monkeypatch)
        providers_env(
            monkeypatch,
            {
                "id": "google",
                "label": "Google (explicit)",
                "discovery_url": GOOGLE_OIDC_DISCOVERY_URL,
                "client_id": "explicit-id",
                "client_secret": "explicit-secret",
            },
        )

        auth = AuthConfig()

        assert len(auth.oidc_providers) == 1
        assert auth.oidc_providers[0].label == "Google (explicit)"
        assert auth.oidc_providers[0].client_id == "explicit-id"

    def test_other_providers_keep_their_place_before_the_legacy_one(self, monkeypatch):
        self._google(monkeypatch)
        providers_env(monkeypatch, kc())
        assert [p.id for p in AuthConfig().oidc_providers] == ["kc", "google"]


class TestLegacyEnvCheck:
    def _logger(self, monkeypatch) -> MagicMock:
        fake = MagicMock()
        monkeypatch.setattr(oidc, "logger", fake)
        return fake

    def test_clean_environment_finds_nothing_and_logs_no_error(self, monkeypatch):
        fake = self._logger(monkeypatch)

        found = oidc.check_legacy_sso_env(
            {"PATH": "/usr/bin", "DEPICTIO_AUTH_OIDC_PROVIDERS": "[]"}
        )

        assert found == []
        fake.error.assert_not_called()

    def test_saml_variables_are_reported_with_their_replacement(self, monkeypatch):
        fake = self._logger(monkeypatch)
        env = {
            "DEPICTIO_AUTH_SAML_ENABLED": "true",
            "DEPICTIO_AUTH_SAML_IDP_ENTITY_ID": "https://idp.example.org",
            "DEPICTIO_AUTH_SAML_ATTRIBUTE_GROUPS": "memberOf",
            "DEPICTIO_AUTH_SAML_IDP_CERT": "",
            "UNRELATED": "x",
        }

        found = oidc.check_legacy_sso_env(env)

        assert found == sorted(k for k in env if k.startswith("DEPICTIO_AUTH_SAML_"))
        fake.error.assert_called_once()
        message = fake.error.call_args.args[0]
        for name in found:
            assert name in message
        assert "claims.groups" in message
        assert "issuer" in message
        assert "JWKS" in message
        assert "DEPICTIO_AUTH_OIDC_PROVIDERS" in message
        assert "UNRELATED" not in message

    def test_variable_names_are_matched_case_insensitively(self, monkeypatch):
        fake = self._logger(monkeypatch)
        found = oidc.check_legacy_sso_env({"depictio_auth_saml_enabled": "1"})
        assert found == ["depictio_auth_saml_enabled"]
        fake.error.assert_called_once()

    def test_every_documented_saml_variable_has_a_replacement(self):
        assert "DEPICTIO_AUTH_SAML_ATTRIBUTE_TITLE" in oidc.LEGACY_SAML_REPLACEMENTS
        assert all(oidc.LEGACY_SAML_REPLACEMENTS.values())
        assert len(oidc.LEGACY_SAML_REPLACEMENTS) == 14

    def test_legacy_google_variables_are_reported_when_google_is_enabled(self, monkeypatch):
        from depictio.api.v1.configs.config import settings

        fake = self._logger(monkeypatch)
        monkeypatch.setattr(settings.auth, "google_oauth_enabled", True)

        found = oidc.check_legacy_sso_env({"DEPICTIO_AUTH_GOOGLE_OAUTH_ENABLED": "true"})

        assert found == ["DEPICTIO_AUTH_GOOGLE_OAUTH_ENABLED"]
        fake.warning.assert_called()
        assert "deprecated" in fake.warning.call_args.args[0]
