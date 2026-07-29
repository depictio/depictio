"""Rank every seeded dashboard by how completely it exports as JSON.

The point is to pick two honest examples: one where *every* component comes
back as a Plotly spec, and one where some components can only be embedded as
HTML, so the gap is visible rather than hidden.
"""

import showcase_lib as s

token = s.admin_token()

rows = []
for dash in s.list_dashboards(token):
    dash_id = str(dash.get("_id"))
    try:
        comps = s.manifest(dash_id, token)
    except Exception:  # noqa: BLE001 - survey script
        continue
    if not comps:
        continue

    json_ok = [c for c in comps if "json" in c.get("formats", [])]
    html_only = [c for c in comps if "json" not in c.get("formats", [])]
    kinds = sorted({(c.get("viz_kind") or c["component_type"]) for c in comps})

    rows.append(
        {
            "id": dash_id,
            "title": dash.get("title") or "(untitled)",
            "total": len(comps),
            "json": len(json_ok),
            "html_only": len(html_only),
            "html_only_kinds": sorted(
                {(c.get("viz_kind") or c["component_type"]) for c in html_only}
            ),
            "kinds": kinds,
            "has_multiqc": any(c["component_type"] == "multiqc" for c in comps),
            "has_bench": any(
                (c.get("viz_kind") or "")
                in {"roc_pr_curve", "pr_benchmark", "confusion_matrix", "metric_ci_bars"}
                for c in comps
            ),
        }
    )

rows.sort(key=lambda r: (-(r["json"] / r["total"]), -r["total"]))

print("=== FULL JSON COVERAGE ===")
for r in rows:
    if r["html_only"] == 0 and r["total"] >= 2:
        flags = f"{'MQC ' if r['has_multiqc'] else ''}{'BENCH' if r['has_bench'] else ''}"
        print(f"{r['id']}  {r['json']}/{r['total']}  {r['title'][:40]:40s} {flags}")
        print(f"    {', '.join(r['kinds'])}")

print()
print("=== PARTIAL (has html-only components) ===")
for r in rows:
    if r["html_only"]:
        flags = f"{'MQC ' if r['has_multiqc'] else ''}{'BENCH' if r['has_bench'] else ''}"
        print(f"{r['id']}  {r['json']}/{r['total']}  {r['title'][:40]:40s} {flags}")
        print(f"    html-only: {', '.join(r['html_only_kinds'])}")

print()
print("=== MULTIQC / BENCHMARK LOCATIONS ===")
for r in rows:
    if r["has_multiqc"] or r["has_bench"]:
        print(
            f"{r['id']}  {r['title'][:40]:40s} "
            f"mqc={r['has_multiqc']} bench={r['has_bench']} json={r['json']}/{r['total']}"
        )
