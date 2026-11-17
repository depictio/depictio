"""The notebook's header: what was exported, from where, and how to run it."""

from __future__ import annotations

from datetime import datetime
from html import escape as _esc
from typing import Any

HOW_TO_RUN = """\
```bash
pip install depictio-cli jupyter itables py3Dmol   # the client, its kernel, tables, structures
export DEPICTIO_API_URL={api_url}
export DEPICTIO_API_TOKEN=...              # a long-lived token from the "CLI agents" page
quarto render {stem}.qmd                   # or `quarto preview {stem}.qmd` while you edit
```

Quarto picks the first `python3` on your PATH; if that one has no Jupyter it renders a report
with every result missing and still exits 0, so point `QUARTO_PYTHON` at the interpreter you
installed into. Any editor with Quarto support (VS Code, Positron, RStudio) runs the cells one
by one as well.
`itables` is optional: without it tables print as plain HTML, every row still there. So is
`py3Dmol`: without it a 3D structure is drawn as its backbone.
Offline: set `DEPICTIO_DATA_DIR` to a folder holding `<dc_id>.parquet` files instead of the
API variables; the cells marked *rendered by Depictio* need the API and show a placeholder
saying so offline.
"""


# The parameters block is the one section of the export that is not a dashboard
# section, so it has no author-picked icon to inherit. It still gets one, from
# the same Iconify set the dashboard's own sections draw from, so the header
# does not read as the one unlabelled block in the document.
PROVENANCE_ICON = "mdi:tune-variant"

# The second half of the header's provenance: not what the pipeline was run
# with, but what produced this file — which Depictio, which project, which
# dashboard. A reader who wants to go back to the source needs the ids, not
# just the titles, and a reader debugging a stale export needs the versions.
EXPORT_DETAILS_ICON = "mdi:server-outline"
# "How to run": the commands that re-execute this document.
RUN_ICON = "mdi:console-line"


def _md_escape(text: object) -> str:
    return str(text).replace("|", "\\|").replace("\n", " ")


def provenance_table(entries: list[dict[str, Any]], *, limit: int = 40) -> str:
    """The run provenance (``TemplateOrigin.run_provenance``) as an HTML table.

    HTML rather than markdown: this sits inside the header's collapsible
    ``<details>`` block, and markdown syntax inside a raw HTML block is not
    reliably re-parsed by pandoc — an HTML table renders as written.
    Highlighted entries first, then the rest in their stored order; capped so
    a pipeline with hundreds of parameters does not turn the header into a
    wall.
    """
    if not entries:
        return ""
    ordered = sorted(enumerate(entries), key=lambda ie: (not bool(ie[1].get("highlight")), ie[0]))
    rows = [e for _, e in ordered][:limit]
    trs = "".join(
        "<tr>"
        f'<td style="padding:2px 12px 2px 0;color:#868e96;white-space:nowrap">'
        f"{_esc(str(e.get('group') or ''))}</td>"
        f'<td style="padding:2px 12px 2px 0"><code>{_esc(str(e.get("key") or ""))}</code></td>'
        # Pipeline parameters are full of long unbroken URLs and S3 URIs. Left
        # to itself the table grows as wide as its widest value and spills past
        # the page column; wrapping mid-token keeps it inside.
        f'<td style="padding:2px 0;overflow-wrap:anywhere">'
        f"{_esc(str(e.get('value') if e.get('value') is not None else 'null'))}</td>"
        "</tr>"
        for e in rows
    )
    more = (
        f'<div style="font-size:0.8rem;color:#868e96;margin-top:4px">'
        f"{len(entries) - limit} more entries not shown</div>"
        if len(entries) > limit
        else ""
    )
    return (
        '<table style="border-collapse:collapse;font-size:0.85rem;'
        f'width:100%;max-width:100%">{trs}</table>{more}'
    )


def details_table(rows: list[tuple[str, str]]) -> str:
    """A label/value table for the export's own provenance.

    Values are plain text; a newline in one becomes a line break, which is how
    a row with several entries (the data collections) stays one row.
    """
    trs = "".join(
        "<tr>"
        f'<td style="padding:2px 12px 2px 0;color:#868e96;white-space:nowrap;'
        f'vertical-align:top">{_esc(label)}</td>'
        f'<td style="padding:2px 0;overflow-wrap:anywhere">'
        f"{'<br>'.join(_esc(line) for line in str(value).split(chr(10)))}</td>"
        "</tr>"
        for label, value in rows
        if value
    )
    return (
        '<table style="border-collapse:collapse;font-size:0.85rem;'
        f'width:100%;max-width:100%">{trs}</table>'
    )


# The parameters block's anchor: a text tile's ``[Settings](params:key)`` link
# (the app opens its run-parameters dialog) lands here in the document.
PARAMS_ANCHOR = "export-parameters"


def _details_block(
    title: str, icon: str, body: str, count: str = "", anchor: str | None = None
) -> str:
    """One collapsed block of the header, with its icon and optional count."""
    icon_html = (
        f'<span style="display:inline-block;vertical-align:-0.125em;font-size:0.9em;'
        f'line-height:1;color:#868e96">{icon}</span> '
        if icon
        else ""
    )
    count_html = f'<span style="color:#868e96;font-weight:normal">({count})</span>' if count else ""
    id_attr = f' id="{anchor}"' if anchor else ""
    # A browser's fold: a page (the PDF) has none, so it is left out there.
    return (
        '::: {.content-visible when-format="html"}\n'
        f"<details{id_attr}>\n<summary>{icon_html}<strong>{_esc(title)}</strong> "
        f"{count_html}</summary>\n\n{body}\n\n</details>\n:::"
    )


def header_markdown(
    *,
    title: str,
    subtitle: str | None,
    project: dict[str, Any] | None,
    exported_by: str | None,
    exported_at: datetime,
    instance: str | None,
    api_url: str,
    dashboard_id: str,
    stem: str,
    state_version: int,
    warnings: list[str],
    params_icon: str = "",
    details_rows: list[tuple[str, str]] | None = None,
    details_icon: str = "",
    run_icon: str = "",
) -> str:
    parts = []
    # No ``# title`` / subtitle here: the front matter carries both and Quarto
    # draws them in its title block, so repeating them printed the dashboard
    # name twice at the top of every report.
    del title, subtitle

    # A persistent link back to the live dashboard: the export is a point-in-
    # time snapshot, and a reader who wants the current view (or to change a
    # filter) needs a way back that survives the file being renamed, moved,
    # or opened months later — a URL, not "ask whoever sent you this".
    dashboard_url = f"{api_url.rstrip('/')}/dashboard/{dashboard_id}"

    project = project or {}
    workflows = project.get("workflows") or []
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

    # A table scans faster than a run-on sentence.
    meta_rows = [("Live dashboard", f"[{dashboard_url}]({dashboard_url})")]
    exported_line = f"{exported_at.strftime('%Y-%m-%d %H:%M UTC')}"
    if exported_by:
        exported_line += f" by {_md_escape(exported_by)}"
    if instance:
        exported_line += f" from `{_md_escape(instance)}`"
    exported_line += f" · analysis state v{state_version}"
    meta_rows.append(("Exported", exported_line))
    if project.get("name") or wf_bits:
        proj_val = _md_escape(project.get("name") or "")
        if wf_bits:
            proj_val += (" — " if proj_val else "") + ", ".join(wf_bits)
        meta_rows.append(("Project", proj_val))
    parts.append("| | |\n|---|---|\n" + "\n".join(f"| **{k}** | {v} |" for k, v in meta_rows))
    parts.append(
        "Every cell below is what the dashboard computed for that view: the same table, "
        "the same filters, in the same order."
    )

    origin = project.get("template_origin") or {}
    entries = origin.get("run_provenance") if isinstance(origin, dict) else None
    if entries:
        files = origin.get("run_provenance_files") or []
        files_html = (
            '<div style="font-size:0.8rem;color:#868e96;margin-top:6px">Read from: '
            + ", ".join(f"<code>{_esc(str(f))}</code>" for f in files)
            + "</div>"
            if files
            else ""
        )
        # Collapsed by default: the parameters are provenance, not the point —
        # a reader wants the computed results first, the pipeline's exact
        # inputs on demand, not a wall of rows before the first result.
        parts.append(
            _details_block(
                "Parameters",
                params_icon,
                provenance_table(list(entries)) + files_html,
                count=str(len(entries)),
                anchor=PARAMS_ANCHOR,
            )
        )
    if details_rows:
        parts.append(_details_block("Export details", details_icon, details_table(details_rows)))
    # Folded like the rest of the header: a reader opens a report for its
    # results, and re-running it is a step for the few who will.
    parts.append(
        _details_block(
            "How to run", run_icon, HOW_TO_RUN.format(api_url=api_url, stem=stem).strip()
        )
    )
    if warnings:
        parts.append("**Notes from the export**\n\n" + "\n".join(f"- {w}" for w in warnings))
    return "\n\n".join(parts)
