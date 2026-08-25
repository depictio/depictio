"""Every config key an advanced-viz renderer touches must exist on its model.

The renderers are the only place that decides what a visualisation's settings
are, and `configs.py` is the only place that decides what may be stored. Nothing
kept the two in step: the save endpoint takes `stored_metadata` as an untyped
list, so a config carrying a key with no field is written happily and only
explodes much later, on an export, a re-import, or a `validate-dashboard`.

Four such keys had already drifted in by the time this test was written
(manhattan `top_n_labels`, coverage_track `view_mode`, upset
`default_annotation_cols`, and a complex_heatmap `index_col` that should have
been `index_column`). Persisting the settings a user changes makes that drift
easier, not harder, so the check belongs in CI rather than in a review habit.

The renderer sources are read directly. A manifest would be less clever and
would drift from the thing it claims to describe.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import get_args, get_origin

import pytest
from pydantic import TypeAdapter

from depictio.models.components.advanced_viz.configs import VizConfig

REPO = Path(__file__).resolve().parents[3]
ADVANCED_VIZ = REPO / "packages" / "depictio-react-core" / "src" / "components" / "advanced_viz"
DISPATCH = ADVANCED_VIZ / "AdvancedVizDispatch.tsx"

# `ancombc_differentials` is a legacy kind string kept alive so old dashboards
# keep rendering; it reuses da_barplot's renderer and has no model of its own.
LEGACY_KIND_ALIASES = {"ancombc_differentials"}

def _kind_to_model() -> dict[str, type]:
    """Derive kind -> config model from the discriminated union itself."""
    return {m.model_fields["viz_kind"].default: m for m in get_args(get_args(VizConfig)[0])}


def _kind_to_source() -> dict[str, Path]:
    """Parse the RENDERERS literal so this map cannot go stale."""
    src = DISPATCH.read_text()
    imports = dict(re.findall(r"^import\s+(\w+)\s+from\s+'\./(\w+)';", src, re.MULTILINE))
    table = re.search(r"const RENDERERS[^=]*=\s*\{(.*?)\n\};", src, re.DOTALL)
    assert table, "could not find the RENDERERS table in AdvancedVizDispatch.tsx"
    out: dict[str, Path] = {}
    for kind, component in re.findall(r"^\s*(\w+):\s*(\w+),", table.group(1), re.MULTILINE):
        module = imports.get(component, component)
        out[kind] = ADVANCED_VIZ / f"{module}.tsx"
    return out


def _code(path: Path) -> str:
    """Renderer source with comments removed.

    The scanners below look for `config.<key>` and for hook call sites, and
    prose mentions both. One renderer documents that "config.dim_*_col are
    undefined" in live-compute mode, which reads as a `dim_` key that no model
    has. Only full-line comments are dropped, so a `//` inside a string literal
    (a URL, say) cannot take a line of real code with it.
    """
    src = path.read_text()
    src = re.sub(r"/\*.*?\*/", "", src, flags=re.DOTALL)
    src = re.sub(r"^\s*//.*$", "", src, flags=re.MULTILINE)
    # Import lines name the hook without calling it, and mention config keys in
    # the module paths they resolve.
    return re.sub(r"^import .*$", "", src, flags=re.MULTILINE)


VIZ_CONFIG = TypeAdapter(VizConfig)
KIND_MODELS = _kind_to_model()
KIND_SOURCES = _kind_to_source()
CHECKED_KINDS = sorted(set(KIND_SOURCES) - LEGACY_KIND_ALIASES)


def test_every_dispatched_kind_has_a_model_and_a_source():
    """The three maps agree, so neither of the tests below can silently skip."""
    assert set(KIND_MODELS) == set(KIND_SOURCES) - LEGACY_KIND_ALIASES
    missing = [k for k, path in KIND_SOURCES.items() if not path.exists()]
    assert not missing, f"dispatch names renderers that do not exist: {missing}"


@pytest.mark.parametrize("kind", CHECKED_KINDS)
def test_renderer_only_reads_config_keys_the_model_declares(kind: str):
    model = KIND_MODELS[kind]
    reads = set(re.findall(r"\bconfig\.([a-z_][a-z0-9_]*)\b", _code(KIND_SOURCES[kind])))
    unknown = sorted(k for k in reads if k not in model.model_fields)
    assert not unknown, (
        f"{kind}: the renderer reads config keys with no field on "
        f"{model.__name__}: {unknown}. Add the field, or stop reading the key."
    )


@pytest.mark.parametrize("kind", CHECKED_KINDS)
def test_persisted_controls_survive_their_model(kind: str):
    """Every key written back through usePersistedVizControl must validate.

    `extra="forbid"` means a persisted key with no field does not merely go
    unvalidated, it makes the whole component unloadable. This is the check that
    catches it at the moment the control is wired up rather than on someone's
    export months later.
    """
    # A call is the identifier followed by a type argument or an open paren,
    # which is what separates it from a prose mention.
    body = _code(KIND_SOURCES[kind])
    calls = len(re.findall(r"\busePersistedVizControl\s*[<(]", body))
    keys = re.findall(r"usePersistedVizControl[^(]*\(\s*metadata,\s*'([a-z_0-9]+)'", body)
    assert len(keys) == calls, (
        f"{kind}: {calls} usePersistedVizControl call(s) but {len(keys)} parsed. "
        f"Keep `metadata` and the config key together on one line so this test "
        f"can see them."
    )
    model = KIND_MODELS[kind]
    unknown = sorted(k for k in keys if k not in model.model_fields)
    assert not unknown, (
        f"{kind}: persisted control keys with no field on {model.__name__}: {unknown}"
    )

    if not keys:
        return
    # A blob of every persisted key at its declared default, plus whatever the
    # model requires, must round-trip through the union.
    blob: dict[str, object] = {"viz_kind": kind}
    for name, field in model.model_fields.items():
        if field.is_required():
            blob[name] = ["a", "b"] if get_origin(field.annotation) is list else "col"
    for key in keys:
        default = model.model_fields[key].get_default(call_default_factory=True)
        if default is not None:
            blob[key] = default
    VIZ_CONFIG.validate_python(blob)
