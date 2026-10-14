"""The builder's core runs on the CLI-only install: no FastAPI, no Starlette, no Celery.

``depictio project-builder`` and ``depictio ingest --template`` use these modules
where the server stack is not installed. Only ``routes.py`` and ``standalone.py``
import FastAPI. A fresh interpreter refuses those packages (and the server's
entry points) and runs the whole core through a small build.
"""

from __future__ import annotations

import subprocess
import sys
import textwrap

SCRIPT = textwrap.dedent(
    """
    import importlib.abc
    import sys

    BLOCKED = {"fastapi", "starlette", "celery", "uvicorn", "flower"}
    BLOCKED_MODULES = {"depictio.api.main", "depictio.api.v1.db", "depictio.api.celery_app"}


    class Block(importlib.abc.MetaPathFinder):
        def find_spec(self, name, path, target=None):
            if name.split(".")[0] in BLOCKED or name in BLOCKED_MODULES:
                raise ImportError(f"blocked on the CLI-only install: {name}")


    sys.meta_path.insert(0, Block())

    import json
    import tempfile
    from pathlib import Path

    from depictio.cli.cli.utils.data_root import LocalDataRoot
    from depictio.project_builder import (
        assemble,
        bundle,
        capabilities,
        errors,
        infer,
        match,
        metadata,
        plan,
        roots,
        stores,
        tracks,
        tree,
        validate,
    )

    base = Path(tempfile.mkdtemp())
    (base / "star" / "S1").mkdir(parents=True)
    (base / "star" / "S1" / "quant.tsv").write_text("gene\\tcount\\nA\\t1\\n")
    root = roots.standalone_root(base)

    listing = tree.list_folder(root)
    suggestion = infer.suggest(root, "star/S1/quant.tsv")
    dc = assemble.DcDraft(
        tag="quant",
        type="table",
        mode="recursive",
        regex=r"^quant\\.tsv$",
        props=assemble.TableProps(format="tsv", separator="\\t"),
    )
    draft = assemble.ProjectDraft(
        name="Lab",
        workflows=[assemble.WorkflowDraft(name="main", data_collections=[dc])],
    )
    template = assemble.build_template(draft)
    warnings = validate.validate_inline_template(template, remote=False)
    found = match.match_collection(root, "flat", None, dc)
    report = plan.plan_inline(template, root)
    written = bundle.write_bundle(template, base / "out", data_root=str(base))
    fetched = metadata.fetch_workflow_metadata(
        "https://github.com/nf-core/rnaseq",
        get_text=lambda url: (_ for _ in ()).throw(OSError("offline")),
        get_bytes=lambda url: (_ for _ in ()).throw(OSError("offline")),
    )

    offered = capabilities.capabilities("standalone", None)

    leaked = sorted(
        name for name in sys.modules if name.split(".")[0] in BLOCKED or name in BLOCKED_MODULES
    )
    print(
        json.dumps(
            {
                "leaked": leaked,
                "entries": [e["name"] for e in listing["entries"]],
                "type": suggestion["type"],
                "warnings": warnings,
                "files": found["files"],
                "status": report["data_collections"][0]["status"],
                "written": Path(written["path"]).is_file(),
                "sources": fetched["sources"],
                "realtime": offered["realtime"]["events_enabled"],
            }
        )
    )
    """
)


def test_the_core_works_with_the_server_stack_refused(tmp_path):
    done = subprocess.run(
        [sys.executable, "-c", SCRIPT],
        capture_output=True,
        text=True,
        cwd=tmp_path,
        timeout=120,
    )
    assert done.returncode == 0, done.stderr[-3000:]
    import json

    result = json.loads(done.stdout.strip().splitlines()[-1])
    assert result == {
        "leaked": [],
        "entries": ["star"],
        "type": "table",
        "warnings": [],
        "files": ["star/S1/quant.tsv"],
        "status": "ok",
        "written": True,
        "sources": ["nf-core"],
        "realtime": None,
    }


def test_the_router_module_is_the_one_that_needs_fastapi():
    """``routes.py`` is the only core module allowed to import FastAPI (or the
    standalone server, the other front door)."""
    import ast
    import pathlib

    import depictio.project_builder as package

    importing = set()
    for path in pathlib.Path(package.__file__).parent.glob("*.py"):
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [node.module or ""]
            else:
                continue
            if any(name.split(".")[0] in ("fastapi", "starlette", "celery") for name in names):
                importing.add(path.name)
    assert importing <= {"routes.py", "standalone.py"}
    assert "routes.py" in importing
