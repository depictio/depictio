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


class ReaderOptions(BaseModel):
    """How a csv/tsv file is read (polars ``scan_csv`` options), beyond its separator."""

    model_config = _STRICT
    has_header: bool | None = None
    skip_rows: int | None = Field(default=None, ge=0, le=10_000)
    comment_prefix: str | None = Field(default=None, min_length=1, max_length=5)
    null_values: list[str] | None = Field(default=None, max_length=50)
    quote_char: str | None = Field(default=None, max_length=1)
    decimal_comma: bool | None = None

    def polars_kwargs(self) -> dict[str, Any]:
        return {
            key: value
            for key, value in self.model_dump().items()
            if value is not None and value != []
        }


class SpatialDataTableSource(BaseModel):
    """What a table collection reads from a SpatialData store (``format: spatialdata``)."""

    model_config = _STRICT
    table: str = "tables/table"
    image: str | None = None
    coordinates: Literal["auto", "obsm", "region"] = "auto"
    genes: list[str] = Field(default_factory=list, max_length=500)
    layer: str | None = None


class TableProps(BaseModel):
    model_config = _STRICT
    kind: Literal["table"] = "table"
    format: str = "csv"
    separator: str | None = None
    columns_description: dict[str, str] | None = None
    reader: ReaderOptions | None = None
    # Map coordinates: both columns, or neither.
    lat_column: str | None = None
    lon_column: str | None = None
    crs: str | None = None
    # Required iff format is "spatialdata".
    spatialdata: SpatialDataTableSource | None = None


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
    reader: ReaderOptions | None = None
    columns_description: dict[str, str] | None = None
    thumbnail_size: int | None = Field(default=None, ge=50, le=1000)
    supported_formats: list[str] | None = Field(default=None, max_length=50)


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


class CustomAssembly(BaseModel):
    """A reference genome that is not a built-in preset. Each ``*_uri`` is a
    root-relative path, or an ``https://``/``s3://`` URL read in place."""

    model_config = _STRICT
    name: str = Field(min_length=1, max_length=100)
    display_name: str | None = None
    aliases: list[str] = Field(default_factory=list, max_length=50)
    twobit_uri: str | None = None
    chrom_sizes_uri: str | None = None
    fasta_uri: str | None = None
    fai_uri: str | None = None
    gzi_uri: str | None = None
    refname_aliases_uri: str | None = None


ASSEMBLY_URI_FIELDS = (
    "twobit_uri",
    "chrom_sizes_uri",
    "fasta_uri",
    "fai_uri",
    "gzi_uri",
    "refname_aliases_uri",
)


class GenomicTracksProps(BaseModel):
    """A manifest of genome-browser tracks: the table (format, separator) and
    which of its columns says what."""

    model_config = _STRICT
    kind: Literal["genomic_tracks"] = "genomic_tracks"
    format: str = "tsv"
    separator: str | None = None
    uri_column: str = "uri"
    sample_column: str | None = None
    format_column: str | None = None
    index_column: str | None = None
    name_column: str | None = None
    color_column: str | None = None
    category_column: str | None = None
    order_column: str | None = None
    track_id_column: str | None = None
    default_format: str | None = None
    assembly: str | CustomAssembly = "hg38"
    # Root-relative folder relative uris resolve against; None: the manifest's folder.
    tracks_base_path: str | None = None


class BioimageProps(BaseModel):
    model_config = _STRICT
    kind: Literal["bioimage"] = "bioimage"
    format: Literal["ome-zarr", "ome-tiff", "spatialdata"] = "ome-zarr"
    ngff_version: Literal["0.4", "0.5"] | None = None
    upload: bool = True
    # The image element of a SpatialData store ("images/<name>"), required for it.
    image_path: str | None = None


DcProps = Annotated[
    TableProps
    | MultiQCProps
    | ImageProps
    | IndexedFileProps
    | GeoJSONProps
    | PhylogenyProps
    | GenomicTracksProps
    | BioimageProps,
    Field(discriminator="kind"),
]

DcType = Literal[
    "table",
    "multiqc",
    "image",
    "indexed_file",
    "geojson",
    "phylogeny",
    "genomic_tracks",
    "bioimage",
]


class WildcardDraft(BaseModel):
    """A ``{name}`` of a recursive scan's regex: what it matches, and the column it becomes."""

    model_config = _STRICT
    name: str = Field(min_length=1, max_length=64)
    regex: str = Field(min_length=1, max_length=500)


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
    # None: automatic (Metadata for one file, Aggregate for a scan).
    metatype: Literal["Metadata", "Aggregate"] | None = None
    wildcards: list[WildcardDraft] = Field(default_factory=list, max_length=20)
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


class LinkDraft(BaseModel):
    """A cross-collection filter: values of ``source_column`` select rows of the target.

    The target's link type comes from its collection's type, so it is never
    asked for; ``target_field`` and the resolver default from it too.
    """

    model_config = _STRICT
    source_tag: str = Field(min_length=1)
    source_column: str = Field(min_length=1)
    target_tag: str = Field(min_length=1)
    resolver: Literal["direct", "sample_mapping", "pattern", "regex", "wildcard"] | None = None
    target_field: str | None = None
    pattern: str | None = None
    description: str | None = None


class ProjectDraft(BaseModel):
    model_config = _STRICT
    name: str = Field(min_length=1, max_length=200)
    description: str | None = None
    is_public: bool = False
    realtime: bool = False
    data_management_platform_project_url: str | None = None
    workflows: list[WorkflowDraft] = Field(default_factory=list)
    links: list[LinkDraft] = Field(default_factory=list, max_length=100)


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
    matching exactly that path. A recursive scan's wildcards stand in its
    regex as ``{name}`` and each becomes a column of the table.
    """
    if dc.mode == "single" and dc.type != "multiqc":
        return {"mode": "single", "scan_parameters": {"filename": under_root(dc.path)}}
    pattern = dc.regex or (exact_path_regex(dc.path) if dc.path else "")
    regex_config: dict[str, Any] = {"pattern": pattern}
    if dc.mode == "recursive" and dc.wildcards:
        regex_config["wildcards"] = [
            {"name": wildcard.name, "wildcard_regex": wildcard.regex} for wildcard in dc.wildcards
        ]
    parameters: dict[str, Any] = {"regex_config": regex_config}
    if dc.max_depth is not None:
        parameters["max_depth"] = dc.max_depth
    if dc.ignore:
        parameters["ignore"] = list(dc.ignore)
    return {"mode": "recursive", "scan_parameters": parameters}


def _table_properties(
    fmt: str, separator: str | None, reader: ReaderOptions | None = None
) -> dict[str, Any]:
    """``format`` and, for a text table, the reader options as ``polars_kwargs``."""
    properties: dict[str, Any] = {"format": fmt}
    if fmt in ("csv", "tsv"):
        kwargs = {"separator": separator} if separator else {}
        kwargs.update(reader.polars_kwargs() if reader else {})
        if kwargs:
            properties["polars_kwargs"] = kwargs
    return properties


def _drop_none(values: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in values.items() if value is not None}


def _metatype(dc: DcDraft, scan: dict[str, Any]) -> str:
    if dc.metatype:
        return dc.metatype
    return "Aggregate" if scan["mode"] == "recursive" else "Metadata"


def _assembly_uri(value: str) -> str:
    """A custom assembly file: a URL as given, a root-relative path under ``{DATA_ROOT}``."""
    if "://" in value:
        return value
    return under_root(value)


def _assembly(assembly: str | CustomAssembly) -> str | dict[str, Any]:
    if isinstance(assembly, str):
        return assembly
    block = _drop_none(assembly.model_dump())
    if not block.get("aliases"):
        block.pop("aliases", None)
    for field in ASSEMBLY_URI_FIELDS:
        if block.get(field):
            block[field] = _assembly_uri(block[field])
    return block


def _tracks_base(dc: DcDraft, props: GenomicTracksProps) -> str:
    """The root-relative folder a manifest's relative uris resolve against."""
    if props.tracks_base_path is not None:
        return props.tracks_base_path.strip("/")
    if dc.mode == "single" and dc.path:
        parent = dc.path.strip("/").rpartition("/")[0]
        return parent
    return ""


def _genomic_tracks_properties(
    dc: DcDraft, props: GenomicTracksProps, *, remote: bool
) -> dict[str, Any]:
    properties = _table_properties(props.format, props.separator)
    properties.update(
        _drop_none(
            {
                "uri_column": props.uri_column,
                "sample_column": props.sample_column,
                "format_column": props.format_column,
                "index_column": props.index_column,
                "name_column": props.name_column,
                "color_column": props.color_column,
                "category_column": props.category_column,
                "order_column": props.order_column,
                "track_id_column": props.track_id_column,
                "default_format": props.default_format,
            }
        )
    )
    properties["assembly"] = _assembly(props.assembly)
    if remote:
        # Tracks under an s3:// root are read in place: relative uris resolve
        # against the prefix, nothing is uploaded from a local folder.
        base = _tracks_base(dc, props)
        properties["remote_base_uri"] = under_root(base) + "/"
    elif props.tracks_base_path is not None:
        properties["tracks_base_path"] = under_root(props.tracks_base_path)
    return properties


def dc_config(dc: DcDraft, *, remote: bool = False) -> dict[str, Any]:
    """The ``config`` block of one data collection, in the shipped templates' shape.

    ``remote``: the template is for an ``s3://`` root (only genomic tracks
    differ: their files are then read in place under it).
    """
    props = dc.props
    scan = scan_block(dc)
    if isinstance(props, TableProps):
        if props.format == "spatialdata":
            source = props.spatialdata or SpatialDataTableSource()
            block: dict[str, Any] = {"table": source.table}
            if source.image:
                block["image"] = source.image
            if source.coordinates != "auto":
                block["coordinates"] = source.coordinates
            if source.genes:
                block["genes"] = list(source.genes)
            if source.layer:
                block["layer"] = source.layer
            properties = {"format": "spatialdata", "spatialdata": block}
        else:
            properties = _table_properties(props.format, props.separator, props.reader)
            if props.lat_column or props.lon_column:
                properties["lat_column"] = props.lat_column
                properties["lon_column"] = props.lon_column
                if props.crs:
                    properties["crs"] = props.crs
        if props.columns_description:
            properties["columns_description"] = dict(props.columns_description)
        return {
            "type": "Table",
            "metatype": _metatype(dc, scan),
            "scan": scan,
            "dc_specific_properties": properties,
        }
    if isinstance(props, MultiQCProps):
        return {"type": "MultiQC", "scan": scan, "dc_specific_properties": {}}
    if isinstance(props, ImageProps):
        properties = _table_properties(props.format, props.separator, props.reader)
        properties["image_column"] = props.image_column
        if props.local_images_path:
            properties["local_images_path"] = under_root(props.local_images_path)
        if props.s3_base_folder:
            properties["s3_base_folder"] = props.s3_base_folder
        if props.columns_description:
            properties["columns_description"] = dict(props.columns_description)
        if props.thumbnail_size is not None:
            properties["thumbnail_size"] = props.thumbnail_size
        if props.supported_formats:
            properties["supported_formats"] = list(props.supported_formats)
        config: dict[str, Any] = {"type": "image"}
        if dc.metatype:
            config["metatype"] = dc.metatype
        return {**config, "scan": scan, "dc_specific_properties": properties}
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
    if isinstance(props, GenomicTracksProps):
        return {
            "type": "genomic_tracks",
            "metatype": dc.metatype or "Metadata",
            "scan": scan,
            "dc_specific_properties": _genomic_tracks_properties(dc, props, remote=remote),
        }
    if isinstance(props, BioimageProps):
        properties = {"format": props.format}
        if props.ngff_version and props.format != "ome-tiff":
            properties["ngff_version"] = props.ngff_version
        properties["upload"] = props.upload
        if props.format == "spatialdata" and props.image_path:
            properties["image_path"] = props.image_path
        return {"type": "bioimage", "scan": scan, "dc_specific_properties": properties}
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


def data_collection(dc: DcDraft, *, remote: bool = False) -> dict[str, Any]:
    entry: dict[str, Any] = {"data_collection_tag": dc.tag}
    if dc.description:
        entry["description"] = dc.description
    if dc.optional:
        entry["optional"] = True
    entry["config"] = dc_config(dc, remote=remote)
    return entry


def data_location(workflow: WorkflowDraft) -> dict[str, Any]:
    location: dict[str, Any] = {"structure": workflow.structure, "locations": [DATA_ROOT]}
    if workflow.structure == "sequencing-runs":
        location["runs_regex"] = workflow.runs_regex or ""
    return location


def workflow_block(workflow: WorkflowDraft, *, remote: bool = False) -> dict[str, Any]:
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
    block["data_collections"] = [
        data_collection(dc, remote=remote) for dc in workflow.data_collections
    ]
    return block


def link_target_type(dc: DcDraft) -> str:
    """The link ``target_type`` a collection is filtered as: its own type, a
    table read from a store being a table like any other."""
    return dc.type


def _link_block(link: LinkDraft, collections: dict[str, DcDraft]) -> dict[str, Any]:
    target = collections.get(link.target_tag)
    target_type = link_target_type(target) if target is not None else ""
    resolver = link.resolver or ("sample_mapping" if target_type == "multiqc" else "direct")
    target_field = link.target_field
    if target_field is None and target is not None:
        if target_type == "multiqc":
            target_field = "sample_name"
        elif isinstance(target.props, GenomicTracksProps):
            target_field = target.props.sample_column
    link_config: dict[str, Any] = {"resolver": resolver}
    if target_field:
        link_config["target_field"] = target_field
    if resolver == "pattern" and link.pattern:
        link_config["pattern"] = link.pattern
    block: dict[str, Any] = {
        "source_dc_tag": link.source_tag,
        "source_column": link.source_column,
        "target_dc_tag": link.target_tag,
        "target_type": target_type,
        "link_config": link_config,
    }
    if link.description:
        block["description"] = link.description
    return block


def build_template(draft: ProjectDraft, *, remote: bool = False) -> dict[str, Any]:
    """The ad-hoc template a draft stands for (not yet validated: see ``validate``).

    ``remote``: the root it is built against is an ``s3://`` prefix. Every
    location is under ``{DATA_ROOT}`` either way; only genomic tracks say
    where their files are read differently (see ``dc_config``).
    """
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
    if draft.data_management_platform_project_url:
        template["data_management_platform_project_url"] = (
            draft.data_management_platform_project_url
        )
    if draft.realtime:
        template["realtime"] = {"enabled": True, "debounce_ms": 1000}
    template["workflows"] = [
        workflow_block(workflow, remote=remote) for workflow in draft.workflows
    ]
    if draft.links:
        collections = {
            dc.tag: dc for workflow in draft.workflows for dc in workflow.data_collections
        }
        template["links"] = [_link_block(link, collections) for link in draft.links]
    return template


YAML_HEADER = """\
# Defined with the Depictio Project Builder.
# Run it against the folder (or s3:// prefix) it was built from, or any other
# with the same layout:
#   depictio ingest <folder or s3://prefix> --template <this file>
"""


def template_yaml(template: dict[str, Any]) -> str:
    return YAML_HEADER + yaml.safe_dump(template, sort_keys=False, allow_unicode=True, width=100)
