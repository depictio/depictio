"""A builder draft, and the ad-hoc template it becomes.

The SPA keeps the user's work as a :class:`ProjectDraft`: workflows, each with
its data collections (a scan rule, a type and that type's properties). This
module turns it into a template in the shipped templates' own shape, every
location under ``{DATA_ROOT}``, so it resolves against a local folder and an
``s3://`` prefix alike (``resolve_template_config`` repoints a recursive scan
to ``s3_prefix`` under a remote root) and ``depictio ingest --template`` runs
the very same file.
"""

from __future__ import annotations

import re
from typing import Annotated, Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from depictio.cli.cli.utils.compose import slug

DATA_ROOT = "{DATA_ROOT}"
TEMPLATE_PREFIX = "custom"

_STRICT = ConfigDict(extra="forbid")


class TableProps(BaseModel):
    model_config = _STRICT
    kind: Literal["table"] = "table"
    format: str = "csv"
    separator: str | None = None
    columns_description: dict[str, str] | None = None


class MultiQCProps(BaseModel):
    model_config = _STRICT
    kind: Literal["multiqc"] = "multiqc"


class ImageProps(BaseModel):
    model_config = _STRICT
    kind: Literal["image"] = "image"
    format: str = "csv"
    separator: str | None = None
    image_column: str
    # Root-relative folder of the images, uploaded at ingest.
    local_images_path: str | None = None
    s3_base_folder: str | None = None


class IndexedFileProps(BaseModel):
    model_config = _STRICT
    kind: Literal["indexed_file"] = "indexed_file"
    format: str = "vcf"
    index_suffix: str | None = None
    sample_regex: str | None = None
    sample_col: str | None = None
    assembly: str | None = None
    max_file_size_mb: int | None = None


class GeoJSONProps(BaseModel):
    model_config = _STRICT
    kind: Literal["geojson"] = "geojson"
    feature_id_key: str = "id"


class PhylogenyProps(BaseModel):
    model_config = _STRICT
    kind: Literal["phylogeny"] = "phylogeny"
    format: Literal["newick", "nexus"] = "newick"
    ladderize: bool = True
    metadata_dc_tag: str | None = None
    metadata_taxon_column: str | None = None
    tip_label_strategy: Literal["taxon", "first_token"] | None = None


DcProps = Annotated[
    TableProps | MultiQCProps | ImageProps | IndexedFileProps | GeoJSONProps | PhylogenyProps,
    Field(discriminator="kind"),
]

DcType = Literal["table", "multiqc", "image", "indexed_file", "geojson", "phylogeny"]


class DcDraft(BaseModel):
    """One data collection as the builder edits it."""

    model_config = _STRICT
    tag: str = Field(min_length=1, max_length=128)
    description: str | None = None
    type: DcType
    mode: Literal["single", "recursive"]
    # single: the root-relative file
    path: str | None = None
    # recursive: the scan regex (the glob is the UI's, kept for display only)
    regex: str | None = None
    glob: str | None = None
    max_depth: int | None = Field(default=None, ge=0)
    ignore: list[str] = Field(default_factory=list)
    optional: bool = False
    props: DcProps

    @model_validator(mode="after")
    def _has_a_rule(self) -> DcDraft:
        if self.mode == "single" and not (self.path or "").strip("/"):
            raise ValueError("A single-file collection needs the file's path.")
        if self.mode == "recursive" and not (self.regex or self.path):
            raise ValueError("A scanning collection needs a regex.")
        return self


class CatalogRef(BaseModel):
    model_config = _STRICT
    name: Literal["nf-core", "workflowhub", "smk-wf-catalog"]
    url: str


class WorkflowDraft(BaseModel):
    model_config = _STRICT
    name: str = Field(min_length=1, max_length=128)
    engine: str = "python"
    engine_version: str | None = None
    version: str | None = None
    repository_url: str | None = None
    catalog: CatalogRef | None = None
    structure: Literal["flat", "sequencing-runs"] = "flat"
    runs_regex: str | None = None
    data_collections: list[DcDraft] = Field(default_factory=list)


class ProjectDraft(BaseModel):
    model_config = _STRICT
    name: str = Field(min_length=1, max_length=200)
    description: str | None = None
    is_public: bool = False
    realtime: bool = False
    workflows: list[WorkflowDraft] = Field(default_factory=list)


def template_id_for(name: str) -> str:
    """``custom/<slug>``: the id an ad-hoc template is recorded under."""
    return f"{TEMPLATE_PREFIX}/{slug(name, 64).replace('_', '-')}"


def under_root(rel: str | None) -> str:
    """A root-relative path written under ``{DATA_ROOT}``."""
    rel = (rel or "").strip("/")
    return f"{DATA_ROOT}/{rel}" if rel else DATA_ROOT


def exact_path_regex(rel: str) -> str:
    """A scan regex matching exactly the root-relative file ``rel``."""
    return "^" + re.escape(rel.strip("/")) + "$"


def scan_block(dc: DcDraft) -> dict[str, Any]:
    """The ``scan`` of a data collection, in template form.

    A MultiQC collection is always walked (its processor reads every report a
    scan registered), so a single picked parquet becomes a recursive scan
    matching exactly that path.
    """
    if dc.mode == "single" and dc.type != "multiqc":
        return {"mode": "single", "scan_parameters": {"filename": under_root(dc.path)}}
    pattern = dc.regex or (exact_path_regex(dc.path) if dc.path else "")
    parameters: dict[str, Any] = {"regex_config": {"pattern": pattern}}
    if dc.max_depth is not None:
        parameters["max_depth"] = dc.max_depth
    if dc.ignore:
        parameters["ignore"] = list(dc.ignore)
    return {"mode": "recursive", "scan_parameters": parameters}


def _table_properties(fmt: str, separator: str | None) -> dict[str, Any]:
    properties: dict[str, Any] = {"format": fmt}
    if separator and fmt in ("csv", "tsv"):
        properties["polars_kwargs"] = {"separator": separator}
    return properties


def _drop_none(values: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in values.items() if value is not None}


def dc_config(dc: DcDraft) -> dict[str, Any]:
    """The ``config`` block of one data collection, in the shipped templates' shape."""
    props = dc.props
    scan = scan_block(dc)
    if isinstance(props, TableProps):
        properties = _table_properties(props.format, props.separator)
        if props.columns_description:
            properties["columns_description"] = dict(props.columns_description)
        metatype = "Aggregate" if scan["mode"] == "recursive" else "Metadata"
        return {
            "type": "Table",
            "metatype": metatype,
            "scan": scan,
            "dc_specific_properties": properties,
        }
    if isinstance(props, MultiQCProps):
        return {"type": "MultiQC", "scan": scan, "dc_specific_properties": {}}
    if isinstance(props, ImageProps):
        properties = _table_properties(props.format, props.separator)
        properties["image_column"] = props.image_column
        if props.local_images_path:
            properties["local_images_path"] = under_root(props.local_images_path)
        if props.s3_base_folder:
            properties["s3_base_folder"] = props.s3_base_folder
        return {"type": "image", "scan": scan, "dc_specific_properties": properties}
    if isinstance(props, IndexedFileProps):
        properties = _drop_none(
            {
                "format": props.format,
                "index_suffix": props.index_suffix,
                "sample_regex": props.sample_regex,
                "sample_col": props.sample_col,
                "assembly": props.assembly,
                "max_file_size_mb": props.max_file_size_mb,
            }
        )
        return {
            "type": "indexed_file",
            "metatype": "Metadata",
            "scan": scan,
            "dc_specific_properties": properties,
        }
    if isinstance(props, GeoJSONProps):
        return {
            "type": "geojson",
            "metatype": "GeoJSON",
            "scan": scan,
            "dc_specific_properties": {"feature_id_key": props.feature_id_key},
        }
    properties = _drop_none(
        {
            "format": props.format,
            "ladderize": props.ladderize,
            "metadata_dc_tag": props.metadata_dc_tag,
            "metadata_taxon_column": props.metadata_taxon_column,
            "tip_label_strategy": props.tip_label_strategy,
        }
    )
    return {
        "type": "phylogeny",
        "metatype": "Aggregate",
        "scan": scan,
        "dc_specific_properties": properties,
    }


def data_collection(dc: DcDraft) -> dict[str, Any]:
    entry: dict[str, Any] = {"data_collection_tag": dc.tag}
    if dc.description:
        entry["description"] = dc.description
    if dc.optional:
        entry["optional"] = True
    entry["config"] = dc_config(dc)
    return entry


def data_location(workflow: WorkflowDraft) -> dict[str, Any]:
    location: dict[str, Any] = {"structure": workflow.structure, "locations": [DATA_ROOT]}
    if workflow.structure == "sequencing-runs":
        location["runs_regex"] = workflow.runs_regex or ""
    return location


def workflow_block(workflow: WorkflowDraft) -> dict[str, Any]:
    engine: dict[str, Any] = {"name": (workflow.engine or "python").strip().lower()}
    if workflow.engine_version:
        engine["version"] = workflow.engine_version
    block: dict[str, Any] = {"name": workflow.name, "engine": engine}
    if workflow.version:
        block["version"] = workflow.version
    if workflow.repository_url:
        block["repository_url"] = workflow.repository_url
    if workflow.catalog:
        block["catalog"] = workflow.catalog.model_dump()
    block["data_location"] = data_location(workflow)
    block["data_collections"] = [data_collection(dc) for dc in workflow.data_collections]
    return block


def build_template(draft: ProjectDraft) -> dict[str, Any]:
    """The ad-hoc template a draft stands for (not yet validated: see ``validate``)."""
    template: dict[str, Any] = {
        "template": {
            "template_id": template_id_for(draft.name),
            "description": draft.description or f"{draft.name}, defined with the Project Builder",
            "version": "1",
            "variables": [
                {
                    "name": "DATA_ROOT",
                    "description": "The folder or s3:// prefix the collections are read from",
                    "required": True,
                }
            ],
        },
        "name": draft.name,
        "project_type": "advanced",
        "is_public": draft.is_public,
    }
    if draft.description:
        template["description"] = draft.description
    if draft.realtime:
        template["realtime"] = {"enabled": True, "debounce_ms": 1000}
    template["workflows"] = [workflow_block(workflow) for workflow in draft.workflows]
    return template


YAML_HEADER = """\
# Defined with the Depictio Project Builder.
# Run it against the folder (or s3:// prefix) it was built from, or any other
# with the same layout:
#   depictio ingest <folder or s3://prefix> --template <this file>
"""


def template_yaml(template: dict[str, Any]) -> str:
    return YAML_HEADER + yaml.safe_dump(template, sort_keys=False, allow_unicode=True, width=100)
