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

TOP_LEVEL_KEYS = frozenset(
    {"template", "name", "description", "project_type", "is_public", "realtime", "workflows"}
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
}
_TEMPLATE_ID = re.compile(rf"{TEMPLATE_PREFIX}/[a-z0-9][a-z0-9-]{{0,63}}")
REMOTE_REFUSED_TYPES = {
    "indexed_file": (
        "Indexed files can't be read from an S3 prefix yet; build this collection from "
        "a folder on this computer."
    ),
    "image": (
        "Images are uploaded from a folder on this computer; an S3 prefix can't be uploaded from."
    ),
}


def _refuse(detail: str) -> BuilderRefused:
    return BuilderRefused(422, detail, INVALID)


def _properties_model(dc_type: str):
    from depictio.models.models.data_collections_types.geojson import DCGeoJSONConfig
    from depictio.models.models.data_collections_types.image import DCImageConfig
    from depictio.models.models.data_collections_types.indexed_file import DCIndexedFileConfig
    from depictio.models.models.data_collections_types.multiqc import DCMultiQC
    from depictio.models.models.data_collections_types.phylogeny import DCPhylogenyConfig
    from depictio.models.models.data_collections_types.table import DCTableConfig

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
    return set(re.findall(r"\{([A-Za-z0-9_]+)\}", json.dumps(value)))


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
    elif mode == "recursive":
        if set(parameters) - {"regex_config", "max_depth", "ignore"}:
            raise _refuse(f"{where}: unknown recursive scan parameters.")
        regex_config = parameters.get("regex_config") or {}
        if set(regex_config) - {"pattern"}:
            raise _refuse(f"{where}: wildcards are not supported here.")
        _check_regex(regex_config.get("pattern"), where)
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


def _check_properties(config: dict, dc_type: str, where: str) -> None:
    properties = config.get("dc_specific_properties")
    if properties is None:
        properties = {}
    if not isinstance(properties, dict):
        raise _refuse(f"{where}: dc_specific_properties must be a mapping.")
    if dc_type == "image" and properties.get("local_images_path") is not None:
        _under_root(properties["local_images_path"], f"{where} local_images_path")
    model = _properties_model(dc_type)
    # Placeholders are resolved later; validate the shape with a neutral value.
    neutral = json.loads(json.dumps(properties).replace(DATA_ROOT, "/data-root"))
    try:
        model(**neutral)
    except ValidationError as exc:
        first = exc.errors()[0]
        field = ".".join(str(part) for part in first.get("loc", ())) or "properties"
        raise _refuse(f"{where}: {field}: {first.get('msg')}") from exc


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
    extra = _placeholders({k: v for k, v in template.items() if k != "template"}) - {"DATA_ROOT"}
    if extra:
        raise _refuse(f"Unknown placeholders: {', '.join('{' + n + '}' for n in sorted(extra))}.")

    workflows = template.get("workflows")
    if not isinstance(workflows, list) or not workflows:
        raise _refuse("A project needs at least one workflow.")
    if len(workflows) > MAX_WORKFLOWS:
        raise _refuse(f"At most {MAX_WORKFLOWS} workflows.")

    warnings: list[str] = []
    names: set[str] = set()
    tags: dict[str, str] = {}
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
            if remote and dc_type in REMOTE_REFUSED_TYPES:
                raise _refuse(f"{where}: {REMOTE_REFUSED_TYPES[dc_type]}")
            warnings += _check_scan(config.get("scan"), dc_type, where, remote=remote)
            _check_properties(config, dc_type, where)
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
    return warnings
