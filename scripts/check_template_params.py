#!/usr/bin/env python3
"""Check every template's ``from_params`` rules against the pipeline they target.

Each nf-core template lives at depictio/projects/nf-core/<pipeline>/<release>/.
For each one with ``from_params`` rules, the pipeline's own nextflow_schema.json
at that release is fetched from GitHub, and every param a rule reads must be a
parameter of that release: a misspelt or renamed param would otherwise make the
rule silently never hold.

    python scripts/check_template_params.py [--cache DIR] [pipeline ...]

Exit 1 when a rule names an unknown param, 2 when a schema cannot be fetched.
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.request
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
NFCORE = ROOT / "depictio" / "projects" / "nf-core"
SCHEMA_URL = "https://raw.githubusercontent.com/nf-core/{pipeline}/{release}/nextflow_schema.json"


def schema_params(schema: dict) -> set[str]:
    """Every parameter name of an nf-core schema (draft-07 `definitions` or
    2020-12 `$defs` groups, plus top-level `properties`)."""
    names = set(schema.get("properties", {}))
    for key in ("definitions", "$defs"):
        for group in schema.get(key, {}).values():
            names |= set(group.get("properties", {}))
    return names


def rule_params(rule: dict) -> set[str]:
    if "param" in rule:
        return {rule["param"]}
    return set().union(*(rule_params(r) for r in rule.get("any", []) + rule.get("all", [])))


def fetch(pipeline: str, release: str, cache: Path | None) -> dict:
    cached = cache / f"{pipeline}-{release}.json" if cache else None
    if cached and cached.is_file():
        return json.loads(cached.read_text())
    url = SCHEMA_URL.format(pipeline=pipeline, release=release)
    with urllib.request.urlopen(url, timeout=30) as resp:
        text = resp.read().decode()
    if cached:
        cached.parent.mkdir(parents=True, exist_ok=True)
        cached.write_text(text)
    return json.loads(text)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("pipelines", nargs="*")
    ap.add_argument("--cache", type=Path)
    args = ap.parse_args()
    unknown = unreachable = checked = 0
    for template in sorted(NFCORE.glob("*/*/template.yaml")):
        pipeline, release = template.parent.parent.name, template.parent.name
        if args.pipelines and pipeline not in args.pipelines:
            continue
        variables = (yaml.safe_load(template.read_text()).get("template") or {}).get("variables") or []
        rules = {v["name"]: v["from_params"] for v in variables if v.get("from_params")}
        if not rules:
            continue
        try:
            known = schema_params(fetch(pipeline, release, args.cache))
        except Exception as exc:  # noqa: BLE001
            print(f"? nf-core/{pipeline} {release}: no schema ({exc})")
            unreachable += 1
            continue
        for name, rule in rules.items():
            checked += 1
            missing = sorted(rule_params(rule) - known)
            if missing:
                unknown += 1
                print(f"✗ nf-core/{pipeline} {release}: {name} reads {missing}, not a parameter")
            else:
                print(f"✓ nf-core/{pipeline} {release}: {name} <- {sorted(rule_params(rule))}")
    print(f"{checked} rules checked, {unknown} with unknown params, {unreachable} schemas unreachable")
    return 1 if unknown else 2 if unreachable else 0


if __name__ == "__main__":
    sys.exit(main())
