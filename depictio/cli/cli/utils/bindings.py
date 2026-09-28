"""``--bind TAG=LOCATION``: point one data collection at where its data actually is.

The user names a *location*; the scan mode is inferred from its shape. That is
the whole point — a template author's choice of scan mode should not dictate
where the person instantiating it is allowed to keep data.

    /scratch/run42/*.csv     -> recursive  (local walk, glob on the basename)
    /scratch/run42           -> recursive  (keeps the template's own pattern)
    ./samplesheet.csv        -> single
    https://host/data.csv    -> url
    s3://bucket/run42/*.csv  -> s3_prefix  (remote listing + glob)
    s3://bucket/run42/a.csv  -> url

Manifests stay explicit (``--manifest``): a local ``.csv`` is data far more
often than it is a manifest, and guessing that from a filename would be the
kind of magic that bites silently.

``--data-root s3://...`` is the automatic counterpart of the same idea: it is a
``--bind`` for *every* data collection, derived from the paths the template
already declares rather than from anything the user has to type. That is what
:func:`remote_scan_for_dc` and :func:`apply_remote_data_root` do, using the same
"the location's shape decides the mode" rule as ``infer_scan``.
"""

from __future__ import annotations

import fnmatch
import os
import re
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from depictio.cli.cli.utils.data_root import DataRoot

GLOB_CHARS = ("*", "?", "[")
REMOTE_SCHEMES = ("s3://", "http://", "https://")

# Scan modes that already name a remote location. A remote data root has
# nothing to add to them, so they are left exactly as the template wrote them.
ALREADY_REMOTE_SCAN_MODES = ("url", "s3_prefix", "manifest")


class BindingError(ValueError):
    """Raised for a malformed or unresolvable ``--bind`` spec."""


def parse_binding(spec: str) -> tuple[str, str]:
    """Split ``TAG=LOCATION``. The location may itself contain ``=`` (query strings)."""
    if "=" not in spec:
        raise BindingError(f"--bind must be TAG=LOCATION, got {spec!r}")
    tag, _, location = spec.partition("=")
    tag, location = tag.strip(), location.strip()
    if not tag:
        raise BindingError(f"--bind is missing a data collection tag: {spec!r}")
    if not location:
        raise BindingError(f"--bind is missing a location for tag {tag!r}")
    return tag, location


def _has_glob(value: str) -> bool:
    return any(char in value for char in GLOB_CHARS)


def _split_glob(location: str) -> tuple[str, str]:
    """Split a globbed path into (directory part, basename glob)."""
    head, _, tail = location.rpartition("/")
    return head, tail


def id_regex_from_glob(pattern: str) -> str | None:
    """Turn a single-``*`` glob into a capture of what the ``*`` matched.

    ``*.samples.csv`` -> ``^([^/]+?)\\.samples\\.csv$``, so the object key
    ``sample_A.samples.csv`` yields the entity id ``sample_A``. That id becomes
    ``depictio_manifest_id``, which is what lets two DCs bound to two different
    prefixes cross-filter each other without a manifest and without any join
    config.

    The capture excludes ``/`` on purpose: under a nested key like
    ``run1/sample_A.samples.csv`` a greedy capture would yield
    ``run1/sample_A``, which would not join against a plain ``sample_A``
    registered from another prefix. Excluding the separator makes the anchored
    match fail on the full key so the caller falls back to the basename.

    Returns None when the glob has no ``*`` or more than one: with several
    wildcards there is no defensible answer as to which one is the id, and a
    wrong join key is worse than none.
    """
    import re as _re

    if pattern.count("*") != 1 or "?" in pattern or "[" in pattern:
        return None
    head, _, tail = pattern.partition("*")
    if not head and not tail:
        return None
    return f"^{_re.escape(head)}([^/]+?){_re.escape(tail)}$"


def infer_scan(location: str, existing_scan: dict | None = None) -> tuple[dict, str | None]:
    """Infer a scan config from a location.

    Returns ``(scan_dict, local_root)``. ``local_root`` is non-None only for
    local recursive binds, where the walk root lives on the *workflow's*
    data_location rather than on the DC's scan parameters, so the caller has to
    place it there.
    """
    lowered = location.lower()

    if lowered.startswith("s3://"):
        if _has_glob(location):
            head, pattern = _split_glob(location)
            params: dict = {"prefix": head + "/", "pattern": pattern}
            id_regex = id_regex_from_glob(pattern)
            if id_regex:
                params["id_regex"] = id_regex
            return {"mode": "s3_prefix", "scan_parameters": params}, None
        if location.endswith("/"):
            return {
                "mode": "s3_prefix",
                "scan_parameters": {"prefix": location, "pattern": "*"},
            }, None
        # A bare s3:// key is one object, same as any other single remote file.
        return {"mode": "url", "scan_parameters": {"url": location}}, None

    if lowered.startswith(("http://", "https://")):
        if _has_glob(location):
            raise BindingError(
                f"Cannot glob over HTTP ({location!r}): HTTPS exposes no listing operation. "
                "Use an s3:// prefix, or --manifest to list the files explicitly."
            )
        return {"mode": "url", "scan_parameters": {"url": location}}, None

    if "://" in location:
        raise BindingError(
            f"Unsupported scheme in {location!r}. Use a local path, https:// or s3://."
        )

    # ---- local ----------------------------------------------------------
    if _has_glob(location):
        head, pattern = _split_glob(location)
        root = str(Path(head).expanduser().resolve()) if head else os.getcwd()
        return (
            {
                "mode": "recursive",
                "scan_parameters": {"regex_config": {"pattern": fnmatch.translate(pattern)}},
            },
            root,
        )

    path = Path(location).expanduser()
    if path.is_dir():
        # Directory with no glob: keep whatever pattern the template already
        # declared for this DC — the user is repointing the root, not
        # redefining what counts as a match. Only fall back to "everything"
        # when there is no prior pattern to preserve.
        pattern = ".*"
        if existing_scan and str(existing_scan.get("mode", "")).lower() == "recursive":
            prior = (existing_scan.get("scan_parameters") or {}).get("regex_config") or {}
            pattern = prior.get("pattern") or pattern
        return (
            {"mode": "recursive", "scan_parameters": {"regex_config": {"pattern": pattern}}},
            str(path.resolve()),
        )

    if not path.exists():
        raise BindingError(
            f"Local path does not exist: {location}. "
            "Pass a glob (e.g. 'dir/*.csv'), an existing file, or a remote URL."
        )
    return {"mode": "single", "scan_parameters": {"filename": str(path.resolve())}}, None


def remote_scan_for_dc(dc_config: dict, root: DataRoot) -> dict | None:
    """The ``scan`` block a data collection needs when its data root is remote.

    Returns the rewritten block, or None when the DC needs no rewrite: it is
    already remote (``url`` / ``s3_prefix`` / ``manifest``), or it is a recipe DC
    with no ``scan`` block at all, whose sources are read through the root by the
    recipe layer instead.

    ``single`` -> ``url`` is required rather than cosmetic. By this point the
    DC's ``filename`` is a fully substituted ``s3://`` URL, and
    ``ScanSingle.validate_filename`` calls ``Path(v).exists()`` in CLI context,
    so leaving the mode alone would fail every remote single-file DC at model
    validation.

    ``recursive`` -> ``s3_prefix`` keeps the template's own regex verbatim (with
    its wildcards expanded exactly as the local walk expands them) and points it
    at the root. The remote listing is the filesystem, so the pattern that
    selected files on disk is the pattern that selects keys under the prefix.

    Args:
        dc_config: The data collection's ``config`` block. Not modified.
        root: The remote data root the DC is being pointed at.
    """
    scan = dc_config.get("scan")
    if not isinstance(scan, dict):
        # No scan block: a `source: transformed` recipe DC.
        return None

    mode = str(scan.get("mode") or "").lower()
    params = scan.get("scan_parameters") or {}

    if mode in ALREADY_REMOTE_SCAN_MODES:
        return None

    if mode == "single":
        filename = params.get("filename")
        if not filename:
            return None
        return {"mode": "url", "scan_parameters": {"url": filename}}

    if mode == "recursive":
        from depictio.cli.cli.utils.scan_utils import construct_full_regex
        from depictio.models.models.data_collections import Regex

        regex_config = params.get("regex_config") or {}
        pattern = construct_full_regex(
            Regex(
                pattern=regex_config.get("pattern") or ".*", wildcards=regex_config.get("wildcards")
            )
        )
        return {
            "mode": "s3_prefix",
            "scan_parameters": {
                "prefix": f"{root.location.rstrip('/')}/",
                "pattern": pattern,
                "pattern_syntax": "regex",
            },
        }

    return None


def apply_remote_data_root(config: dict, root: DataRoot) -> list[str]:
    """Repoint every data collection in ``config`` at a remote data root. In place.

    The automatic ``--bind``: one remote root stands in for a per-DC binding of
    each declared path. An explicit ``--bind`` still runs afterwards and still
    wins, so a user who wants one DC somewhere else is never blocked by this.

    ``structure`` and ``runs_regex`` are left exactly as the template declared
    them: a remote ``sequencing-runs`` template keeps its run structure, and the
    prefix scan honours it the same way the local walk does.

    Returns human-readable notes, one per rewritten DC.
    """
    notes: list[str] = []
    for workflow in config.get("workflows") or []:
        for dc in workflow.get("data_collections") or []:
            dc_config = dc.get("config")
            if not isinstance(dc_config, dict):
                continue
            scan = remote_scan_for_dc(dc_config, root)
            if scan is None:
                continue
            dc_config["scan"] = scan
            notes.append(f"{dc.get('data_collection_tag')} -> {scan['mode']} ({root.location})")

        data_location = workflow.setdefault("data_location", {})
        data_location["locations"] = [root.location]
    return notes


_SENTINEL_RE = re.compile(r"__DEPICTIO_UNBOUND_([A-Z0-9_]+)__")


def _find_sentinels(node) -> set[str]:
    found: set[str] = set()
    if isinstance(node, dict):
        for value in node.values():
            found |= _find_sentinels(value)
    elif isinstance(node, list):
        for value in node:
            found |= _find_sentinels(value)
    elif isinstance(node, str):
        found.update(_SENTINEL_RE.findall(node))
    return found


def _restore_placeholders(node):
    """Put ``{VAR}`` back wherever a sentinel landed, in-place."""
    if isinstance(node, dict):
        for key, value in node.items():
            node[key] = _restore_placeholders(value)
    elif isinstance(node, list):
        for i, value in enumerate(node):
            node[i] = _restore_placeholders(value)
    elif isinstance(node, str):
        return _SENTINEL_RE.sub(lambda m: "{" + m.group(1) + "}", node)
    return node


def assert_no_unbound_vars(config: dict) -> None:
    """Fail if a deferred template variable survived binding.

    ``resolve_template(allow_missing_vars=True)`` stubs required variables the
    user did not supply, betting that --bind will overwrite whatever used them.
    When that bet is wrong the sentinel would otherwise reach the server as a
    literal path, so surface it here with the variable's real name.

    Only ``workflows`` is checked: that is what drives scanning and ingestion.
    ``template_origin`` is provenance recorded for the DB, and a variable that
    was never provided legitimately shows up there — as its original ``{VAR}``
    placeholder, which is what this restores.
    """
    found = _find_sentinels(config.get("workflows"))
    if found:
        raise BindingError(
            f"Template variable(s) {', '.join(sorted(found))} are still required: "
            "the data collections using them were not covered by --bind. "
            "Either add a --bind for them, or pass the variable "
            "(--data-root / --manifest / --var)."
        )

    origin = config.get("template_origin")
    if isinstance(origin, dict):
        variables = origin.get("variables")
        if isinstance(variables, dict):
            for name in [
                k for k, v in variables.items() if isinstance(v, str) and _SENTINEL_RE.search(v)
            ]:
                # Never record a synthetic value as if the user had supplied it.
                variables.pop(name)
        _restore_placeholders(origin)


def apply_bindings(config: dict, specs: list[str]) -> list[str]:
    """Rewrite each named DC's scan config in-place. Returns human-readable notes.

    Raises BindingError when a tag matches no data collection: a silently
    ignored --bind would leave the DC pointing at the template's original
    location, which is exactly the surprise this flag exists to remove.
    """
    notes: list[str] = []
    if not specs:
        return notes

    index: dict[str, tuple[dict, dict]] = {}
    for workflow in config.get("workflows") or []:
        for dc in workflow.get("data_collections") or []:
            tag = dc.get("data_collection_tag")
            if tag:
                index[tag] = (workflow, dc)

    roots: dict[str, str] = {}
    remote_locations: dict[str, list[str]] = {}
    touched: dict[str, dict] = {}
    for spec in specs:
        tag, location = parse_binding(spec)
        if tag not in index:
            raise BindingError(
                f"--bind targets unknown data collection {tag!r}. "
                f"Available: {', '.join(sorted(index)) or 'none'}"
            )
        workflow, dc = index[tag]
        dc_config = dc.setdefault("config", {})
        scan, local_root = infer_scan(location, existing_scan=dc_config.get("scan"))
        dc_config["scan"] = scan
        notes.append(f"{tag} -> {scan['mode']} ({location})")

        workflow_key = str(workflow.get("name") or id(workflow))
        touched[workflow_key] = workflow
        if not local_root:
            remote_locations.setdefault(workflow_key, []).append(location)

        if local_root:
            workflow_name = workflow.get("name") or id(workflow)
            previous = roots.get(str(workflow_name))
            if previous and previous != local_root:
                # data_location is per-workflow, so two local binds under one
                # workflow cannot disagree on the walk root.
                raise BindingError(
                    f"Conflicting local roots for workflow {workflow_name!r}: "
                    f"{previous} vs {local_root}. Local --bind targets in the same "
                    "workflow must share a directory."
                )
            roots[str(workflow_name)] = local_root
            data_location = workflow.setdefault("data_location", {})
            data_location["structure"] = data_location.get("structure") or "flat"
            data_location["locations"] = [local_root]

    # A workflow whose bindings are all remote has no local root left to walk,
    # yet data_location may still hold the template's placeholder (e.g.
    # ['{MANIFEST_URL}']). Remote scan modes ignore it, but leaving an unresolved
    # sentinel there would trip assert_no_unbound_vars. Record where the data
    # actually came from instead.
    for workflow_key, workflow in touched.items():
        if workflow_key in roots:
            continue
        locations = remote_locations.get(workflow_key)
        if not locations:
            continue
        data_location = workflow.setdefault("data_location", {})
        current = data_location.get("locations") or []
        if any("__DEPICTIO_UNBOUND_" in str(item) for item in current) or not current:
            data_location["structure"] = data_location.get("structure") or "flat"
            data_location["locations"] = locations

    return notes
