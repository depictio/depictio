"""The demo site's runtime composition is the producer's.

``viewer/scripts/combined-runtime.mjs`` composes, in JS, what a report embeds
for the demo pages, the CI byte-budget floor and nothing else; the producer
composes the same in Python (``report_runtime.runtime_parts`` with
``combined.output_config``). Both must write the same bytes, or the demo and
the budget measure a file no producer writes.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from depictio.notebook.report_runtime import runtime_parts
from depictio.serverless.combined import output_config

SCRIPT = Path(__file__).resolve().parents[3] / "viewer" / "scripts" / "combined-runtime.mjs"

CASES = [
    {
        "js": 'run("</script>");/*<!--*/',
        "css": ".a{content:'</script>'}",
        "manifest": {"dashboard": {"id": "d1", "title": "Pingüinos </b> <!-- x"}, "n": [1, 2]},
        "config": {"brand": {"primary": "#228be6"}},
        "addons": '<script data-depictio-addon="3dmol">m()</script>',
        "output": "report",
    },
    {
        "js": "run()",
        "css": "",
        "manifest": None,
        "config": {"combined": {"default_view": "report"}},
        "output": "combined",
        "defaultView": "dashboard",
    },
]


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
@pytest.mark.parametrize("case", CASES, ids=["report", "combined"])
def test_the_demo_composes_what_the_producer_does(case: dict, tmp_path: Path) -> None:
    args = tmp_path / "args.json"
    args.write_text(json.dumps(case))
    js = subprocess.run(
        ["node", str(SCRIPT), str(args)], capture_output=True, text=True, check=True
    ).stdout
    config = output_config(case["config"], case["output"], case.get("defaultView", "report"))
    data, code = runtime_parts(
        js=case["js"],
        css=case["css"],
        manifest=case["manifest"],
        config=config,
        addons=case.get("addons", ""),
    )
    assert js == data + code
