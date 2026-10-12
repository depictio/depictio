"""Find the benchmark dashboards and check MultiQC's JSON export.

The coverage survey missed the benchmarking dashboards, and MultiQC is the
component the user most wants served as a spec rather than a framed page, so
both need checking directly.
"""

import showcase_lib as s

token = s.admin_token()

dashboards = s.list_dashboards(token)
print(f"list_dashboards returned {len(dashboards)}")
for d in dashboards:
    print(f"  {d.get('_id')}  {(d.get('title') or '')[:46]}")

print()
print("=== benchmark dashboards (ids used by qc.js) ===")
for dash_id in (
    "6a6a671b2b176f56bdcf5f2a",
    "6a6a671b2b176f56bdcf5f2c",
    "6a6a671b2b176f56bdcf5f2e",
    "6a6a671b2b176f56bdcf5f30",
):
    try:
        comps = s.manifest(dash_id, token)
    except Exception as exc:  # noqa: BLE001
        print(f"{dash_id}: {exc}")
        continue
    kinds = [(c.get("viz_kind") or c["component_type"], "json" in c["formats"]) for c in comps]
    print(f"{dash_id}: {kinds}")

print()
print("=== MultiQC as JSON ===")
for dash_id in ("646b0f3c1e4a2d7f8e5b8ca2", "746b0f3c1e4a2d7f8e5b9ca2"):
    try:
        comps = s.manifest(dash_id, token)
    except Exception as exc:  # noqa: BLE001
        print(f"{dash_id}: {exc}")
        continue
    for c in comps:
        if c["component_type"] != "multiqc":
            continue
        ok = "json" in c["formats"]
        line = (
            f"  {dash_id[-6:]} {c['component_id'][:8]} {(c.get('title') or '')[:34]:34s} json={ok}"
        )
        if ok:
            try:
                spec = s.export_json(dash_id, c["component_id"], token)
                line += f"  traces={len(spec.get('data', []))}"
            except Exception as exc:  # noqa: BLE001
                line += f"  FAILED {exc}"
        print(line)
