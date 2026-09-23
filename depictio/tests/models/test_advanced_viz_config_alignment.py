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
from collections.abc import Iterator
from pathlib import Path
from typing import get_args, get_origin

import pytest
import yaml
from pydantic import TypeAdapter

from depictio.models.components.advanced_viz.configs import _KIND_ALIASES, VizConfig

REPO = Path(__file__).resolve().parents[3]
ADVANCED_VIZ = REPO / "packages" / "depictio-react-core" / "src" / "components" / "advanced_viz"
DISPATCH = ADVANCED_VIZ / "AdvancedVizDispatch.tsx"

# Legacy kind strings kept alive so old dashboards keep rendering. Each one has
# no model of its own: the backend rewrites it into the kind that survived it
# before the union discriminates (`_KIND_ALIASES` in configs.py), and the React
# dispatch keeps the old key so a `stored_metadata` blob, which reaches the
# client unvalidated, still finds a renderer.
#
# `ancombc_differentials` was collapsed into `da_barplot` and reuses its
# renderer; the four view merges each still have their own renderer until the
# survivor learns to draw the view (see the TODO(P4) comments in the dispatch).
LEGACY_KIND_ALIASES = {"ancombc_differentials"} | set(_KIND_ALIASES)


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


# ---------------------------------------------------------------------------
# Registry reachability
# ---------------------------------------------------------------------------
#
# A kind that no catalog output and no shipped dashboard binds is a kind nobody
# can see. Several were added that way: registered across the seven
# touchpoints, given a renderer, and then never bound, so the only proof they
# work was the author's local stack. This test makes "can a user reach it?" a
# CI question, with two named escapes: a retired kind (rewritten into another
# at read time, so it is reachable through the survivor) and an INCUBATING one
# (kept on purpose with its reason written down next to it).


def _catalog_kinds() -> set[str]:
    """Kinds bound by a catalog `renders_as` entry.

    Parsed through the catalog models rather than by grepping the YAML: the
    models are what decides whether a `renders_as` entry is an advanced_viz one
    at all, and a regex over `kind:` also picks up figure and card entries.
    """
    from depictio.models.components.advanced_viz.catalog import load_catalog_entries

    return {
        render.kind
        for entry in load_catalog_entries()
        for output in entry.outputs
        for render in (output.renders_as or [])
        if getattr(render, "component", None) == "advanced_viz" and render.kind
    }


def _walk(node: object) -> "Iterator[dict]":
    """Every dict inside a parsed YAML document, at any depth."""
    if isinstance(node, dict):
        yield node
        for value in node.values():
            yield from _walk(value)
    elif isinstance(node, list):
        for value in node:
            yield from _walk(value)


def _dashboard_yaml_kinds() -> set[str]:
    """Kinds bound by a shipped dashboard YAML.

    Reads `viz_kind` wherever it appears rather than assuming a component
    layout, because the shipped dashboards nest components under tabs, sections
    and persistent sections, and the nesting has changed more than once.
    """
    kinds: set[str] = set()
    for path in sorted(REPO.glob("depictio/projects/**/dashboards/*.yaml")):
        doc = yaml.safe_load(path.read_text())
        for node in _walk(doc):
            kind = node.get("viz_kind")
            if isinstance(kind, str):
                kinds.add(kind)
    return kinds


def test_every_kind_is_reachable():
    """Every kind is bound by a catalog output or by a shipped dashboard."""
    from depictio.models.components.advanced_viz.schemas import INCUBATING
    from depictio.models.components.types import AdvancedVizKind

    declared = set(get_args(AdvancedVizKind))
    reachable = _catalog_kinds() | _dashboard_yaml_kinds()
    unreachable = sorted(declared - reachable - LEGACY_KIND_ALIASES - set(INCUBATING))
    assert not unreachable, (
        f"kinds nobody can reach: {unreachable}. Bind each one from a catalog "
        f"output's `renders_as` or from a shipped dashboard YAML, or add it to "
        f"`INCUBATING` in schemas.py with the reason written next to it."
    )


def test_incubating_names_real_kinds():
    """`INCUBATING` is an escape from the test above, so it may not go stale.

    A name that no longer exists in `AdvancedVizKind` means a kind was renamed
    or removed and its exemption outlived it, which would silently exempt
    nothing while looking like it exempts something.
    """
    from depictio.models.components.advanced_viz.schemas import INCUBATING
    from depictio.models.components.types import AdvancedVizKind

    unknown = sorted(set(INCUBATING) - set(get_args(AdvancedVizKind)))
    assert not unknown, f"INCUBATING names kinds that do not exist: {unknown}"


def test_retired_kinds_resolve_to_a_live_kind():
    """Each alias points at a kind the union can actually build.

    The alias table is the whole backward-compatibility story for the four
    retired kinds, so a typo in it turns every stored `ma` tile into a
    validation error rather than into a volcano.
    """
    for old_kind, (survivor, overrides) in _KIND_ALIASES.items():
        assert old_kind not in KIND_MODELS, f"{old_kind} is both retired and in the union"
        assert survivor in KIND_MODELS, f"{old_kind} resolves to unknown kind {survivor}"
        model = KIND_MODELS[survivor]
        for key in overrides:
            assert key in model.model_fields, (
                f"{old_kind} -> {survivor}: override {key!r} has no field on {model.__name__}"
            )
        # The rewrite has to produce something the union validates, from the
        # bare minimum a stored config carries.
        cfg = VIZ_CONFIG.validate_python({"viz_kind": old_kind})
        assert cfg.viz_kind == survivor
        for key, value in overrides.items():
            assert getattr(cfg, key) == value
