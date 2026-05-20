"""Strip every advanced_viz showcase dashboard down to a single full-screen viz.

Drops cards / interactives / tables / figures (and their layout entries),
keeps only the lone advanced_viz component, and resizes it to fill the grid
so we can take clean per-viz screenshots from a running depictio instance.

Skips dashboard_overview.json — that one is a curated 4-viz overview tab.
"""

from __future__ import annotations

import json
from pathlib import Path

SEED_DIR = Path(
    "/Users/tweber/Gits/workspaces/depictio-workspace/"
    "depictio-worktrees/claude-volcano-plot-interactive-cTRTQ/"
    "depictio/projects/init/advanced_viz_showcase/.db_seeds"
)
SKIP = {"dashboard_overview.json"}

# Target layout: fill the right panel grid. depictio uses a 12-column grid;
# h=10 lines (~300px content area, ~360px with the viz frame chrome) keeps
# the whole viz inside a typical viewport (≥720p) without vertical scroll.
FILL_W = 12
FILL_H = 8


def strip(path: Path) -> tuple[bool, str]:
    data = json.loads(path.read_text())
    components = data.get("stored_metadata", [])
    viz_entries = [c for c in components if c.get("component_type") == "advanced_viz"]
    if len(viz_entries) != 1:
        return False, f"expected exactly 1 advanced_viz, got {len(viz_entries)}"
    viz = viz_entries[0]
    viz_index = viz.get("index")
    if not viz_index:
        return False, "viz missing 'index' field"

    # Strip everything except the lone advanced_viz.
    data["stored_metadata"] = [viz]

    # Drop all left-panel filters and reshape the right panel to a single
    # full-screen tile for the viz.
    data["left_panel_layout_data"] = []
    data["right_panel_layout_data"] = [
        {
            "i": f"box-{viz_index}",
            "x": 0,
            "y": 0,
            "w": FILL_W,
            "h": FILL_H,
            "static": False,
            "resizeHandles": ["se", "s", "e", "sw", "w"],
        }
    ]

    # Empty button data — no add-component noise on the screenshot.
    data["stored_add_button"] = {"count": 0}
    if "buttons_data" in data:
        data["buttons_data"]["add_components_button"] = {"count": 0}

    path.write_text(json.dumps(data, indent=2) + "\n")
    return True, f"kept viz {viz_index!r} ({viz.get('viz_kind', '?')})"


def main() -> None:
    rows = []
    for path in sorted(SEED_DIR.glob("dashboard_*.json")):
        if path.name in SKIP:
            rows.append((path.name, "SKIP", "in skip-list"))
            continue
        ok, msg = strip(path)
        rows.append((path.name, "OK" if ok else "FAIL", msg))

    print(f"{'File':<40} {'Status':<6} Detail")
    print("-" * 90)
    for name, status, detail in rows:
        print(f"{name:<40} {status:<6} {detail}")


if __name__ == "__main__":
    main()
