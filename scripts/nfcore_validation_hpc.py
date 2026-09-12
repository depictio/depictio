#!/usr/bin/env python3
"""Run the nf-core validation profiles on the EMBL cluster, bring the results back.

Maintainer tool (not shipped with ``depictio-cli``). ``TEST_DATASETS.md`` surveys
every ``test*`` profile nf-core ships for the twelve pinned pipelines and says
which of them a Depictio template could ingest. This module executes that
survey: one profile per pipeline, submitted to SLURM, repatriated by rsync, then
reprocessed and ingested locally.

Why the cluster rather than a laptop: the two local runs ever attempted died on
``no space left on device`` inside the Colima VM. The cluster already carries
everything the runs need - a SLURM config, a shared Singularity cache, and both
a DSL2 and a DSL1-capable Nextflow - so nothing has to be provisioned.

The four subcommands are the four stages:

* ``submit``  write an sbatch head job per run and queue it (``--dry-run`` prints it),
* ``status``  read ``.nextflow.log`` and the execution trace, ``squeue -j`` only as a fallback,
* ``fetch``   rsync the outputs back, minus the alignment blobs, and build the
  DATA_ROOT the template expects (samplesheet into ``input/``, viralrecon under ``run_1/``),
* ``ingest``  run ``depictio-cli run`` over the repatriated trees.

The Nextflow head process runs *inside* a small SLURM job, never on the login
node, and the Depictio trigger is deliberately absent from the cluster: these
runs generate data, they do not test the trigger. The trigger is covered
separately by ``scripts/nfcore_trigger_stub.py`` and by one tunnelled run.

Only the standard library is required.

Usage::

    python scripts/nfcore_validation_hpc.py list
    python scripts/nfcore_validation_hpc.py submit --run rnaseq --dry-run
    python scripts/nfcore_validation_hpc.py submit --run rnaseq
    python scripts/nfcore_validation_hpc.py status --run rnaseq
    python scripts/nfcore_validation_hpc.py fetch --run rnaseq
    python scripts/nfcore_validation_hpc.py ingest --run rnaseq

Exit codes: 0 ok, 1 error (ssh, rsync, missing run), 2 usage.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import subprocess
import sys
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[1]
NFCORE_PROJECTS_DIR = _REPO_ROOT / "depictio" / "projects" / "nf-core"

# --- cluster coordinates -----------------------------------------------------
# login01 does not exist in EMBL DNS; the submission host is login1, no zero.
HPC_HOST = os.environ.get("NFCORE_HPC_HOST", "tweber@login1.cluster.embl.de")
HPC_ROOT = os.environ.get("NFCORE_HPC_ROOT", "/scratch/tweber/NF_CORE")
# Already on the cluster, already pointing at the shared Singularity cache. Reused
# verbatim: it carries --account=datasci, queue htc-el8, resourceLimits and the
# per-process errorStrategy exceptions that previous runs needed.
HPC_SLURM_CONFIG = f"{HPC_ROOT}/nf_slurm.config"
HPC_SINGULARITY_CACHE = f"{HPC_ROOT}/singularity_cache"
# Apptainer stages a download into its own cache before handing the image to
# Nextflow's cacheDir, and it defaults to $HOME/.apptainer - a filesystem that is
# 95% full here. Point the staging at scratch too.
HPC_APPTAINER_CACHE = f"{HPC_ROOT}/apptainer_cache"
HPC_APPTAINER_TMP = f"{HPC_ROOT}/apptainer_tmp"
# A private NXF_HOME for the campaign. $HOME/.nextflow/assets is a shared set of
# git checkouts the user also edits by hand, and a dirty asset makes `-r <tag>`
# fail outright with "contains uncommitted changes -- Cannot switch to revision".
# Isolating it costs one framework download and removes the whole class of
# problem, including two runs pulling the same pipeline at once.
HPC_NXF_HOME = f"{HPC_ROOT}/nxf_home"
# A TMPDIR inside the bind mount; see scripts/nfcore_validation.config.
HPC_TMPDIR = f"{HPC_ROOT}/tmp"
# Campaign overrides, shipped from the repo and loaded after nf_slurm.config.
VALIDATION_CONFIG = _REPO_ROOT / "scripts" / "nfcore_validation.config"
HPC_VALIDATION_CONFIG = f"{HPC_ROOT}/nfcore_validation.config"
# Container registries reset connections mid-download often enough that a single
# attempt is not a fair test of a pipeline. Each retry resumes, so an attempt that
# got further keeps its ground and only the failed pull is repeated.
HEAD_ATTEMPTS = 3
CONDA_PROFILE = "/g/korbel2/weber/miniconda3/etc/profile.d/conda.sh"

# Where repatriated runs land locally: the layout scripts/nfcore_megatest.py uses.
LOCAL_ROOT = Path(os.environ.get("NFCORE_LOCAL_ROOT", "~/Data/depictio-nfcore")).expanduser()

# The head job is mostly a scheduler client: it sleeps on a socket while SLURM
# runs the actual tasks. But it is also where Nextflow builds Singularity images,
# and mksquashfs on a large one (QIIME2, for ampliseq) is the real memory peak -
# at 6 GB it was killed with exit 137 before the pipeline had run a single task.
HEAD_CPUS = 2
HEAD_MEM = "24G"
HEAD_TIME = "24:00:00"
HEAD_PARTITION = "htc-el8"
HEAD_ACCOUNT = "datasci"


@dataclass
class RunSpec:
    """One pipeline profile to execute, and everything that makes it special."""

    key: str
    pipeline: str
    version: str  # the Depictio template version, i.e. the directory under nf-core/
    profile: str
    # -r. Left None it falls back to `version`: every template version here was
    # verified to be a real nf-core tag, and pinning the revision explicitly beats
    # relying on the default branch happening to point at the right release.
    revision: str | None = None
    nf_env: str = "nextflow25"  # conda env on the cluster
    nxf_ver: str | None = None  # NXF_VER, when no env carries a new enough Nextflow
    extra_args: list[str] = field(default_factory=list)
    samples: int = 0
    # The samplesheet is not published into outdir by most pipelines, so `fetch`
    # pulls the URL named by pipeline_info/params.json into <dest>/input/.
    inject_samplesheet: bool = True
    # viralrecon is the only `sequencing-runs` template: its DATA_ROOT must be the
    # PARENT of run_* directories, so the output lands under <dest>/run_1/.
    run_subdir: str | None = None
    note: str = ""

    @property
    def effective_revision(self) -> str:
        return self.revision or self.version

    @property
    def template_id(self) -> str:
        return f"nf-core/{self.pipeline}/{self.version}"

    @property
    def remote_dir(self) -> str:
        return f"{HPC_ROOT}/{self.pipeline}/{self.version}"

    @property
    def remote_outdir(self) -> str:
        return f"{self.remote_dir}/run_{self.profile}"

    @property
    def remote_workdir(self) -> str:
        return f"{self.remote_dir}/work_{self.profile}"

    @property
    def remote_launchdir(self) -> str:
        """Launch dir: holds .nextflow.log, the .nextflow/ cache and the sbatch output.

        Per-run so that two concurrent head jobs never share a LevelDB cache, which
        is what the existing generate_validation_runs.sh scripts get wrong.
        """
        return f"{self.remote_dir}/launch_{self.profile}"

    @property
    def local_dir(self) -> Path:
        return LOCAL_ROOT / self.pipeline / self.version / self.profile

    @property
    def data_root(self) -> Path:
        """What --data-root is pointed at: the parent when the structure is sequencing-runs."""
        return self.local_dir

    @property
    def local_payload_dir(self) -> Path:
        """Where the pipeline output itself lands (under run_1/ for viralrecon)."""
        return self.local_dir / self.run_subdir if self.run_subdir else self.local_dir


# One profile per pipeline, picked "richest at equal cost" rather than lightest.
# rnafusion is absent on purpose: its three profiles are stub, references_only and
# full-with-COSMIC-credentials, none of which produces real outputs.
RUNS: list[RunSpec] = [
    RunSpec(
        key="rnaseq",
        pipeline="rnaseq",
        version="3.26.0",
        profile="test",
        samples=5,
        note="cheapest CI profile of the survey, no database downloads: the canary",
    ),
    RunSpec(
        key="viralrecon",
        pipeline="viralrecon",
        version="3.0.0",
        profile="test",
        samples=4,
        run_subdir="run_1",
        inject_samplesheet=False,  # no samplesheet collection in this template
        note="already run on this cluster; exercises the sequencing-runs layout",
    ),
    RunSpec(
        key="diffabundance",
        pipeline="differentialabundance",
        version="2.0.0",
        profile="test_full",
        nxf_ver="25.10.7",  # manifest floor !>=25.10.4
        samples=24,
        note="richest metadata of the survey (4 factors x 24 samples), matrix-based so cheap",
    ),
    RunSpec(
        key="cutandrun",
        pipeline="cutandrun",
        version="3.1",
        profile="test_full_small",
        revision="3.1",
        samples=6,
        inject_samplesheet=False,  # publishes pipeline_info/samplesheet.valid.csv
        note="2 marks x 2 replicates + IgG, no S3; MultiQC 1.14 so it needs reprocessing",
    ),
    RunSpec(
        key="chipseq",
        pipeline="chipseq",
        version="1.2.0",
        profile="test",
        revision="1.2.0",
        nf_env="nextflow_old",  # DSL1: 22.10.6 is the last release that can run it
        # The pipeline default is `narrow_peak = false`, i.e. broadPeak, and the
        # template binds the narrowPeak route only. Worse than a mismatch: the
        # template's scans match on file NAME, so a broadPeak run's *_peaks.xls
        # and *_peaks.annotatePeaks.txt are collected anyway and then fail on
        # schema (BED6+3, no summit column) instead of skipping as out of scope.
        extra_args=["--narrow_peak"],
        samples=6,
        inject_samplesheet=False,  # DSL1 publishes pipeline_info/design_reads.csv
        note="DSL1; richest ChIP design (antibody + control); MultiQC 1.9 so it needs reprocessing",
    ),
    RunSpec(
        key="atacseq",
        pipeline="atacseq",
        version="1.2.2",
        profile="test",
        revision="1.2.2",
        nf_env="nextflow_old",
        # 22.10.6 runs it in DSL1 mode but enforces the single-consumer channel
        # rule strictly enough to reject the pipeline's own main.nf:377
        # ("Channel `design_multiple_samples` has been used as an input by more
        # than a process or an operator"). 1.2.2 is from 2021; a Nextflow of its
        # own era accepts it. chipseq 1.2.0 has no such problem on 22.10.6.
        nxf_ver="21.10.6",
        samples=4,
        inject_samplesheet=False,
        note=(
            "DSL1; MultiQC 1.9 so it needs reprocessing; the 1.2.2 tag declares "
            "manifest.version = 1.2.1, so the trigger forwards a pipeline id with no template"
        ),
    ),
    RunSpec(
        key="taxprofiler",
        pipeline="taxprofiler",
        version="2.0.1",
        profile="test",
        nxf_ver="25.10.7",  # manifest floor !>=25.10.4
        samples=7,
        note="18 small public databases, two sequencing platforms",
    ),
    RunSpec(
        key="funcscan",
        pipeline="funcscan",
        version="4.0.0",
        profile="test",
        nxf_ver="25.10.7",  # manifest floor !>=25.10.4
        samples=2,
        note="AMRFinderPlus + DeepARG downloads",
    ),
    RunSpec(
        key="variantbench",
        pipeline="variantbenchmarking",
        version="1.4.0",
        profile="germline_small",
        revision="1.4.0",
        samples=2,
        inject_samplesheet=False,  # the template reads the summary tables, not the sheet
        note="the only clean germline profile; the profile hardcodes outdir='results'",
    ),
    RunSpec(
        key="ampliseq",
        pipeline="ampliseq",
        version="2.18.0",
        profile="test",
        nxf_ver="25.10.7",  # manifest floor !>=25.10.4
        samples=4,
        inject_samplesheet=False,  # the only pipeline that publishes input/ itself
        note="publishes input/ (samplesheet + metadata); pulls GTDB R07-RS207",
    ),
    RunSpec(
        key="airrflow",
        pipeline="airrflow",
        version="5.1.0",
        profile="test",
        revision="5.1.0",
        nxf_ver="26.04.6",  # manifest floor !>=26.04.1, above every conda env
        samples=6,
        inject_samplesheet=False,  # publishes pipeline_info/samplesheet.valid.tsv
        note="7 grouping columns, the richest AIRR metadata of the survey",
    ),
    # --- second wave -----------------------------------------------------------
    # One profile per pipeline answers "does this template read this pipeline's
    # output". It does not answer "does it read the pipeline's OTHER routes",
    # and the route conditionals are where the untested surface actually sits.
    # The cluster already carries these three ampliseq routes at 2.16.0
    # (run_its_pacbio, run_iontorrent, run_multiregion); these reproduce them at
    # the template version the showcase actually uses.
    RunSpec(
        key="ampliseq-pacbio",
        pipeline="ampliseq",
        version="2.18.0",
        profile="test_pacbio_its",
        nxf_ver="25.10.7",
        samples=3,
        inject_samplesheet=False,
        note="sintax route (--skip_qiime): the only way to reach sintax_rel_abundance",
    ),
    RunSpec(
        key="ampliseq-iontorrent",
        pipeline="ampliseq",
        version="2.18.0",
        profile="test_iontorrent",
        nxf_ver="25.10.7",
        samples=3,
        inject_samplesheet=False,
        note="sintax route, single-end IonTorrent; sintax ref is fetched from ut.ee",
    ),
    RunSpec(
        key="ampliseq-multiregion",
        pipeline="ampliseq",
        version="2.18.0",
        profile="test_multiregion",
        nxf_ver="25.10.7",
        samples=3,
        inject_samplesheet=False,
        note="SIDLE route: the only way to reach sidle_reconstructed / _reconstruction_qc",
    ),
    RunSpec(
        key="variantbench-sv",
        pipeline="variantbenchmarking",
        version="1.4.0",
        profile="germline_sv",
        revision="1.4.0",
        samples=3,
        inject_samplesheet=False,
        note="SV route, 3 callers; germline_small reached only 3 of 9 collections",
    ),
]

RUNS_BY_KEY = {spec.key: spec for spec in RUNS}

# Alignment and sequence blobs: large, and no template reads them. Everything else
# comes back. An exclude list rather than the megatest.yaml `keys:` include lists,
# because those globs encode megatest sample names (chipseq filters on *_IP_*) and
# a megatest-only run root, neither of which exists in CI data.
RSYNC_EXCLUDES = [
    "*.bam",
    "*.bam.bai",
    "*.bai",
    "*.cram",
    "*.crai",
    "*.sam",
    "*.fastq",
    "*.fastq.gz",
    "*.fq",
    "*.fq.gz",
    "*.bigWig",
    "*.bw",
    "*.bedGraph",
    "*.bedgraph",
    "*.2bit",
    "*.ht2",
    "*.bt2",
    "*.sa",
    "*.pac",
    "*.nhr",
    "*.nin",
    "*.nsq",
    # Anchored to the transfer root on purpose. An unanchored "genome/" also
    # matches variants/bowtie2/mosdepth/genome/, which is where viralrecon puts
    # the whole-genome coverage table the template scans for; the collection then
    # skips as "no files" and the run looks degraded for a reason that is ours.
    "/genome/",
    "/work/",
    "/.nextflow/",
    "*.h5",
    "*.fast5",
    "*.pod5",
]


def _log(message: str) -> None:
    print(message, file=sys.stderr, flush=True)


def _human_size(num: float) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(num) < 1024.0:
            return f"{num:.1f}{unit}" if unit != "B" else f"{int(num)}B"
        num /= 1024.0
    return f"{num:.1f}PB"


def ssh(command: str, *, check: bool = True, quiet: bool = False) -> subprocess.CompletedProcess:
    """Run one command on the submission host. Batch mode: never prompt, fail instead."""
    argv = ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=25", HPC_HOST, command]
    if not quiet:
        _log(f"-> ssh {HPC_HOST} {command.splitlines()[0][:100]}")
    return subprocess.run(argv, check=check, capture_output=True, text=True)


# --- state -------------------------------------------------------------------
# depictio-cli run exits 1 both for a real failure and for "the project already
# exists", and a SLURM job id is the only durable handle on a submitted run, so
# the driver keeps its own record instead of re-deriving one from exit codes.
STATE_PATH = LOCAL_ROOT / ".validation-state.json"


def load_state() -> dict[str, Any]:
    if STATE_PATH.is_file():
        return json.loads(STATE_PATH.read_text())
    return {}


def save_state(state: dict[str, Any]) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n")


def update_state(key: str, **fields: Any) -> dict[str, Any]:
    state = load_state()
    entry = state.setdefault(key, {})
    entry.update(fields)
    save_state(state)
    return entry


# --- submit ------------------------------------------------------------------
def nextflow_command(spec: RunSpec) -> list[str]:
    argv = ["nextflow", "run", f"nf-core/{spec.pipeline}", "-r", spec.effective_revision]
    argv += [
        "-profile",
        f"{spec.profile},singularity",
        "-c",
        HPC_SLURM_CONFIG,
        # Second -c, so the campaign's own overrides win over the shared file
        # without editing it.
        "-c",
        HPC_VALIDATION_CONFIG,
        "-w",
        spec.remote_workdir,
        "--outdir",
        spec.remote_outdir,
        "-resume",
        "-ansi-log",
        "false",
    ]
    argv += spec.extra_args
    return argv


def sbatch_script(spec: RunSpec) -> str:
    """The head job. It is a scheduler client: SLURM runs the pipeline's own tasks."""
    exports = [
        f"export NXF_SINGULARITY_CACHEDIR={shlex.quote(HPC_SINGULARITY_CACHE)}",
        f"export APPTAINER_CACHEDIR={shlex.quote(HPC_APPTAINER_CACHE)}",
        f"export SINGULARITY_CACHEDIR={shlex.quote(HPC_APPTAINER_CACHE)}",
        f"export APPTAINER_TMPDIR={shlex.quote(HPC_APPTAINER_TMP)}",
        f"export SINGULARITY_TMPDIR={shlex.quote(HPC_APPTAINER_TMP)}",
        f"export NXF_HOME={shlex.quote(HPC_NXF_HOME)}",
        "export NXF_OPTS='-Xms512m -Xmx4g'",
        "export NXF_ANSI_LOG=false",
    ]
    if spec.nxf_ver:
        # No conda env carries this release; Nextflow fetches it itself, which the
        # login node's outbound network allows.
        exports.append(f"export NXF_VER={spec.nxf_ver}")
    command = " \\\n        ".join(shlex.quote(token) for token in nextflow_command(spec))
    return f"""#!/bin/bash
#SBATCH --job-name=nfval-{spec.key}
#SBATCH --account={HEAD_ACCOUNT}
#SBATCH --partition={HEAD_PARTITION}
#SBATCH --cpus-per-task={HEAD_CPUS}
#SBATCH --mem={HEAD_MEM}
#SBATCH --time={HEAD_TIME}
#SBATCH --chdir={spec.remote_launchdir}
#SBATCH --output={spec.remote_launchdir}/head.%j.out
#SBATCH --error={spec.remote_launchdir}/head.%j.out
# No -e: the retry loop below inspects nextflow's exit status itself.
set -uo pipefail

source {CONDA_PROFILE}
conda activate {spec.nf_env}
{chr(10).join(exports)}

echo "=== {spec.key}: {spec.pipeline} {spec.version} -profile {spec.profile} ==="
echo "nextflow: $(nextflow -v 2>&1 | head -1)"
echo "launch  : $(pwd)"
date

mkdir -p {HPC_APPTAINER_CACHE} {HPC_APPTAINER_TMP} {HPC_NXF_HOME} {HPC_TMPDIR}

status=1
for attempt in $(seq 1 {HEAD_ATTEMPTS}); do
    echo "=== attempt $attempt/{HEAD_ATTEMPTS} ==="
    {command}
    status=$?
    if [ $status -eq 0 ]; then
        break
    fi
    echo "=== attempt $attempt failed with $status ==="
    if [ $attempt -lt {HEAD_ATTEMPTS} ]; then
        # Almost always a registry resetting a download. -resume keeps whatever
        # the previous attempt managed to complete, so retrying is cheap.
        sleep 120
    fi
done

echo "=== exit $status ==="
date
exit $status
"""


def cmd_submit(args: argparse.Namespace) -> int:
    specs = _select(args)
    for spec in specs:
        script = sbatch_script(spec)
        if args.dry_run:
            print(f"\n{'=' * 78}\n# {spec.key}: {spec.template_id} -profile {spec.profile}")
            print(f"# outdir  {spec.remote_outdir}")
            print(f"# workdir {spec.remote_workdir}")
            print(f"{'=' * 78}\n{script}")
            continue
        # mkdir -p of the three per-run directories, then drop the script in the
        # launch dir so the submitted job is reproducible from the cluster alone.
        remote_script = f"{spec.remote_launchdir}/submit.sh"
        # Ship the campaign config every time: it is versioned here, so the copy
        # on the cluster is a cache, never the source of truth.
        config_body = VALIDATION_CONFIG.read_text()
        setup = (
            f"cat > {shlex.quote(HPC_VALIDATION_CONFIG)} <<'NFVAL_CFG_EOF'\n"
            f"{config_body}\nNFVAL_CFG_EOF\n"
            f"mkdir -p {shlex.quote(spec.remote_launchdir)} "
            f"{shlex.quote(spec.remote_outdir)} {shlex.quote(spec.remote_workdir)} && "
            f"cat > {shlex.quote(remote_script)} <<'NFVAL_EOF'\n{script}\nNFVAL_EOF\n"
            f"chmod +x {shlex.quote(remote_script)} && "
            f"sbatch --parsable {shlex.quote(remote_script)}"
        )
        result = ssh(setup)
        job_id = result.stdout.strip().splitlines()[-1] if result.stdout.strip() else ""
        if not job_id.isdigit():
            _log(f"! {spec.key}: sbatch did not return a job id: {result.stdout}{result.stderr}")
            return 1
        update_state(
            spec.key,
            job_id=job_id,
            pipeline=spec.pipeline,
            version=spec.version,
            profile=spec.profile,
            remote_outdir=spec.remote_outdir,
            submitted=True,
        )
        print(f"{spec.key:<14} job {job_id}  -> {spec.remote_outdir}")
    return 0


# --- status ------------------------------------------------------------------
_COMPLETED_RE = re.compile(r"Execution (complete|aborted)|Workflow completed|Pipeline completed")


def cmd_status(args: argparse.Namespace) -> int:
    """Read the run's own files first; squeue only when they say nothing yet.

    The account is shared, so squeue is always scoped to this run's job id. Never
    -u: that would list, and risk acting on, other people's jobs.
    """
    specs = _select(args)
    state = load_state()
    for spec in specs:
        entry = state.get(spec.key, {})
        job_id = entry.get("job_id")
        # One ssh round trip per run: log tail, trace summary, output size.
        probe = (
            f"log={shlex.quote(spec.remote_launchdir)}/.nextflow.log; "
            # DEBUG lines dominate .nextflow.log and say nothing a human needs here.
            f"echo '--- tail'; grep -v ' DEBUG ' \"$log\" 2>/dev/null | tail -n 8 "
            f"|| echo '(no .nextflow.log yet)'; "
            f"echo '--- trace'; "
            f"t=$(ls -t {shlex.quote(spec.remote_outdir)}/pipeline_info/execution_trace*.txt "
            f"2>/dev/null | head -1); "
            f"if [ -n \"$t\" ]; then awk -F'\\t' 'NR>1{{c[$5]++}} END{{for(s in c) "
            f'printf "%s=%s ", s, c[s]; print ""}}\' "$t"; else echo "(no trace yet)"; fi; '
            f"echo '--- outdir'; du -sh {shlex.quote(spec.remote_outdir)} 2>/dev/null || true"
        )
        if job_id:
            probe += (
                f"; echo '--- squeue'; squeue -h -j {shlex.quote(job_id)} "
                f"-o '%T %M %R' 2>/dev/null || echo '(not in queue: finished or purged)'"
            )
        result = ssh(probe, check=False, quiet=True)
        print(
            f"\n{'=' * 78}\n{spec.key}  {spec.template_id}  -profile {spec.profile}"
            f"  job {job_id or '-'}\n{'=' * 78}"
        )
        print(result.stdout.rstrip() or result.stderr.rstrip())
    return 0


# --- fetch -------------------------------------------------------------------
sys.path.insert(0, str(Path(__file__).resolve().parent))
try:  # reuse the manifest reader rather than re-parsing megatest.yaml here
    from nfcore_megatest import load_manifest, manifest_path  # noqa: E402
except ImportError:  # pragma: no cover - only if the sibling script is missing
    load_manifest = manifest_path = None  # type: ignore[assignment]


def needs_reprocess(spec: RunSpec) -> bool:
    """Does this pipeline write a MultiQC below the 1.29 parquet floor?

    Read from the pipeline's own megatest.yaml (`multiqc.reprocess`) instead of
    being restated here, so the two cannot drift. Templates with no manifest
    (viralrecon 3.0.0) were validated on a MultiQC that already wrote parquet.
    """
    if manifest_path is None:
        return False
    path = manifest_path(spec.pipeline, spec.version)
    if not path.is_file():
        return False
    try:
        return bool(load_manifest(path).multiqc.get("reprocess"))
    except (OSError, ValueError):
        return False


def _rsync(spec: RunSpec, *, dry_run: bool) -> int:
    dest = spec.local_payload_dir
    dest.mkdir(parents=True, exist_ok=True)
    argv = ["rsync", "-az", "--partial", "--human-readable", "--delete"]
    # --delete, because a re-run is not always a superset of the previous one. A
    # chipseq run redone with --narrow_peak writes macs/narrowPeak/ and stops
    # writing macs/broadPeak/, but a merging rsync leaves the stale broadPeak
    # tree in place; the template's scans match on file name, so it collects both
    # and fails on the older one's schema. The two things we create locally after
    # the transfer have to survive it.
    argv += [
        "--filter=P /input/***",  # samplesheet injected from params.json
        "--filter=P /multiqc/multiqc_data/***",  # reprocessed MultiQC parquet
    ]
    for pattern in RSYNC_EXCLUDES:
        argv += ["--exclude", pattern]
    if dry_run:
        argv += ["--dry-run", "--stats"]
    else:
        argv += ["--info=stats2"]
    argv += [f"{HPC_HOST}:{spec.remote_outdir}/", f"{dest}/"]
    _log(f"-> rsync {spec.remote_outdir}/ -> {dest}/")
    return subprocess.run(argv, check=False).returncode


def _inject_samplesheet(spec: RunSpec) -> None:
    """Pull the samplesheet the run was given into <dest>/input/.

    Most nf-core pipelines never publish `--input` into outdir, which is the
    `SHEET` blocker in TEST_DATASETS.md: the template's samplesheet collection is
    required but absent. The URL is not hardcoded here; it is read back from
    pipeline_info/params.json, which records what the run actually used.
    """
    payload = spec.local_payload_dir
    candidates = sorted(payload.glob("pipeline_info/params*.json"))
    if not candidates:
        _log(f"! {spec.key}: no pipeline_info/params*.json, cannot resolve the samplesheet")
        return
    params = json.loads(candidates[-1].read_text())
    url = params.get("input")
    if not url or not isinstance(url, str):
        _log(f"! {spec.key}: params.json has no 'input', skipping samplesheet injection")
        return
    suffix = Path(urllib.parse.urlparse(url).path).suffix or ".csv"
    target = payload / "input" / f"samplesheet{suffix}"
    target.parent.mkdir(parents=True, exist_ok=True)
    if url.startswith(("http://", "https://")):
        with urllib.request.urlopen(url, timeout=60) as response:  # noqa: S310
            target.write_bytes(response.read())
    elif Path(url).is_file():
        target.write_bytes(Path(url).read_bytes())
    else:
        _log(f"! {spec.key}: cannot fetch samplesheet {url}")
        return
    _log(f"-> {spec.key}: samplesheet -> {target.relative_to(spec.local_dir)}")


def cmd_fetch(args: argparse.Namespace) -> int:
    specs = _select(args)
    failed = 0
    for spec in specs:
        code = _rsync(spec, dry_run=args.dry_run)
        if code != 0:
            _log(f"! {spec.key}: rsync exited {code}")
            failed += 1
            continue
        if args.dry_run:
            continue
        if spec.inject_samplesheet:
            _inject_samplesheet(spec)
        size = sum(f.stat().st_size for f in spec.local_dir.rglob("*") if f.is_file())
        update_state(spec.key, fetched=True, local_bytes=size)
        flag = "  (needs MultiQC reprocess)" if needs_reprocess(spec) else ""
        print(f"{spec.key:<14} {_human_size(size):>10}  {spec.data_root}{flag}")
    return 1 if failed else 0


# --- reprocess ---------------------------------------------------------------
def cmd_reprocess(args: argparse.Namespace) -> int:
    """Re-run MultiQC over the raw inputs, for runs below the 1.29 parquet floor.

    Strictly serial, and not by accident: multiqc_reprocess stages into the fixed
    path /tmp/depictio-multiqc-reprocess, so two concurrent invocations would mix
    each other's inputs into one report and the first to finish would rmtree the
    other's staging directory mid-analysis.
    """
    specs = [spec for spec in _select(args) if needs_reprocess(spec)]
    if not specs:
        print("nothing to reprocess in this selection")
        return 0
    failed = 0
    for spec in specs:
        payload = spec.local_payload_dir
        argv = [
            str(args.python),
            "-m",
            "depictio.dev_scripts.multiqc_reprocess",
            "--src",
            str(payload),
            "--dest",
            str(payload),
        ]
        if args.dry_run:
            argv.append("--dry-run")
        _log(f"-> {spec.key}: {' '.join(argv[2:])}")
        code = subprocess.run(argv, check=False, cwd=_REPO_ROOT).returncode
        if code != 0:
            _log(f"! {spec.key}: multiqc_reprocess exited {code}")
            failed += 1
        else:
            update_state(spec.key, reprocessed=not args.dry_run)
    return 1 if failed else 0


# --- ingest ------------------------------------------------------------------
def cmd_ingest(args: argparse.Namespace) -> int:
    """Ingest the repatriated runs with the 1.10.0 CLI.

    Every run gets an explicit --project-name. The automatic name is
    "<template_id> - <basename(data_root)>", and project creation is a
    check-then-insert with no unique index on the name, so two runs that derive
    the same name can both insert and leave a pair of homonym projects behind.
    """
    specs = _select(args)
    failed = 0
    for index, spec in enumerate(specs):
        project = args.project_prefix + f"{spec.pipeline}-{spec.version}-{spec.profile}"
        argv = [args.cli, "run"]
        if args.cli_config:
            # Each worktree stack has its own token and port, so the default
            # ~/.depictio/CLI.yaml is rarely the right one here.
            argv += ["--CLI-config-path", str(args.cli_config)]
        argv += [
            "--template",
            spec.template_id,
            "--data-root",
            str(spec.data_root),
            "--project-name",
            project,
        ]
        if index > 0:
            # The check writes the fixed key .depictio/write_test; one probe per batch.
            argv.append("--skip-s3-check")
        if args.update:
            argv += ["--update-config", "--overwrite"]
        if args.dry_run:
            argv.append("--dry-run")
        _log(f"-> {' '.join(shlex.quote(t) for t in argv)}")
        code = subprocess.run(argv, check=False, cwd=_REPO_ROOT).returncode
        if code != 0:
            _log(f"! {spec.key}: depictio-cli run exited {code}")
            failed += 1
        update_state(spec.key, ingested=code == 0 and not args.dry_run, project_name=project)
    return 1 if failed else 0


# --- list --------------------------------------------------------------------
def cmd_list(args: argparse.Namespace) -> int:
    state = load_state()
    header = f"{'key':<14} {'template':<48} {'profile':<18} {'n':>3} {'nf':<14} status"
    print(header)
    print("-" * len(header))
    for spec in RUNS:
        entry = state.get(spec.key, {})
        marks = "".join(
            mark if entry.get(flag) else "."
            for flag, mark in (
                ("submitted", "S"),
                ("fetched", "F"),
                ("reprocessed", "M"),
                ("ingested", "I"),
            )
        )
        nf = spec.nxf_ver or spec.nf_env.replace("nextflow", "nf")
        rev = f" -r {spec.effective_revision}"
        print(
            f"{spec.key:<14} {spec.template_id + rev:<48} {spec.profile:<18} "
            f"{spec.samples:>3} {nf:<14} {marks} {entry.get('job_id', '')}"
        )
    print("\nstatus: S submitted, F fetched, M multiqc-reprocessed, I ingested")
    if args.verbose:
        print()
        for spec in RUNS:
            print(f"{spec.key:<14} {spec.note}")
    return 0


# --- cli ---------------------------------------------------------------------
def _select(args: argparse.Namespace) -> list[RunSpec]:
    if not getattr(args, "run", None):
        return list(RUNS)
    selected = []
    for key in args.run:
        if key not in RUNS_BY_KEY:
            raise SystemExit(f"unknown run {key!r}; known: {', '.join(RUNS_BY_KEY)}")
        selected.append(RUNS_BY_KEY[key])
    return selected


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="nfcore_validation_hpc.py",
        description=__doc__.splitlines()[0],
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    def add_run_option(sub: argparse.ArgumentParser) -> None:
        sub.add_argument(
            "--run",
            action="append",
            metavar="KEY",
            help="restrict to this run (repeatable); default: all",
        )

    p_list = subparsers.add_parser("list", help="show the runs and their state")
    p_list.add_argument("-v", "--verbose", action="store_true", help="also print why each profile")
    p_list.set_defaults(func=cmd_list)

    p_submit = subparsers.add_parser("submit", help="queue the head job for each run")
    add_run_option(p_submit)
    p_submit.add_argument("--dry-run", action="store_true", help="print the sbatch script only")
    p_submit.set_defaults(func=cmd_submit)

    p_status = subparsers.add_parser("status", help="read .nextflow.log and the execution trace")
    add_run_option(p_status)
    p_status.set_defaults(func=cmd_status)

    p_fetch = subparsers.add_parser("fetch", help="rsync the outputs back and build the DATA_ROOT")
    add_run_option(p_fetch)
    p_fetch.add_argument("--dry-run", action="store_true", help="rsync --dry-run --stats")
    p_fetch.set_defaults(func=cmd_fetch)

    p_reprocess = subparsers.add_parser("reprocess", help="re-run MultiQC where the parquet is old")
    add_run_option(p_reprocess)
    p_reprocess.add_argument(
        "--python",
        type=lambda v: Path(v).expanduser(),
        # multiqc_reprocess needs MultiQC itself, which the bare interpreter does
        # not have; the repo venv is where the pinned one lives.
        default=(_REPO_ROOT / ".venv" / "bin" / "python")
        if (_REPO_ROOT / ".venv" / "bin" / "python").exists()
        else Path(sys.executable),
        help="interpreter that has MultiQC installed",
    )
    p_reprocess.add_argument("--dry-run", action="store_true")
    p_reprocess.set_defaults(func=cmd_reprocess)

    p_ingest = subparsers.add_parser("ingest", help="depictio-cli run over the repatriated trees")
    add_run_option(p_ingest)
    p_ingest.add_argument(
        "--cli",
        default=os.environ.get("DEPICTIO_CLI_BIN", "depictio-cli"),
        help="the 1.10.0 CLI to use (default: $DEPICTIO_CLI_BIN or depictio-cli)",
    )
    p_ingest.add_argument(
        "--cli-config",
        type=lambda v: Path(v).expanduser(),
        default=os.environ.get("DEPICTIO_CLI_CONFIG_PATH"),
        help="CLI config to use (default: $DEPICTIO_CLI_CONFIG_PATH, else the CLI's own)",
    )
    p_ingest.add_argument("--project-prefix", default="", help="prepended to every project name")
    p_ingest.add_argument("--update", action="store_true", help="--update-config --overwrite")
    p_ingest.add_argument("--dry-run", action="store_true")
    p_ingest.set_defaults(func=cmd_ingest)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return int(args.func(args))
    except subprocess.CalledProcessError as exc:
        _log(f"! command failed ({exc.returncode}): {exc.stderr or exc.stdout}")
        return 1
    except (OSError, ValueError) as exc:
        _log(f"! {exc}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
