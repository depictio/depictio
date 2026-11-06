"""Every mutating route is classified against the published lock (#1303).

A published project refuses every change to what was published (409). The guard
is an explicit call in each route, so a route added later is unguarded unless
someone decides otherwise. This test makes that decision mandatory: every
POST/PUT/PATCH/DELETE route of the API must be listed here, either in
``GUARDED`` (it reaches a lock helper) or in ``EXEMPT`` (with a reason).

Adding a route: if it changes a project, its dashboards, its data collections or
their data, guard it with one of the helpers in
``projects_endpoints/publish_lock.py`` and list it in ``GUARDED``. Otherwise list
it in ``EXEMPT`` with the reason it cannot change a release.
"""

from __future__ import annotations

import importlib
import inspect
import types

import pytest
from fastapi.routing import APIRoute

MUTATING = {"POST", "PUT", "PATCH", "DELETE"}
PREFIX = "depictio.api.v1.endpoints."

#: Depth to which a route's calls are followed to find a lock check: route ->
#: shared helper -> its helper -> the ``publish_lock`` call.
MAX_DEPTH = 4


_LOCK_MODULE = "depictio.api.v1.endpoints.projects_endpoints.publish_lock"

#: The ``publish_lock`` helpers whose call shows a route consults the lock.
_LOCK_HELPERS = {
    "assert_project_unlocked",
    "assert_dc_project_unlocked",
    "assert_workflow_project_unlocked",
    "assert_dashboard_unlocked",
    "assert_dashboard_creation_allowed",
}


def _is_lock_marker(value: object) -> bool:
    """A lock helper, or the 409 detail the import routes answer with.

    Matched by module and name, not identity: a test that reloads or patches
    ``publish_lock`` must not make a guarded route look unguarded.
    """
    if inspect.isfunction(value):
        return value.__module__ == _LOCK_MODULE and value.__name__ in _LOCK_HELPERS
    from depictio.api.v1.endpoints.projects_endpoints.publish_lock import LOCKED_DETAIL

    return isinstance(value, str) and value == LOCKED_DETAIL


def _code_names(code: types.CodeType) -> set[str]:
    names = set(code.co_names)
    for const in code.co_consts:
        if isinstance(const, types.CodeType):
            names |= _code_names(const)
    return names


def _import(dotted: str) -> types.ModuleType | None:
    try:
        return importlib.import_module(dotted)
    except ImportError:
        return None


def _reaches_lock(fn: object, depth: int, seen: set[int]) -> bool:
    """Whether ``fn``, or a depictio function it calls, uses a lock marker."""
    fn = inspect.unwrap(fn)  # ty: ignore[invalid-argument-type]
    if id(fn) in seen or depth > MAX_DEPTH:
        return False
    seen.add(id(fn))
    code = getattr(fn, "__code__", None)
    if code is None:
        return False
    module_globals = getattr(fn, "__globals__", {})
    names = _code_names(code)
    # Function-level ``from depictio.x import y`` leaves both the module path
    # and ``y`` in co_names; resolve ``y`` against that module too.
    local_modules = [_import(n) for n in names if n.startswith("depictio.")]
    local_modules = [m for m in local_modules if m is not None]
    for name in names:
        value = module_globals.get(name)
        if value is None:
            value = next(
                (getattr(m, name) for m in local_modules if hasattr(m, name)),
                None,
            )
        if value is None:
            continue
        if _is_lock_marker(value):
            return True
        if inspect.ismodule(value):
            if not value.__name__.startswith("depictio."):
                continue
            # ``publish_lock.assert_project_unlocked(...)`` style access
            if value.__name__ == _LOCK_MODULE and names & _LOCK_HELPERS:
                return True
            continue
        if (
            inspect.isfunction(value)
            and value.__module__.startswith("depictio.")
            and _reaches_lock(value, depth + 1, seen)
        ):
            return True
    return False


def _dependency_calls(dependant) -> list[object]:
    calls = []
    for dep in dependant.dependencies:
        if dep.call is not None:
            calls.append(dep.call)
        calls.extend(_dependency_calls(dep))
    return calls


def _route_consults_lock(route: APIRoute) -> bool:
    candidates = [route.endpoint, *_dependency_calls(route.dependant)]
    return any(_reaches_lock(c, 0, set()) for c in candidates)


#: Modules none of whose routes can change a release, with the reason.
EXEMPT_MODULES: dict[str, str] = {
    "user_endpoints.routes": "accounts and tokens, not project content",
    "groups_endpoints.routes": "groups, not project content",
    "auth_endpoints.oidc_routes": "login",
    "comments_endpoints.routes": "comments are conversation about a release, not part of it",
    "dashboards_endpoints.filter_state_routes": "per-viewer filter state",
    "figure_endpoints.routes": "renders a preview, writes nothing",
    "advanced_viz_endpoints.routes": "computes a render, writes nothing",
    "advanced_viz_endpoints.structure_resolver": "resolves a structure for rendering",
    "export_endpoints.routes": "exports a component, writes nothing",
    "monitoring_endpoints.routes": "ingestion and agent telemetry; the CLI preflight refuses a locked project",
    "cli_endpoints.routes": "validates a CLI config, writes nothing",
    "backup_endpoints.routes": "admin-only instance backup and restore",
    "utils_endpoints.routes": "instance branding and admin maintenance",
    "jobs_endpoints.routes": "job bookkeeping",
    "celery_endpoints.routes": "worker bookkeeping",
    "events_endpoints.routes": "event stream",
    "analytics_endpoints.routes": "usage analytics",
    "analytics_data_endpoints.routes": "usage analytics",
    "catalog_endpoints.routes": "template catalog, not a project",
    "jbrowse_endpoints.routes": "session rendering",
}

_DASH = "dashboards_endpoints.routes"
_VER = "dashboards_endpoints.versions_routes"
_PROJ = "projects_endpoints.routes"
_DC = "datacollections_endpoints.routes"
_DT = "deltatables_endpoints.routes"
_MQC = "multiqc_endpoints.routes"
_LINKS = "links_endpoints.routes"
_WF = "workflow_endpoints.routes"
_MIG = "migrate_endpoints.routes"

#: Routes of the content modules that must consult the lock: (module, function).
GUARDED: set[tuple[str, str]] = {
    # dashboards: content and structure of a published dashboard family
    (_DASH, "edit_dashboard"),
    (_DASH, "save_dashboard"),
    (_DASH, "update_dashboard_appearance"),
    (_DASH, "upload_dashboard_logo"),
    (_DASH, "delete_dashboard"),
    (_DASH, "update_tab"),
    (_DASH, "delete_tab"),
    (_DASH, "reorder_tabs"),
    (_DASH, "import_dashboard_from_yaml"),
    (_DASH, "import_dashboard_from_json"),
    # versions: rewriting a published dashboard from its history
    (_VER, "delete_dashboard_version"),
    (_VER, "restore_dashboard_version"),
    (_VER, "restore_component_from_version"),
    # project document, its storage and its ingestion
    (_PROJ, "trigger_project_ingestion"),
    (_PROJ, "ingest_manifest"),
    (_PROJ, "refresh_manifest"),
    (_PROJ, "set_project_storage"),
    (_PROJ, "delete_project_storage"),
    (_PROJ, "update_project"),
    (_PROJ, "delete_project"),
    (_PROJ, "toggle_public_private"),
    # data collections and their data
    (_DC, "delete_datacollection"),
    (_DC, "update_data_collection_name"),
    (_DC, "update_dc_specific_properties"),
    (_DC, "delete_data_collection_by_id"),
    (_DC, "append_table_dc"),
    (_DC, "replace_table_dc"),
    (_DC, "clear_table_dc"),
    (_DC, "create_data_collection_from_upload"),
    (_DC, "create_data_collection_from_url"),
    (_DC, "create_multiqc_data_collection_from_upload"),
    (_DT, "upsert_deltatable"),
    (_DT, "delete_deltatable"),
    (_MQC, "create_multiqc_report"),
    (_MQC, "update_multiqc_report"),
    (_MQC, "delete_multiqc_report"),
    (_MQC, "delete_all_reports_for_data_collection"),
    (_MQC, "replace_multiqc_reports"),
    (_MQC, "append_multiqc_reports"),
    ("files_endpoints.routes", "create_file"),
    ("files_endpoints.routes", "delete_files_batch"),
    ("files_endpoints.routes", "delete_file"),
    ("runs_endpoints.routes", "create_run"),
    ("runs_endpoints.routes", "delete_runs_batch"),
    ("runs_endpoints.routes", "delete_run"),
    (_LINKS, "create_link"),
    (_LINKS, "update_link"),
    (_LINKS, "delete_link"),
    (_WF, "create_workflow"),
    (_WF, "update_workflow"),
    (_WF, "delete_workflow"),
    # an import over a published project is refused; only an approved
    # migration request rewrites one
    (_MIG, "import_project"),
    (_MIG, "import_project_zip"),
}

_READ = "computes a response, writes nothing"
_NEW = "creates a new project, which is not published"
_PERM = "permissions are not part of a release (the lock is content and data)"

#: Routes of the content modules that need no guard, with the reason.
EXEMPT: dict[tuple[str, str], str] = {
    (_DASH, "sync_dashboard_permissions_with_projects"): _PERM,
    (_DASH, "bulk_get_component_data_endpoint"): _READ,
    (_DASH, "bulk_compute_cards"): _READ,
    (_DASH, "render_figure_endpoint"): _READ,
    (_DASH, "render_table_endpoint"): _READ,
    (_DASH, "render_image_paths_endpoint"): _READ,
    (_DASH, "render_map_endpoint"): _READ,
    (_DASH, "map_data_endpoint"): _READ,
    (_DASH, "render_jbrowse_endpoint"): _READ,
    (_DASH, "jbrowse_calls_endpoint"): _READ,
    (_DASH, "jbrowse_call_density_endpoint"): _READ,
    (_DASH, "render_multiqc_endpoint"): _READ,
    (_DASH, "render_multiqc_general_stats_endpoint"): _READ,
    (_DASH, "validate_yaml_content"): _READ,
    (_DASH, "validate_json_import"): _READ,
    (_DASH, "funnel_values_endpoint"): _READ,
    (_DASH, "filter_options_endpoint"): _READ,
    (_DASH, "data_version_status_endpoint"): _READ,
    (_VER, "create_dashboard_version"): "records the current state; changes no content",
    (_VER, "pin_dashboard_version"): "ledger metadata; changes no content",
    (_VER, "unpin_dashboard_version"): "ledger metadata; changes no content",
    (_VER, "rename_dashboard_version"): "ledger metadata; changes no content",
    (_PROJ, "export_project_template"): _READ,
    (_PROJ, "test_project_storage"): _READ,
    (_PROJ, "test_run_storage"): _READ,
    (_PROJ, "post_run_file_preview"): _READ,
    (_PROJ, "post_s3_dirs"): _READ,
    (_PROJ, "post_folder_inspect"): _READ,
    (_PROJ, "post_find_runs"): _READ,
    (_PROJ, "create_project"): _NEW,
    (_PROJ, "create_project_from_manifest"): _NEW,
    (_PROJ, "create_project_from_run"): _NEW,
    (_PROJ, "clean_example_projects"): "admin-only reset of the bundled example projects",
    (_PROJ, "add_or_update_permission"): _PERM,
    (_PROJ, "lock_project"): "the lock's own admin switch",
    (_PROJ, "unlock_project"): "the lock's own admin switch",
    (_DC, "multiqc_uniformity_check"): _READ,
    (_DT, "batch_check_deltatables_exist"): _READ,
    (_DT, "get_breakdown_filtered"): _READ,
    (_DT, "get_card_metric"): _READ,
    (_DT, "get_preview_filtered"): _READ,
    (_MQC, "multiqc_preview"): _READ,
    (_LINKS, "resolve_link"): _READ,
    (_WF, "compare_models_endpoint"): _READ,
    (_MIG, "export_project"): "reads the project into a bundle",
    ("migrate_endpoints.targets_routes", "create_target"): (
        "instance registry of push targets, no project content"
    ),
    ("migrate_endpoints.targets_routes", "delete_target"): (
        "instance registry of push targets, no project content"
    ),
    ("migrate_endpoints.push_routes", "preflight"): _READ,
    ("migrate_endpoints.inbound_routes", "inbound_preflight"): _READ,
    ("migrate_endpoints.inbound_routes", "inbound_probe"): _READ,
    ("migrate_endpoints.inbound_routes", "inbound_check"): _READ,
    ("migrate_endpoints.inbound_routes", "inbound_create_request"): (
        "stages a request; with a pairing key nothing reaches a project until an admin "
        "approves it, with an invite code the invite is that approval given in advance "
        "and the import is the same one-writer-past-the-lock job"
    ),
    ("migrate_endpoints.requests_routes", "retry_request"): (
        "re-runs an approved import a restart interrupted: the same one writer past the lock"
    ),
    ("migrate_endpoints.invites_routes", "create_invite"): (
        "instance registry of invite codes, no project content"
    ),
    ("migrate_endpoints.invites_routes", "revoke_invite"): (
        "instance registry of invite codes, no project content"
    ),
    ("migrate_endpoints.push_routes", "retry_push"): (
        "starts a new push: reads the project into a bundle, like start_push"
    ),
    ("migrate_endpoints.requests_routes", "approve_request"): (
        "the approved migration is the one writer past the lock: it records the "
        "replaced state and a new version, then sets the lock again"
    ),
    ("migrate_endpoints.requests_routes", "reject_request"): "writes the request record only",
    ("migrate_endpoints.requests_routes", "revalidate_request"): "writes the request record only",
    ("migrate_endpoints.requests_routes", "regenerate_thumbnails"): (
        "queues screenshots of imported dashboards: writes thumbnail PNGs, no project content"
    ),
    ("migrate_endpoints.push_routes", "start_push"): (
        "reads the project into a bundle; a published project may be pushed on"
    ),
}


def _walk(routes):
    for route in routes:
        if isinstance(route, APIRoute):
            yield route
            continue
        inner = getattr(route, "original_router", None) or route
        sub = getattr(inner, "routes", None)
        if sub is not None and sub is not routes:
            yield from _walk(sub)


def _mutating_routes() -> list[tuple[str, str, str, APIRoute]]:
    from depictio.api.v1.endpoints.routers import router

    found = []
    for route in _walk(router.routes):
        methods = route.methods & MUTATING
        if not methods:
            continue
        module = route.endpoint.__module__
        assert module.startswith(PREFIX), module
        found.append((module[len(PREFIX) :], route.endpoint.__name__, route.path, route))
    return found


# Resolved when the module is collected, before any test reloads the settings
# module (``test_security_pr1`` does), which breaks a late import of the
# routers and of the modules they import lazily.
_ROUTES = _mutating_routes()
_BY_KEY = {(m, n): r for m, n, _, r in _ROUTES}
_CONSULTS = {key: _route_consults_lock(route) for key, route in _BY_KEY.items()}


def test_routes_are_found():
    assert len(_ROUTES) > 100


def test_every_mutating_route_is_classified():
    unclassified = [
        f"{', '.join(sorted(r.methods & MUTATING))} {path} ({module}.{name})"
        for module, name, path, r in _ROUTES
        if module not in EXEMPT_MODULES
        and (module, name) not in GUARDED
        and (module, name) not in EXEMPT
    ]
    assert not unclassified, (
        "Mutating routes not classified against the published lock. Guard each one "
        "(projects_endpoints/publish_lock.py) and add it to GUARDED, or add it to "
        "EXEMPT with a reason:\n  " + "\n  ".join(unclassified)
    )


def test_classifications_name_real_routes():
    real = set(_BY_KEY)
    stale = sorted((GUARDED | set(EXEMPT)) - real)
    assert not stale, f"Classified routes that no longer exist: {stale}"
    assert not GUARDED & set(EXEMPT), "A route cannot be both guarded and exempt"
    for module, _name in GUARDED:
        assert module not in EXEMPT_MODULES, module


@pytest.mark.parametrize("key", sorted(GUARDED), ids=lambda k: f"{k[0]}.{k[1]}")
def test_guarded_routes_consult_the_lock(key):
    assert _CONSULTS[key], (
        f"{key[0]}.{key[1]} is listed as guarded but reaches no publish_lock check"
    )


def test_exempt_reasons_are_given():
    for key, reason in EXEMPT.items():
        assert reason.strip(), key
    for module, reason in EXEMPT_MODULES.items():
        assert reason.strip(), module
