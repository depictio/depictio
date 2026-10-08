"""Is the running dev server actually serving the code in the repo?

Twice now, a feature has been correct in source, correct in the API, and broken
on screen. Both times the cause was the same: Vite had cached a transform of a
shared renderer from a moment when an import failed to resolve, and kept
serving it. The served `FigureRenderer` contained no reference to
`useDataVersionRequest` while the source contained two, so data time travel
reached cards (whose values come from the app) and nothing else.

Nothing catches that. A compile reads the source. The API tests read the API.
The one thing neither looks at is the bytes the browser is given.

So this fetches modules from the dev server and asserts the markers that must
be present. It is a staleness check, not a logic check — if it fails, restart
the viewer container rather than looking for a bug in the code.
"""

import os
import sys

import requests

# The dev server's public base. `/dashboard/` is its configured base URL, so
# module paths hang off that rather than the root.
VITE = os.environ.get("DEPICTIO_VITE", "http://127.0.0.1:5600") + "/dashboard"
PKG = "/@fs/build/packages/depictio-react-core/src"

#: module path -> markers that must appear in the served transform.
#:
#: Chosen to be the wiring that went stale, not incidental strings: each of
#: these renderers has to read the pin from context and put the version in its
#: fetch effect's dependency list. One without the other is the silent form of
#: this bug — the request body changes while the fetch never re-runs.
#: `definitionKey` is here for the same reason: a renderer whose definition is
#: swapped in place (a single-component restore) must refetch, and without it
#: the change only appears after a page reload.
REQUIRED = {
    f"{PKG}/components/FigureRenderer.tsx": [
        "useDataVersionRequest",
        "versionKey",
        "definitionKey",
    ],
    f"{PKG}/components/TableRenderer.tsx": [
        "useDataVersionRequest",
        "versionKey",
        "definitionKey",
    ],
    f"{PKG}/components/MapRenderer.tsx": [
        "useDataVersionRequest",
        "versionKey",
        "definitionKey",
    ],
    f"{PKG}/components/ImageRenderer.tsx": [
        "useDataVersionRequest",
        "versionKey",
        "definitionKey",
    ],
    f"{PKG}/dataVersions.tsx": ["component_overrides", "data_versions"],
    "/src/EditorApp.tsx": ["DataVersionProvider", "ComponentVersionModal"],
    # The viewer must NOT offer to re-point live data; that is edit-mode only.
    # Asserted as an absence below.
    # `componentOverrides` is required, not optional: a `?version=` preview that
    # sends only data pins renders a past version's numbers through today's
    # component definitions and labels the result as the past. That was a real
    # bug, and it is invisible in source review because both halves are correct
    # on their own.
    "/src/App.tsx": ["DataVersionProvider", "componentOverrides"],
    "/src/versions/preview.ts": ["overridesFromVersion"],
}

#: module path -> markers that must be ABSENT. Time travel controls belong to
#: the editor, and a stale bundle could keep serving a removed one.
FORBIDDEN = {
    # Version history in full: the drawer itself, the per-component modal, and
    # the dataset picker's callback. All of it either writes or re-points the
    # dashboard at data it was not saved with, so all of it is edit-mode.
    "/src/App.tsx": [
        "VersionHistoryDrawer",
        "ComponentVersionModal",
        "onDataPinsChange",
        "onOpenVersionHistory",
    ],
}

failures: list[str] = []


def fetch(path: str) -> str | None:
    try:
        res = requests.get(VITE + path, timeout=30)
    except requests.RequestException as exc:
        print(f"  SKIP  {path}: dev server unreachable ({exc.__class__.__name__})")
        return None
    if res.status_code != 200:
        failures.append(f"{path} -> HTTP {res.status_code}")
        print(f"  FAIL  {path}: HTTP {res.status_code}")
        return None
    return res.text


print(f"dev server: {VITE}\n")
print("1. Time-travel wiring is present in the served modules")
reachable = False
for path, markers in REQUIRED.items():
    body = fetch(path)
    if body is None:
        continue
    reachable = True
    missing = [m for m in markers if m not in body]
    name = path.rsplit("/", 1)[-1]
    if missing:
        failures.append(f"{name} served without {missing}")
        print(f"  FAIL  {name}: missing {missing} — stale transform, restart the viewer")
    else:
        print(f"  PASS  {name}: {', '.join(markers)}")

if not reachable:
    print("\nDev server not reachable; nothing checked.")
    sys.exit(0)

print("\n2. Edit-only controls are absent from the viewer")
for path, markers in FORBIDDEN.items():
    body = fetch(path)
    if body is None:
        continue
    present = [m for m in markers if m in body]
    name = path.rsplit("/", 1)[-1]
    if present:
        failures.append(f"{name} still serves {present}")
        print(f"  FAIL  {name}: still serves {present}")
    else:
        print(f"  PASS  {name}: no {', '.join(markers)}")

print()
if failures:
    print(f"FAILED ({len(failures)}): {'; '.join(failures)}")
    print("\nIf the source looks right, the dev server is serving a stale transform:")
    print("  docker restart <stack>-depictio-viewer-dev")
    sys.exit(1)
print("ALL PASS")
