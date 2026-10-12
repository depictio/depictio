"""The rules an ad-hoc template must keep before a server resolves it.

``POST /projects/from_run`` normally resolves a template from the server's own
catalogue, which nobody but the operator writes. An inline template comes from
the browser, so it is held to what the Project Builder itself produces: native
scans of files under ``{DATA_ROOT}`` and nothing that reads anything else
(no dashboards, conditionals, provenance globs, recipes, joins, URLs, manifests,
or variables besides ``DATA_ROOT``). ``from_run`` still confines every resolved
location to the data root afterwards; this refuses the rest up front, with
messages the builder can show next to the field at fault.
"""

from __future__ import annotations

import json
import re
from typing import Any

from pydantic import ValidationError

from depictio.project_builder.assemble import DATA_ROOT, TEMPLATE_PREFIX
from depictio.project_builder.errors import BuilderRefused

INVALID = "inline_template_invalid"

MAX_WORKFLOWS = 20
MAX_DATA_COLLECTIONS = 200
MAX_TEMPLATE_BYTES = 256 * 1024
# The reader options a builder collection sets on a text table (polars
# ``scan_csv`` keyword arguments), and the type each must have.
READER_OPTION_TYPES: dict[str, type | tuple[type, ...]] = {
    "separator": str,
    "has_header": bool,
    "skip_rows": int,
    "comment_prefix": str,
    "null_values": list,
    "quote_char": str,
    "decimal_comma": bool,
}
ALLOWED_POLARS_KWARGS = frozenset(READER_OPTION_TYPES)
TEXT_TABLE_FORMATS = frozenset({"csv", "tsv"})

TOP_LEVEL_KEYS = frozenset(
    {
        "template",
        "name",
        "description",
        "project_type",
        "is_public",
        "realtime",
        "data_management_platform_project_url",
        "workflows",
        "links",
    }
)
TEMPLATE_KEYS = frozenset({"template_id", "description", "version", "variables"})
WORKFLOW_KEYS = frozenset(
    {"name", "engine", "version", "repository_url", "catalog", "data_location", "data_collections"}
)
DC_KEYS = frozenset({"data_collection_tag", "description", "optional", "config"})
CONFIG_KEYS = frozenset({"type", "metatype", "scan", "dc_specific_properties"})
TYPES = {
    "table": "table",
    "multiqc": "multiqc",
    "image": "image",
    "indexed_file": "indexed_file",
    "geojson": "geojson",
    "phylogeny": "phylogeny",
    "genomic_tracks": "genomic_tracks",
    "bioimage": "bioimage",
}
METATYPES = frozenset({"Metadata", "Aggregate"})
# Types the builder emits a fixed metatype for.
FIXED_METATYPES = {"indexed_file": "Metadata", "geojson": "GeoJSON", "phylogeny": "Aggregate"}
WILDCARD_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
# A {NAME} in capitals is a template variable to the template engine.
TEMPLATE_VARIABLE_NAME = re.compile(r"[A-Z0-9_]+")
GENOMIC_TRACKS_KEYS = frozenset(
    {
        "format",
        "polars_kwargs",
        "columns_description",
        "uri_column",
        "track_id_column",
        "sample_column",
        "format_column",
        "default_format",
        "index_column",
        "order_column",
        "name_column",
        "color_column",
        "category_column",
        "assembly",
        "tracks_base_path",
        "remote_base_uri",
    }
)
BIOIMAGE_KEYS = frozenset({"format", "ngff_version", "upload", "image_path"})
ASSEMBLY_URI_KEYS = (
    "twobit_uri",
    "chrom_sizes_uri",
    "fasta_uri",
    "fai_uri",
    "gzi_uri",
    "refname_aliases_uri",
)
LINK_KEYS = frozenset(
    {"source_dc_tag", "source_column", "target_dc_tag", "target_type", "link_config", "description"}
)
LINK_CONFIG_KEYS = frozenset({"resolver", "target_field", "pattern"})
LINK_RESOLVERS = frozenset({"direct", "sample_mapping", "pattern", "regex", "wildcard"})
# Collections whose rows a link can read its source column from.
LINK_SOURCE_TYPES = frozenset({"table", "image", "genomic_tracks"})
MAX_LINKS = 100
_TEMPLATE_ID = re.compile(rf"{TEMPLATE_PREFIX}/[a-z0-9][a-z0-9-]{{0,63}}")
REMOTE_REFUSED_TYPES = {
    "indexed_file": (
        "Indexed files can't be read from an S3 prefix yet; build this collection from "
        "a folder on this computer."
    ),
    "image": (
        "Images are uploaded from a folder on this computer; an S3 prefix can't be uploaded from."
    ),
    "bioimage": (
        "Image stores are read from a folder on this computer at ingest; an S3 prefix can't "
        "be scanned for them."
    ),
}
SPATIALDATA_REMOTE = (
    "A SpatialData store is read from a folder on this computer at ingest; an S3 prefix "
    "can't be scanned for it."
)


def _refuse(detail: str) -> BuilderRefused:
    return BuilderRefused(422, detail, INVALID)


def _properties_model(dc_type: str, properties: dict):
    from depictio.models.models.data_collections_types.geojson import DCGeoJSONConfig
    from depictio.models.models.data_collections_types.image import DCImageConfig
    from depictio.models.models.data_collections_types.indexed_file import DCIndexedFileConfig
    from depictio.models.models.data_collections_types.multiqc import DCMultiQC
    from depictio.models.models.data_collections_types.phylogeny import DCPhylogenyConfig
    from depictio.models.models.data_collections_types.table import DCTableConfig
    from depictio.models.models.data_collections_types.table_coordinates import (
        DCTableCoordinatesConfig,
    )
    from depictio.project_builder import capabilities

    if dc_type == "table" and str(properties.get("format") or "").lower() == "spatialdata":
        # Only a table model that reads stores knows the format and its block.
        return DCTableConfig if "spatialdata" in DCTableConfig.model_fields else None
    if dc_type == "table" and ("lat_column" in properties or "lon_column" in properties):
        return DCTableCoordinatesConfig
    if dc_type == "genomic_tracks":
        return getattr(capabilities.genomic_tracks_model(), "DCGenomicTracksConfig", None)
    if dc_type == "bioimage":
        return getattr(capabilities.bioimage_model(), "DCBioimageConfig", None)
    return {
        "table": DCTableConfig,
        "multiqc": DCMultiQC,
        "image": DCImageConfig,
        "indexed_file": DCIndexedFileConfig,
        "geojson": DCGeoJSONConfig,
        "phylogeny": DCPhylogenyConfig,
    }[dc_type]


def _under_root(value: Any, where: str) -> None:
    if not isinstance(value, str) or not (value == DATA_ROOT or value.startswith(DATA_ROOT + "/")):
        raise _refuse(f"{where} must be a path under {DATA_ROOT}, got {value!r}.")
    if ".." in value.split("/"):
        raise _refuse(f"{where} may not contain '..'.")


def _placeholders(value: Any) -> set[str]:
    """The ``{NAME}`` placeholders in ``value``; a regex repetition (``\\d{3}``) is not one."""
    return set(re.findall(r"\{([A-Za-z_][A-Za-z0-9_]*)\}", json.dumps(value)))


def _without_patterns(template: dict) -> dict:
    """A copy of ``template`` without scan regexes and link patterns: their
    ``{name}`` are wildcards and ``{sample}``, checked where they stand."""
    copy = json.loads(json.dumps(template))
    for workflow in copy.get("workflows") or []:
        for dc in (workflow.get("data_collections") or []) if isinstance(workflow, dict) else []:
            try:
                dc["config"]["scan"]["scan_parameters"]["regex_config"].pop("pattern", None)
            except (KeyError, TypeError, AttributeError):
                continue
    for link in copy.get("links") or []:
        try:
            link["link_config"].pop("pattern", None)
        except (KeyError, TypeError, AttributeError):
            continue
    return copy


def _check_wildcards(wildcards: Any, pattern: str, where: str) -> None:
    """Each wildcard named once, as a column could be, standing in the regex,
    with a regex of its own that the scan can splice in."""
    if not isinstance(wildcards, list):
        raise _refuse(f"{where}: wildcards must be a list.")
    names: set[str] = set()
    for wildcard in wildcards:
        if not isinstance(wildcard, dict) or set(wildcard) != {"name", "wildcard_regex"}:
            raise _refuse(f"{where}: each wildcard has a name and a wildcard_regex.")
        name, regex = wildcard["name"], wildcard["wildcard_regex"]
        if not isinstance(name, str) or not WILDCARD_NAME.fullmatch(name):
            raise _refuse(
                f"{where}: wildcard name {name!r} must be a letter or _ then letters, digits or _."
            )
        if TEMPLATE_VARIABLE_NAME.fullmatch(name):
            raise _refuse(
                f"{where}: use a lowercase wildcard name: {{{name}}} reads as a template variable."
            )
        if name in names:
            raise _refuse(f"{where}: the wildcard {name!r} is declared twice.")
        names.add(name)
        if f"{{{name}}}" not in pattern:
            raise _refuse(f"{where}: the regex does not use the wildcard {{{name}}}.")
        if not isinstance(regex, str) or not regex:
            raise _refuse(f"{where}: the wildcard {name!r} needs a regex.")
        try:
            compiled = re.compile(regex)
        except re.error as exc:
            raise _refuse(f"{where}: invalid regex for the wildcard {name!r} ({exc}).") from exc
        if compiled.groupindex:
            raise _refuse(f"{where}: the wildcard {name!r} regex may not name groups.")
    unknown = _placeholders(pattern) - names
    if unknown:
        raise _refuse(
            f"{where}: the regex uses {', '.join('{' + n + '}' for n in sorted(unknown))}, "
            "declared as no wildcard."
        )


def _check_regex(pattern: Any, where: str) -> None:
    if not isinstance(pattern, str) or not pattern:
        raise _refuse(f"{where}: a recursive scan needs a regex.")
    try:
        re.compile(pattern)
    except re.error as exc:
        raise _refuse(f"{where}: invalid regex ({exc}).") from exc


def _check_scan(scan: Any, dc_type: str, where: str, *, remote: bool) -> list[str]:
    warnings: list[str] = []
    if not isinstance(scan, dict):
        raise _refuse(f"{where}: a scan block is required.")
    mode = str(scan.get("mode") or "").lower()
    parameters = scan.get("scan_parameters") or {}
    if mode == "single":
        if set(parameters) - {"filename"}:
            raise _refuse(f"{where}: a single-file scan takes a filename only.")
        _under_root(parameters.get("filename"), f"{where} filename")
        if parameters.get("filename") == DATA_ROOT:
            raise _refuse(f"{where}: a single-file scan names a file, not the data root itself.")
    elif mode == "recursive":
        if set(parameters) - {"regex_config", "max_depth", "ignore"}:
            raise _refuse(f"{where}: unknown recursive scan parameters.")
        regex_config = parameters.get("regex_config") or {}
        if set(regex_config) - {"pattern", "wildcards"}:
            raise _refuse(f"{where}: a regex_config holds a pattern and its wildcards only.")
        pattern = regex_config.get("pattern")
        if not isinstance(pattern, str) or not pattern:
            raise _refuse(f"{where}: a recursive scan needs a regex.")
        _check_wildcards(regex_config.get("wildcards") or [], pattern, where)
        full = pattern
        for wildcard in regex_config.get("wildcards") or []:
            full = full.replace(f"{{{wildcard['name']}}}", f"({wildcard['wildcard_regex']})")
        _check_regex(full, where)
        if remote and (parameters.get("max_depth") is not None or parameters.get("ignore")):
            warnings.append(
                f"{where}: max_depth and ignore apply to local folders only; an S3 prefix "
                "is listed whole."
            )
    else:
        raise _refuse(f"{where}: scan mode must be single or recursive, got {mode!r}.")
    if dc_type in ("geojson", "phylogeny") and mode != "single":
        raise _refuse(f"{where}: a {dc_type} collection reads one file (single scan).")
    return warnings


def _check_reader_options(properties: dict, dc_type: str, where: str) -> None:
    kwargs = properties.get("polars_kwargs") or {}
    if not isinstance(kwargs, dict):
        raise _refuse(f"{where}: polars_kwargs must be a mapping.")
    unknown_kwargs = set(kwargs) - ALLOWED_POLARS_KWARGS
    if unknown_kwargs:
        raise _refuse(
            f"{where}: polars_kwargs takes {', '.join(sorted(ALLOWED_POLARS_KWARGS))} only, "
            f"not {', '.join(sorted(unknown_kwargs))}."
        )
    if not kwargs:
        return
    fmt = str(properties.get("format") or "").lower()
    if fmt not in TEXT_TABLE_FORMATS:
        raise _refuse(f"{where}: reader options apply to csv and tsv files only, not {fmt!r}.")
    for key, value in kwargs.items():
        expected = READER_OPTION_TYPES[key]
        # bool is an int to Python; a skip_rows of True is still not a count.
        if not isinstance(value, expected) or (expected is int and isinstance(value, bool)):
            raise _refuse(f"{where}: polars_kwargs.{key} has the wrong type.")
    if "separator" in kwargs and len(kwargs["separator"]) != 1:
        raise _refuse(f"{where}: the separator is one character.")
    if "quote_char" in kwargs and len(kwargs["quote_char"]) > 1:
        raise _refuse(f"{where}: the quote character is one character.")
    if "skip_rows" in kwargs and kwargs["skip_rows"] < 0:
        raise _refuse(f"{where}: skip_rows can't be negative.")
    if "null_values" in kwargs and not all(isinstance(v, str) for v in kwargs["null_values"]):
        raise _refuse(f"{where}: null_values is a list of strings.")


def _check_coordinates(properties: dict, where: str) -> None:
    has_lat, has_lon = bool(properties.get("lat_column")), bool(properties.get("lon_column"))
    if has_lat != has_lon or (not has_lat and "crs" in properties):
        raise _refuse(f"{where}: map coordinates need both a latitude and a longitude column.")


def _check_assembly(assembly: Any, where: str) -> list[str]:
    from depictio.project_builder.capabilities import assemblies

    if isinstance(assembly, str):
        known = assemblies()
        if known and assembly.lower() not in {name.lower() for name in known}:
            return [
                f"{where}: {assembly!r} is not one of this server's assemblies "
                f"({', '.join(known)}); it must be an alias the genome browser knows."
            ]
        return []
    if not isinstance(assembly, dict):
        raise _refuse(f"{where}: assembly is a preset name or a custom assembly.")
    for key in ASSEMBLY_URI_KEYS:
        value = assembly.get(key)
        if value is None:
            continue
        if isinstance(value, str) and value.lower().startswith(("https://", "s3://")):
            continue
        _under_root(value, f"{where} assembly {key}")
    if not (assembly.get("fasta_uri") or assembly.get("twobit_uri")):
        raise _refuse(f"{where}: a custom assembly needs a FASTA or a 2bit file.")
    return []


def _check_genomic_tracks(properties: dict, where: str, *, remote: bool) -> list[str]:
    unknown = set(properties) - GENOMIC_TRACKS_KEYS
    if unknown:
        raise _refuse(f"{where}: unexpected genomic track settings: {', '.join(sorted(unknown))}.")
    if remote:
        if "tracks_base_path" in properties:
            raise _refuse(
                f"{where}: under an s3:// root tracks are read in place (remote_base_uri)."
            )
        base = properties.get("remote_base_uri")
        if base is None:
            raise _refuse(f"{where}: under an s3:// root, remote_base_uri says where tracks are.")
        _under_root(str(base).rstrip("/"), f"{where} remote_base_uri")
    else:
        if "remote_base_uri" in properties:
            raise _refuse(f"{where}: remote_base_uri is for an s3:// root.")
        if properties.get("tracks_base_path") is not None:
            _under_root(properties["tracks_base_path"], f"{where} tracks_base_path")
    if not str(properties.get("uri_column") or "uri").strip():
        raise _refuse(f"{where}: the uri column can't be empty.")
    default_format = properties.get("default_format")
    if default_format is not None:
        from depictio.project_builder.capabilities import track_formats

        known = track_formats()
        if known and default_format not in known:
            raise _refuse(f"{where}: default_format must be one of {', '.join(known)}.")
    warnings = _check_assembly(properties.get("assembly", "hg38"), where)
    if remote:
        warnings.append(
            f"{where}: tracks under an s3:// prefix are read in place: the server must allow "
            "that bucket (DEPICTIO_JBROWSE_REMOTE_S3_BUCKETS) or they fail when viewed."
        )
    return warnings


def _check_bioimage(properties: dict, where: str) -> None:
    unknown = set(properties) - BIOIMAGE_KEYS
    if unknown:
        raise _refuse(f"{where}: unexpected bioimage settings: {', '.join(sorted(unknown))}.")
    fmt = properties.get("format", "ome-zarr")
    image_path = properties.get("image_path")
    if fmt == "spatialdata":
        if not isinstance(image_path, str) or not re.fullmatch(r"images/[^/]+", image_path):
            raise _refuse(f"{where}: a SpatialData store shows one image: images/<name>.")
    elif image_path is not None:
        raise _refuse(f"{where}: image_path is for a SpatialData store only.")


def _check_properties(config: dict, dc_type: str, where: str, *, remote: bool) -> list[str]:
    warnings: list[str] = []
    properties = config.get("dc_specific_properties")
    if properties is None:
        properties = {}
    if not isinstance(properties, dict):
        raise _refuse(f"{where}: dc_specific_properties must be a mapping.")
    if dc_type == "image" and properties.get("local_images_path") is not None:
        _under_root(properties["local_images_path"], f"{where} local_images_path")
    spatialdata = (
        dc_type == "table" and str(properties.get("format") or "").lower() == "spatialdata"
    )
    if spatialdata:
        from depictio.project_builder.capabilities import spatialdata_tables

        if not spatialdata_tables():
            raise _refuse(f"{where}: this Depictio has no tables read from SpatialData stores yet.")
        if remote:
            raise _refuse(f"{where}: {SPATIALDATA_REMOTE}")
        if properties.get("polars_kwargs") or "lat_column" in properties:
            raise _refuse(f"{where}: a SpatialData table takes no reader options or map columns.")
    else:
        _check_reader_options(properties, dc_type, where)
    if dc_type == "table":
        _check_coordinates(properties, where)
    if dc_type == "indexed_file" and properties.get("sample_regex"):
        try:
            compiled = re.compile(properties["sample_regex"])
        except re.error as exc:
            raise _refuse(f"{where}: invalid sample_regex ({exc}).") from exc
        if "sample" not in compiled.groupindex:
            raise _refuse(
                f"{where}: sample_regex needs a group named sample, e.g. (?P<sample>[^/]+?)\\.vcf\\.gz$."
            )
    if dc_type == "genomic_tracks":
        warnings += _check_genomic_tracks(properties, where, remote=remote)
    if dc_type == "bioimage":
        _check_bioimage(properties, where)
    model = _properties_model(dc_type, properties)
    if model is None:
        return warnings
    # Placeholders are resolved later; validate the shape with a neutral value
    # of the root's kind (a remote base must stay an s3:// URL).
    neutral_root = "s3://data-root" if remote else "/data-root"
    neutral = json.loads(json.dumps(properties).replace(DATA_ROOT, neutral_root))
    try:
        model(**neutral)
    except ValidationError as exc:
        first = exc.errors()[0]
        field = ".".join(str(part) for part in first.get("loc", ())) or "properties"
        raise _refuse(f"{where}: {field}: {first.get('msg')}") from exc
    return warnings


def _check_links(links: Any, types: dict[str, str]) -> None:
    """Links name collections of this project by tag, as a type a link may target."""
    from depictio.models.models.links import DCLink
    from depictio.project_builder.capabilities import link_target_types

    if not isinstance(links, list):
        raise _refuse("links must be a list.")
    if len(links) > MAX_LINKS:
        raise _refuse(f"At most {MAX_LINKS} links.")
    targets = set(link_target_types())
    for index, link in enumerate(links, start=1):
        where = f"Link {index}"
        if not isinstance(link, dict) or set(link) - LINK_KEYS:
            raise _refuse(f"{where}: unexpected keys.")
        config = link.get("link_config") or {}
        if not isinstance(config, dict) or set(config) - LINK_CONFIG_KEYS:
            raise _refuse(f"{where}: link_config takes a resolver, target_field and pattern only.")
        source, target = link.get("source_dc_tag"), link.get("target_dc_tag")
        if source not in types:
            raise _refuse(f"{where}: {source!r} is not a data collection of the project.")
        if target not in types:
            raise _refuse(f"{where}: {target!r} is not a data collection of the project.")
        if source == target:
            raise _refuse(f"{where}: a collection can't filter itself.")
        if types[source] not in LINK_SOURCE_TYPES:
            raise _refuse(f"{where}: {source!r} ({types[source]}) has no rows to filter from.")
        if link.get("target_type") != types[target]:
            raise _refuse(
                f"{where}: target_type must be {types[target]!r}, the type of {target!r}."
            )
        if types[target] not in targets:
            raise _refuse(f"{where}: this Depictio can't filter a {types[target]} collection.")
        resolver = config.get("resolver", "direct")
        if resolver not in LINK_RESOLVERS:
            raise _refuse(f"{where}: unknown resolver {resolver!r}.")
        if resolver == "pattern" and "{sample}" not in str(config.get("pattern") or ""):
            raise _refuse(f"{where}: a pattern link needs a pattern with {{sample}}.")
        if config.get("pattern") is not None and resolver != "pattern":
            raise _refuse(f"{where}: a pattern is for the pattern resolver.")
        try:
            DCLink(**link)
        except ValidationError as exc:
            first = exc.errors()[0]
            raise _refuse(f"{where}: {first.get('msg')}") from exc


def validate_inline_template(template: Any, *, remote: bool) -> list[str]:
    """Refuse (``BuilderRefused`` 422 ``inline_template_invalid``) a template the
    builder could not have produced; return the warnings worth showing.

    ``remote``: the template will be resolved against an ``s3://`` root.
    """
    if not isinstance(template, dict):
        raise _refuse("The template must be a mapping.")
    if len(json.dumps(template)) > MAX_TEMPLATE_BYTES:
        raise _refuse(f"The template is larger than {MAX_TEMPLATE_BYTES // 1024} KB.")
    unknown = set(template) - TOP_LEVEL_KEYS
    if unknown:
        raise _refuse(f"Unexpected top-level keys: {', '.join(sorted(unknown))}.")

    section = template.get("template")
    if not isinstance(section, dict):
        raise _refuse("The template section is missing.")
    if set(section) - TEMPLATE_KEYS:
        raise _refuse(
            "An inline template declares no dashboards, conditionals or provenance: "
            f"{', '.join(sorted(set(section) - TEMPLATE_KEYS))}."
        )
    template_id = str(section.get("template_id") or "")
    if not _TEMPLATE_ID.fullmatch(template_id):
        raise _refuse(
            f"template_id must look like '{TEMPLATE_PREFIX}/<name>', got {template_id!r}."
        )
    variables = section.get("variables") or []
    if any(not isinstance(v, dict) or v.get("name") != "DATA_ROOT" for v in variables):
        raise _refuse("An inline template declares DATA_ROOT as its only variable.")
    body = _without_patterns({k: v for k, v in template.items() if k != "template"})
    extra = _placeholders(body) - {"DATA_ROOT"}
    if extra:
        raise _refuse(f"Unknown placeholders: {', '.join('{' + n + '}' for n in sorted(extra))}.")

    platform_url = template.get("data_management_platform_project_url")
    if platform_url is not None and not re.match(r"https?://\S+$", str(platform_url)):
        raise _refuse("The data management platform URL must be an http(s) URL.")

    workflows = template.get("workflows")
    if not isinstance(workflows, list) or not workflows:
        raise _refuse("A project needs at least one workflow.")
    if len(workflows) > MAX_WORKFLOWS:
        raise _refuse(f"At most {MAX_WORKFLOWS} workflows.")

    from depictio.project_builder.capabilities import UNAVAILABLE, available_types

    present = available_types()
    warnings: list[str] = []
    names: set[str] = set()
    tags: dict[str, str] = {}
    types: dict[str, str] = {}
    table_tags: set[str] = set()
    phylogeny_refs: list[tuple[str, str]] = []
    total = 0
    for workflow in workflows:
        if not isinstance(workflow, dict):
            raise _refuse("Each workflow must be a mapping.")
        if set(workflow) - WORKFLOW_KEYS:
            raise _refuse(
                f"Unexpected workflow keys: {', '.join(sorted(set(workflow) - WORKFLOW_KEYS))}."
            )
        name = str(workflow.get("name") or "").strip()
        if not name:
            raise _refuse("Every workflow needs a name.")
        if name in names:
            raise _refuse(f"Two workflows are named {name!r}: workflow names must be unique.")
        names.add(name)
        location = workflow.get("data_location") or {}
        if location.get("locations") != [DATA_ROOT] or location.get("attached_locations"):
            raise _refuse(f"Workflow {name!r} reads {DATA_ROOT} only.")
        structure = location.get("structure")
        if structure not in ("flat", "sequencing-runs"):
            raise _refuse(f"Workflow {name!r}: structure must be flat or sequencing-runs.")
        if structure == "sequencing-runs":
            runs_regex = location.get("runs_regex")
            if not runs_regex:
                raise _refuse(f"Workflow {name!r}: sequencing runs need a runs regex.")
            _check_regex(runs_regex, f"Workflow {name!r} runs regex")

        collections = workflow.get("data_collections") or []
        if not collections:
            raise _refuse(f"Workflow {name!r} needs at least one data collection.")
        for dc in collections:
            total += 1
            if not isinstance(dc, dict) or set(dc) - DC_KEYS:
                raise _refuse(f"Workflow {name!r}: unexpected data collection keys.")
            tag = str(dc.get("data_collection_tag") or "").strip()
            if not tag:
                raise _refuse(f"Workflow {name!r}: every data collection needs a tag.")
            if tag in tags:
                raise _refuse(
                    f"The tag {tag!r} is used in workflows {tags[tag]!r} and {name!r}: tags "
                    "must be unique in the project."
                )
            tags[tag] = name
            where = f"{tag!r}"
            config = dc.get("config")
            if not isinstance(config, dict) or set(config) - CONFIG_KEYS:
                raise _refuse(f"{where}: unexpected config keys (no source, join or transform).")
            dc_type = TYPES.get(str(config.get("type") or "").lower())
            if dc_type is None:
                raise _refuse(f"{where}: unsupported type {config.get('type')!r}.")
            if dc_type not in present:
                raise _refuse(f"{where}: {UNAVAILABLE.get(dc_type, 'not available here.')}")
            if remote and dc_type in REMOTE_REFUSED_TYPES:
                raise _refuse(f"{where}: {REMOTE_REFUSED_TYPES[dc_type]}")
            metatype = config.get("metatype")
            allowed = {FIXED_METATYPES[dc_type]} if dc_type in FIXED_METATYPES else METATYPES
            if metatype is not None and metatype not in allowed:
                raise _refuse(f"{where}: metatype must be {' or '.join(sorted(allowed))}.")
            types[tag] = dc_type
            warnings += _check_scan(config.get("scan"), dc_type, where, remote=remote)
            warnings += _check_properties(config, dc_type, where, remote=remote)
            if dc_type == "table":
                table_tags.add(tag)
            if dc_type == "image" and not (config.get("dc_specific_properties") or {}).get(
                "s3_base_folder"
            ):
                warnings.append(
                    f"{where}: no s3_base_folder. The server picks one in its bucket when it "
                    "creates the project; `depictio ingest` needs it set."
                )
            if dc_type == "phylogeny":
                ref = (config.get("dc_specific_properties") or {}).get("metadata_dc_tag")
                if ref:
                    phylogeny_refs.append((tag, ref))
    if total > MAX_DATA_COLLECTIONS:
        raise _refuse(f"At most {MAX_DATA_COLLECTIONS} data collections.")
    for tag, ref in phylogeny_refs:
        if ref not in table_tags:
            raise _refuse(
                f"{tag!r}: metadata_dc_tag {ref!r} is not a table collection of the project."
            )
    if template.get("links") is not None:
        _check_links(template["links"], types)
    return warnings
