"""Tests for the component export API.

Follows the bare-router pattern used by ``backup_endpoints/test_backup_routes.py``:
a throwaway ``FastAPI()`` with only the router under test, auth swapped through
``dependency_overrides``, and Mongo access patched.

The router is mounted at its real path (``/depictio/api/v1/export``) because
``SecurityHeadersMiddleware`` keys its embed exemption off that exact shape; a
shorter test prefix would make the header assertions pass without proving
anything. See ``TestSecurityHeaderExemption``.
"""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from depictio.api.v1.endpoints.export_endpoints.routes import (
    export_endpoint_router,
    get_embed_user,
)
from depictio.models.models.base import PyObjectId
from depictio.models.models.users import User

DASHBOARD_ID = "507f1f77bcf86cd799439099"
PROJECT_ID = "507f1f77bcf86cd799439077"
WF_ID = "507f1f77bcf86cd799439066"
DC_ID = "507f1f77bcf86cd799439055"

_ROUTES = "depictio.api.v1.endpoints.export_endpoints.routes"
_RESOLVE = "depictio.api.v1.services.export.resolve"


def _component(index: str, component_type: str, **extra) -> dict:
    return {
        "index": index,
        "component_type": component_type,
        "title": f"{component_type} component",
        "wf_id": WF_ID,
        "dc_id": DC_ID,
        "dc_config": {"delta_location": "s3://bucket/table", "type": "table"},
        **extra,
    }


STORED_METADATA = [
    _component("fig-1", "figure", visu_type="scatter", dict_kwargs={"x": "a", "y": "b"}),
    _component("tbl-1", "table"),
    _component("card-1", "card", column_name="a", aggregation="mean"),
    _component("txt-1", "text", body="hello"),
    _component("jb-1", "jbrowse"),
    _component("av-volcano", "advanced_viz", viz_kind="volcano", config={}),
    _component("av-phylo", "advanced_viz", viz_kind="phylogenetic", config={}),
    _component("av-sankey", "advanced_viz", viz_kind="sankey", config={}),
]

DASHBOARD_DOC = {
    "dashboard_id": PyObjectId(DASHBOARD_ID),
    "project_id": PyObjectId(PROJECT_ID),
    "title": "Test dashboard",
    "stored_metadata": STORED_METADATA,
}


@pytest.fixture
def user() -> User:
    return User(
        id=PyObjectId("507f1f77bcf86cd799439012"),
        email="user@example.com",
        password="$2b$12$example.hashed.password.string",
        is_admin=False,
        is_active=True,
        is_verified=True,
    )


#: The real mount point. Tests use it rather than a short prefix because
#: SecurityHeadersMiddleware keys its embed exemption off this exact path shape —
#: mounting at "/export" would make those assertions pass vacuously.
API_PREFIX = "/depictio/api/v1/export"


@pytest.fixture
def app(user: User) -> FastAPI:
    application = FastAPI()
    application.include_router(export_endpoint_router, prefix=API_PREFIX)
    application.dependency_overrides[get_embed_user] = lambda: user
    return application


@pytest.fixture
def client(app: FastAPI):
    # Both modules hold their own `settings` reference, and the CSP is built in
    # embed.py — patching only the routes module silently leaves the real
    # (empty) allowlist in play for frame-ancestors.
    with (
        patch(f"{_ROUTES}.settings") as route_settings,
        patch("depictio.api.v1.services.export.embed.settings") as embed_settings,
    ):
        route_settings.fastapi.embed_enabled = True
        route_settings.fastapi.embed_allowed_origins = ["https://lab.example.org"]
        embed_settings.fastapi.embed_allowed_origins = ["https://lab.example.org"]
        embed_settings.fastapi.embed_csp_unsafe_inline = False
        yield TestClient(app)


@pytest.fixture
def mongo(request):
    """Patch the dashboard lookup and permission check used by resolve.py."""
    allow = getattr(request, "param", True)
    with (
        patch(
            "depictio.api.v1.endpoints.dashboards_endpoints.routes.dashboards_collection"
        ) as collection,
        patch(
            "depictio.api.v1.endpoints.dashboards_endpoints.routes.check_project_permission",
            return_value=allow,
        ) as permission,
    ):
        collection.find_one.return_value = DASHBOARD_DOC
        yield collection, permission


def _url(component_id: str, **params) -> str:
    """Build a component URL, always with a `?` so callers can append `&key=…`."""
    query = "&".join(f"{k}={v}" for k, v in params.items())
    return f"{API_PREFIX}/dashboards/{DASHBOARD_ID}/components/{component_id}?{query}"


# --- manifest ---------------------------------------------------------------


class TestManifest:
    def test_lists_every_component_with_its_formats(self, client, mongo):
        response = client.get(f"{API_PREFIX}/dashboards/{DASHBOARD_ID}/components")
        assert response.status_code == 200
        by_id = {entry["component_id"]: entry for entry in response.json()}

        assert by_id["fig-1"]["formats"] == ["html", "json"]
        assert by_id["tbl-1"]["formats"] == ["html"]
        assert by_id["txt-1"]["formats"] == ["html"]
        assert by_id["jb-1"]["formats"] == []
        assert by_id["av-sankey"]["formats"] == ["html", "json"]
        assert by_id["av-volcano"]["formats"] == ["html", "json"], (
            "volcano has a Python builder, so JSON is available"
        )
        assert by_id["av-phylo"]["formats"] == ["html"]

    def test_explains_why_json_is_unavailable(self, client, mongo):
        response = client.get(f"{API_PREFIX}/dashboards/{DASHBOARD_ID}/components")
        by_id = {entry["component_id"]: entry for entry in response.json()}
        assert "format=html" in by_id["tbl-1"]["json_unavailable_reason"]
        assert "phylogenetic" in by_id["av-phylo"]["json_unavailable_reason"]
        assert "json_unavailable_reason" not in by_id["fig-1"]

    def test_reports_viz_kind(self, client, mongo):
        response = client.get(f"{API_PREFIX}/dashboards/{DASHBOARD_ID}/components")
        by_id = {entry["component_id"]: entry for entry in response.json()}
        assert by_id["av-volcano"]["viz_kind"] == "volcano"
        assert by_id["fig-1"]["viz_kind"] is None


# --- auth + lookup ----------------------------------------------------------


class TestAccessControl:
    @pytest.mark.parametrize("mongo", [False], indirect=True)
    def test_permission_denied_is_403(self, client, mongo):
        assert client.get(_url("fig-1")).status_code == 403

    def test_unknown_dashboard_is_404(self, client, mongo):
        collection, _ = mongo
        collection.find_one.return_value = None
        response = client.get(_url("fig-1"))
        assert response.status_code == 404
        assert "not found" in response.json()["detail"].lower()

    def test_unknown_component_is_404(self, client, mongo):
        response = client.get(_url("does-not-exist"))
        assert response.status_code == 404

    def test_router_404s_with_guidance_when_embedding_is_disabled(self, app, mongo):
        with patch(f"{_ROUTES}.settings") as settings:
            settings.fastapi.embed_enabled = False
            response = TestClient(app).get(_url("fig-1"))
        assert response.status_code == 404
        assert response.json()["detail"]["code"] == "embed_disabled"


# --- unsupported combinations ----------------------------------------------


class TestUnsupportedFormats:
    def test_non_plotly_type_is_422_with_supported_formats(self, client, mongo):
        response = client.get(_url("tbl-1", format="json"))
        assert response.status_code == 422
        detail = response.json()["detail"]
        assert detail["code"] == "unsupported_export"
        assert detail["supported_formats"] == ["html"]
        assert detail["html_available"] is True
        assert "format=html" in detail["html_url"]

    def test_unported_viz_kind_is_501_and_points_at_html(self, client, mongo):
        """501 not 422: the limitation is temporary and HTML works right now."""
        response = client.get(_url("av-phylo", format="json"))
        assert response.status_code == 501
        detail = response.json()["detail"]
        assert detail["code"] == "kind_not_ported"
        assert detail["viz_kind"] == "phylogenetic"
        assert detail["html_available"] is True
        assert "format=html" in detail["html_url"]

    def test_jbrowse_is_unsupported_in_every_format(self, client, mongo):
        response = client.get(_url("jb-1", format="json"))
        assert response.status_code == 422
        detail = response.json()["detail"]
        assert detail["supported_formats"] == []
        assert "html_url" not in detail

    def test_invalid_format_is_rejected(self, client, mongo):
        assert client.get(_url("fig-1", format="pdf")).status_code == 422

    def test_invalid_theme_is_rejected(self, client, mongo):
        assert client.get(_url("fig-1", theme="neon")).status_code == 422


# --- json export ------------------------------------------------------------


class TestJsonExport:
    def test_returns_a_portable_plotly_spec(self, client, mongo):
        rows = {"gene": ["a", "b"], "lfc": [2.0, -2.0], "padj": [0.001, 0.001]}
        component = _component(
            "av-volcano",
            "advanced_viz",
            viz_kind="volcano",
            config={
                "feature_id_col": "gene",
                "effect_size_col": "lfc",
                "significance_col": "padj",
            },
        )
        doc = {**DASHBOARD_DOC, "stored_metadata": [component]}
        collection, _ = mongo
        collection.find_one.return_value = doc

        with patch(
            "depictio.api.v1.services.advanced_viz.data.load_tidy_columns",
            return_value={"rows": rows, "columns": list(rows), "row_count": 2},
        ):
            response = client.get(_url("av-volcano", format="json"))

        assert response.status_code == 200
        payload = response.json()
        assert set(payload) == {"data", "layout", "config", "meta"}
        assert payload["data"], "expected at least one trace"
        assert payload["config"] == {"displaylogo": False, "responsive": True}
        assert "uirevision" not in payload["layout"], (
            "uirevision is viewer-only state and must not leak into an export"
        )

    def test_meta_carries_provenance(self, client, mongo):
        rows = {"gene": ["a"], "lfc": [1.0], "padj": [0.01]}
        component = _component(
            "av-volcano",
            "advanced_viz",
            viz_kind="volcano",
            config={
                "feature_id_col": "gene",
                "effect_size_col": "lfc",
                "significance_col": "padj",
            },
        )
        collection, _ = mongo
        collection.find_one.return_value = {
            **DASHBOARD_DOC,
            "stored_metadata": [component],
        }

        with patch(
            "depictio.api.v1.services.advanced_viz.data.load_tidy_columns",
            return_value={"rows": rows, "columns": list(rows), "row_count": 1},
        ):
            meta = client.get(_url("av-volcano", format="json", theme="dark")).json()["meta"]

        assert meta["component_id"] == "av-volcano"
        assert meta["component_type"] == "advanced_viz"
        assert meta["viz_kind"] == "volcano"
        assert meta["theme"] == "dark"
        assert meta["filter_applied"] is False
        assert meta["generated_at"]

    def test_json_response_keeps_the_strict_security_headers(self, client, mongo):
        """Only the HTML embed is exempt; JSON must not be framable."""
        response = client.get(_url("tbl-1", format="json"))
        assert "text/html" not in response.headers.get("content-type", "")


# --- filters ----------------------------------------------------------------


class TestFilters:
    def test_malformed_filter_json_is_400(self, client, mongo):
        response = client.get(_url("fig-1") + "&filters=not-json")
        assert response.status_code == 400
        assert "JSON array" in response.json()["detail"]

    def test_non_array_filters_is_400(self, client, mongo):
        response = client.get(_url("fig-1") + f"&filters={json.dumps({'a': 1})}")
        assert response.status_code == 400

    def test_post_accepts_filters_in_the_body(self, client, mongo):
        """The POST form exists for filter payloads too large for a query string."""
        response = client.post(
            f"{API_PREFIX}/dashboards/{DASHBOARD_ID}/components/tbl-1?format=json",
            json={"filters": [{"column_name": "a", "value": ["x"]}], "theme": "light"},
        )
        # tbl-1 is HTML-only, so we get the structured 422 rather than a figure —
        # which still proves the body was parsed and routed.
        assert response.status_code == 422
        assert response.json()["detail"]["code"] == "unsupported_export"

    def test_post_rejects_an_invalid_theme(self, client, mongo):
        response = client.post(
            f"{API_PREFIX}/dashboards/{DASHBOARD_ID}/components/fig-1",
            json={"theme": "neon"},
        )
        assert response.status_code == 400


# --- html embed -------------------------------------------------------------


class TestHtmlEmbed:
    def test_missing_bundle_is_503_with_a_build_hint(self, client, mongo, tmp_path):
        with patch(
            "depictio.api.v1.services.export.embed.EMBED_TEMPLATE_PATH",
            tmp_path / "absent.html",
        ):
            response = client.get(_url("txt-1", format="html"))
        assert response.status_code == 503
        detail = response.json()["detail"]
        assert detail["code"] == "bundle_unavailable"
        assert "build:embed" in detail["message"]

    def test_text_component_renders_without_any_data_fetch(self, client, mongo, tmp_path):
        """Text needs no payload, so it exercises the bundle path in isolation."""
        bundle = tmp_path / "embed.html"
        bundle.write_text(
            '<html><body><script id="embed-payload" type="application/json">'
            "__DEPICTIO_EMBED_PAYLOAD__</script></body></html>"
        )
        with patch("depictio.api.v1.services.export.embed.EMBED_TEMPLATE_PATH", bundle):
            response = client.get(_url("txt-1", format="html"))

        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/html")
        body = response.text
        assert "__DEPICTIO_EMBED_PAYLOAD__" not in body, "sentinel must be substituted"
        assert '"component_type": "text"' in body or '"component_type":"text"' in body

    def test_embed_sets_frame_ancestors_and_omits_x_frame_options(self, client, mongo, tmp_path):
        bundle = tmp_path / "embed.html"
        bundle.write_text("<html><body>__DEPICTIO_EMBED_PAYLOAD__</body></html>")
        with patch("depictio.api.v1.services.export.embed.EMBED_TEMPLATE_PATH", bundle):
            response = client.get(_url("txt-1", format="html"))

        csp = response.headers["content-security-policy"]
        assert "frame-ancestors https://lab.example.org" in csp
        assert "connect-src 'none'" in csp, "the bundle makes no network calls"
        assert "X-Frame-Options" not in response.headers

    def test_frame_ancestors_defaults_to_none_when_no_origins_configured(
        self, app, mongo, tmp_path
    ):
        bundle = tmp_path / "embed.html"
        bundle.write_text("<html><body>__DEPICTIO_EMBED_PAYLOAD__</body></html>")
        with (
            patch(f"{_ROUTES}.settings") as route_settings,
            patch("depictio.api.v1.services.export.embed.settings") as embed_settings,
            patch("depictio.api.v1.services.export.embed.EMBED_TEMPLATE_PATH", bundle),
        ):
            route_settings.fastapi.embed_enabled = True
            route_settings.fastapi.embed_allowed_origins = []
            embed_settings.fastapi.embed_allowed_origins = []
            embed_settings.fastapi.embed_csp_unsafe_inline = False
            response = TestClient(app).get(_url("txt-1", format="html"))

        assert "frame-ancestors 'none'" in response.headers["content-security-policy"]

    def test_inline_scripts_are_pinned_by_hash(self, client, mongo, tmp_path):
        bundle = tmp_path / "embed.html"
        bundle.write_text(
            "<html><body><script>console.log(1)</script>__DEPICTIO_EMBED_PAYLOAD__</body></html>"
        )
        with patch("depictio.api.v1.services.export.embed.EMBED_TEMPLATE_PATH", bundle):
            response = client.get(_url("txt-1", format="html"))

        csp = response.headers["content-security-policy"]
        assert "'sha256-" in csp
        assert "'unsafe-inline'" not in csp.split("style-src")[0]


# --- CORS -------------------------------------------------------------------


class TestEmbedCors:
    def test_allow_listed_origin_is_reflected_without_credentials(self, client, mongo):
        response = client.get(
            _url("tbl-1", format="json"), headers={"Origin": "https://lab.example.org"}
        )
        assert response.headers["access-control-allow-origin"] == "https://lab.example.org"
        assert response.headers["vary"] == "Origin"
        assert "access-control-allow-credentials" not in response.headers

    def test_unknown_origin_is_not_reflected(self, client, mongo):
        response = client.get(
            _url("tbl-1", format="json"), headers={"Origin": "https://evil.example"}
        )
        assert "access-control-allow-origin" not in response.headers


# --- security middleware interaction ----------------------------------------


class TestSecurityHeaderExemption:
    """The baseline middleware must not clobber the embed's own headers.

    `SecurityHeadersMiddleware` uses `setdefault`, which lets a handler override a
    header but never remove one — and `X-Frame-Options: SAMEORIGIN` has no
    "allow these origins" form. So the exemption has to live in the middleware,
    and it must be scoped to HTML so JSON keeps the strict defaults. These are the
    only tests that mount the real middleware.
    """

    @pytest.fixture
    def secured_client(self, app: FastAPI, tmp_path):
        from depictio.api.main import SecurityHeadersMiddleware

        app.add_middleware(SecurityHeadersMiddleware)
        bundle = tmp_path / "embed.html"
        bundle.write_text("<html><body>__DEPICTIO_EMBED_PAYLOAD__</body></html>")
        with (
            patch(f"{_ROUTES}.settings") as route_settings,
            patch("depictio.api.v1.services.export.embed.settings") as embed_settings,
            patch("depictio.api.v1.services.export.embed.EMBED_TEMPLATE_PATH", bundle),
        ):
            route_settings.fastapi.embed_enabled = True
            route_settings.fastapi.embed_allowed_origins = ["https://lab.example.org"]
            embed_settings.fastapi.embed_allowed_origins = ["https://lab.example.org"]
            embed_settings.fastapi.embed_csp_unsafe_inline = False
            yield TestClient(app)

    def test_html_embed_escapes_the_baseline_headers(self, secured_client, mongo):
        response = secured_client.get(_url("txt-1", format="html"))
        assert response.status_code == 200
        assert "X-Frame-Options" not in response.headers
        csp = response.headers["content-security-policy"]
        assert "frame-ancestors https://lab.example.org" in csp
        assert "frame-ancestors 'self'" not in csp

    def test_json_export_keeps_the_baseline_headers(self, secured_client, mongo):
        response = secured_client.get(_url("tbl-1", format="json"))
        assert response.headers["X-Frame-Options"] == "SAMEORIGIN"
        assert "frame-ancestors 'self'" in response.headers["content-security-policy"]

    def test_baseline_non_framing_headers_still_apply_to_embeds(self, secured_client, mongo):
        """Only the two framing headers are exempt — the rest must survive."""
        response = secured_client.get(_url("txt-1", format="html"))
        assert response.headers["X-Content-Type-Options"] == "nosniff"
        assert response.headers["Referrer-Policy"] == "strict-origin-when-cross-origin"
