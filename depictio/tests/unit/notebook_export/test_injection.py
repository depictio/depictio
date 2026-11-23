"""Request and author text in an export is never run, included or expanded.

A rendered report executes the document on a worker, and a downloaded one on
its reader's machine, so a string from the export request (a filter's column
name or value) or from the dashboard (a title, a text tile, a caption, a
section) that reaches the ``.qmd`` as a Quarto construct is code execution:

* an inline expression `` `{python} …` ``, run even inside raw HTML;
* a shortcode, ``{{< env … >}}`` or ``{{< include … >}}``, expanded nearly
  everywhere, a code cell's string literals included;
* a fenced chunk ```` ```{python} ```` inside prose;
* a line terminator other than ``\\n`` inside a ``# comment`` line.

The generator half runs everywhere. The render half runs the document through
Quarto (``QUARTO_PATH`` for a copy off ``PATH``) and skips without it.
"""

from __future__ import annotations

import copy
import json
import os
import re
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import polars as pl
import pytest
import yaml

from depictio.api.v1.services.notebook_export.generator import (
    DCPlan,
    ExportPlan,
    StagePlan,
    generate_qmd,
)
from depictio.api.v1.services.notebook_export.quarto import QuartoFrontMatter
from depictio.api.v1.services.notebook_export.render import quarto_binary, render_available
from depictio.models.models.analysis_state import AnalysisState
from depictio.notebook.qmd_safe import ZWSP, meta_text
from depictio.tests.unit.notebook_export.test_generator import (
    PENGUINS_DASHBOARD,
    PENGUINS_DC,
    PENGUINS_DTYPES,
    python_chunks,
)

SECRET_VAR = "DEPICTIO_POC_SECRET"
SECRET = "TOPSECRET9f2c"
INCLUDED = "INCLUDEDMARKER7a1"

# Each payload leaves a marker in the output only if Quarto ran or expanded it.
MARKERS = {
    "inline": ("`{python} 1000000+42`", "1000042"),
    "env": ("{{< env " + SECRET_VAR + " >}}", SECRET),
    "fence": ("\n\n```{python}\nprint('PWNED' + 'FENCE')\n```\n\n", "PWNEDFENCE"),
    "cr": ("x\rprint('PWNED' + 'CR')", "PWNEDCR"),
    "ls": ("x print('PWNED' + 'LS')", "PWNEDLS"),
    "vt": ("x\x0b!echo PWNED''VT", "PWNEDVT"),
}


def _payload(include_path: str) -> str:
    bits = [p for p, _ in MARKERS.values()]
    bits.append("{{< include " + include_path + " >}}")
    bits.append("{{{< env " + SECRET_VAR + " >}}}")
    return " ".join(bits)


def _poisoned(obj, payload: str, keys: tuple[str, ...]):
    """Every string under ``keys`` in ``obj`` (recursively) with the payload added."""
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            if k in keys and isinstance(v, str):
                out[k] = f"{v} {payload}"
            else:
                out[k] = _poisoned(v, payload, keys)
        return out
    if isinstance(obj, list):
        return [_poisoned(v, payload, keys) for v in obj]
    return obj


def _plan(penguins_tabs, payload: str, *, pdf: bool = False) -> ExportPlan:
    tabs = _poisoned(
        copy.deepcopy(penguins_tabs),
        payload,
        (
            "title",
            "subtitle",
            "description",
            "caption",
            "body",
            "name",
            "main_tab_name",
        ),
    )
    poisoned_filter = {
        # An index no component has: the label comes from the request alone.
        "index": "not-a-component",
        "column_name": f"species {payload}",
        "interactive_component_type": "MultiSelect",
        "value": ["Adelie", payload],
        "metadata": {"dc_id": PENGUINS_DC, "column_name": "species"},
    }
    state = AnalysisState.model_validate(
        {
            "filters": [poisoned_filter],
            "groups": [
                {
                    "id": "g1",
                    "name": f"Group {payload}",
                    "color": "#e64980",
                    "dc_id": PENGUINS_DC,
                    "column_name": "individual_id",
                    "values": ["N1A1"],
                    "filter_active": False,
                }
            ],
            "context": {"dashboard_id": PENGUINS_DASHBOARD},
        }
    )
    stage = StagePlan(
        index="not-a-component",
        label=f"species {payload}",
        column="species",
        interactive_component_type="MultiSelect",
        value=["Adelie", payload],
        source_dc_id=PENGUINS_DC,
        per_dc={
            PENGUINS_DC: [
                {
                    "interactive_component_type": "MultiSelect",
                    "column_name": "species",
                    "value": ["Adelie", payload],
                }
            ]
        },
        rows_by_dc={PENGUINS_DC: 3},
    )
    return ExportPlan(
        tabs=tabs,
        project={"name": f"Penguins {payload}", "workflows": []},
        state=state,
        dcs=[
            DCPlan(
                dc_id=PENGUINS_DC,
                tag="penguins_complete",
                dtypes=PENGUINS_DTYPES,
                initial_rows=4,
                n_cols=len(PENGUINS_DTYPES),
            )
        ],
        stages=[stage],
        title=f"Penguins {payload}",
        subtitle=f"Sub {payload}",
        exported_by=f"someone {payload}",
        instance="depictio.example.org",
        warnings=[f"warning {payload}"],
        pdf=pdf,
    )


_LIVE = (
    re.compile(r"\{\{+\s*[<%]"),  # a shortcode
    re.compile(r"`[ \t]*\{(?!=)"),  # an inline expression, or a chunk fence
    re.compile(r"~{3,}[ \t]*\{"),
)


def _markdown_and_code(src: str) -> tuple[str, list[str]]:
    chunks = python_chunks(src)
    md = re.sub(r"^(`{3,})\{python\}\n.*?\n\1$", "", src, flags=re.S | re.M)
    return md, chunks


@pytest.mark.parametrize("pdf", [False, True])
def test_no_live_construct_reaches_the_document(penguins_tabs, pdf):
    src = generate_qmd(_plan(penguins_tabs, _payload("/etc/hostname"), pdf=pdf))
    md, chunks = _markdown_and_code(src)
    for pattern in _LIVE:
        found = pattern.findall(md)
        assert not found, f"{pattern.pattern}: {found[:3]}"
    # The generator's own chunks are the only executable ones.
    assert len(re.findall(r"^\s*(`{3,}|~{3,})\s*\{(?!=)", src, flags=re.M)) == len(chunks)
    for chunk in chunks:
        assert not re.search(r"\{\{+\s*[<%]", chunk), chunk[:200]
        for line in chunk.split("\n"):
            assert not re.search(r"[\r\v\f\x1c-\x1e\x85  ]", line), repr(line)
    # The payload is still there for the reader to see.
    assert "env " + SECRET_VAR in md


def test_a_poisoned_cover_date_reaches_the_front_matter_inert():
    """The cover's date is author text: it reaches the front matter through
    ``meta_text``, neutralised the same way as a poisoned title."""
    poison = "d >}} {{< env X >}} `{python} 1`"
    out = QuartoFrontMatter(title=f"t {poison}", date=poison).to_yaml()
    doc = yaml.safe_load(out)
    assert doc["date"] == meta_text(poison)
    assert doc["date"] == doc["title"].removeprefix("t ")
    for pattern in _LIVE:
        assert not pattern.findall(out), pattern.pattern
    # The pairs are broken by the zero-width space, the backtick is an entity.
    assert ZWSP in doc["date"] and "&#96;" in out


def test_the_downloaded_notebook_keeps_the_authors_code_and_the_report_does_not(penguins_tabs):
    tabs = copy.deepcopy(penguins_tabs)
    tabs[0]["stored_metadata"].append(
        {
            "index": "code-fig",
            "component_type": "figure",
            "mode": "code",
            "title": "Authored",
            "dc_id": PENGUINS_DC,
            "code_content": "import os\nfig = px.scatter(df, x='year', y='body_mass_g')",
        }
    )
    plan = _plan(tabs, "plain")
    assert "import os" in generate_qmd(plan)
    plan.author_code = False
    src = generate_qmd(plan)
    assert "import os" not in src
    assert "client.component(" in src and "'code-fig'" in src


# ---------------------------------------------------------------------------
# Through Quarto.
# ---------------------------------------------------------------------------


class _OfflineApi(BaseHTTPRequestHandler):
    """The dashboard documents, and nothing else: every other call fails the
    way an unreachable API does, and the tiles say so and move on."""

    docs: dict[str, dict] = {}

    def log_message(self, *args):
        pass

    def _send(self, code: int, payload: dict) -> None:
        body = json.dumps(payload).encode()
        self.send_response(code)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        m = re.search(r"/dashboards/get/([0-9a-f]+)", self.path)
        if m and m.group(1) in self.docs:
            return self._send(200, self.docs[m.group(1)])
        self._send(503, {"detail": "offline test API"})

    def do_POST(self):
        n = int(self.headers.get("content-length") or 0)
        if n:
            self.rfile.read(n)
        self._send(503, {"detail": "offline test API"})


@pytest.fixture(scope="module")
def rendered(penguins_tabs, tmp_path_factory):
    if quarto_binary() is None or not render_available():
        pytest.skip("Quarto and a Jupyter kernel are needed to render")
    work = tmp_path_factory.mktemp("injection")
    include = work / "included.txt"
    include.write_text(INCLUDED)
    data = work / "data"
    data.mkdir()
    pl.DataFrame(
        {
            "individual_id": ["N1A1", "N1A2", "N2A1", "N2A2"],
            "species": ["Adelie", "Adelie", "Gentoo", "Chinstrap"],
            "island": ["Biscoe", "Dream", "Biscoe", "Dream"],
            "sex": ["male", "female", "male", None],
            "year": [2007, 2008, 2009, 2009],
            "body_mass_g": [3700.0, 3400.0, 5000.0, 3600.0],
            "bill_length_mm": [39.1, 38.0, 47.0, 51.0],
            "bill_depth_mm": [18.7, 17.0, 15.0, 19.0],
            "flipper_length_mm": [181.0, 186.0, 215.0, 196.0],
        },
        schema=PENGUINS_DTYPES,
    ).write_parquet(data / f"{PENGUINS_DC}.parquet")

    plan = _plan(penguins_tabs, _payload(str(include)), pdf=True)
    handler = type("Api", (_OfflineApi,), {"docs": {str(t["dashboard_id"]): t for t in plan.tabs}})
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    env = {
        **os.environ,
        SECRET_VAR: SECRET,
        "QUARTO_PYTHON": sys.executable,
        "DEPICTIO_API_URL": f"http://127.0.0.1:{server.server_address[1]}",
        "DEPICTIO_API_TOKEN": "offline",
        "DEPICTIO_DATA_DIR": str(data),
        "DEPICTIO_CONTEXT": "client",
    }
    out: dict[str, str] = {}
    try:
        for to in ("html", "typst"):
            src = generate_qmd(plan)
            (work / "poc.qmd").write_text(src)
            cmd = [str(quarto_binary()), "render", "poc.qmd", "--execute", "--to", to]
            if to == "typst":
                cmd += ["-M", "keep-typ:true"]
                env["DEPICTIO_STATIC_FIGURES"] = "1"
            proc = subprocess.run(
                cmd, cwd=work, env=env, capture_output=True, text=True, timeout=900
            )
            log = proc.stdout + proc.stderr
            assert proc.returncode == 0, log[-3000:]
            assert "Executing" in log
            target = work / ("poc.html" if to == "html" else "poc.typ")
            out[to] = target.read_text(errors="replace") + "\n" + log
    finally:
        server.shutdown()
    return out


@pytest.mark.parametrize("to", ["html", "typst"])
@pytest.mark.parametrize("marker", sorted(MARKERS))
def test_nothing_in_the_payload_runs_or_expands(rendered, to, marker):
    assert MARKERS[marker][1] not in rendered[to]


@pytest.mark.parametrize("to", ["html", "typst"])
def test_no_file_is_included_and_no_variable_read(rendered, to):
    assert INCLUDED not in rendered[to]
    assert SECRET not in rendered[to]
    # And the payload is shown as the text it is.
    assert SECRET_VAR in rendered[to]
