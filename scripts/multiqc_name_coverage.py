#!/usr/bin/env python3
"""Report how many MultiQC sample names each hub id claims, per project link.

A project link ``source DC (hub) --source_column--> multiqc_data`` is what the
dashboard resolver reads: it takes the hub's unique ``source_column`` values and
turns them into MultiQC names through ``canonicalize_to_hub`` (see
``_resolve_multiqc_sample_filter``). A MultiQC name that no hub id claims is
dropped from the panels as soon as a hub filter is pinned. This tool measures
that, on a RUNNING instance, with the rule currently in the package.

Read-only. Endpoints used (all GET, existing):

* ``/projects/get/all``                                  projects, DCs and links
* ``/deltatables/unique_values/{dc_id}?column=&limit=``  hub ids (unique values)
* ``/links/{project_id}/multiqc/{dc_id}/sample-mappings`` MultiQC names (keys and
  variants of the ingest-time ``sample_mappings``, unioned over every report)

Usage::

    PYTHONPATH=<repo> python scripts/multiqc_name_coverage.py \\
        [--server-config ~/.depictio/local-v2/cli/admin_config.yaml] \\
        [--api-url http://127.0.0.1:8121] [--project ampliseq ...] \\
        [--min-ratio 0.9] [--examples 5] [--json]

Exit code 1 when ``--min-ratio`` is set and any link falls below it.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Iterable

import httpx
import yaml

from depictio.cli.cli.utils.sample_mapping import canonicalize_to_hub
from depictio.models.models.links import resolve_link_tag_refs

DEFAULT_CONFIG = "~/.depictio/local-v2/cli/admin_config.yaml"
API_PREFIX = "/depictio/api/v1"
# unique_values caps at ``limit`` (default 1000); a hub never has this many ids.
UNIQUE_LIMIT = 1_000_000


# --------------------------------------------------------------------------- #
# Pure core
# --------------------------------------------------------------------------- #
def coverage(hub_ids: Iterable[str], names: Iterable[str]) -> dict[str, Any]:
    """How many of ``names`` some hub id claims through ``canonicalize_to_hub``.

    Returns ``{attached, total, unattached, by_hub}``: ``by_hub`` maps every hub
    id to the (sorted) names it claims, empty for an id that claims nothing;
    ``unattached`` lists the names no hub id claims. No I/O.
    """
    hubs = {str(h) for h in hub_ids if h is not None and str(h) != ""}
    unique_names = sorted({str(n) for n in names if n is not None and str(n) != ""})
    by_hub: dict[str, list[str]] = {h: [] for h in sorted(hubs)}
    unattached: list[str] = []
    for name in unique_names:
        hub = canonicalize_to_hub(name, hubs)
        if hub is None:
            unattached.append(name)
        else:
            by_hub[hub].append(name)
    return {
        "attached": len(unique_names) - len(unattached),
        "total": len(unique_names),
        "unattached": unattached,
        "by_hub": by_hub,
    }


def mapping_names(mappings: dict[str, list[str]]) -> list[str]:
    """Every name of an ingest-time ``{canonical: [variants]}`` mapping."""
    out: set[str] = set()
    for key, variants in (mappings or {}).items():
        out.add(str(key))
        out.update(str(v) for v in (variants or []))
    return sorted(out)


# --------------------------------------------------------------------------- #
# I/O layer
# --------------------------------------------------------------------------- #
class Api:
    def __init__(self, base_url: str, token: str, timeout: float = 120.0) -> None:
        self._client = httpx.Client(
            base_url=base_url.rstrip("/") + API_PREFIX,
            headers={"Authorization": f"Bearer {token}"},
            timeout=timeout,
        )
        self._cache: dict[tuple, Any] = {}

    def get(self, path: str, **params: Any) -> Any:
        resp = self._client.get(path, params=params or None)
        resp.raise_for_status()
        return resp.json()

    def projects(self) -> list[dict]:
        return self.get("/projects/get/all")

    def hub_ids(self, dc_id: str, column: str) -> list[str]:
        key = ("hub", dc_id, column)
        if key not in self._cache:
            data = self.get(
                f"/deltatables/unique_values/{dc_id}", column=column, limit=UNIQUE_LIMIT
            )
            self._cache[key] = [str(v) for v in data.get("values", [])]
        return self._cache[key]

    def multiqc_names(self, project_id: str, dc_id: str) -> list[str]:
        key = ("mq", dc_id)
        if key not in self._cache:
            data = self.get(f"/links/{project_id}/multiqc/{dc_id}/sample-mappings")
            self._cache[key] = mapping_names(data)
        return self._cache[key]


def load_config(path: str) -> tuple[str | None, str]:
    cfg = yaml.safe_load(Path(path).expanduser().read_text()) or {}
    token = ((cfg.get("user") or {}).get("token") or {}).get("access_token")
    if not token:
        raise SystemExit(f"No user.token.access_token in {path}")
    return cfg.get("api_base_url"), token


def _dc_index(project: dict) -> dict[str, dict]:
    """``{dc_id: {tag, type}}`` over the project's workflows' data collections."""
    out: dict[str, dict] = {}
    for wf in project.get("workflows") or []:
        for dc in wf.get("data_collections") or []:
            dc_id = str(dc.get("id") or dc.get("_id") or "")
            if dc_id:
                out[dc_id] = {
                    "tag": dc.get("data_collection_tag"),
                    "type": ((dc.get("config") or {}).get("type") or "").lower(),
                }
    return out


def multiqc_links(project: dict) -> list[dict]:
    """Enabled links of ``project`` whose target is a MultiQC DC (deduplicated)."""
    dcs = _dc_index(project)
    seen: set[tuple] = set()
    out: list[dict] = []
    for link in project.get("links") or []:
        if link.get("enabled", True) is False:
            continue
        target = str(link.get("target_dc_id") or "")
        is_mq = (link.get("target_type") == "multiqc") or (
            dcs.get(target, {}).get("type") == "multiqc"
        )
        if not is_mq:
            continue
        key = (str(link.get("source_dc_id")), link.get("source_column"), target)
        if key in seen:
            continue
        seen.add(key)
        out.append(link)
    return out


def measure_project(api: Api, project: dict, examples: int) -> list[dict]:
    # Same read-time normalisation as the resolver: `tag:<dc_tag>` placeholders
    # left by a skipped CLI sync become real DC ids.
    resolve_link_tag_refs(project)
    dcs = _dc_index(project)
    project_id = str(project.get("id") or project.get("_id"))
    rows: list[dict] = []
    for link in multiqc_links(project):
        src = str(link.get("source_dc_id") or "")
        tgt = str(link.get("target_dc_id") or "")
        src_tag = link.get("source_dc_tag") or dcs.get(src, {}).get("tag") or src
        label = f"{src_tag}.{link.get('source_column')}"
        row: dict[str, Any] = {
            "project": project.get("name"),
            "link": label,
            "target": link.get("target_dc_tag") or dcs.get(tgt, {}).get("tag") or tgt,
        }
        try:
            hubs = api.hub_ids(src, str(link["source_column"]))
            names = api.multiqc_names(project_id, tgt)
        except httpx.HTTPError as exc:
            row["error"] = _http_error(exc)
            rows.append(row)
            continue
        cov = coverage(hubs, names)
        if not names:
            row["note"] = "no MultiQC sample names stored for the target DC"
        zero = [h for h, claimed in cov["by_hub"].items() if not claimed]
        row.update(
            hubs=len(cov["by_hub"]),
            names=cov["total"],
            attached=cov["attached"],
            ratio=(cov["attached"] / cov["total"]) if cov["total"] else None,
            unattached=cov["unattached"][:examples] if examples >= 0 else cov["unattached"],
            n_unattached=len(cov["unattached"]),
            zero_hubs=len(zero),
            zero_hub_examples=zero[:examples] if examples >= 0 else zero,
        )
        rows.append(row)
    return rows


def _http_error(exc: httpx.HTTPError) -> str:
    if isinstance(exc, httpx.HTTPStatusError):
        try:
            detail = exc.response.json().get("detail")
        except Exception:
            detail = None
        return f"HTTP {exc.response.status_code}" + (f": {detail}" if detail else "")
    return f"{type(exc).__name__}: {exc}"


# --------------------------------------------------------------------------- #
# Output
# --------------------------------------------------------------------------- #
def render(rows: list[dict]) -> str:
    ok = [r for r in rows if "error" not in r]
    w_proj = max([len("project")] + [len(str(r["project"])) for r in rows])
    w_link = max([len("link")] + [len(r["link"]) for r in rows])
    head = (
        f"{'project':<{w_proj}}  {'link (source dc . column)':<{w_link}}  "
        f"{'hubs':>5}  {'names':>5}  attached/total"
    )
    lines = [head, "-" * len(head)]
    for r in rows:
        if "error" in r:
            lines.append(f"{r['project']:<{w_proj}}  {r['link']:<{w_link}}  ERROR {r['error']}")
            continue
        pct = f"{100 * r['ratio']:.0f}%" if r["ratio"] is not None else "n/a"
        lines.append(
            f"{r['project']:<{w_proj}}  {r['link']:<{w_link}}  {r['hubs']:>5}  "
            f"{r['names']:>5}  {r['attached']}/{r['names']} ({pct})"
        )
        if r.get("note"):
            lines.append(f"    note: {r['note']}")
        if r["n_unattached"]:
            more = r["n_unattached"] - len(r["unattached"])
            tail = f" (+{more} more)" if more > 0 else ""
            lines.append(f"    unattached: {', '.join(r['unattached'])}{tail}")
        if r["zero_hubs"]:
            more = r["zero_hubs"] - len(r["zero_hub_examples"])
            tail = f" (+{more} more)" if more > 0 else ""
            lines.append(
                f"    hub ids claiming no name ({r['zero_hubs']}): "
                f"{', '.join(r['zero_hub_examples'])}{tail}"
            )
    tot = sum(r["names"] for r in ok)
    att = sum(r["attached"] for r in ok)
    lines.append("")
    lines.append(
        f"{len(ok)} link(s) measured, {len(rows) - len(ok)} failed; "
        f"{att}/{tot} names attached" + (f" ({100 * att / tot:.1f}%)" if tot else "")
    )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--server-config", default=DEFAULT_CONFIG, help="depictio CLI config yaml")
    ap.add_argument("--api-url", help="override the config's api_base_url")
    ap.add_argument(
        "--project",
        action="append",
        default=[],
        help="project name substring (repeatable, case-insensitive)",
    )
    ap.add_argument(
        "--min-ratio", type=float, help="exit 1 if any link attaches a smaller share of names"
    )
    ap.add_argument(
        "--examples", type=int, default=5, help="unattached names to show per link (default 5)"
    )
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    args = ap.parse_args(argv)

    cfg_url, token = load_config(args.server_config)
    base = args.api_url or cfg_url
    if not base:
        raise SystemExit("No API URL: pass --api-url or set api_base_url in the config")

    api = Api(base, token)
    try:
        projects = api.projects()
    except httpx.HTTPError as exc:
        print(f"Cannot list projects at {base}: {_http_error(exc)}", file=sys.stderr)
        return 2
    wanted = [s.lower() for s in args.project]
    projects = [
        p for p in projects if not wanted or any(s in str(p.get("name", "")).lower() for s in wanted)
    ]
    projects.sort(key=lambda p: str(p.get("name", "")).lower())

    rows: list[dict] = []
    for project in projects:
        rows.extend(measure_project(api, project, args.examples))

    if args.json:
        print(json.dumps(rows, indent=2))
    else:
        print(render(rows))

    if args.min_ratio is not None:
        below = [r for r in rows if r.get("ratio") is not None and r["ratio"] < args.min_ratio]
        if below:
            print(f"{len(below)} link(s) below --min-ratio {args.min_ratio}", file=sys.stderr)
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
