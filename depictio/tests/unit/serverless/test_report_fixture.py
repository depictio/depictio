"""The report skeleton the demo site and the report-host e2e spec mount into.

It is the DOM Quarto renders from the notebook generator's placeholders, for
the penguins demo manifest; it must not drift from the markup helpers the
generator itself uses (``depictio/notebook/report_runtime.py``).
"""

from __future__ import annotations

from depictio.serverless.examples import generate_report_fixture as fixture


def test_the_committed_skeleton_is_up_to_date() -> None:
    assert fixture.OUT.read_text() == fixture.build(), (
        "depictio/viewer/demo/reports/penguins.html is stale: run "
        "depictio/serverless/examples/generate_report_fixture.py"
    )


def test_the_skeleton_names_every_drawable_tile_once() -> None:
    import json

    manifest = json.loads(fixture.MANIFEST.read_text())
    html = fixture.build()
    tab = manifest["dashboard"]["id"]
    for comp in manifest["dashboard"]["doc"]["stored_metadata"]:
        ref = f"{tab}:{comp['index']}"
        expected = 0 if comp["component_type"] in ("text", "interactive") else 1
        assert html.count(ref) == expected, ref
    assert html.count(fixture.TOKEN) == 1
