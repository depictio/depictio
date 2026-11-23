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

Quarto and the kernel it starts get an environment of their own
(``render_environment``), not the worker's: the worker holds the S3 root
credentials, the Mongo URL and every ``DEPICTIO_*`` secret, and the document
needs none of them. It needs to find its binaries and a home, a locale, and the
API's URL with a token minted for this one render. Quarto's and Jupyter's own
variables pass, so does a proxy. The process runs in a session of its own, so a
timeout kills the kernel and whatever it started along with Quarto.
"""

from __future__ import annotations

import contextlib
import importlib
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
from contextlib import AbstractContextManager
from pathlib import Path

# What the render may inherit from the worker, by name. Nothing else passes.
_ENV_NAMES = frozenset(
    {
        "PATH",
        "HOME",
        "USER",
        "LOGNAME",
        "SHELL",
        "TMPDIR",
        "TEMP",
        "TMP",
        "LANG",
        "LANGUAGE",
        "TZ",
        "PYTHONPATH",
        "VIRTUAL_ENV",
        "SSL_CERT_FILE",
        "SSL_CERT_DIR",
        "REQUESTS_CA_BUNDLE",
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "NO_PROXY",
        "http_proxy",
        "https_proxy",
        "no_proxy",
        "XDG_CACHE_HOME",
        "XDG_CONFIG_HOME",
        "XDG_DATA_HOME",
        "XDG_RUNTIME_DIR",
        "PLAYWRIGHT_BROWSERS_PATH",
        # depictio.notebook's own switch, not a secret.
        "DEPICTIO_NOTEBOOK_NATIVE",
    }
)
# Locale (LC_*), Quarto's (QUARTO_*), Jupyter's and Deno's (Quarto's runtime).
_ENV_PREFIXES = re.compile(r"^(LC_|QUARTO_|JUPYTER_|IPYTHON|DENO_)")


def render_environment(
    api_url: str, api_token: str | None, extra: dict[str, str] | None = None
) -> dict[str, str]:
    """The environment a render runs in: the allow-list above, plus what it needs.

    Never the worker's own ``os.environ``: a document that read a variable (a
    shortcode in its output, code in a kernel) would find no credential there.
    """
    env = {k: v for k, v in os.environ.items() if k in _ENV_NAMES or _ENV_PREFIXES.match(k)}
    # Quarto runs whatever `python3` it finds first, and a report rendered by an
    # interpreter without Jupyter comes out empty and successful.
    env["QUARTO_PYTHON"] = sys.executable
    env["DEPICTIO_API_URL"] = api_url
    if api_token:
        env["DEPICTIO_API_TOKEN"] = api_token
    # The notebook is a client of this deployment, whichever side of it runs.
    env["DEPICTIO_CONTEXT"] = "client"
    env.update(extra or {})
    return env


def _kill_group(proc: subprocess.Popen) -> None:
    """Quarto, the kernel it started and anything the kernel started."""
    try:
        os.killpg(proc.pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        pass
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:  # nothing more to do for a process that will not die
        pass


class RenderUnavailable(RuntimeError):
    """Quarto is missing, timed out, or failed to produce a report.

    ``str()`` is safe to show the user; ``log`` (Quarto's output) is for the
    worker's log only.
    """

    def __init__(self, message: str, *, log: str = "") -> None:
        super().__init__(message)
        self.log = log


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


def render_unavailable_reason() -> str | None:
    """Why ``render_available`` is False, as one sentence for the user, or
    ``None`` when a render could run."""
    if not quarto_binary():
        return (
            "Quarto is not installed on this server, so reports cannot be rendered. "
            "Install Quarto (https://quarto.org/docs/get-started/) and the render extra: "
            "pip install 'depictio[render]'"
        )
    try:
        import ipykernel  # noqa: F401
        import nbclient  # noqa: F401
    except Exception:
        return (
            "The server has no Jupyter kernel to execute a report with. "
            "Install Quarto (https://quarto.org/docs/get-started/) and the render extra: "
            "pip install 'depictio[render]'"
        )
    return None


#: Set for a render whose output has no browser (the PDF): the notebook client
#: then gives every figure a PNG and every table a markdown copy, which is what
#: a typst page can hold (``depictio.notebook.components``).
STATIC_FIGURES_ENV = "DEPICTIO_STATIC_FIGURES"

#: What Quarto prints when ``--cache`` found the notebook's code unchanged and
#: read its executed outputs back instead of running the kernel.
CACHE_HIT_MARK = "(Notebook read from cache)"


def render_quarto_html(
    qmd: bytes,
    *,
    stem: str,
    api_url: str,
    api_token: str | None,
    timeout_s: int = 900,
    extra_env: dict[str, str] | None = None,
    workdir: str | None = None,
    cache: bool = False,
    force: bool = False,
) -> bytes:
    """The HTML report for an exported ``.qmd``, executed end to end.

    ``api_url`` and ``api_token`` are what the notebook's own cells read: the
    report is computed with the rights of whoever asked for it, exactly as if
    they had run the file themselves. ``extra_env`` reaches those cells too.

    ``workdir`` renders into a persistent directory instead of a temporary
    one: with ``cache`` (or ``force``), Quarto's jupyter-cache keeps the
    executed cells there across renders, so a preview that only changed text
    reuses the last run's outputs. ``force`` asks for ``--cache-refresh``
    instead: re-execute every cell, and refresh the cache with the results.
    """
    return _render(
        qmd,
        stem=stem,
        api_url=api_url,
        api_token=api_token,
        timeout_s=timeout_s,
        to="html",
        extra_env=extra_env,
        workdir=workdir,
        cache=cache,
        force=force,
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
    workdir: str | None = None,
    cache: bool = False,
    force: bool = False,
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

    env = render_environment(api_url, api_token, extra_env)

    if workdir is None:
        workspace: AbstractContextManager[str] = tempfile.TemporaryDirectory(
            prefix="depictio-report-"
        )
    else:
        # A persistent workdir (the preview cache): Quarto's own cache lives
        # here and outlives the render, so the next preview of the same
        # dashboard re-executes only the cells that changed. Nothing is
        # cleaned up: the directory is the cache.
        wd = Path(workdir)
        wd.mkdir(parents=True, exist_ok=True)
        workspace = contextlib.nullcontext(str(wd))
    with workspace as tmp:
        src = Path(tmp) / f"{stem}.qmd"
        out = Path(tmp) / f"{stem}.{'pdf' if to == 'typst' else 'html'}"
        src.write_bytes(qmd)
        cmd = [str(quarto_binary()), "render", src.name, "--execute", "--to", to]
        if workdir is not None and (cache or force):
            # Only worth it with jupyter-cache on this interpreter; without it
            # the flags are unknown to Quarto and the render would fail.
            try:
                importlib.import_module("jupyter_cache")
            except Exception:
                pass
            else:
                cmd.append("--cache-refresh" if force else "--cache")
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            cwd=tmp,
            env=env,
            start_new_session=True,
        )
        try:
            stdout, _ = proc.communicate(timeout=timeout_s)
        except subprocess.TimeoutExpired as exc:
            _kill_group(proc)
            raise RenderUnavailable(f"quarto render timed out after {timeout_s}s") from exc
        except BaseException:
            # A soft time limit, a worker shutdown: nothing of the render may
            # outlive the task (its temporary directory is about to go).
            _kill_group(proc)
            raise
        finally:
            # The kernel, should Quarto have left it running.
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                pass
        log = stdout or ""
        if proc.returncode != 0 or not out.exists():
            # The log is the server's: it can hold paths and what the document
            # printed. The caller gets a sentence (``RenderUnavailable.log``).
            raise RenderUnavailable("quarto render failed", log=log.strip()[-4000:])
        # A preview's cache hit executes nothing by design: Quarto read the
        # notebook it executed last time, whose code has not changed.
        from_cache = "--cache" in cmd and CACHE_HIT_MARK in log
        if "Executing" not in log and not from_cache:
            raise RenderUnavailable(
                "quarto render produced a report without executing the notebook — "
                "the interpreter it used has no Jupyter kernel"
            )
        return out.read_bytes()
