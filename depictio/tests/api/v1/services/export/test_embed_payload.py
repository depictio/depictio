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
    _companion_dc_ids,
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
        assert "tabs" not in payload

    @pytest.mark.asyncio
    async def test_a_text_with_tab_links_carries_its_tab_family(self) -> None:
        family = [
            {"dashboard_id": "d1", "title": "Run", "main_tab_name": "Overview"},
            {
                "dashboard_id": "d2",
                "parent_dashboard_id": "d1",
                "title": "QC",
                "tab_icon": "mdi:check",
            },
        ]
        with patch(
            "depictio.api.v1.endpoints.dashboards_endpoints.routes._resolve_tab_family",
            return_value=("d1", family),
        ):
            payload = await _build(_component("text", body="See [QC](tab:QC)."))
        assert payload["tabs"] == family

    @pytest.mark.asyncio
    async def test_a_tab_family_the_caller_may_not_read_is_left_out(self) -> None:
        from fastapi import HTTPException

        with patch(
            "depictio.api.v1.endpoints.dashboards_endpoints.routes._resolve_tab_family",
            side_effect=HTTPException(status_code=403),
        ):
            payload = await _build(_component("text", body="See [QC](tab:QC)."))
        assert "tabs" not in payload

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
    async def test_phylogenetic_tip_metadata_is_read_from_its_own_collection(self) -> None:
        """The renderer asks for `metadata_dc_id`; the component's own DC may be
        the tree, which has no rows (it answered 404 and took the page down)."""
        component = _component(
            "advanced_viz",
            viz_kind="phylogenetic",
            config={
                "tree_dc_id": "507f1f77bcf86cd799439033",
                "metadata_wf_id": "507f1f77bcf86cd799439066",
                "metadata_dc_id": "507f1f77bcf86cd799439044",
                "taxon_col": "taxon",
                "color_col": "group",
            },
        )
        with (
            patch(
                "depictio.api.v1.endpoints.advanced_viz_endpoints.routes.get_phylogeny_newick",
                return_value="(a,b);",
            ),
            patch(
                "depictio.api.v1.services.advanced_viz.data.load_tidy_columns",
                return_value={"rows": {"taxon": ["a"], "group": ["x"]}},
            ) as load,
        ):
            payload = await _build(component)

        assert [c.kwargs["dc_id"] for c in load.call_args_list] == ["507f1f77bcf86cd799439044"]
        assert "507f1f77bcf86cd799439044" in payload["data"]["advancedVizData"]

    @pytest.mark.asyncio
    async def test_a_precomputed_embedding_ships_rows_and_a_live_one_a_compute(self) -> None:
        rows = {"rows": {"sample_id": ["s1"], "dim_1": [0.1], "dim_2": [0.2]}}
        precomputed = _component(
            "advanced_viz",
            viz_kind="embedding",
            config={"sample_id_col": "sample_id", "dim_1_col": "dim_1", "dim_2_col": "dim_2"},
        )
        live = _component(
            "advanced_viz",
            viz_kind="embedding",
            config={"sample_id_col": "sample_id", "compute_method": "umap"},
        )
        with (
            patch(
                "depictio.api.v1.services.advanced_viz.data.load_tidy_columns",
                return_value=rows,
            ),
            patch(
                "depictio.api.v1.services.export.compute.run_compute",
                return_value={"sample_ids": ["s1"], "dim_1": [0.1], "dim_2": [0.2]},
            ) as compute,
        ):
            pre = await _build(precomputed)
            assert compute.call_count == 0, "a precomputed embedding runs no dim-reduction"
            assert pre["data"]["advancedVizData"]["embed::cmp-1"] == rows

            on = await _build(live)
        assert compute.call_count == 1
        assert on["data"]["compute"]["embed::cmp-1"]["sample_ids"] == ["s1"]

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


HITS_WF = "507f1f77bcf86cd799439081"
HITS_DC = "507f1f77bcf86cd799439082"
DOMAINS_DC = "507f1f77bcf86cd799439083"
VARIANTS_DC = "507f1f77bcf86cd799439084"
STRUCTURE_DC = "507f1f77bcf86cd799439085"
PAE_DC = "507f1f77bcf86cd799439086"
MAIN_DC = "507f1f77bcf86cd799439055"

LOGO_CONFIG = {
    "profile_source": "hmm",
    "entity_col": "entity",
    "position_col": "position",
    "model_col": "hmm_name",
    "state_col": "hmm_position",
    "letter_col": "hmm_letter",
    "emission_col": "emission",
    "hits_wf_id": HITS_WF,
    "hits_dc_id": HITS_DC,
    "hits_model_col": "label",
    "hits_entity_col": "entity",
    "hits_from_col": "hmm_from",
    "hits_to_col": "hmm_to",
    "hits_evalue_col": "i_evalue",
}

PROFILE_ROWS = {
    "rows": {
        "entity": ["P1", "P1"],
        "hmm_name": ["PF1", "PF1"],
        "hmm_position": [1, 2],
        "hmm_letter": ["A", "C"],
        "emission": [0.7, 0.3],
    }
}
HITS_ROWS = {
    "rows": {
        "entity": ["Q1", "Q2"],
        "label": ["PF1", "PF1"],
        "hmm_from": [1, 2],
        "hmm_to": [30, 28],
        "i_evalue": [1e-9, 1e-4],
    }
}


def _dc_types(**by_dc_id: str | None):
    """A stand-in for the lookup of a collection's type; unknown ids are not found."""
    return patch(
        "depictio.api.v1.deltatables_utils._get_dc_type_from_db",
        side_effect=lambda oid: by_dc_id.get(str(oid)),
    )


def _tidy(**rows_by_dc_id):
    """A stand-in for the data route that answers per collection (or raises)."""

    def load(**kwargs):
        rows = rows_by_dc_id.get(kwargs["dc_id"])
        if isinstance(rows, Exception):
            raise rows
        return rows if rows is not None else {"rows": {}}

    return patch("depictio.api.v1.services.advanced_viz.data.load_tidy_columns", side_effect=load)


class TestTableCompanions:
    """A tile reads some tables beside its own; the offline shim answers by dc_id alone."""

    @pytest.mark.asyncio
    async def test_a_logo_export_carries_its_hits_rows(self) -> None:
        component = _component("advanced_viz", viz_kind="hmm_logo", config=dict(LOGO_CONFIG))
        with (
            _dc_types(**{HITS_DC: "table"}),
            _tidy(**{MAIN_DC: PROFILE_ROWS, HITS_DC: HITS_ROWS}) as load,
        ):
            payload = await _build(component)

        shipped = payload["data"]["advancedVizData"]
        assert shipped[_synthetic_dc_id("cmp-1")] == PROFILE_ROWS
        # The renderer asks for `hits_dc_id` as the config states it ...
        assert payload["component"]["config"]["hits_dc_id"] == HITS_DC
        # ... so that is the key, and the rows are the hits.
        assert shipped[HITS_DC] == HITS_ROWS
        hits_call = next(c for c in load.call_args_list if c.kwargs["dc_id"] == HITS_DC)
        assert hits_call.kwargs["wf_id"] == HITS_WF
        assert hits_call.kwargs["viz_kind"] == "hmm_logo"
        assert {"label", "hmm_from", "hmm_to", "i_evalue"} <= set(hits_call.kwargs["columns"])

    @pytest.mark.asyncio
    async def test_indexed_file_companions_are_left_out(self) -> None:
        """Structures and PAE matrices are objects fetched from storage: the data
        route has no rows for them (404), and the kinds that read them cannot go
        offline anyway (`HTML_UNAVAILABLE_KINDS`)."""
        component = _component(
            "advanced_viz",
            viz_kind="hmm_logo",
            config={**LOGO_CONFIG, "structure_dc_id": STRUCTURE_DC, "pae_dc_id": PAE_DC},
        )
        with (
            _dc_types(**{HITS_DC: "table", STRUCTURE_DC: "indexed_file", PAE_DC: "indexed_file"}),
            _tidy(**{HITS_DC: HITS_ROWS}) as load,
        ):
            payload = await _build(component)

        asked = [c.kwargs["dc_id"] for c in load.call_args_list]
        assert STRUCTURE_DC not in asked
        assert PAE_DC not in asked
        assert HITS_DC in payload["data"]["advancedVizData"]
        assert STRUCTURE_DC not in payload["data"]["advancedVizData"]

    @pytest.mark.asyncio
    async def test_a_sequence_track_carries_its_domains_and_variants(self) -> None:
        component = _component(
            "advanced_viz",
            viz_kind="sequence_track",
            config={
                "entity_col": "entity",
                "position_col": "position",
                "domains_dc_id": DOMAINS_DC,
                "domain_start_col": "start",
                "domain_end_col": "end",
                "domain_label_col": "label",
                "variants_wf_id": HITS_WF,
                "variants_dc_id": VARIANTS_DC,
                "variant_position_col": "position",
            },
        )
        domains = {"rows": {"entity": ["P1"], "start": [3], "end": [40], "label": ["Kinase"]}}
        variants = {"rows": {"entity": ["P1"], "position": [7], "ref_aa": ["A"], "alt_aa": ["V"]}}
        with (
            _dc_types(**{DOMAINS_DC: "table", VARIANTS_DC: "TABLE"}),
            _tidy(**{DOMAINS_DC: domains, VARIANTS_DC: variants}) as load,
        ):
            payload = await _build(component)

        shipped = payload["data"]["advancedVizData"]
        assert shipped[DOMAINS_DC] == domains
        assert shipped[VARIANTS_DC] == variants
        by_dc = {c.kwargs["dc_id"]: c.kwargs for c in load.call_args_list}
        # Read by a fixed name, so no `*_col` key would have asked for them.
        assert "source" in by_dc[DOMAINS_DC]["columns"]
        assert {"ref_aa", "alt_aa"} <= set(by_dc[VARIANTS_DC]["columns"])
        assert "ref_aa" not in by_dc[DOMAINS_DC]["columns"]
        # The companion's workflow is its own where the config names one.
        assert by_dc[VARIANTS_DC]["wf_id"] == HITS_WF
        assert by_dc[DOMAINS_DC]["wf_id"] == "507f1f77bcf86cd799439066"

    @pytest.mark.asyncio
    async def test_a_companion_that_cannot_be_read_costs_its_lane_not_the_export(self) -> None:
        from fastapi import HTTPException

        component = _component("advanced_viz", viz_kind="hmm_logo", config=dict(LOGO_CONFIG))
        with (
            _dc_types(**{HITS_DC: "table"}),
            _tidy(
                **{
                    MAIN_DC: PROFILE_ROWS,
                    HITS_DC: HTTPException(status_code=404, detail="no Delta table"),
                }
            ),
        ):
            payload = await _build(component)

        shipped = payload["data"]["advancedVizData"]
        assert shipped[_synthetic_dc_id("cmp-1")] == PROFILE_ROWS
        assert HITS_DC not in shipped

    @pytest.mark.asyncio
    async def test_a_collection_that_is_not_a_table_is_left_out(self) -> None:
        component = _component("advanced_viz", viz_kind="hmm_logo", config=dict(LOGO_CONFIG))
        for other in (None, "multiqc"):
            with _dc_types(**{HITS_DC: other}), _tidy(**{HITS_DC: HITS_ROWS}) as load:
                payload = await _build(component)
            assert HITS_DC not in payload["data"]["advancedVizData"]
            assert HITS_DC not in [c.kwargs["dc_id"] for c in load.call_args_list]


class TestCompanionDiscovery:
    def test_every_dc_id_key_but_the_ones_with_their_own_path(self) -> None:
        config = {
            "hits_dc_id": "h",
            "hits_wf_id": "hw",
            "msa_dc_id": "m",
            "tree_dc_id": "t",
            "ma_dc_id": "ma",
            "matrix_dc_id": "mx",
            "pae_dc_tag": "a-tag-names-no-id",
            "variants_dc_id": None,
        }
        assert _companion_dc_ids(config) == {"h": ("hw", []), "m": (None, [])}

    def test_a_collection_named_twice_is_listed_once_with_both_fixed_column_sets(self) -> None:
        found = _companion_dc_ids(
            {"domains_dc_id": "x", "variants_dc_id": "x", "variants_wf_id": "w"}
        )
        assert found == {"x": ("w", ["source", "ref_aa", "alt_aa"])}


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


class TestEmbedCsp:
    """The embed renders the viewer's own renderers, so it needs what they need."""

    def test_webgl_and_workers_are_allowed(self) -> None:
        from depictio.api.v1.services.export.embed import build_embed_csp

        csp = build_embed_csp()
        assert "'unsafe-eval'" in csp, "Plotly's WebGL traces compile at runtime"
        assert "worker-src blob:" in csp, "maplibre parses tiles in blob: workers"

    def test_only_a_map_may_reach_the_network_and_only_the_basemaps(self) -> None:
        from depictio.api.v1.configs.security_headers import BASEMAP_CONNECT_SRC
        from depictio.api.v1.services.export.embed import build_embed_csp

        assert "connect-src 'none'" in build_embed_csp()
        assert f"connect-src {BASEMAP_CONNECT_SRC};" in build_embed_csp(basemaps=True)
