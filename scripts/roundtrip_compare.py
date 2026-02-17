#!/usr/bin/env python3
"""
Minimal round-trip comparison.
Usage: python3 roundtrip_compare.py yaml1.yaml yaml2.yaml
Prints the two component dicts as JSON and reports diffs.
"""

import json
import sys

import yaml

SKIP_DASHBOARD_KEYS = {"dashboard_id", "title"}  # changed on purpose
SKIP_COMPONENT_KEYS: set[str] = set()  # tags ARE preserved; index not in YAML


def load(path: str) -> dict:
    with open(path) as f:
        return yaml.safe_load(f)


def by_tag(comps: list | None) -> dict:
    return {
        c["tag"]: {k: v for k, v in c.items() if k not in SKIP_COMPONENT_KEYS}
        for c in (comps or [])
    }


yaml1 = load(sys.argv[1])
yaml2 = load(sys.argv[2])

comps1 = by_tag(yaml1.get("components", []))
comps2 = by_tag(yaml2.get("components", []))

print("── YAML_1 components ──────────────────────────────────────")
print(json.dumps(comps1, indent=2, ensure_ascii=False))

print("\n── YAML_2 components ──────────────────────────────────────")
print(json.dumps(comps2, indent=2, ensure_ascii=False))

print("\n── DIFF ────────────────────────────────────────────────────")
tags1, tags2 = set(comps1), set(comps2)
if tags1 != tags2:
    print(f"  TAGS DIFFER: only in YAML_1={tags1 - tags2}  only in YAML_2={tags2 - tags1}")
else:
    print(f"  Tags match: {len(tags1)} components")

errors = []
for tag in tags1 & tags2:
    c1, c2 = comps1[tag], comps2[tag]
    if c1 != c2:
        for key in set(c1) | set(c2):
            v1, v2 = c1.get(key), c2.get(key)
            if v1 != v2:
                errors.append(f"  [{tag}] {key}:\n    YAML_1: {v1}\n    YAML_2: {v2}")

if errors:
    print(f"\n  {len(errors)} field(s) differ:")
    for e in errors:
        print(e)
    sys.exit(1)
else:
    print("\n  ✓ All components match!")
