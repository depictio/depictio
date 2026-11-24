"""A catalog chart must not preview in one colour or on one category.

The catalog gallery and the editor's picker draw every render on its committed
fixture. A render that colours by a column the fixture holds once (one lane, one
sample, one condition) draws a single colour, and a bar or box split by a column
with one value draws a single bar: the render looks wrong although its binding is
right. RULES.md §7 asks for colour by data; this keeps the fixtures able to show it.

A render whose column is constant by design says so with a `# C1 N/A` comment
above it (or inside it) in the output YAML, and is exempt.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from depictio.models.components.advanced_viz.catalog import load_catalog_entries

# Roles that colour or split a chart, in the order a kind would use them.
_COLOUR_ROLES = (
    "color",
    "category",
    "series",
    "group",
    "sample",
    "class",
    "taxon",
    "contrast",
    "cluster",
    "mutation_type",
    "partner",
    "colour_by",
    "sample_id",
)


def _c1_na(source: Path | None, index: int) -> bool:
    """True when render `index` of `source` carries a `C1 N/A` comment."""
    if source is None:
        return False
    n, pending, in_renders = -1, False, False
    for line in source.read_text().splitlines():
        if line.startswith("renders_as:"):
            in_renders = True
            continue
        if not in_renders:
            continue
        if re.match(r"\s{2}- ", line):
            n += 1
            if n == index and pending:
                return True
            pending = False
        if "C1 N/A" in line:
            if n == index and not re.match(r"\s{2}#", line):
                return True
            pending = True
    return False


def _cases():
    for entry in load_catalog_entries():
        for output in entry.outputs:
            for i, render in enumerate(output.renders_as):
                if render.component not in ("figure", "advanced_viz") or render.code:
                    continue
                yield entry, output, i, render


def test_every_chart_previews_more_than_one_colour_or_category():
    from depictio.catalog.payload import _load_fixture_df

    flat: list[str] = []
    for entry, output, i, render in _cases():
        try:
            df = _load_fixture_df(output)
        except Exception:  # noqa: BLE001 — fixture readability has its own test
            continue
        if df is None:
            continue
        columns: list[tuple[str, str]] = []
        if render.component == "figure":
            if render.dict_kwargs.get("color"):
                columns.append(("colour", render.dict_kwargs["color"]))
            if render.visu_type in ("bar", "box") and render.dict_kwargs.get("x"):
                columns.append(("category", render.dict_kwargs["x"]))
        else:
            col = next(
                (render.roles[k] for k in _COLOUR_ROLES if isinstance(render.roles.get(k), str)),
                None,
            ) or (render.config or {}).get("color_col")
            if col:
                columns.append(("colour", col))
        for what, col in columns:
            if col in df.columns and df[col].n_unique() <= 1:
                if not _c1_na(getattr(output, "_source_file", None), i):
                    flat.append(f"{entry.id}/{output.id}#{i}: {what} column {col!r} has one value")
    assert flat == [], "charts that preview in one colour or one category:\n" + "\n".join(flat)


# A column naming samples (or what stands for them: libraries, callsets, assemblies,
# tumours). A chart that draws one bar, box, line or point per sample needs several
# of them to show what it compares; see depictio/catalog/ENRICHED_FIXTURES.md.
_SAMPLE_AXIS = re.compile(
    r"(^|_)(samples?|sample_id|sample_name|library|callset|assembly|tumou?r)($|_)", re.I
)
_MIN_SAMPLES = 3
# Real reports kept as they are: growing them would mean editing a tool's own output.
_REAL_REPORTS = {"multiqc_mirtrace_composition"}


def test_every_sample_axis_previews_several_samples():
    from depictio.catalog.payload import _load_fixture_df

    thin: list[str] = []
    for entry, output, i, render in _cases():
        if output.id in _REAL_REPORTS:
            continue
        try:
            df = _load_fixture_df(output)
        except Exception:  # noqa: BLE001 — fixture readability has its own test
            continue
        if df is None:
            continue
        if render.component == "figure":
            keys = ("x", "y", "color", "facet_col", "facet_row")
            values = [render.dict_kwargs.get(k) for k in keys]
        else:
            values = list((render.roles or {}).values())
        bound = {v for v in values if isinstance(v, str)}
        for col in sorted(c for c in bound if _SAMPLE_AXIS.search(c)):
            if col in df.columns and df[col].n_unique() < _MIN_SAMPLES:
                if not _c1_na(getattr(output, "_source_file", None), i):
                    thin.append(
                        f"{entry.id}/{output.id}#{i}: {col!r} has {df[col].n_unique()} value(s)"
                    )
    assert thin == [], f"charts previewing fewer than {_MIN_SAMPLES} samples:\n" + "\n".join(thin)


@pytest.mark.parametrize("probe", ["  # C1 N/A: pooled row\n  - {component: figure}\n"])
def test_a_c1_na_comment_exempts_the_render_below_it(tmp_path, probe):
    f = tmp_path / "o.yaml"
    f.write_text("id: o\nrenders_as:\n" + probe)
    assert _c1_na(f, 0)
    assert not _c1_na(f, 1)
