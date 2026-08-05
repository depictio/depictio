#!/usr/bin/env python
"""Generate ``fixtures/manifest-tabs.json`` — a multi-tab bundle manifest.

Derived from ``fixtures/manifest-basic.json`` so the two stay in step: the
entry tab IS the basic fixture's dashboard, byte for byte, which is what lets
the tab specs assert that a family behaves like the single-tab bundle plus
pills. Two further tabs carry their own documents and their own component
indices (uuid-like in a real export, never colliding across tabs).

The fixture also fills every ``provenance`` field and marks one component
``frozen`` / ``celery_compute`` — the two things a hand-written single-tab
fixture cannot exercise.

    python packages/depictio-static-core/scripts/generate_tabs_fixture.py
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
FIXTURES = HERE.parent / "fixtures"

MAIN_ID = "f1x70000000000000000c0de"  # == manifest-basic's dashboard id
SECOND_ID = "f1x70000000000000000cafe"
THIRD_ID = "f1x70000000000000000beef"


def main() -> None:
    manifest = json.loads((FIXTURES / "manifest-basic.json").read_text())

    main_doc = copy.deepcopy(manifest["dashboard"]["doc"])
    main_doc["title"] = "Overview"
    manifest["dashboard"] = {"id": MAIN_ID, "title": "Overview", "doc": main_doc}

    second_doc = {
        "title": "Distributions",
        "stored_metadata": [
            {
                "index": "comp-figure-2",
                "component_type": "figure",
                "wf_id": None,
                "dc_id": "dc00000000000000000000a1",
                "visu_type": "scatter",
                "mode": "ui",
            },
            {
                "index": "comp-text-2",
                "component_type": "text",
                "title": "Second tab note",
                "order": 1,
                "body": "Second tab body.",
            },
        ],
        "stored_layout_data": [],
    }
    third_doc = {
        "title": "Details",
        "stored_metadata": [
            {
                "index": "comp-text-3",
                "component_type": "text",
                "title": "Third tab note",
                "order": 0,
                "body": "Third tab body.",
            },
        ],
        "stored_layout_data": [],
    }

    manifest["tabs"] = [
        {
            "id": MAIN_ID,
            "title": "Overview",
            "tab_order": 0,
            "is_main_tab": True,
            "icon": "mdi:view-dashboard",
            "icon_color": "orange",
            "doc": main_doc,
        },
        {
            "id": SECOND_ID,
            "title": "Distributions",
            "tab_order": 1,
            "is_main_tab": False,
            "icon": "mdi:chart-bell-curve",
            "icon_color": "blue",
            "doc": second_doc,
        },
        {
            "id": THIRD_ID,
            "title": "Details",
            "tab_order": 2,
            "is_main_tab": False,
            "icon": "mdi:table",
            "icon_color": "grape",
            "doc": third_doc,
        },
    ]

    manifest["provenance"] = {
        "exported_by": "curator@example.org",
        # Deliberately naive (no offset) — that is what the API writes, and the
        # sidebar formatter has to read it as UTC rather than as local time.
        "exported_at": "2026-08-03T09:15:00",
        "source": "https://demo.depictio.example",
        "project_name": "Fixture project",
        "dashboard_url": f"https://demo.depictio.example/dashboard/{MAIN_ID}",
    }

    # A Celery-computed view: shipped as the payload the worker produced at
    # export time, so no filter can move it.
    manifest["tiers"]["comp-figure-2"] = {
        "tier": "frozen",
        "reason": "celery_compute",
        "detail": "computed at export time — filters do not refresh this view",
    }
    manifest["tiers"]["comp-text-2"] = {"tier": "live", "reason": None, "detail": None}
    manifest["tiers"]["comp-text-3"] = {"tier": "live", "reason": None, "detail": None}

    second_figure = copy.deepcopy(manifest["frozen"]["comp-figure-1"])
    second_figure["payload"]["figure"]["layout"]["title"]["text"] = "Second tab scatter"
    manifest["frozen"]["comp-figure-2"] = second_figure

    out = FIXTURES / "manifest-tabs.json"
    out.write_text(json.dumps(manifest, indent=1) + "\n")
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
