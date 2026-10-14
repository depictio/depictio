"""A shipped template, turned back into a builder draft.

The inverse of :mod:`assemble`: ``build_template`` writes a draft as a
template, this reads a template as a draft, so the SPA can open
``nf-core/viralrecon/3.0.0`` in the builder as an editable starting point. A
shipped template says more than the builder can express (collections built by
recipes from other collections, dashboards, conditionals, provenance, extra
template variables), so the answer lists, plainly, what was **not** carried
over. Nothing is guessed: a collection the builder cannot write back exactly
is dropped with its reason rather than approximated.

It works on the raw template as loaded from YAML: ``{DATA_ROOT}`` placeholders
and root-relative scan patterns stay as they are, and nothing is read from a
data root. Each collection converts or is dropped, never raises, and every
collection it keeps is held to what ``validate.validate_inline_template`` asks
of an inline template, so the draft it returns builds a template that passes.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from depictio.project_builder import assemble
from depictio.project_builder.assemble import (
    DATA_ROOT,
    BioimageProps,
    CatalogRef,
    CustomAssembly,
    DcDraft,
    GenomicTracksProps,
    GeoJSONProps,
    ImageProps,
    IndexedFileProps,
    LinkDraft,
    MultiQCProps,
    PhylogenyProps,
    ProjectDraft,
    ReaderOptions,
    SpatialDataTableSource,
    TableProps,
    WildcardDraft,
    WorkflowDraft,
)
from depictio.project_builder.errors import BuilderRefused
from depictio.project_builder.validate import (
    MAX_DATA_COLLECTIONS,
    MAX_LINKS,
    MAX_WORKFLOWS,
    _check_links,
    validate_inline_template,
)

# Config keys the builder writes; a collection carrying any other (source,
# transform, recipe, join...) is built from something the builder cannot say.
_CONFIG_KEYS = frozenset({"type", "metatype", "scan", "dc_specific_properties"})
_DERIVED_KEYS = frozenset({"source", "sources", "transform", "recipe", "join", "joins"})
# Collection-level keys that are bookkeeping, not content.
_IGNORED_DC_KEYS = frozenset({"id", "data_collection_tag", "description", "optional", "config"})

_TYPES = frozenset(
    {
        "table",
        "multiqc",
        "image",
        "indexed_file",
        "geojson",
        "phylogeny",
        "genomic_tracks",
        "bioimage",
    }
)

_TABLE_KEYS = frozenset(
    {
        "format",
        "polars_kwargs",
        "columns_description",
        "lat_column",
        "lon_column",
        "crs",
        "spatialdata",
    }
)
_IMAGE_KEYS = frozenset(
    {
        "format",
        "polars_kwargs",
        "image_column",
        "local_images_path",
        "s3_base_folder",
        "columns_description",
        "thumbnail_size",
        "supported_formats",
    }
)
_INDEXED_KEYS = frozenset(
    {"format", "index_suffix", "sample_regex", "sample_col", "assembly", "max_file_size_mb"}
)
_GEOJSON_KEYS = frozenset({"feature_id_key"})
_PHYLOGENY_KEYS = frozenset(
    {"format", "ladderize", "metadata_dc_tag", "metadata_taxon_column", "tip_label_strategy"}
)
_TRACK_COLUMNS = (
    "uri_column",
    "sample_column",
    "format_column",
    "index_column",
    "name_column",
    "color_column",
    "category_column",
    "order_column",
    "track_id_column",
    "default_format",
)
_TRACKS_KEYS = frozenset(
    {"format", "polars_kwargs", "assembly", "tracks_base_path", "remote_base_uri", *_TRACK_COLUMNS}
)
_BIOIMAGE_KEYS = frozenset({"format", "ngff_version", "upload", "image_path"})

_PLACEHOLDER = re.compile(r"\{([A-Za-z_][A-Za-z0-9_]*)\}")
# A scan regex that matches exactly one path (what assemble.exact_path_regex writes):
# anchors around literal characters, each special one escaped.
_EXACT_PATH = re.compile(r"\^((?:[^\\^$.|?*+()\[\]{}]|\\.)*)\$")


class _Unsupported(Exception):
    """A collection that cannot be carried; the message is the reason shown."""


def _plain(text: str) -> str:
    """A reason as one short sentence, without trailing punctuation noise."""
    return " ".join(text.split()).rstrip(".")


def _first_error(exc: ValidationError) -> str:
    first = exc.errors()[0]
    field = ".".join(str(part) for part in first.get("loc", ()))
    message = first.get("msg", "invalid")
    return _plain(f"{field}: {message}" if field else message)


def _names(names: Any) -> str:
    return ", ".join(sorted(str(n) for n in names))


def _root_relative(value: Any, what: str) -> str:
    """A template location as a root-relative path (the inverse of ``under_root``)."""
    if not isinstance(value, str):
        raise _Unsupported(f"{what} is not a path")
    if "://" in value:
        raise _Unsupported(f"{what} is a URL ({value}), which the builder does not read")
    rel = value[len(DATA_ROOT) :] if value.startswith(DATA_ROOT) else value
    rel = rel.strip("/")
    found = set(_PLACEHOLDER.findall(rel))
    if found:
        names = ", ".join("{" + name + "}" for name in sorted(found))
        raise _Unsupported(
            f"{what} uses the template variable {names}, which the builder has no equivalent for"
        )
    if ".." in rel.split("/"):
        raise _Unsupported(f"{what} leaves the data root")
    return rel


def _optional_relative(value: Any, what: str) -> str | None:
    return None if value is None else _root_relative(value, what)


def _reader(properties: dict[str, Any]) -> tuple[str | None, ReaderOptions | None]:
    """``polars_kwargs`` as a separator and the reader options the builder offers."""
    kwargs = properties.get("polars_kwargs")
    if kwargs is None:
        return None, None
    if not isinstance(kwargs, dict):
        raise _Unsupported("its reader options (polars_kwargs) are not a mapping")
    unknown = set(kwargs) - set(ReaderOptions.model_fields) - {"separator"}
    if unknown:
        raise _Unsupported(
            f"it reads its file with options the builder has no field for ({_names(unknown)})"
        )
    separator = kwargs.get("separator")
    options = {k: v for k, v in kwargs.items() if k != "separator"}
    return separator, ReaderOptions(**options) if options else None


def _table_format(properties: dict[str, Any]) -> dict[str, Any]:
    """``{"format": ...}`` of a table-like collection, lowercase as the builder writes it."""
    fmt = properties.get("format")
    return {} if fmt is None else {"format": str(fmt).lower()}


def _check_keys(properties: dict[str, Any], allowed: frozenset[str]) -> None:
    unknown = set(properties) - allowed
    if unknown:
        raise _Unsupported(f"it sets properties the builder has no field for ({_names(unknown)})")


def _metatype(raw: Any, automatic: str | None) -> str | None:
    """The draft's metatype: None when the template's is what the builder picks itself."""
    if raw is None:
        return None
    text = str(raw).strip().lower()
    if text == "metadata":
        value = "Metadata"
    elif text.startswith("aggregat"):
        value = "Aggregate"
    else:
        raise _Unsupported(f"its metatype {raw!r} is not Metadata or Aggregate")
    return None if value == automatic else value


def _assembly(raw: Any) -> str | CustomAssembly:
    if isinstance(raw, str):
        return raw
    if not isinstance(raw, dict):
        raise _Unsupported("its genome assembly is neither a preset name nor a custom assembly")
    block = dict(raw)
    for field in assemble.ASSEMBLY_URI_FIELDS:
        value = block.get(field)
        if isinstance(value, str) and "://" not in value:
            block[field] = _root_relative(value, f"the assembly {field}")
    return CustomAssembly(**block)


def _scan(config: dict[str, Any], dc_type: str) -> dict[str, Any]:
    """The scan fields of a :class:`DcDraft` (the inverse of ``assemble.scan_block``)."""
    scan = config.get("scan")
    if not isinstance(scan, dict):
        raise _Unsupported("it has no file scan to read")
    mode = str(scan.get("mode") or "").lower()
    parameters = scan.get("scan_parameters") or {}
    if not isinstance(parameters, dict):
        raise _Unsupported("its scan parameters are not a mapping")
    if mode == "single":
        extra = set(parameters) - {"filename"}
        if extra:
            raise _Unsupported(f"its single-file scan sets {_names(extra)}")
        return {"mode": "single", "path": _root_relative(parameters.get("filename"), "its file")}
    if mode != "recursive":
        raise _Unsupported(f"its scan mode is {scan.get('mode')!r}, not a file or a folder scan")
    extra = set(parameters) - {"regex_config", "max_depth", "ignore"}
    if extra:
        raise _Unsupported(f"its scan sets {_names(extra)}, which the builder has no field for")
    regex_config = parameters.get("regex_config") or {}
    if not isinstance(regex_config, dict) or set(regex_config) - {"pattern", "wildcards"}:
        raise _Unsupported("its scan regex is configured in a way the builder cannot write")
    pattern = regex_config.get("pattern")
    if not isinstance(pattern, str) or not pattern:
        raise _Unsupported("its scan has no regex")
    wildcards = regex_config.get("wildcards") or []
    if not isinstance(wildcards, list) or not all(
        isinstance(w, dict) and {"name", "wildcard_regex"} <= set(w) for w in wildcards
    ):
        raise _Unsupported("its wildcards are not name and regex pairs")
    fields: dict[str, Any] = {"mode": "recursive", "regex": pattern}
    if wildcards:
        fields["wildcards"] = [
            WildcardDraft(name=w["name"], regex=w["wildcard_regex"]) for w in wildcards
        ]
    if parameters.get("max_depth") is not None:
        fields["max_depth"] = parameters["max_depth"]
    if parameters.get("ignore"):
        fields["ignore"] = list(parameters["ignore"])
    exact = _EXACT_PATH.fullmatch(pattern)
    if dc_type == "multiqc" and exact and not wildcards:
        # The builder walks a single MultiQC report as a scan of exactly that path.
        path = re.sub(r"\\(.)", r"\1", exact.group(1))
        if assemble.exact_path_regex(path) == pattern and not {"max_depth", "ignore"} & set(
            parameters
        ):
            return {"mode": "single", "path": path}
    return fields


def _props(
    dc_type: str, config: dict[str, Any], scan: dict[str, Any], lost: list[str]
) -> tuple[Any, str | None]:
    """The type's props and the draft metatype (None: automatic).

    ``lost``: properties of a collection that is kept without them.
    """
    properties = config.get("dc_specific_properties") or {}
    if not isinstance(properties, dict):
        raise _Unsupported("its properties are not a mapping")
    raw_metatype = config.get("metatype")

    if dc_type == "table":
        _check_keys(properties, _TABLE_KEYS)
        automatic = "Aggregate" if scan["mode"] == "recursive" else "Metadata"
        metatype = _metatype(raw_metatype, automatic)
        columns = properties.get("columns_description")
        fields: dict[str, Any] = {"columns_description": columns or None}
        fields.update(_table_format(properties))
        if fields.get("format") == "spatialdata":
            if properties.get("polars_kwargs"):
                raise _Unsupported("a SpatialData table takes no reader options")
            source = properties.get("spatialdata")
            fields["spatialdata"] = SpatialDataTableSource(**(source or {}))
        else:
            fields["separator"], fields["reader"] = _reader(properties)
            for key in ("lat_column", "lon_column", "crs"):
                fields[key] = properties.get(key)
        return TableProps(**fields), metatype
    if dc_type == "multiqc":
        if properties:
            lost.append(
                f"MultiQC settings the builder has no field for were left out ({_names(properties)})"
            )
        return MultiQCProps(), None
    if dc_type == "image":
        _check_keys(properties, _IMAGE_KEYS)
        fields = {"columns_description": properties.get("columns_description") or None}
        fields.update(_table_format(properties))
        fields["separator"], fields["reader"] = _reader(properties)
        for key in ("image_column", "s3_base_folder", "thumbnail_size", "supported_formats"):
            fields[key] = properties.get(key)
        fields["local_images_path"] = _optional_relative(
            properties.get("local_images_path"), "its image folder"
        )
        return ImageProps(**fields), _metatype(raw_metatype, None)
    if dc_type == "indexed_file":
        _check_keys(properties, _INDEXED_KEYS)
        return IndexedFileProps(**properties), None
    if dc_type == "geojson":
        _check_keys(properties, _GEOJSON_KEYS)
        return GeoJSONProps(**properties), None
    if dc_type == "phylogeny":
        _check_keys(properties, _PHYLOGENY_KEYS)
        return PhylogenyProps(**properties), None
    if dc_type == "genomic_tracks":
        _check_keys(properties, _TRACKS_KEYS | {"columns_description"})
        if properties.get("columns_description"):
            lost.append("its column descriptions were left out (a track manifest takes none)")
        fields = {key: properties[key] for key in _TRACK_COLUMNS if key in properties}
        fields.update(_table_format(properties))
        fields["separator"], _ = _reader(properties)
        if properties.get("assembly") is not None:
            fields["assembly"] = _assembly(properties["assembly"])
        base = properties.get("tracks_base_path")
        remote = properties.get("remote_base_uri")
        if base is None and remote is not None:
            base = str(remote).rstrip("/")
        if base is not None:
            relative = _root_relative(base, "its tracks folder")
            # A folder that is just the manifest's own is what the builder assumes.
            manifest_folder = (
                scan["path"].rpartition("/")[0] if scan.get("mode") == "single" else ""
            )
            fields["tracks_base_path"] = None if relative == manifest_folder else relative
        return GenomicTracksProps(**fields), _metatype(raw_metatype, "Metadata")
    _check_keys(properties, _BIOIMAGE_KEYS)
    return BioimageProps(**properties), None


def _probe(dc: DcDraft) -> str | None:
    """Why the builder would refuse ``dc`` on its own, or None when it passes.

    A phylogeny's metadata reference is checked later, against the collections
    that were kept; a collection is probed without it.
    """
    probe = dc.model_copy(deep=True)
    if isinstance(probe.props, PhylogenyProps):
        probe.props.metadata_dc_tag = None
    draft = ProjectDraft(
        name="probe",
        workflows=[WorkflowDraft(name="probe", data_collections=[probe])],
    )
    try:
        validate_inline_template(assemble.build_template(draft), remote=False)
    except BuilderRefused as exc:
        return _plain(exc.detail.removeprefix(f"{dc.tag!r}: "))
    return None


def _text_or_none(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None


def _collection(raw: Any) -> tuple[DcDraft, str, list[str]]:
    """``(draft, tag, lost)`` for one template collection; raises :class:`_Unsupported`
    with the reason when it cannot be carried."""
    lost: list[str] = []
    if not isinstance(raw, dict):
        raise _Unsupported("it is not a mapping")
    tag = str(raw.get("data_collection_tag") or "").strip()
    if not tag:
        raise _Unsupported("it has no tag")
    config = raw.get("config")
    if not isinstance(config, dict):
        raise _Unsupported("it has no config")
    derived = _DERIVED_KEYS & set(config)
    if derived:
        raise _Unsupported(
            f"it is built from other collections ({_names(derived)}), which the builder "
            "cannot express: it only reads files"
        )
    extra = set(config) - _CONFIG_KEYS
    if extra:
        raise _Unsupported(f"it sets {_names(extra)}, which the builder has no field for")
    extra_keys = set(raw) - _IGNORED_DC_KEYS
    if extra_keys:
        raise _Unsupported(f"it sets {_names(extra_keys)}, which the builder has no field for")
    type_name = str(config.get("type") or "")
    dc_type = type_name.lower()
    if dc_type not in _TYPES:
        raise _Unsupported(f"its type {type_name!r} is not one the builder offers")
    scan = _scan(config, dc_type)
    props, metatype = _props(dc_type, config, scan, lost)
    dc = DcDraft(
        tag=tag,
        description=_text_or_none(raw.get("description")),
        type=dc_type,  # ty: ignore[invalid-argument-type]
        optional=bool(raw.get("optional", False)),
        metatype=metatype,  # ty: ignore[invalid-argument-type]
        props=props,
        **scan,
    )
    reason = _probe(dc)
    if reason:
        raise _Unsupported(reason)
    return dc, tag, lost


def _workflow_fields(raw: dict[str, Any], lost: list[str]) -> dict[str, Any]:
    fields: dict[str, Any] = {}
    engine = raw.get("engine")
    if isinstance(engine, dict):
        if engine.get("name"):
            fields["engine"] = str(engine["name"]).strip().lower()
        if engine.get("version"):
            fields["engine_version"] = str(engine["version"])
    elif isinstance(engine, str) and engine.strip():
        fields["engine"] = engine.strip().lower()
    for key in ("version", "repository_url"):
        if raw.get(key):
            fields[key] = str(raw[key])
    catalog = raw.get("catalog")
    if isinstance(catalog, dict):
        try:
            fields["catalog"] = CatalogRef(**catalog)
        except ValidationError:
            lost.append(f"its catalog ({catalog.get('name')!r}) is not one the builder lists")
    location = raw.get("data_location")
    if isinstance(location, dict):
        if location.get("structure") in ("flat", "sequencing-runs"):
            fields["structure"] = location["structure"]
        if location.get("runs_regex"):
            fields["runs_regex"] = str(location["runs_regex"])
        if location.get("locations") not in ([DATA_ROOT], None) or location.get(
            "attached_locations"
        ):
            lost.append("it reads more than the data root; the draft reads the data root only")
    if raw.get("description"):
        lost.append("its description was left out (a workflow has none in the builder)")
    return fields


def _link_draft(raw: Any, by_tag: dict[str, DcDraft]) -> tuple[LinkDraft | None, str | None]:
    """``(draft, None)`` or ``(None, reason)`` for one template link."""
    if not isinstance(raw, dict):
        return None, "it is not a mapping"
    if raw.get("enabled") is False:
        return None, "it is disabled in the template"
    extra = set(raw) - {
        "id",
        "source_dc_tag",
        "source_column",
        "target_dc_tag",
        "target_type",
        "link_config",
        "description",
        "enabled",
    }
    if extra:
        return None, f"it sets {_names(extra)}, which the builder has no field for"
    config = raw.get("link_config") or {}
    if not isinstance(config, dict):
        return None, "its link settings are not a mapping"
    extra = set(config) - {"resolver", "target_field", "pattern"}
    if extra:
        return (
            None,
            f"its link settings include {_names(extra)}, which the builder has no field for",
        )
    source, target = raw.get("source_dc_tag"), raw.get("target_dc_tag")
    if source not in by_tag or target not in by_tag:
        gone = [str(tag) for tag in (source, target) if tag not in by_tag]
        verb = "was" if len(gone) == 1 else "were"
        return None, f"{' and '.join(gone)} {verb} not carried over"
    column = str(raw.get("source_column") or "")
    found = _PLACEHOLDER.findall(column)
    if found:
        return None, f"its source column is the template variable {{{found[0]}}}"
    resolver = config.get("resolver")
    target_dc = by_tag[str(target)]
    if resolver == (
        "sample_mapping" if target_dc.type == "multiqc" else "direct"
    ):  # the builder's own default
        resolver = None
    field = config.get("target_field")
    default_field = None
    if target_dc.type == "multiqc":
        default_field = "sample_name"
    elif isinstance(target_dc.props, GenomicTracksProps):
        default_field = target_dc.props.sample_column
    try:
        link = LinkDraft(
            source_tag=str(source),
            source_column=column,
            target_tag=str(target),
            resolver=resolver,
            target_field=None if field == default_field else field,
            pattern=config.get("pattern"),
            description=raw.get("description") or None,
        )
    except ValidationError as exc:
        return None, _first_error(exc)
    types = {tag: dc.type for tag, dc in by_tag.items()}
    try:
        _check_links([assemble._link_block(link, by_tag)], types)
    except BuilderRefused as exc:
        return None, _plain(re.sub(r"^Link \d+: ", "", exc.detail))
    return link, None


def _project_url(raw: dict[str, Any]) -> str | None:
    url = raw.get("data_management_platform_project_url")
    return url if isinstance(url, str) and re.match(r"https?://\S+$", url) else None


def template_to_draft(raw: dict[str, Any], *, template_id: str) -> dict[str, Any]:
    """The builder draft a raw (unresolved) template stands for, and what was lost.

    Never raises on an odd template: each collection and link converts or is
    listed in ``dropped`` with a reason. ``editable`` is False when no
    collection survives.
    """
    dropped: list[dict[str, Any]] = []

    def drop(kind: str, tag: str | None, reason: str) -> None:
        dropped.append({"kind": kind, "tag": tag, "reason": reason})

    section = raw.get("template") if isinstance(raw.get("template"), dict) else {}
    name = str(raw.get("name") or template_id).strip()[:200] or template_id
    description = raw.get("description") or section.get("description")
    realtime = raw.get("realtime")
    if isinstance(realtime, dict):
        realtime = realtime.get("enabled")

    workflows: list[WorkflowDraft] = []
    by_tag: dict[str, DcDraft] = {}
    workflow_names: set[str] = set()
    raw_workflows = raw.get("workflows") if isinstance(raw.get("workflows"), list) else []
    for raw_workflow in raw_workflows:
        if not isinstance(raw_workflow, dict):
            drop("workflow", None, "it is not a mapping")
            continue
        workflow_name = str(raw_workflow.get("name") or "").strip() or "workflow"
        if workflow_name in workflow_names:
            drop("workflow", workflow_name, "another workflow already has this name")
            continue
        if len(workflows) >= MAX_WORKFLOWS:
            drop("workflow", workflow_name, f"the builder takes at most {MAX_WORKFLOWS} workflows")
            continue
        kept: list[DcDraft] = []
        raw_dcs = raw_workflow.get("data_collections")
        for raw_dc in raw_dcs if isinstance(raw_dcs, list) else []:
            tag = raw_dc.get("data_collection_tag") if isinstance(raw_dc, dict) else None
            tag = str(tag).strip() if tag else None
            try:
                dc, tag, lost = _collection(raw_dc)
                if tag in by_tag:
                    raise _Unsupported("another collection already has this tag")
                if len(by_tag) >= MAX_DATA_COLLECTIONS:
                    raise _Unsupported(
                        f"the builder takes at most {MAX_DATA_COLLECTIONS} collections"
                    )
            except _Unsupported as exc:
                drop("collection", tag, _plain(str(exc)))
                continue
            except ValidationError as exc:
                drop("collection", tag, _first_error(exc))
                continue
            except Exception as exc:
                drop("collection", tag, f"it could not be read ({type(exc).__name__})")
                continue
            for note in lost:
                drop("option", tag, _plain(note))
            by_tag[tag] = dc
            kept.append(dc)
        if not kept:
            drop("workflow", workflow_name, "none of its data collections could be carried over")
            continue
        lost_workflow: list[str] = []
        try:
            fields = _workflow_fields(raw_workflow, lost_workflow)
            workflow = WorkflowDraft(name=workflow_name[:128], data_collections=kept, **fields)
        except ValidationError as exc:
            for dc in kept:
                by_tag.pop(dc.tag, None)
            drop("workflow", workflow_name, _first_error(exc))
            continue
        for note in lost_workflow:
            drop("option", workflow_name, _plain(note))
        workflow_names.add(workflow_name)
        workflows.append(workflow)

    # A phylogeny names its tip metadata by tag: keep the reference only if that table was kept.
    for dc in by_tag.values():
        props = dc.props
        if isinstance(props, PhylogenyProps) and props.metadata_dc_tag:
            target = by_tag.get(props.metadata_dc_tag)
            if target is None or target.type != "table":
                drop(
                    "option",
                    dc.tag,
                    f"its tip metadata collection {props.metadata_dc_tag} was not carried over",
                )
                props.metadata_dc_tag = None
                props.metadata_taxon_column = None

    links: list[LinkDraft] = []
    raw_links = raw.get("links") if isinstance(raw.get("links"), list) else []
    for raw_link in raw_links:
        label = None
        if isinstance(raw_link, dict):
            label = f"{raw_link.get('source_dc_tag')} -> {raw_link.get('target_dc_tag')}"
        link, reason = _link_draft(raw_link, by_tag)
        if link is not None and len(links) >= MAX_LINKS:
            link, reason = None, f"the builder takes at most {MAX_LINKS} links"
        if link is None:
            drop("link", label, reason or "it could not be read")
        else:
            links.append(link)

    if isinstance(section.get("dashboards"), (list, dict)) and section["dashboards"]:
        drop(
            "dashboards",
            None,
            "dashboards are not part of a builder draft; add them in the dashboard editor "
            "once the project exists",
        )
    if section.get("conditional"):
        drop(
            "conditional",
            None,
            "conditional rules (collections switched on or off by the run's parameters) "
            "have no equivalent in the builder",
        )
    if section.get("provenance"):
        drop(
            "provenance",
            None,
            "run provenance (parameters and software versions read from the run) is not "
            "carried: the builder does not read it",
        )
    variables = section.get("variables")
    extra_variables = [
        str(v.get("name"))
        for v in (variables if isinstance(variables, list) else [])
        if isinstance(v, dict) and v.get("name") and v.get("name") != "DATA_ROOT"
    ]
    if extra_variables:
        drop(
            "variables",
            None,
            f"the template variables {', '.join(extra_variables)} have no equivalent: "
            "the draft reads DATA_ROOT only",
        )

    draft = ProjectDraft(
        name=name,
        description=_text_or_none(description),
        is_public=bool(raw.get("is_public", False)),
        realtime=bool(realtime),
        data_management_platform_project_url=_project_url(raw),
        workflows=workflows,
        links=links,
    )
    editable = bool(by_tag)
    return {
        "template_id": template_id,
        "title": str(raw["name"]) if raw.get("name") else None,
        "draft": draft.model_dump(mode="json", exclude_none=True),
        "carried": {"workflows": len(workflows), "collections": len(by_tag), "links": len(links)},
        "dropped": dropped,
        "editable": editable,
        "reason": None
        if editable
        else "None of this template's data collections can be expressed in the builder "
        "(they are built from other collections or read variables the builder lacks).",
    }


def _shipped_roots() -> list[Path]:
    from depictio.cli.cli.utils.templates import _projects_roots

    return [root.resolve() for root in _projects_roots()]


def load_shipped_template(template_id: str) -> dict[str, Any]:
    """The raw YAML of a template shipped with Depictio, found by id.

    Only ids that resolve inside the shipped projects folders are accepted:
    the id comes from a browser, and neither a path nor a dot segment may
    reach a file outside them.
    """
    from depictio.cli.cli.utils.templates import TemplateNotFoundError, _load_yaml, locate_template

    cleaned = (template_id or "").strip()
    segments = cleaned.split("/")
    if (
        not cleaned
        or len(cleaned) > 200
        or cleaned.startswith(("/", "~"))
        or "\\" in cleaned
        or any(segment in ("", ".", "..") for segment in segments)
    ):
        raise BuilderRefused(400, f"{template_id!r} is not a template id.", "template_invalid")
    try:
        located = locate_template(cleaned)
    except (TemplateNotFoundError, FileNotFoundError) as exc:
        raise BuilderRefused(
            404, f"No template {cleaned!r} is shipped with this Depictio.", "template_not_found"
        ) from exc
    resolved = located.resolve()
    if not any(resolved.is_relative_to(root) for root in _shipped_roots()):
        # Only a CLI-context path lookup gets here; the builder serves shipped templates only.
        raise BuilderRefused(
            404, f"No template {cleaned!r} is shipped with this Depictio.", "template_not_found"
        )
    try:
        return _load_yaml(str(resolved))
    except (OSError, ValueError) as exc:
        raise BuilderRefused(
            422, f"The template {cleaned!r} could not be read.", "template_unreadable"
        ) from exc


def draft_for_template(template_id: str) -> dict[str, Any]:
    """:func:`template_to_draft` for a shipped template id (``latest`` resolves)."""
    raw = load_shipped_template(template_id)
    section = raw.get("template")
    resolved_id = section.get("template_id") if isinstance(section, dict) else None
    return template_to_draft(raw, template_id=str(resolved_id or template_id))
