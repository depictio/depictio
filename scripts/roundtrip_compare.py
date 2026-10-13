#!/usr/bin/env python3
"""
Minimal round-trip comparison.
Usage: python3 roundtrip_compare.py yaml1.yaml yaml2.yaml
Prints the two component dicts as JSON and reports diffs.

Handles both export shapes: a single dashboard at the top level, and a tab
family (`main_dashboard` + `tabs`). A family is compared document by document
in order, so a tab losing components on the way back through YAML fails here
rather than passing vacuously against an empty top-level `components` list.
"""

import json
import sys

import yaml

SKIP_DASHBOARD_KEYS = {"dashboard_id", "title"}  # changed on purpose
SKIP_COMPONENT_KEYS: set[str] = set()  # tags ARE preserved; index not in YAML


def load(path: str) -> dict:
    with open(path) as f:
        return yaml.safe_load(f)


def documents(doc: dict) -> list[tuple[str, dict]]:
    """(label, dashboard) for every dashboard the export carries."""
    if "main_dashboard" not in doc:
        return [("dashboard", doc)]
    out = [("main_dashboard", doc["main_dashboard"])]
    for i, tab in enumerate(doc.get("tabs") or []):
        out.append((f"tabs[{i}]", tab))
    return out


def by_tag(comps: list | None) -> dict:
    return {
        c["tag"]: {k: v for k, v in c.items() if k not in SKIP_COMPONENT_KEYS}
        for c in (comps or [])
    }


yaml1 = load(sys.argv[1])
yaml2 = load(sys.argv[2])

docs1 = documents(yaml1)
docs2 = documents(yaml2)

errors: list[str] = []

if len(docs1) != len(docs2):
    print(
        f"  DOCUMENT COUNT DIFFERS: YAML_1={len(docs1)} ({[d[0] for d in docs1]}) "
        f"YAML_2={len(docs2)} ({[d[0] for d in docs2]})"
    )
    sys.exit(1)

for (label, d1), (_, d2) in zip(docs1, docs2):
    comps1 = by_tag(d1.get("components", []))
    comps2 = by_tag(d2.get("components", []))

    print(f"── {label}: YAML_1 components ──────────────────────────────")
    print(json.dumps(comps1, indent=2, ensure_ascii=False))

    print(f"\n── {label}: YAML_2 components ──────────────────────────────")
    print(json.dumps(comps2, indent=2, ensure_ascii=False))

    print(f"\n── {label}: DIFF ───────────────────────────────────────────")
    tags1, tags2 = set(comps1), set(comps2)
    if tags1 != tags2:
        print(
            f"  TAGS DIFFER: only in YAML_1={tags1 - tags2}  only in YAML_2={tags2 - tags1}"
        )
        errors.append(f"  [{label}] component tags differ")
    else:
        print(f"  Tags match: {len(tags1)} components")

    for tag in tags1 & tags2:
        c1, c2 = comps1[tag], comps2[tag]
        if c1 != c2:
            for key in set(c1) | set(c2):
                v1, v2 = c1.get(key), c2.get(key)
                if v1 != v2:
                    errors.append(
                        f"  [{label}][{tag}] {key}:\n    YAML_1: {v1}\n    YAML_2: {v2}"
                    )

if errors:
    print(f"\n  {len(errors)} field(s) differ:")
    for e in errors:
        print(e)
    sys.exit(1)
else:
    print("\n  ✓ All components match!")
