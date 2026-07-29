#!/usr/bin/env python3
"""Export every exportable component on this instance, in both formats.

Walks the seeded dashboards, asks each one's manifest what it supports, then
writes `exports/<component_type>[--<viz_kind>]/<slug>.json` and `.html`.

The point is coverage, not volume: one representative component per
(component_type, viz_kind) pair by default, so the output is small enough to
eyeball and the per-type behaviour (including the deliberate 501s) is visible.

    python export_all.py            # one per type
    python export_all.py --all      # every component on every dashboard
"""

from __future__ import annotations

import argparse
import glob
import json
import re
import shutil
import sys
import time
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import showcase_lib as s  # noqa: E402

REPO_ROOT = s.REPO_ROOT
EXPORT_DIR = s.EXPORT_DIR


def seed_dashboard_ids() -> list[tuple[str, str]]:
    """(dashboard_id, title) for every bundled seed dashboard."""
    out: list[tuple[str, str]] = []
    pattern = str(REPO_ROOT / "depictio" / "projects" / "**" / ".db_seeds" / "dashboard_*.json")
    for path in sorted(glob.glob(pattern, recursive=True)):
        data = json.loads(Path(path).read_text())
        raw_id = data.get("_id")
        did = raw_id.get("$oid") if isinstance(raw_id, dict) else raw_id
        if did:
            out.append((str(did), data.get("title") or Path(path).stem))
    return out


def slugify(text: str, fallback: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")
    return (slug or fallback)[:60]


def type_key(entry: dict) -> str:
    kind = entry.get("viz_kind")
    return f"{entry['component_type']}--{kind}" if kind else entry["component_type"]


def is_degenerate(record: dict) -> bool:
    """True when this component exported but is not worth showing.

    Two real cases on the seeded instance:

    * a multiqc *General Statistics* panel is a table, not a Plotly figure, so its
      `json` comes back with zero traces and a placeholder annotation;
    * a component whose data collection was never ingested 404s on both formats.

    Neither is an export bug, but neither makes a good representative either, so
    the picker walks on to the next candidate of the same type.
    """
    json_rec, html_rec = record["json"], record["html"]
    if json_rec["status"] == "ok" and json_rec.get("traces") == 0:
        return True
    return json_rec["status"].startswith("http") or html_rec["status"].startswith("http")



def export_one(entry: dict, out_dir: Path, token: str, theme: str) -> dict:
    """Export one component in both formats, recording what each one did."""
    did = entry["dashboard_id"]
    cid = entry["component_id"]
    key = type_key(entry)
    slug = slugify(entry.get("title") or "", cid)
    record = {
        "type": key,
        "component_type": entry["component_type"],
        "viz_kind": entry.get("viz_kind"),
        "title": entry.get("title") or "",
        "dashboard_id": did,
        "dashboard_title": entry["dashboard_title"],
        "component_id": cid,
        "declared_formats": entry["formats"],
        "embed_url": s.embed_url(did, cid, theme),
    }

    if "json" in entry["formats"]:
        t0 = time.time()
        try:
            spec = s.export_json(did, cid, token, theme)
            path = out_dir / f"{slug}.json"
            path.write_text(json.dumps(spec, indent=2))
            record["json"] = {
                "status": "ok",
                "path": str(path.relative_to(EXPORT_DIR)),
                "bytes": path.stat().st_size,
                "traces": len(spec.get("data") or []),
                "seconds": round(time.time() - t0, 2),
            }
        except s.ExportError as exc:
            record["json"] = {"status": f"http {exc.status}", "detail": exc.detail}
    else:
        # A 501 the manifest already predicted. The reason text is the same one the
        # route would return, so the showcase can print it without a wasted request.
        record["json"] = {
            "status": "not offered",
            "detail": entry.get("json_unavailable_reason", ""),
        }

    if "html" in entry["formats"]:
        t0 = time.time()
        try:
            body = s.export_html(did, cid, token, theme)
            path = out_dir / f"{slug}.html"
            path.write_bytes(body)
            record["html"] = {
                "status": "ok",
                "path": str(path.relative_to(EXPORT_DIR)),
                "bytes": len(body),
                "seconds": round(time.time() - t0, 2),
            }
        except s.ExportError as exc:
            record["html"] = {"status": f"http {exc.status}", "detail": exc.detail}
    else:
        record["html"] = {"status": "not offered"}

    return record


def drop_files(record: dict) -> None:
    """Remove the artefacts of a rejected candidate so exports/ stays clean."""
    for fmt in ("json", "html"):
        rel = record.get(fmt, {}).get("path")
        if rel:
            (EXPORT_DIR / rel).unlink(missing_ok=True)


def fmt_line(record: dict) -> str:
    def cell(part: dict) -> str:
        size = f" {part['bytes']}B" if part.get("bytes") else ""
        return f"{part['status']:>10}{size:>10}"

    return f"{record['type']:36} json={cell(record['json'])}   html={cell(record['html'])}"



def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--all", action="store_true", help="export every component, not one per type")
    parser.add_argument("--theme", default="light", choices=["light", "dark"])
    parser.add_argument("--clean", action="store_true", help="wipe exports/ first")
    args = parser.parse_args()

    token = s.admin_token()
    print(f"API      {s.api_base()}")
    print(f"Exports  {EXPORT_DIR}")

    if args.clean and EXPORT_DIR.exists():
        shutil.rmtree(EXPORT_DIR)
    EXPORT_DIR.mkdir(parents=True, exist_ok=True)

    dashboards = seed_dashboard_ids()
    print(f"\nProbing {len(dashboards)} seeded dashboards...\n")

    by_type: dict[str, list[dict]] = defaultdict(list)
    reachable = 0
    for did, title in dashboards:
        try:
            entries = s.manifest(did, token)
        except s.ExportError as exc:
            if exc.status != 404:
                print(f"  !! {did} {title}: {exc.status}")
            continue
        reachable += 1
        for entry in entries:
            by_type[type_key(entry)].append({**entry, "dashboard_id": did, "dashboard_title": title})

    print(f"{reachable}/{len(dashboards)} dashboards reachable, "
          f"{sum(len(v) for v in by_type.values())} components, {len(by_type)} distinct types\n")

    index: list[dict] = []
    for key in sorted(by_type):
        out_dir = EXPORT_DIR / key
        out_dir.mkdir(parents=True, exist_ok=True)
        candidates = by_type[key]

        if args.all:
            for entry in candidates:
                record = export_one(entry, out_dir, token, args.theme)
                index.append(record)
                print(f"  {fmt_line(record)}")
            continue

        # Pick the first candidate that actually produced something worth showing,
        # keeping the last rejected one as evidence if none does.
        chosen: dict | None = None
        fallback: dict | None = None
        for entry in candidates:
            record = export_one(entry, out_dir, token, args.theme)
            if not is_degenerate(record):
                chosen = record
                break
            if fallback is not None:
                drop_files(fallback)
            fallback = record
        if chosen is None:
            chosen = fallback
        elif fallback is not None:
            drop_files(fallback)
        if chosen is not None:
            index.append(chosen)
            print(f"  {fmt_line(chosen)}")

    (EXPORT_DIR / "index.json").write_text(json.dumps(index, indent=2))

    ok_json = sum(1 for r in index if r["json"]["status"] == "ok")
    ok_html = sum(1 for r in index if r["html"]["status"] == "ok")
    print(f"\n{len(index)} components  |  json ok: {ok_json}  |  html ok: {ok_html}")
    print(f"index -> {EXPORT_DIR / 'index.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
