"""
Models for the project template system.

Templates allow users to reuse predefined project configurations (e.g., nf-core/ampliseq)
with their own data by providing a data root directory. The template system resolves
path variables like {DATA_ROOT} throughout the project config at runtime.

Key concepts:
- TemplateMetadata: Declared in template project.yaml, describes the template identity
- TemplateOrigin: Stored on Project model to track that a template was used
- TemplateVariable: A required variable (e.g., DATA_ROOT) with description
- TemplateConditional: Optional-variable rules for DC removal and dashboard selection
"""

from datetime import datetime
from typing import Any

from bson import ObjectId
from pydantic import BaseModel, Field, field_validator


def _require_nonempty(v: str, label: str) -> str:
    """Strip and validate that a string field is non-empty."""
    if not v or not v.strip():
        raise ValueError(f"{label} cannot be empty")
    return v.strip()


class TemplateVariable(BaseModel):
    """A variable required by a template (e.g., DATA_ROOT).

    Variables are declared in the template metadata section and must be provided
    by the user at template instantiation time (e.g., via --data-root CLI flag).
    """

    name: str = Field(..., description="Variable name (e.g., 'DATA_ROOT')")
    description: str = Field(..., description="Human-readable description of this variable")
    required: bool = Field(default=True, description="Whether this variable must be provided")

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        """Ensure variable name is non-empty and uppercase with underscores."""
        if not v or not v.strip():
            raise ValueError("Variable name cannot be empty")
        v = v.strip()
        if not all(c.isalnum() or c == "_" for c in v):
            raise ValueError(
                "Variable name must contain only alphanumeric characters and underscores"
            )
        return v


class DCOverride(BaseModel):
    """Repoint an existing DC's source binding when a route conditional fires.

    Lets a route IF (e.g. ``if_var_present: IS_NANOPORE``) point an existing DC at the
    route's divergent file layout *without duplicating the DC* — so downstream
    canonicals and dashboards that reference the tag keep working unchanged. Scan DCs
    override the scan regex / filename / format; recipe DCs override the recipe and/or
    its source globs/paths (see SourceOverride).

    Example YAML:
        override_dcs:
          - data_collection_tag: "mosdepth_genome_coverage"
            scan_pattern: "artic_minion/mosdepth/genome/all_samples.mosdepth.coverage.tsv"
          - data_collection_tag: "pangolin_lineages"
            source_overrides:
              pangolin_raw: {glob_pattern: "artic_minion/pangolin/*.pangolin.csv"}
    """

    data_collection_tag: str = Field(..., description="Tag of the DC to repoint")
    scan_pattern: str | None = Field(
        default=None, description="New scan regex_config.pattern (scan DCs)"
    )
    scan_filename: str | None = Field(
        default=None, description="New scan_parameters.filename (single-file scan DCs)"
    )
    format: str | None = Field(
        default=None, description="New dc_specific_properties.format (e.g. TSV/CSV)"
    )
    recipe: str | None = Field(default=None, description="New transform.recipe (recipe DCs)")
    source_overrides: dict[str, dict] | None = Field(
        default=None,
        description="Recipe source overrides: ref -> {path: ...} or {glob_pattern: ...}",
    )


class TemplateConditional(BaseModel):
    """A conditional rule applied during template resolution based on variable presence.

    Rules fire when the named optional variable is absent or present. Matching rules
    remove listed DCs (and links that reference them), repoint surviving DCs at a
    route's file layout (override_dcs), and override the dashboard list.

    Example YAML:
        conditional:
          - if_var_absent: "METADATA_FILE"
            remove_dc_tags: ["metadata", "ancombc_results"]
            dashboards: ["dashboards/base.yaml"]
          - if_var_present: "METADATA_FILE"
            dashboards: ["dashboards/base.yaml", "dashboards/extended.yaml"]
    """

    if_var_absent: str | None = Field(
        default=None,
        description="Variable name: rule fires when this variable is NOT provided",
    )
    if_var_present: str | None = Field(
        default=None,
        description="Variable name: rule fires when this variable IS provided",
    )
    remove_dc_tags: list[str] = Field(
        default_factory=list,
        description="DC tags to remove from all workflows when this rule fires",
    )
    override_dcs: list[DCOverride] = Field(
        default_factory=list,
        description="DC source-binding overrides applied to surviving DCs when this rule fires",
    )
    dashboards: list[str] = Field(
        default_factory=list,
        description="Dashboard paths to use when this rule fires (overrides template default)",
    )


class ProvenanceSource(BaseModel):
    """One file (or file family) the run's provenance is collected from.

    Declared in a template's ``template.provenance.sources``. Paths are globs
    relative to DATA_ROOT, so the same spec works for every instantiation of
    the pipeline. Reusable across pipelines: any template can point at its own
    params/versions/recap files, and the CLI's ``--provenance-file`` flag adds
    ad-hoc user files through the same machinery.
    """

    name: str = Field(..., description="Source label shown next to each entry (e.g. 'params')")
    glob: str = Field(..., description="Glob relative to DATA_ROOT (e.g. 'pipeline_info/params*.json')")
    format: str = Field(
        default="auto",
        description="File format: 'json', 'yaml', 'tsv' (2-column key/value) or 'auto' (by suffix)",
    )
    pick: str = Field(
        default="latest",
        description="When the glob matches several files: 'latest' (last in sorted order — "
        "nf-core timestamps sort chronologically), 'first', or 'all' (merged in order, later wins)",
    )
    exclude_keys: list[str] = Field(
        default_factory=list,
        description="fnmatch globs of keys to drop (e.g. '*_ref_databases' — bulky catalogs). "
        "The ONLY way an available key is omitted: everything else is kept, so the "
        "listing stays complete.",
    )
    group: str | None = Field(
        default=None,
        description="Assign every key of this source to one group (e.g. 'Software versions'), "
        "bypassing the group rules",
    )

    @field_validator("format")
    @classmethod
    def validate_format(cls, v: str) -> str:
        allowed = {"json", "yaml", "tsv", "auto"}
        if v not in allowed:
            raise ValueError(f"format must be one of {sorted(allowed)}, got {v!r}")
        return v

    @field_validator("pick")
    @classmethod
    def validate_pick(cls, v: str) -> str:
        allowed = {"latest", "first", "all"}
        if v not in allowed:
            raise ValueError(f"pick must be one of {sorted(allowed)}, got {v!r}")
        return v


class ProvenanceGroupRule(BaseModel):
    """Assigns keys matching any pattern to a named group, in declaration order.

    Keys no rule matches land in the catch-all 'Other' group — nothing is
    silently dropped.
    """

    group: str = Field(..., description="Group name shown as an accordion in the UI")
    key_patterns: list[str] = Field(
        ..., description="fnmatch globs matched against the flattened key (first match wins)"
    )


class ProvenanceSpec(BaseModel):
    """Template-declared recipe for collecting a run's provenance.

    Lives under ``template.provenance``. When a template has none, the CLI
    falls back to a default spec (nf-core ``pipeline_info/params*.json``,
    everything in one 'Parameters' group).
    """

    sources: list[ProvenanceSource] = Field(default_factory=list)
    groups: list[ProvenanceGroupRule] = Field(default_factory=list)
    highlight: list[str] = Field(
        default_factory=list,
        description="Keys surfaced inline in the dashboard Settings drawer (the full listing "
        "stays in the ingestion report)",
    )


class ProvenanceEntry(BaseModel):
    """One collected provenance fact: a parameter, threshold or tool version."""

    source: str = Field(..., description="ProvenanceSource name (or 'user' for --provenance-file)")
    group: str = Field(..., description="Group the key was assigned to")
    key: str = Field(..., description="Flattened key (nested files use dotted paths)")
    value: str = Field(..., description="Stringified value ('null' for unset params)")
    highlight: bool = Field(default=False, description="Listed in the spec's highlight set")


class TemplateMetadata(BaseModel):
    """Metadata section declared in a template project.yaml.

    This section is parsed from the top-level 'template' key in the YAML file.
    It describes the template identity and required variables.

    Example YAML:
        template:
          template_id: "nf-core/ampliseq/2.16.0"
          description: "nf-core/ampliseq microbial community analysis template"
          version: "1.0.0"
          variables:
            - name: "DATA_ROOT"
              description: "Root directory containing ampliseq output data"
              required: true
            - name: "METADATA_FILE"
              description: "Path to metadata TSV (optional)"
              required: false
          dashboards:
            - "dashboards/base.yaml"
          conditional:
            - if_var_absent: "METADATA_FILE"
              remove_dc_tags: ["metadata", "ancombc_results"]
              dashboards: ["dashboards/base.yaml"]
            - if_var_present: "METADATA_FILE"
              dashboards: ["dashboards/base.yaml", "dashboards/extended.yaml"]
    """

    template_id: str = Field(
        ..., description="Unique template identifier (e.g., 'nf-core/ampliseq/2.16.0')"
    )
    description: str = Field(..., description="Human-readable description of this template")
    version: str = Field(..., description="Template schema version (semver)")
    variables: list[TemplateVariable] = Field(
        default_factory=list, description="Variables required by this template"
    )
    dashboards: list[str] = Field(
        default_factory=list,
        description=(
            "Relative paths to dashboard YAML files bundled with this template "
            "(e.g., 'dashboards/base.yaml'). Imported automatically after "
            "project setup unless overridden via --dashboard CLI flag."
        ),
    )
    conditional: list[TemplateConditional] = Field(
        default_factory=list,
        description=(
            "Conditional rules applied during resolution based on optional variable presence. "
            "Each rule fires when its if_var_absent / if_var_present condition matches."
        ),
    )
    structure: str | None = Field(
        default=None,
        description="Data layout structure: 'flat' (files directly under DATA_ROOT) "
        "or 'sequencing-runs' (files under run directories matching runs_regex)",
    )
    runs_regex: str | None = Field(
        default=None,
        description="Regex pattern for run directory names (e.g., 'run_*'). "
        "Only used when structure='sequencing-runs'.",
    )
    provenance: ProvenanceSpec | None = Field(
        default=None,
        description="How to collect this pipeline's run provenance (params, thresholds, "
        "tool versions) — see ProvenanceSpec. None = the CLI's generic default.",
    )

    @field_validator("template_id")
    @classmethod
    def validate_template_id(cls, v: str) -> str:
        return _require_nonempty(v, "Template ID")

    @field_validator("version")
    @classmethod
    def validate_version(cls, v: str) -> str:
        return _require_nonempty(v, "Template version")

    def get_required_variable_names(self) -> list[str]:
        """Return names of all required variables."""
        return [var.name for var in self.variables if var.required]


class ExpectedDataCollection(BaseModel):
    """One entry in a project's frozen expected-DC manifest (see TemplateOrigin).

    Records the *full* template DC superset at resolution time — including DCs that
    were conditionally gated out — so the ingestion report can show what the template
    expected vs. what was actually identified, faithful to the template version used.
    """

    data_collection_tag: str = Field(..., description="DC tag as declared in the template")
    type: str | None = Field(
        default=None, description="DC type (table, multiqc, jbrowse2, ...) if known"
    )
    optional: bool = Field(default=False, description="False = required/mandatory; True = optional")
    included: bool = Field(
        default=True,
        description="Whether this DC survived conditional + missing-file pruning",
    )
    removal_reason: str | None = Field(
        default=None,
        description="Why an excluded DC was dropped "
        "(e.g. 'gated: METADATA_FILE absent (if_var_absent)')",
    )


class TemplateOrigin(BaseModel):
    """Stored on Project model to track that a template was used to create the project.

    This enables the DB and UI to distinguish template-instantiated projects from
    manually configured ones, and to show which template was used.
    """

    template_id: str = Field(
        ..., description="Template identifier (e.g., 'nf-core/ampliseq/2.16.0')"
    )
    template_version: str = Field(..., description="Template schema version at time of use")
    data_root: str = Field(..., description="The actual --data-root value provided by the user")
    applied_at: str = Field(
        default_factory=lambda: datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        description="Timestamp when template was applied",
    )
    variables: dict[str, str] = Field(
        default_factory=dict,
        description="Resolved template variables (DATA_ROOT, SAMPLESHEET_FILE, GROUP_COL, etc.)",
    )
    config_snapshot: dict[str, Any] = Field(
        default_factory=dict,
        description="Frozen copy of the resolved template config (for reproducibility)",
    )
    expected_data_collections: list[ExpectedDataCollection] = Field(
        default_factory=list,
        description="Full template DC superset at resolution time (required + optional), "
        "each marked included/excluded with a removal reason — drives the ingestion report",
    )
    run_provenance: list[ProvenanceEntry] = Field(
        default_factory=list,
        description="Collected run provenance (pipeline parameters, filtering thresholds, "
        "tool versions), grouped and ordered — drives the ingestion report's "
        "'Run provenance' card and the dashboard Settings highlights",
    )
    run_provenance_files: list[str] = Field(
        default_factory=list,
        description="The files the provenance was collected from (relative to data_root "
        "where possible)",
    )

    @field_validator("config_snapshot", mode="before")
    @classmethod
    def sanitize_objectids(cls, v: Any) -> Any:
        """Recursively convert bson ObjectId values to strings for JSON serialization."""

        def _convert(obj: Any) -> Any:
            if isinstance(obj, ObjectId):
                return str(obj)
            if isinstance(obj, dict):
                return {k: _convert(val) for k, val in obj.items()}
            if isinstance(obj, list):
                return [_convert(item) for item in obj]
            return obj

        return _convert(v)

    @field_validator("template_id")
    @classmethod
    def validate_template_id(cls, v: str) -> str:
        return _require_nonempty(v, "Template ID")

    @field_validator("data_root")
    @classmethod
    def validate_data_root(cls, v: str) -> str:
        return _require_nonempty(v, "Data root")
