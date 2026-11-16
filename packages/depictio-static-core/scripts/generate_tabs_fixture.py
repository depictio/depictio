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
MQC_ID = "f1x70000000000000000face"
PROJECT_ID = "f1x7000000000000000000p1"
WF_ID = "f1x7000000000000000000w1"
DC_ID = "dc00000000000000000000a1"  # == manifest-basic's bundled table
MQC_DC_ID = "dc00000000000000000000m1"  # a MultiQC report: listed, not bundled as a table
# The legacy YAML path a template's MultiQC tab carries; the runtime swaps it
# for the inlined logo (it would 404 from a file:// page).
MULTIQC_ICON = "/assets/images/logos/multiqc_icon_color.svg"


def main() -> None:
    manifest = json.loads((FIXTURES / "manifest-basic.json").read_text())

    main_doc = copy.deepcopy(manifest["dashboard"]["doc"])
    main_doc["title"] = "Overview"
    # A persistent filter section: declared on the main tab, drawn on every tab
    # of the family through `fetchCrossTabComponents` (the species filter must
    # still be on screen on "Distributions").
    main_doc["filter_sections"] = [{"name": "Cohort", "persistent": True}]
    for meta in main_doc["stored_metadata"]:
        if meta["index"] == "comp-interactive-1":
            meta["section"] = "Cohort"
            meta["title"] = "Species picker"
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
    mqc_doc = {
        "title": "MultiQC",
        "tab_icon": MULTIQC_ICON,
        "stored_metadata": [
            {
                "index": "comp-text-4",
                "component_type": "text",
                "title": "Quality note",
                "order": 0,
                "body": "MultiQC tab body.",
            },
        ],
        "stored_layout_data": [],
    }
    # The main tab's text links to the MultiQC tab by name: the link draws the
    # tab's own icon, which must be the MultiQC logo, offline.
    for meta in main_doc["stored_metadata"]:
        if meta["index"] == "comp-text-1":
            meta["body"] = f"{meta.get('body', '')}\n\nRead quality in [MultiQC](tab:MultiQC)."

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

    # Every TabEntry field filled, so the vitest contract test can pin the TS
    # mirror's TabEntry against the schema snapshot from this fixture. Two
    # sections ("Analysis", "Quality") under the ungrouped main tab, as the
    # live rail draws a family whose tabs name a `tab_group`.
    def tab(
        tab_id: str,
        title: str,
        order: int,
        doc: dict,
        *,
        icon: str,
        color: str | None,
        group: str | None = None,
        main_name: str | None = None,
        subtitle: str | None = None,
    ) -> dict:
        return {
            "id": tab_id,
            "title": title,
            "tab_order": order,
            "is_main_tab": order == 0,
            "icon": icon,
            "icon_color": color,
            "main_tab_name": main_name,
            "tab_group": group,
            "tab_icon": icon,
            "tab_icon_color": color,
            "subtitle": subtitle,
            "doc": doc,
        }

    manifest["tabs"] = [
        tab(
            MAIN_ID,
            "Fixture dashboard",
            0,
            main_doc,
            icon="mdi:view-dashboard",
            color="orange",
            main_name="Overview",
            subtitle="The run at a glance",
        ),
        tab(
            SECOND_ID,
            "Distributions",
            1,
            second_doc,
            icon="mdi:chart-bell-curve",
            color="blue",
            group="Analysis",
            subtitle="How the measures spread",
        ),
        tab(THIRD_ID, "Details", 2, third_doc, icon="mdi:table", color="grape", group="Analysis"),
        tab(MQC_ID, "MultiQC", 3, mqc_doc, icon=MULTIQC_ICON, color="orange", group="Quality"),
    ]
    # The main tab's document names itself the way the tab list does.
    main_doc["main_tab_name"] = "Overview"
    main_doc["title"] = "Fixture dashboard"
    main_doc["project_id"] = PROJECT_ID
    manifest["dashboard"]["title"] = "Fixture dashboard"

    # The project page's data: every ProjectSummary field filled (the vitest
    # contract test pins the TS mirror against the snapshot from it).
    manifest["project"] = {
        "id": PROJECT_ID,
        "name": "Fixture project",
        "description": "A hand-written project around the penguin fixture table.",
        "project_type": "advanced",
        "registered_at": "2026-08-01 10:00:00",
        "external_url": "https://lims.example.org/projects/42",
        "project_url": f"https://demo.depictio.example/projects/{PROJECT_ID}",
        "template": {
            "template_id": "nf-core/fixture/1.0.0",
            "template_version": "1.2.0",
            "applied_at": "2026-08-01T10:00:00",
        },
        "workflows": [
            {
                "id": WF_ID,
                "name": "fixture-pipeline",
                "tag": "nf-core/fixture",
                "engine": "nextflow",
                "engine_version": "24.10.0",
                "version": "1.0.0",
                "repository_url": "https://github.com/nf-core/fixture",
                "catalog": "nf-core",
            }
        ],
        "data_collections": [
            {
                "id": DC_ID,
                "tag": "penguins",
                "type": "table",
                "metatype": "Aggregate",
                "workflow_id": WF_ID,
                "description": "One row per penguin.",
            },
            {
                "id": MQC_DC_ID,
                "tag": "multiqc_report",
                "type": "multiqc",
                "metatype": None,
                "workflow_id": WF_ID,
                "description": None,
            },
        ],
        "links": [
            {
                "id": "f1x7000000000000000000l1",
                "source_dc_id": DC_ID,
                "source_dc_tag": "penguins",
                "source_column": "species",
                "target_dc_id": MQC_DC_ID,
                "target_dc_tag": "multiqc_report",
                "target_type": "multiqc",
                "resolver": "sample_mapping",
                "target_field": "sample_name",
                "description": "Species to report samples",
                "enabled": True,
            }
        ],
        "joins": [
            {
                "name": "penguins_with_report",
                "left_dc": "penguins",
                "right_dc": "multiqc_report",
                "on_columns": ["species"],
                "how": "left",
                "description": None,
            }
        ],
        "run_parameters": [
            {
                "source": "params",
                "group": "Sampling",
                "key": "island",
                "value": "Biscoe",
                "highlight": True,
            },
            {
                "source": "params",
                "group": "Input",
                "key": "input",
                "value": "…/samplesheet.csv",
                "highlight": False,
            },
        ],
        "run_parameter_files": ["params.json"],
    }

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
    manifest["tiers"]["comp-text-4"] = {"tier": "live", "reason": None, "detail": None}

    second_figure = copy.deepcopy(manifest["frozen"]["comp-figure-1"])
    second_figure["payload"]["figure"]["layout"]["title"]["text"] = "Second tab scatter"
    manifest["frozen"]["comp-figure-2"] = second_figure

    out = FIXTURES / "manifest-tabs.json"
    out.write_text(json.dumps(manifest, indent=1) + "\n")
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
