"""AdvancedViz component model (lite + full).

Lite is YAML-friendly. Full adds runtime fields (resolved IDs, dc_config,
cached columns). Both store the per-kind config in a discriminated-union
field; ``viz_kind`` at the top level mirrors ``config.viz_kind`` and is
enforced consistent by a validator.
"""

from __future__ import annotations

import uuid
from typing import Any, Literal

from pydantic import Field, model_validator

from depictio.models.components.advanced_viz.configs import VizConfig
from depictio.models.components.lite import BaseLiteComponent
from depictio.models.components.types import AdvancedVizKind


class AdvancedVizLiteComponent(BaseLiteComponent):
    """User-definable advanced visualisation component.

    Example YAML:
        - tag: volcano-1
          component_type: advanced_viz
          workflow_tag: nf-core/ampliseq
          data_collection_tag: ancombc_volcano
          viz_kind: volcano
          config:
            viz_kind: volcano
            feature_id_col: feature_id
            effect_size_col: effect_size
            significance_col: significance
            significance_threshold: 0.05
            effect_threshold: 1.0
    """

    component_type: Literal["advanced_viz"] = "advanced_viz"

    # Optional catalog reference. ``use: <tool>/<output>`` (e.g.
    # ``mosdepth/genome_coverage``) is expanded at load time into ``viz_kind``
    # + ``config`` from the catalog output's advanced_viz ``renders_as`` entry
    # (role→column mapping). See ``_expand_catalog_use``. When an output
    # renders more than one advanced_viz kind, set ``viz_kind`` to pick one.
    use: str | None = Field(
        default=None,
        description="Catalog output ref '<tool>/<output>' to inherit viz_kind + role bindings",
    )

    # Top-level viz_kind mirrors config.viz_kind. Convenient for lookups and
    # for the outer dispatch in the React renderer without unwrapping config.
    viz_kind: AdvancedVizKind = Field(..., description="Advanced viz kind")

    # Per-kind configuration. Pydantic discriminates by config.viz_kind.
    config: VizConfig = Field(
        ..., description="Per-kind configuration (column bindings + display defaults)"
    )

    @model_validator(mode="before")
    @classmethod
    def _expand_catalog_use(cls, data: Any) -> Any:
        """Expand ``use: <tool>/<ref>`` into ``viz_kind`` + ``config``.

        Delegates to the shared :func:`resolve_use` (which also serves the other
        component kinds). For advanced_viz, ``<ref>`` resolves as a render id
        first (``use: ivar/manhattan``) then an output id (+ ``viz_kind`` to
        disambiguate); each declared role becomes a ``<role>_col`` config field
        and a user-supplied ``config`` overrides the inherited bindings. Runs
        before the legacy-kind rewrite and before union discrimination.
        """
        if not isinstance(data, dict) or not data.get("use"):
            return data

        # Lazy import: avoids a module-load cycle (catalog_use ← catalog ← models).
        from depictio.models.components.catalog_use import resolve_use

        # This class only renders advanced_viz, so hint the resolver to pick the
        # advanced_viz render of an output (component_type isn't in the raw dict
        # yet — it's a class default applied after this before-validator).
        return resolve_use({"component_type": "advanced_viz", **data})

    @model_validator(mode="before")
    @classmethod
    def _rewrite_legacy_kinds(cls, data: Any) -> Any:
        """Rewrite removed/renamed viz_kind strings before discrimination.

        ``ancombc_differentials`` was collapsed into ``da_barplot`` with a new
        ``contrast_view`` field. Persisted dashboards carrying the legacy kind
        are transparently rewritten here: the kind is renamed and the original
        contrast (if the renderer had a single-contrast view stored) becomes
        ``contrast_view`` so the user lands on the same panel they last saw.
        Any other ANCOM-BC-specific extras (``significance_threshold``,
        ``top_n``, ``label_col``) carry over unchanged via the shared schema.
        """
        if not isinstance(data, dict):
            return data
        cfg = data.get("config") if isinstance(data.get("config"), dict) else None
        rewritten = False
        if data.get("viz_kind") == "ancombc_differentials":
            data = {**data, "viz_kind": "da_barplot"}
            rewritten = True
        if cfg is not None and cfg.get("viz_kind") == "ancombc_differentials":
            new_cfg = {**cfg, "viz_kind": "da_barplot"}
            # Preserve any persisted single-contrast selection. ANCOMBC's
            # dropdown state was never serialised on the config, so default to
            # "all" — the user can switch tabs in-app.
            new_cfg.setdefault("contrast_view", "all")
            data = {**data, "config": new_cfg}
            rewritten = True
        if rewritten:
            # Make sure top-level and nested viz_kind agree after rewrite so
            # the post-validator below doesn't fire spuriously.
            data["viz_kind"] = "da_barplot"
        return data

    @model_validator(mode="after")
    def _kind_matches_config(self) -> "AdvancedVizLiteComponent":
        if self.viz_kind != self.config.viz_kind:
            raise ValueError(
                f"viz_kind={self.viz_kind!r} does not match config.viz_kind={self.config.viz_kind!r}"
            )
        return self


class AdvancedVizComponent(AdvancedVizLiteComponent):
    """Runtime advanced viz component with resolved data-source IDs."""

    # Override to auto-generate UUID
    index: str = Field(default_factory=lambda: str(uuid.uuid4()))

    # Override to be optional (resolved at runtime)
    workflow_tag: str | None = None
    data_collection_tag: str | None = None

    # Runtime: resolved IDs
    wf_id: str | None = None
    dc_id: str | None = None
    project_id: str | None = None

    # Runtime: full data collection config
    dc_config: dict[str, Any] = Field(default_factory=dict)

    # Runtime: column metadata (column_name -> polars dtype string)
    cols_json: dict[str, Any] = Field(default_factory=dict)

    # Runtime: parent reference (unused today but kept for parity with siblings)
    parent_index: str | None = None
