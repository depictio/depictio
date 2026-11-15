"""Large-compute kinds in a bundle (RFC §13): contact_map live, group_compare frozen.

contact_map's windowing is ``contact_map_window`` (services/contact_map.py),
which the Celery task now calls after its load and the browser port is pinned
against (packages/depictio-static-core/fixtures/contact-map-expected.json).
group_compare freezes the pair its tile opens on.
"""

from __future__ import annotations

import polars as pl
import pytest

pytest.importorskip("fastapi")

from depictio.api.v1.services.contact_map import contact_map_window  # noqa: E402
from depictio.models.models.serverless import ComponentTier, TierReason  # noqa: E402
from depictio.serverless import producer_a  # noqa: E402
from depictio.serverless.computes import group_compare_opening_pair  # noqa: E402
from depictio.serverless.pruning import advanced_viz_columns, ships_frozen_inputs  # noqa: E402

GC = {
    "component_type": "advanced_viz",
    "viz_kind": "group_compare",
    "wf_id": "a" * 24,
    "dc_id": "b" * 24,
    "config": {"viz_kind": "group_compare", "index_col": "cell_id", "group_col": "cluster"},
}


def test_contact_map_window_matches_the_task_contract() -> None:
    df = pl.DataFrame(
        {
            "chrom": ["c1"] * 4,
            "start": [0, 0, 10, 0],
            "start2": [0, 10, 10, 0],
            "count": [5, 3, 2, 9],
            "resolution": [10, 10, 10, 20],
        }
    )
    payload = {
        "chrom1_col": "chrom",
        "start1_col": "start",
        "chrom2_col": "chrom",
        "start2_col": "start2",
        "count_col": "count",
        "chrom": "c1",
        "start": 0,
        "end": 20,
        "resolution": 10,
    }
    out = contact_map_window(df, payload, "resolution")
    assert out["row_count"] == 3
    assert out["summary"]["resolutions"] == [10, 20]
    assert out["summary"]["resolution"] == 10
    assert out["rows"]["count"] == [5, 3, 2]


def test_contact_map_bundles_its_resolution_column() -> None:
    comp = {
        "component_type": "advanced_viz",
        "viz_kind": "contact_map",
        "config": {"count_col": "n"},
    }
    assert "resolution" in advanced_viz_columns(comp)


@pytest.mark.parametrize(
    ("labels", "a", "b", "pair"),
    [
        (["c1", "c2", "c3"], "c3", "c1", ("c3", "c1")),
        (["c1", "c2", "c3"], None, None, ("c1", "c2")),
        (["c1", "c2", "c3"], "c2", "c2", ("c1", "c2")),
        (["c1", "c2", "c3"], "c9", "c1", ("c1", "c2")),
        (["c1"], None, None, None),
    ],
)
def test_group_compare_opening_pair(labels, a, b, pair) -> None:
    assert group_compare_opening_pair(labels, a, b) == pair


def test_group_compare_plans_frozen_and_ships_its_label_column() -> None:
    plan = producer_a.classify_stored_component(GC)
    assert plan.tier is ComponentTier.FROZEN
    assert plan.reason is TierReason.CELERY_COMPUTE
    assert ships_frozen_inputs(GC)
    assert producer_a.live_column_sets([GC]) == {"b" * 24: {"cell_id", "cluster"}}
    task, request = producer_a.celery_compute_request(GC)
    assert task == "group_compare_opening"
    assert request["group_col"] == "cluster"


def test_group_compare_freezes_the_opening_pair_and_opens_on_it(monkeypatch) -> None:
    class FakeDtu:
        @staticmethod
        def load_deltatable_lite(**kwargs):
            assert kwargs["select_columns"] == ["cluster"]
            return pl.DataFrame({"cluster": ["c2", "c1", "c2", "c3", None]})

    seen = {}

    class FakeCelery:
        @staticmethod
        def compute_group_compare(payload):
            seen.update(payload)
            return {"rows": [], "group_a": {"label": "c1", "n": 1}}

    monkeypatch.setattr(producer_a, "_dtu", lambda: FakeDtu)
    monkeypatch.setattr(producer_a, "_celery", lambda: FakeCelery)
    comp = {**GC, "config": dict(GC["config"])}
    payload, detail = producer_a.freeze_celery_compute(comp, producer_a.ComputeBudget(total=60))
    assert payload is not None
    assert seen["group_a"] == {"label": "c1", "column": "cluster", "values": ["c1"]}
    assert seen["group_b"]["label"] == "c2"
    assert "group_col" not in seen and "default_group_a" not in seen
    assert payload["request"]["group_b"]["values"] == ["c2"]
    assert "__request__" not in payload["result"]
    assert "c1 vs c2" in detail
    # The bundled tile opens on the frozen pair and runs it on mount.
    assert comp["config"]["default_group_a"] == "c1"
    assert comp["config"]["default_group_b"] == "c2"
    assert comp["config"]["auto_run"] is True
