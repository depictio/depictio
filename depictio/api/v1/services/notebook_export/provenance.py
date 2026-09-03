"""The notebook's header: what was exported, from where, and how to run it."""

from __future__ import annotations

from datetime import datetime
from html import escape as _esc
from typing import Any

HOW_TO_RUN = """\
**How to run**

```bash
pip install depictio-cli marimo            # the client, and marimo itself
export DEPICTIO_API_URL={api_url}
export DEPICTIO_API_TOKEN=...              # a long-lived token from the "CLI agents" page
marimo edit {stem}.py
```

The Jupyter and Quarto variants run on a Jupyter kernel, which neither of those two
packages brings: `pip install jupyter` as well for either of them.
Jupyter: download the Jupyter variant and open it, or convert this one with
`marimo export ipynb {stem}.py -o {stem}.ipynb --no-include-outputs`.
Quarto: download the Quarto variant and run `quarto render {stem}.quarto.ipynb`. Quarto
picks the first `python3` on your PATH; if that one has no Jupyter it renders a report with
every result missing and still exits 0, so point `QUARTO_PYTHON` at the interpreter you
installed into.
Offline: set `DEPICTIO_DATA_DIR` to a folder holding `<dc_id>.parquet` files instead of the
API variables; the cells marked *rendered by Depictio* need the API and are skipped offline.
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


def _md_escape(text: object) -> str:
    return str(text).replace("|", "\\|").replace("\n", " ")


def _brand_header_html(brand: dict[str, Any] | None) -> str:
    """A small brand byline: the instance's own mark, not the dashboard's.

    ``brand`` carries the *resolved* instance theme (env defaults, admin
    overrides, whichever preset an operator picked) — the same identity the
    live app's chrome shows, so an exported report doesn't read as a
    generic file once it has left the dashboard around it. Raw HTML in a
    markdown cell renders identically in marimo, Jupyter and Quarto, so one
    block covers all three formats.
    """
    if not brand:
        return ""
    app_name = _md_escape(brand.get("app_name") or "Depictio")
    logo = brand.get("logo_data_uri")
    logo_html = (
        f'<div style="margin-bottom:0.25rem">'
        f'<img src="{logo}" alt="{app_name}" style="height:44px;width:auto" />'
        "</div>"
        if logo
        else ""
    )
    primary = brand.get("primary") or "#1c7ed6"
    return (
        f'<div style="height:3px;background:{primary};border-radius:2px;margin:0 0 0.75rem">'
        "</div>\n"
        f"{logo_html}"
    )


def provenance_table(entries: list[dict[str, Any]], *, limit: int = 40) -> str:
    """The run provenance (``TemplateOrigin.run_provenance``) as an HTML table.

    HTML rather than markdown: this sits inside the header's collapsible
    ``<details>`` block, and markdown syntax inside a raw HTML block is not
    reliably re-parsed the same way across marimo, Jupyter and Quarto's three
    different renderers — an HTML table renders identically in all three.
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


def _details_block(title: str, icon: str, body: str, count: str = "") -> str:
    """One collapsed block of the header, with its icon and optional count."""
    icon_html = (
        f'<span style="display:inline-block;vertical-align:-0.125em;font-size:0.9em;'
        f'line-height:1;color:#868e96">{icon}</span> '
        if icon
        else ""
    )
    count_html = f'<span style="color:#868e96;font-weight:normal">({count})</span>' if count else ""
    return (
        f"<details>\n<summary>{icon_html}<strong>{_esc(title)}</strong> "
        f"{count_html}</summary>\n\n{body}\n\n</details>"
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
    brand: dict[str, Any] | None = None,
    params_icon: str = "",
    details_rows: list[tuple[str, str]] | None = None,
    details_icon: str = "",
) -> str:
    parts = []
    brand_html = _brand_header_html(brand)
    if brand_html:
        parts.append(brand_html)
    parts.append(f"# {title}")
    if subtitle:
        parts.append(f"*{subtitle}*")

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

    # A table scans faster than a run-on sentence, and it's the same markdown
    # in marimo, Jupyter and Quarto — no format-specific callout syntax.
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
            )
        )
    if details_rows:
        parts.append(_details_block("Export details", details_icon, details_table(details_rows)))
    parts.append(HOW_TO_RUN.format(api_url=api_url, stem=stem))
    if warnings:
        parts.append("**Notes from the export**\n\n" + "\n".join(f"- {w}" for w in warnings))
    return "\n\n".join(parts)
