"""The notebook's header: what was exported, from where, and how to run it."""

from __future__ import annotations

from datetime import datetime
from typing import Any

HOW_TO_RUN = """\
**How to run**

```bash
pip install depictio-cli marimo            # the client, and marimo itself
export DEPICTIO_API_URL={api_url}
export DEPICTIO_API_TOKEN=...              # a long-lived token from the "CLI agents" page
marimo edit {stem}.py
```

Jupyter: `marimo export ipynb {stem}.py -o {stem}.ipynb --no-include-outputs`, then open it.
Quarto: download the Quarto variant and run `quarto render {stem}.quarto.ipynb`.
Offline: set `DEPICTIO_DATA_DIR` to a folder holding `<dc_id>.parquet` files instead of the
API variables; the cells marked *rendered by Depictio* need the API and are skipped offline.
"""


def _md_escape(text: object) -> str:
    return str(text).replace("|", "\\|").replace("\n", " ")


def provenance_table(entries: list[dict[str, Any]], *, limit: int = 40) -> str:
    """The run provenance (``TemplateOrigin.run_provenance``) as a markdown table.

    Highlighted entries first, then the rest in their stored order, grouped
    by ``group``; capped so a pipeline with hundreds of parameters does not
    turn the header into a wall.
    """
    if not entries:
        return ""
    ordered = sorted(enumerate(entries), key=lambda ie: (not bool(ie[1].get("highlight")), ie[0]))
    rows = [e for _, e in ordered][:limit]
    lines = ["| Group | Parameter | Value |", "| --- | --- | --- |"]
    for e in rows:
        lines.append(
            f"| {_md_escape(e.get('group') or '')} | `{_md_escape(e.get('key') or '')}` | "
            f"{_md_escape(e.get('value') if e.get('value') is not None else 'null')} |"
        )
    if len(entries) > limit:
        lines.append(f"| … | *{len(entries) - limit} more entries not shown* | |")
    return "\n".join(lines)


def header_markdown(
    *,
    title: str,
    subtitle: str | None,
    project: dict[str, Any] | None,
    exported_by: str | None,
    exported_at: datetime,
    instance: str | None,
    api_url: str,
    stem: str,
    state_version: int,
    warnings: list[str],
) -> str:
    parts = [f"# {title}"]
    if subtitle:
        parts.append(f"*{subtitle}*")
    who = f" by {exported_by}" if exported_by else ""
    where = f" from {instance}" if instance else ""
    parts.append(
        f"Exported{where} on {exported_at.strftime('%Y-%m-%d %H:%M UTC')}{who} "
        f"(analysis state v{state_version}). Every cell below is what the dashboard "
        "computed for that view: the same table, the same filters, in the same order."
    )
    project = project or {}
    workflows = project.get("workflows") or []
    if project.get("name") or workflows:
        wf_bits = []
        for wf in workflows:
            if not isinstance(wf, dict):
                continue
            engine = wf.get("engine") or {}
            engine_txt = ""
            if isinstance(engine, dict) and engine.get("name"):
                engine_txt = f" ({engine.get('name')}"
                if engine.get("version"):
                    engine_txt += f" {engine.get('version')}"
                engine_txt += ")"
            wf_bits.append(f"`{wf.get('workflow_tag') or wf.get('name')}`{engine_txt}")
        proj_line = f"**Project** — {project.get('name') or ''}"
        if wf_bits:
            proj_line += "; workflows: " + ", ".join(wf_bits)
        parts.append(proj_line)
    origin = project.get("template_origin") or {}
    entries = origin.get("run_provenance") if isinstance(origin, dict) else None
    if entries:
        parts.append("**Run provenance**\n\n" + provenance_table(list(entries)))
        files = origin.get("run_provenance_files") or []
        if files:
            parts.append("Read from: " + ", ".join(f"`{f}`" for f in files))
    parts.append(HOW_TO_RUN.format(api_url=api_url, stem=stem))
    if warnings:
        parts.append("**Notes from the export**\n\n" + "\n".join(f"- {w}" for w in warnings))
    return "\n\n".join(parts)
