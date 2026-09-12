#!/usr/bin/env python3
"""Compose the nf-core showcase instance: one Depictio project per scenario.

Every nf-core template ships with at least two bodies of real data: the nf-core
AWS megatest (which IS the `test_full` profile, executed by nf-core and published
to ``s3://nf-core-awsmegatests/<pipeline>/results-<sha>/``) and a light CI profile
run on the EMBL cluster by ``scripts/nfcore_validation_hpc.py``. Showing a
template against both is what demonstrates it copes with more than one scenario.

WHY ONE PROJECT PER SCENARIO. Thirteen of the fourteen templates declare
``structure: flat``, and the scanner then treats the whole DATA_ROOT as a single
run (``depictio/cli/cli/utils/scan.py``, the "Treat the provided directory as a
single run" branch). The underlying ``locations`` field is a list and would give
one run per entry, named after each directory's basename, but the template binds
it to a single ``{DATA_ROOT}`` and ``--data-root`` is a scalar. Building a
project config by hand would reach the list, but ``depictio-cli run`` guards its
dashboard import with ``if is_template_mode``, so that route silently loses the
template's dashboards, which is the entire point of the showcase.

viralrecon is the exception: it declares ``sequencing-runs`` with
``runs_regex: run_.*``, so its DATA_ROOT is the PARENT of the run directories and
one project legitimately holds several runs. Both shapes appear below.

Usage:
    python3 scripts/nfcore_showcase.py list
    python3 scripts/nfcore_showcase.py ingest --dry-run
    python3 scripts/nfcore_showcase.py ingest --only chipseq-1.2.0-megatest \\
        --cli .../depictio-cli --cli-config ~/.depictio/CLI.<stack>.yaml
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import subprocess
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ROOT = Path(os.environ.get("NFCORE_LOCAL_ROOT", "~/Data/depictio-nfcore")).expanduser()
DEFAULT_CLI = _REPO_ROOT / "depictio" / "cli" / ".venv" / "bin" / "depictio-cli"


@dataclass(frozen=True)
class Scenario:
    """One showcase project: a template, a DATA_ROOT and the name it lands under."""

    pipeline: str
    version: str
    scenario: str
    #: Path under the data root. Defaults to "<pipeline>/<version>/<scenario>";
    #: sequencing-runs templates override it to point one level up.
    subpath: str | None = None
    #: Free text shown by `list`, explaining anything unobvious about this entry.
    note: str = ""
    #: Run directories this project is expected to expose (sequencing-runs only).
    runs: tuple[str, ...] = field(default_factory=tuple)

    @property
    def key(self) -> str:
        return f"{self.pipeline}-{self.version}-{self.scenario}"

    @property
    def template_id(self) -> str:
        return f"nf-core/{self.pipeline}/{self.version}"

    def data_root(self, root: Path) -> Path:
        return root / (self.subpath or f"{self.pipeline}/{self.version}/{self.scenario}")


# The showcase, in the order projects should be created. Megatest ("full") first
# for each pipeline so the heavier, more complete dashboard is the one a visitor
# meets first in a name-sorted listing.
#
# ONE VERSION PER TEMPLATE: the newest. ampliseq is the only pipeline shipping
# several template directories (2.14.0, 2.16.0, 2.18.0) and only 2.18.0 appears
# here. The older two keep their data on disk for template development, but a
# showcase that listed them would suggest a version choice a visitor never has
# to make; the seeding, CLI, CI and docs all resolve the highest version dir.
SCENARIOS: list[Scenario] = [
    Scenario("airrflow", "5.1.0", "megatest", note="nf-core AWS megatest (= test_full)"),
    Scenario("airrflow", "5.1.0", "test", note="CI profile, 6 samples"),
    # ampliseq has no megatest on disk; 2.16.0 carries two locally produced runs
    # and 2.18.0 the cluster CI run. 2.14.0 has no data at all.
    Scenario("ampliseq", "2.18.0", "test", note="CI profile; 7-rank DB, see TEST_DATASETS.md"),
    Scenario("ampliseq", "2.18.0", "test_pacbio_its", note="sintax route, PacBio ITS"),
    Scenario("ampliseq", "2.18.0", "test_iontorrent", note="sintax route, IonTorrent single-end"),
    Scenario("atacseq", "1.2.2", "megatest", note="MultiQC reprocessed"),
    Scenario("atacseq", "1.2.2", "test", note="CI profile; needs the HOMER glob fix"),
    Scenario("chipseq", "1.2.0", "megatest", note="MultiQC reprocessed"),
    Scenario("chipseq", "1.2.0", "test", note="CI profile; needs the HOMER glob fix"),
    Scenario("cutandrun", "3.1", "megatest", note="MultiQC reprocessed"),
    Scenario("cutandrun", "3.1", "test_full_small", note="MultiQC reprocessed"),
    Scenario("differentialabundance", "2.0.0", "megatest", note="nf-core AWS megatest"),
    Scenario("differentialabundance", "2.0.0", "test_full", note="the one S3-free test_full"),
    Scenario("funcscan", "4.0.0", "megatest", note="nf-core AWS megatest"),
    Scenario("funcscan", "4.0.0", "test", note="CI profile; several tools not run"),
    Scenario("rnafusion", "4.1.3", "megatest", note="megatest only: no usable test profile"),
    Scenario("rnaseq", "3.26.0", "megatest", note="nf-core AWS megatest"),
    Scenario("rnaseq", "3.26.0", "test", note="CI profile; samplesheet injected"),
    Scenario("taxprofiler", "2.0.1", "megatest", note="nf-core AWS megatest"),
    Scenario("taxprofiler", "2.0.1", "test", note="CI profile, 2 platforms"),
    Scenario("variantbenchmarking", "1.4.0", "germline_small", note="germline route only"),
    # sequencing-runs: DATA_ROOT is the PARENT of the run_* directories, so this
    # single project holds both runs. Pointing it at one run_* directory instead
    # would match runs_regex against that run's own subdirectories and find none.
    Scenario(
        "viralrecon",
        "3.0.0",
        "illumina-nanopore",
        subpath="viralrecon/3.0.0",
        note="two runs in one project (sequencing-runs)",
        runs=("run_illumina_amplicon", "run_nanopore"),
    ),
    Scenario(
        "viralrecon",
        "3.0.0",
        "test",
        subpath="viralrecon/3.0.0/test",
        note="CI profile, restructured under run_1/",
        runs=("run_1",),
    ),
]


def _log(message: str) -> None:
    print(message, flush=True)


def _select(args: argparse.Namespace) -> list[Scenario]:
    if not args.only:
        return list(SCENARIOS)
    wanted = set(args.only)
    chosen = [s for s in SCENARIOS if s.key in wanted or s.pipeline in wanted]
    missing = wanted - {s.key for s in chosen} - {s.pipeline for s in chosen}
    if missing:
        sys.exit(f"unknown --only value(s): {', '.join(sorted(missing))}")
    return chosen


def _existing_projects(cli_config: Path | None, api_url: str | None) -> set[str] | None:
    """Project names already in the instance, or None when they cannot be read.

    Best effort: the CLI config is YAML and this module is stdlib-only, so the
    token and base URL are pulled out with a regex. A failure here must not stop
    an ingest, it only costs the "already there" column.
    """
    if not cli_config or not cli_config.is_file():
        return None
    text = cli_config.read_text()
    token = re.search(r"^\s*access_token:\s*['\"]?([^'\"\s]+)", text, re.M)
    base = api_url or (
        m.group(1) if (m := re.search(r"^\s*api_base_url:\s*['\"]?([^'\"\s]+)", text, re.M)) else None
    )
    if not token or not base:
        return None
    request = urllib.request.Request(
        f"{base.rstrip('/')}/depictio/api/v1/projects/get/all",
        headers={"Authorization": f"Bearer {token.group(1)}"},
    )
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            payload = json.load(response)
    except (urllib.error.URLError, TimeoutError, ValueError, OSError):
        return None
    return {p.get("name", "") for p in payload} if isinstance(payload, list) else None


def cmd_list(args: argparse.Namespace) -> int:
    known = _existing_projects(args.cli_config, args.api_url)
    header = f"{'project':<44} {'template':<34} {'data':>7}  {'state':<12} note"
    _log(header)
    _log("-" * len(header))
    missing_data = 0
    for scenario in _select(args):
        root = scenario.data_root(args.root)
        present = root.is_dir()
        if not present:
            missing_data += 1
        size = "-"
        if present:
            # Only what the scanner reads: for sequencing-runs that is the
            # declared run directories, not the work/ tree beside them. Symlinks
            # are skipped so an aliased run is not counted twice.
            targets = [root / r for r in scenario.runs] if scenario.runs else [root]
            total = sum(
                f.stat().st_size
                for target in targets
                for f in target.rglob("*")
                if f.is_file() and not f.is_symlink()
            )
            size = f"{total / 1e6:.0f}MB"
        if not present:
            state = "NO DATA"
        elif known is None:
            state = "?"
        elif scenario.key in known:
            state = "ingested"
        else:
            state = "to ingest"
        _log(f"{scenario.key:<44} {scenario.template_id:<34} {size:>7}  {state:<12} {scenario.note}")
    _log("-" * len(header))
    _log(f"{len(_select(args))} scenarios, {missing_data} without data on disk")
    return 1 if missing_data else 0


def cmd_ingest(args: argparse.Namespace) -> int:
    """Create one project per scenario with `depictio-cli run --template`.

    Every project gets an explicit --project-name. The automatic name is
    "<template_id> - <basename(data_root)>", which collides across scenarios that
    share a basename, and project creation is a check-then-insert with no unique
    index on the name, so two of them would both insert.
    """
    known = _existing_projects(args.cli_config, args.api_url) if args.skip_existing else None
    scenarios = _select(args)
    failed: list[str] = []
    skipped = 0
    for index, scenario in enumerate(scenarios):
        project = args.project_prefix + scenario.key
        root = scenario.data_root(args.root)
        if not root.is_dir():
            _log(f"! {project}: no data at {root}")
            failed.append(project)
            continue
        if known is not None and project in known:
            _log(f"= {project}: already in the instance, skipped")
            skipped += 1
            continue
        argv = [str(args.cli), "run"]
        if args.cli_config:
            argv += ["--CLI-config-path", str(args.cli_config)]
        argv += [
            "--template",
            scenario.template_id,
            "--data-root",
            str(root),
            "--project-name",
            project,
        ]
        if index > 0:
            # The S3 probe writes the fixed key .depictio/write_test; once per batch.
            argv.append("--skip-s3-check")
        if args.dry_run:
            argv.append("--dry-run")
        _log(f"-> {' '.join(shlex.quote(t) for t in argv)}")
        code = subprocess.run(argv, check=False, cwd=_REPO_ROOT).returncode
        if code != 0:
            _log(f"! {project}: depictio-cli run exited {code}")
            failed.append(project)
    _log("")
    _log(f"{len(scenarios) - len(failed) - skipped} ingested, {skipped} skipped, {len(failed)} failed")
    for project in failed:
        _log(f"  failed: {project}")
    return 1 if failed else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT, help="local data root")
    parser.add_argument("--only", action="append", default=[], help="scenario key or pipeline; repeatable")
    parser.add_argument("--cli-config", type=Path, default=None, help="depictio CLI config (token + api_base_url)")
    parser.add_argument("--api-url", default=None, help="override the API base URL read from the CLI config")
    sub = parser.add_subparsers(dest="command", required=True)

    listing = sub.add_parser("list", help="show every scenario, its data and whether it is already ingested")
    listing.set_defaults(func=cmd_list)

    ingest = sub.add_parser("ingest", help="create one project per scenario")
    ingest.add_argument("--cli", type=Path, default=DEFAULT_CLI, help="depictio-cli executable")
    ingest.add_argument("--project-prefix", default="", help="prefix for every project name")
    ingest.add_argument("--skip-existing", action="store_true", help="skip names already in the instance")
    ingest.add_argument("--dry-run", action="store_true")
    ingest.set_defaults(func=cmd_ingest)

    args = parser.parse_args()
    args.root = args.root.expanduser()
    if args.cli_config:
        args.cli_config = args.cli_config.expanduser()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
