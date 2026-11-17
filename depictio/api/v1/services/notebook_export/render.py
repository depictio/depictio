"""Run an exported notebook and keep the report Quarto renders from it.

This is the one place in the export that executes anything. The notebook is the
same file the download hands out, run against the same API the reader's own
copy would call: the report is the export's output, not a second rendering of
the dashboard written for the server.

Quarto is a binary, not a library, so this is a subprocess, with two footguns
of its own, both of which cost a full render to find:

* Execution can be switched off — by a project ``_quarto.yml``, a freeze
  directory, or for an ``.ipynb`` simply by not asking. It then produces a
  report with every result missing and exits 0.
* It picks the first ``python3`` on ``PATH``, and if that interpreter has no
  Jupyter it skips execution — again silently, again exit 0.

So: ``--execute``, ``QUARTO_PYTHON`` pinned to the interpreter running this,
and the log checked for an execution phase before the bytes are handed back.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


class RenderUnavailable(RuntimeError):
    """Quarto is missing, timed out, or failed to produce a report."""


def quarto_binary() -> str | None:
    """The Quarto executable, or ``None`` where it is not installed."""
    return shutil.which(os.environ.get("QUARTO_PATH") or "quarto")


def quarto_version() -> str | None:
    binary = quarto_binary()
    if not binary:
        return None
    try:
        proc = subprocess.run([binary, "--version"], capture_output=True, text=True, timeout=30)
    except Exception:
        return None
    return proc.stdout.strip() or None


def render_available() -> bool:
    """Whether this process could render a report if asked to.

    Both halves are needed and neither is a dependency of the API: Quarto
    drives the render, and it drives it through a Jupyter kernel.
    """
    if not quarto_binary():
        return False
    try:
        import ipykernel  # noqa: F401
        import nbclient  # noqa: F401
    except Exception:
        return False
    return True


#: Set for a render whose output has no browser (the PDF): the notebook client
#: then gives every figure a PNG and every table a markdown copy, which is what
#: a typst page can hold (``depictio.notebook.components``).
STATIC_FIGURES_ENV = "DEPICTIO_STATIC_FIGURES"


def render_quarto_html(
    qmd: bytes,
    *,
    stem: str,
    api_url: str,
    api_token: str | None,
    timeout_s: int = 900,
    extra_env: dict[str, str] | None = None,
) -> bytes:
    """The HTML report for an exported ``.qmd``, executed end to end.

    ``api_url`` and ``api_token`` are what the notebook's own cells read: the
    report is computed with the rights of whoever asked for it, exactly as if
    they had run the file themselves. ``extra_env`` reaches those cells too.
    """
    return _render(
        qmd,
        stem=stem,
        api_url=api_url,
        api_token=api_token,
        timeout_s=timeout_s,
        to="html",
        extra_env=extra_env,
    )


def render_quarto_pdf(
    qmd: bytes,
    *,
    stem: str,
    api_url: str,
    api_token: str | None,
    timeout_s: int = 900,
    extra_env: dict[str, str] | None = None,
) -> bytes:
    """The same document as a PDF, through Quarto's bundled typst (no TeX).

    Executed again, with static figures: a PDF holds no plotly.js, so each
    figure is a PNG (kaleido) and each table a markdown table; the filter
    panel and anything else that only works in a browser is left out, and the
    document says so where it was.
    """
    return _render(
        qmd,
        stem=stem,
        api_url=api_url,
        api_token=api_token,
        timeout_s=timeout_s,
        to="typst",
        extra_env={**(extra_env or {}), STATIC_FIGURES_ENV: "1"},
    )


def _render(
    qmd: bytes,
    *,
    stem: str,
    api_url: str,
    api_token: str | None,
    timeout_s: int,
    to: str,
    extra_env: dict[str, str] | None = None,
) -> bytes:
    if not quarto_binary():
        raise RenderUnavailable(
            "Quarto is not installed on this worker — the HTML report needs the Quarto CLI. "
            "The worker image installs it only when built with `--build-arg WITH_QUARTO=true` "
            "(docker-images/Dockerfile.worker)"
        )
    try:
        import ipykernel  # noqa: F401
        import nbclient  # noqa: F401
    except Exception as exc:
        raise RenderUnavailable(
            "A Jupyter kernel is needed to execute the notebook: install the 'render' extra"
        ) from exc

    env = dict(os.environ)
    # Quarto runs whatever `python3` it finds first, and a report rendered by an
    # interpreter without Jupyter comes out empty and successful.
    env["QUARTO_PYTHON"] = sys.executable
    env["DEPICTIO_API_URL"] = api_url
    if api_token:
        env["DEPICTIO_API_TOKEN"] = api_token
    # The notebook is a client of this deployment, whichever side of it runs.
    env["DEPICTIO_CONTEXT"] = "client"
    # E.g. DEPICTIO_REPORT_RUNTIME_FILE: the report runtime's block, composed
    # by the worker for the document's last cell to print.
    env.update(extra_env or {})

    with tempfile.TemporaryDirectory(prefix="depictio-report-") as tmp:
        src = Path(tmp) / f"{stem}.qmd"
        out = Path(tmp) / f"{stem}.{'pdf' if to == 'typst' else 'html'}"
        src.write_bytes(qmd)
        cmd = [str(quarto_binary()), "render", src.name, "--execute", "--to", to]
        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout_s,
                cwd=tmp,
                env=env,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise RenderUnavailable(f"quarto render timed out after {timeout_s}s") from exc
        log = (proc.stdout or "") + (proc.stderr or "")
        if proc.returncode != 0 or not out.exists():
            raise RenderUnavailable(f"quarto render failed: {log.strip()[-2000:]}")
        if "Executing" not in log:
            raise RenderUnavailable(
                "quarto render produced a report without executing the notebook — "
                "the interpreter it used has no Jupyter kernel"
            )
        return out.read_bytes()
