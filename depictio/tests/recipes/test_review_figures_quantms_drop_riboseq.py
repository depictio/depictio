"""The code figures redrawn after the live review of quantms, drop and riboseq.

Each runs in the server's sandbox on a small synthetic frame with the columns the
template's recipe writes, and the test reads what the reader would see: the colour keys,
the cut-off marker, the notes. The data is made up; no dataset value is asserted.
"""

from __future__ import annotations

from pathlib import Path

import polars as pl
import pytest
import yaml

from depictio.api.v1.services.figure.code_executor import SimpleCodeExecutor
from depictio.api.v1.services.figure.groups import code_group_globals

NF_CORE = Path(__file__).resolve().parents[2] / "projects" / "nf-core"


def _figure(template: str, index: str) -> tuple[str, dict]:
    doc = yaml.safe_load((NF_CORE / template / "dashboards" / "base.yaml").read_text())
    comps = list(doc["main_dashboard"].get("components", []))
    for tab in doc.get("tabs", []):
        comps += tab.get("components", [])
    comp = next(c for c in comps if c.get("index") == index)
    return comp["code_content"], doc["main_dashboard"]["category_colors"]


def _run(template: str, index: str, df: pl.DataFrame):
    code, colors = _figure(template, index)
    ok, fig, message = SimpleCodeExecutor().execute_code(
        code,
        df,
        code_group_globals({}, [], {k: v for k, v in colors.items() if isinstance(v, dict)}),
    )
    assert ok, message
    return fig


def test_quantms_pvalue_histogram_marks_the_cutoff_and_the_null_level() -> None:
    # A skew toward zero: 200 small p-values over a flat background of 800.
    small = [0.01] * 200
    flat = [(i + 0.5) / 800 for i in range(800)]
    fig = _run("quantms/1.1.1", "da-pvalue-histogram", pl.DataFrame({"p_value": small + flat}))
    names = [t.name for t in fig.data]
    assert names[:2] == ["p below 0.05", "p of 0.05 or more"]
    assert sum(fig.data[0].y) > 200  # the first bin is the p < 0.05 cut-off
    assert fig.data[0].marker.color != fig.data[1].marker.color
    assert "level if none changed" in names
    note = fig.layout.annotations[0].text
    assert "unchanged share" in note and "expected if none changed" in note


def test_quantms_detection_figure_leaves_complete_groups_to_the_note() -> None:
    df = pl.DataFrame(
        {
            "runs_detected": [4] * 90 + [3] * 6 + [2] * 3 + [1] * 1,
            "runs_total": [4] * 100,
            "peptide_support": ["4 or more peptides"] * 90 + ["1 peptide"] * 10,
        }
    )
    fig = _run("quantms/1.1.1", "prot-detection", df)
    bars = [t for t in fig.data if t.type == "bar"]
    assert sum(sum(b.y) for b in bars) == 10  # only the groups missed in some runs
    assert "90 of 100" in fig.layout.annotations[0].text


def test_riboseq_caller_agreement_bars_split_annotated_from_new() -> None:
    rows = [(1, 1, 1)] * 6 + [(1, 1, 0)] * 1 + [(1, 0, 1)] * 3 + [(1, 0, 0)] * 2 + [(0, 1, 0)] * 2
    df = pl.DataFrame(rows, schema=["ribotish", "ribocode", "annotated_cds"], orient="row")
    fig = _run("riboseq/2.0.0", "orf-caller-upset", df)
    assert {t.name for t in fig.data} == {"Annotated CDS", "Outside the annotated CDS"}
    notes = [a.text for a in fig.layout.annotations]
    assert len(notes) == 3 and all(n.endswith("% new") for n in notes)


@pytest.mark.parametrize(
    ("index", "directions"),
    [("ae-per-sample", ["over-expressed", "under-expressed"])],
)
def test_drop_hits_per_sample_are_coloured_by_direction(index: str, directions: list[str]) -> None:
    df = pl.DataFrame(
        {
            "sample": ["a", "a", "b", "b", "c"],
            "gene_name": ["G1", "G2", "G3", "G4", "G5"],
            "direction": [
                directions[0],
                directions[1],
                directions[0],
                directions[0],
                "not significant",
            ],
            "nominal": [True, True, True, True, False],
            "significant": [True, False, False, False, False],
        }
    )
    fig = _run("drop/1.0.0", index, df)
    assert {t.name for t in fig.data} == set(directions)
    assert "(1 called)" in " ".join(a.text for a in fig.layout.annotations)


def test_drop_strongest_genes_rank_by_samples_then_strength() -> None:
    df = pl.DataFrame(
        {
            "sample": ["a", "b", "a", "c"],
            "gene_name": ["G1", "G1", "G2", "G3"],
            "p_value": [0.04, 0.03, 0.001, 0.02],
            "abs_z_score": [2.0, 2.2, 4.0, 2.5],
            "neg_log10_p": [1.4, 1.52, 3.0, 1.7],
            "direction": ["over-expressed", "over-expressed", "under-expressed", "over-expressed"],
            "nominal": [True] * 4,
        }
    )
    fig = _run("drop/1.0.0", "ae-recurrent-genes", df)
    # Plotly Express already lists a horizontal bar's first category on top; the
    # axis must not be reversed again, or the strongest gene lands at the bottom.
    assert fig.layout.yaxis.autorange != "reversed"
    order = list(fig.layout.yaxis.categoryarray)[::-1]
    assert order[0] == "G1"  # two samples beat the single, stronger hit of G2
    assert set(order) == {"G1", "G2", "G3"}
