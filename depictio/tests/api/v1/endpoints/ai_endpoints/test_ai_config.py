"""AI feature gating: settings defaults, router registration and status flags.

The AI endpoints are opt-in (`DEPICTIO_AI_ENABLED`). These tests pin the
three layers of the gate:

- `AIConfig` defaults to disabled with no server key;
- the `/ai` router is only included when the flag is on;
- the public `/utils/status` payload advertises the flags to the SPA.
"""

from __future__ import annotations

import importlib

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from depictio.api.v1.configs.settings_models import AIConfig


class TestAIConfigDefaults:
    def test_disabled_by_default(self):
        config = AIConfig()
        assert config.enabled is False
        assert config.api_key is None
        assert config.allow_user_keys is True

    def test_default_model_is_litellm_identifier(self):
        config = AIConfig()
        assert "/" in config.default_model

    def test_env_override(self, monkeypatch):
        monkeypatch.setenv("DEPICTIO_AI_ENABLED", "true")
        monkeypatch.setenv("DEPICTIO_AI_DEFAULT_MODEL", "ollama/llama3")
        monkeypatch.setenv("DEPICTIO_AI_API_KEY", "sk-test")
        monkeypatch.setenv("DEPICTIO_AI_ALLOW_USER_KEYS", "false")
        config = AIConfig()
        assert config.enabled is True
        assert config.default_model == "ollama/llama3"
        assert config.api_key is not None
        assert config.api_key.get_secret_value() == "sk-test"
        assert config.allow_user_keys is False

    def test_key_never_in_repr(self):
        config = AIConfig(api_key="sk-secret-value")  # type: ignore[arg-type]
        assert "sk-secret-value" not in repr(config)

    def test_dashboard_generation_is_off_by_default_with_its_limits(self):
        config = AIConfig()
        assert config.generate_dashboard_enabled is False
        assert config.generate_max_components == 16
        assert config.generate_max_sections == 4
        assert config.generate_max_tokens_total == 150_000
        assert config.generate_max_wall_clock_s == 180
        assert config.generate_max_repairs_per_component == 1
        assert config.generate_max_collections == 6

    @pytest.mark.parametrize(
        ("field", "value"),
        [
            ("generate_max_components", 0),
            ("generate_max_components", 41),
            ("generate_max_sections", 0),
            ("generate_max_sections", 9),
            ("generate_max_tokens_total", 999),
            ("generate_max_wall_clock_s", 9),
            ("generate_max_repairs_per_component", -1),
            ("generate_max_repairs_per_component", 4),
            ("generate_max_collections", 0),
            ("generate_max_collections", 13),
        ],
    )
    def test_generation_knobs_are_bounded(self, field: str, value: int):
        with pytest.raises(ValidationError):
            AIConfig(**{field: value})

    @pytest.mark.parametrize(
        ("field", "value"),
        [
            ("generate_max_components", 1),
            ("generate_max_components", 40),
            ("generate_max_sections", 8),
            ("generate_max_tokens_total", 1_000),
            ("generate_max_wall_clock_s", 10),
            ("generate_max_repairs_per_component", 0),
            ("generate_max_repairs_per_component", 3),
            ("generate_max_collections", 12),
        ],
    )
    def test_generation_knob_bounds_are_inclusive(self, field: str, value: int):
        assert getattr(AIConfig(**{field: value}), field) == value

    def test_generation_env_override(self, monkeypatch):
        monkeypatch.setenv("DEPICTIO_AI_GENERATE_DASHBOARD_ENABLED", "true")
        monkeypatch.setenv("DEPICTIO_AI_GENERATE_MAX_COMPONENTS", "8")
        monkeypatch.setenv("DEPICTIO_AI_GENERATE_MAX_COLLECTIONS", "2")
        config = AIConfig()
        assert config.generate_dashboard_enabled is True
        assert config.generate_max_components == 8
        assert config.generate_max_collections == 2


def _reload_router_with(ai_enabled: bool):
    """Rebuild the aggregated router under a patched AI flag."""
    from depictio.api.v1.configs.config import settings

    original = settings.ai.enabled
    settings.ai.enabled = ai_enabled
    try:
        import depictio.api.v1.endpoints.routers as routers_module

        module = importlib.reload(routers_module)
        return module.router
    finally:
        settings.ai.enabled = original


@pytest.fixture(autouse=True, scope="module")
def _restore_routers_module():
    """Leave the routers module in its import-time state for other tests."""
    yield
    import depictio.api.v1.endpoints.routers as routers_module

    importlib.reload(routers_module)


def _probe_ai_health(router) -> int:
    """Status code of GET /ai/health on a throwaway app carrying `router`.

    Behavioral probe rather than route introspection: FastAPI 0.141 defers
    sub-router inclusion (`router.routes` holds `_IncludedRouter`
    placeholders without a `.path`), so walking `.routes` misses nested
    paths entirely.
    """
    from fastapi import FastAPI

    app = FastAPI()
    app.include_router(router)
    with TestClient(app) as client:
        return client.get("/ai/health").status_code


class TestRouterGating:
    def test_ai_routes_absent_when_disabled(self):
        router = _reload_router_with(ai_enabled=False)
        assert _probe_ai_health(router) == 404

    def test_ai_routes_present_when_enabled(self):
        router = _reload_router_with(ai_enabled=True)
        # 401 (auth required) still proves the route is registered — only
        # 404 would mean the gate kept it out.
        assert _probe_ai_health(router) != 404


class TestStatusFeatureFlags:
    def test_status_reports_ai_flags(self):
        from depictio.api.main import app

        client = TestClient(app)
        response = client.get("/depictio/api/v1/utils/status")
        assert response.status_code == 200
        payload = response.json()
        assert payload["status"] == "online"
        features = payload["features"]
        # Default config: AI off, so every AI flag is false.
        assert features["ai"] is False
        assert features["ai_user_keys"] is False
        assert features["ai_generate_dashboard"] is False

    def test_user_keys_flag_requires_ai_enabled(self):
        """`ai_user_keys` must never be true while `ai` is false."""
        from depictio.api.v1.configs.config import settings

        original = (settings.ai.enabled, settings.ai.allow_user_keys)
        settings.ai.enabled, settings.ai.allow_user_keys = False, True
        try:
            from depictio.api.main import app

            client = TestClient(app)
            features = client.get("/depictio/api/v1/utils/status").json()["features"]
            assert features["ai"] is False
            assert features["ai_user_keys"] is False
        finally:
            settings.ai.enabled, settings.ai.allow_user_keys = original

    @pytest.mark.parametrize(
        ("ai_enabled", "generate_enabled", "expected"),
        [
            (False, False, False),
            (False, True, False),
            (True, False, False),
            (True, True, True),
        ],
    )
    def test_generate_dashboard_flag_needs_both_switches(
        self, ai_enabled: bool, generate_enabled: bool, expected: bool
    ):
        """`ai_generate_dashboard` is true only when AI and the generation opt-in are both on."""
        from depictio.api.v1.configs.config import settings

        original = (settings.ai.enabled, settings.ai.generate_dashboard_enabled)
        settings.ai.enabled, settings.ai.generate_dashboard_enabled = ai_enabled, generate_enabled
        try:
            from depictio.api.main import app

            client = TestClient(app)
            features = client.get("/depictio/api/v1/utils/status").json()["features"]
            assert features["ai_generate_dashboard"] is expected
            assert features["ai"] is ai_enabled
        finally:
            settings.ai.enabled, settings.ai.generate_dashboard_enabled = original
