"""The embed payload must satisfy the offline shim's keying contract.

``depictio/viewer/src/offline/mockApi.ts`` looks payloads up by component index for
figure/table/map/image/multiqc and by ``dc_id`` for interactive/advanced_viz. Two
components on a real dashboard can share a data collection, so the builder rewrites
``dc_id`` in the embedded metadata to a per-component synthetic value. Getting that
wrong produces a bundle that loads and then throws "no … payload for" at render
time — which no other test would catch.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from depictio.api.v1.services.export.bundle import (
    OfflineBundleError,
    encode_payload,
    inject,
    json_safe,
)
from depictio.api.v1.services.export.embed import (
    EMBED_SENTINEL,
    _advanced_viz_columns,
    _empty_data,
    _script_hashes,
    _synthetic_dc_id,
    build_component_embed_payload,
)

DASHBOARD_DOC = {"dashboard_id": "d1", "project_id": "p1", "title": "T"}


def _component(component_type: str, **extra) -> dict:
    return {
        "index": "cmp-1",
        "component_type": component_type,
        "title": "A component",
        "wf_id": "507f1f77bcf86cd799439066",
        "dc_id": "507f1f77bcf86cd799439055",
        **extra,
    }


async def _build(component: dict) -> dict:
    return await build_component_embed_payload(
        dashboard_doc=DASHBOARD_DOC,
        component=component,
        theme="light",
        filters=[],
        access_token=None,
        current_user=object(),
    )


class TestKeyingContract:
    @pytest.mark.asyncio
    async def test_text_needs_no_data_and_keeps_its_real_dc_id(self) -> None:
        payload = await _build(_component("text", body="hi"))
        assert payload["component"]["component_type"] == "text"
        # Not a dc-keyed type, so no rewrite.
        assert payload["component"]["dc_id"] == "507f1f77bcf86cd799439055"
        assert payload["data"] == _empty_data()

    @pytest.mark.asyncio
    async def test_advanced_viz_dc_id_is_rewritten_and_data_matches(self) -> None:
        component = _component(
            "advanced_viz",
            viz_kind="volcano",
            config={"feature_id_col": "gene", "effect_size_col": "lfc"},
        )
        tidy = {"rows": {"gene": ["a"], "lfc": [1.0]}, "columns": ["gene", "lfc"]}
        with patch(
            "depictio.api.v1.services.advanced_viz.data.load_tidy_columns",
            return_value=tidy,
        ):
            payload = await _build(component)

        synthetic = _synthetic_dc_id("cmp-1")
        assert payload["component"]["dc_id"] == synthetic
        assert synthetic in payload["data"]["advancedVizData"], (
            "the renderer looks this up by the dc_id in its own metadata"
        )
        assert "507f1f77bcf86cd799439055" not in payload["data"]["advancedVizData"]

    @pytest.mark.asyncio
    async def test_two_components_on_one_dc_get_distinct_keys(self) -> None:
        """The collision the synthetic id exists to prevent."""
        tidy = {"rows": {"gene": ["a"]}, "columns": ["gene"]}
        payloads = []
        with patch(
            "depictio.api.v1.services.advanced_viz.data.load_tidy_columns",
            return_value=tidy,
        ):
            for index in ("cmp-1", "cmp-2"):
                component = _component(
                    "advanced_viz", viz_kind="volcano", config={"feature_id_col": "gene"}
                )
                component["index"] = index
                payloads.append(await _build(component))

        keys = [next(iter(p["data"]["advancedVizData"])) for p in payloads]
        assert keys[0] != keys[1]
        assert keys == ["embed::cmp-1", "embed::cmp-2"]

    @pytest.mark.asyncio
    async def test_phylogenetic_tree_dc_gets_its_own_key(self) -> None:
        """The tree lives in a different DC named inside config, not metadata.dc_id."""
        component = _component(
            "advanced_viz",
            viz_kind="phylogenetic",
            config={"tree_dc_id": "507f1f77bcf86cd799439033", "tip_id_col": "tip"},
        )
        with (
            patch(
                "depictio.api.v1.endpoints.advanced_viz_endpoints.routes.get_phylogeny_newick",
                return_value="(a,b);",
            ),
            patch(
                "depictio.api.v1.services.advanced_viz.data.load_tidy_columns",
                return_value={"rows": {"tip": ["a"]}, "columns": ["tip"]},
            ),
        ):
            payload = await _build(component)

        tree_key = _synthetic_dc_id("cmp-1", "tree")
        assert payload["component"]["config"]["tree_dc_id"] == tree_key
        assert payload["data"]["advancedVizData"][f"{tree_key}::newick"] == "(a,b);"

    @pytest.mark.asyncio
    async def test_unsupported_type_is_rejected(self) -> None:
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc:
            await _build(_component("jbrowse"))
        assert exc.value.status_code == 422

    @pytest.mark.asyncio
    async def test_payload_carries_no_object_ids(self) -> None:
        """ObjectId is not JSON-serialisable and would blank the bundle."""
        from bson import ObjectId

        component = _component("text", extra_oid=ObjectId())
        payload = await _build(component)
        assert not isinstance(payload["component"]["extra_oid"], ObjectId)


class TestAdvancedVizColumnDiscovery:
    def test_collects_singular_and_plural_bindings(self) -> None:
        config = {
            "feature_id_col": "gene",
            "rank_cols": ["phylum", "genus"],
            "label_col": None,
            "top_n": 20,
        }
        assert _advanced_viz_columns(config) == ["gene", "phylum", "genus"]

    def test_deduplicates(self) -> None:
        assert _advanced_viz_columns({"x_col": "a", "y_col": "a"}) == ["a"]

    def test_ignores_non_binding_keys(self) -> None:
        assert _advanced_viz_columns({"threshold": 0.05, "viz_kind": "volcano"}) == []


class TestBundleInjection:
    def test_sentinel_is_substituted(self, tmp_path) -> None:
        template = tmp_path / "b.html"
        template.write_text(f"<html>{EMBED_SENTINEL}</html>")
        html = inject(template, EMBED_SENTINEL, {"a": 1})
        assert EMBED_SENTINEL not in html
        assert '{"a": 1}' in html

    def test_missing_bundle_names_the_build_command(self, tmp_path) -> None:
        with pytest.raises(OfflineBundleError) as exc:
            inject(tmp_path / "nope.html", EMBED_SENTINEL, {}, build_hint="pnpm run build:embed")
        assert "pnpm run build:embed" in str(exc.value)

    def test_absent_sentinel_is_an_error_not_a_silent_no_op(self, tmp_path) -> None:
        """A bundle without the sentinel would serve an empty page forever."""
        template = tmp_path / "b.html"
        template.write_text("<html>no placeholder here</html>")
        with pytest.raises(OfflineBundleError) as exc:
            inject(template, EMBED_SENTINEL, {})
        assert "diverged" in str(exc.value)

    def test_closing_script_tag_is_escaped(self) -> None:
        """Otherwise the payload terminates its own <script> element early."""
        encoded = encode_payload({"html": "</script><script>alert(1)</script>"})
        assert "</script>" not in encoded
        assert "<\\/script>" in encoded

    def test_non_finite_floats_become_null(self) -> None:
        """JSON.parse rejects the bare NaN/Infinity tokens Python emits."""
        assert json_safe({"a": float("nan"), "b": float("inf"), "c": 1.5}) == {
            "a": None,
            "b": None,
            "c": 1.5,
        }

    def test_numpy_arrays_are_converted_not_stringified(self) -> None:
        numpy = pytest.importorskip("numpy")
        assert json_safe({"x": numpy.array([1, 2])}) == {"x": [1, 2]}

    def test_script_hashes_cover_inline_scripts_only(self) -> None:
        html = (
            '<script src="/x.js"></script>'
            "<script>console.log(1)</script>"
            "<script>console.log(2)</script>"
        )
        assert len(_script_hashes(html)) == 2

    def test_script_hashes_are_stable(self) -> None:
        html = "<script>console.log(1)</script>"
        assert _script_hashes(html) == _script_hashes(html)
