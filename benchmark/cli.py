"""Typer entrypoint for the benchmark harness.

    python -m benchmark.cli generate --sizes 10mb --dcs 2        # data + configs only
    python -m benchmark.cli run      --sizes 10mb --cli-config ~/.depictio/CLI.yaml
    python -m benchmark.cli report                                # from results.jsonl
    python -m benchmark.cli all      --sizes 10mb --cli-config ~/.depictio/CLI.yaml

The Celery on/off dimension is a *server* setting (restart between halves): run
``run`` twice with different ``--server-mode`` labels against a stack booted with
``DEPICTIO_CELERY_OFFLOAD_RENDERING`` false then true (each render is stamped
with its actual path from the ``X-Celery-Path`` header). See ``benchmark/README.md``.
"""

from __future__ import annotations

from pathlib import Path

import typer

from benchmark.datagen_linked import DEFAULT_N_SAMPLES
from benchmark.matrix import (
    IngestSpec,
    MatrixSpec,
    parse_connect,
    parse_ints,
    parse_kinds,
    parse_sizes,
    parse_visu,
)

app = typer.Typer(add_completion=False, help="Depictio performance benchmark harness.")

DEFAULT_OUTPUT = "benchmark/output"


def _spec(sizes: str, components: str, dcs: str, connect: str, visu: str) -> MatrixSpec:
    return MatrixSpec(
        sizes=parse_sizes(sizes),
        n_components=parse_ints(components),
        n_dcs=parse_ints(dcs),
        connect=parse_connect(connect),
        visu=parse_visu(visu),
    )


# Shared option annotations
_SIZES = typer.Option("10mb", "--sizes", help="Comma list: 10mb,100mb,1gb,5gb,10gb")
_COMPONENTS = typer.Option("5", "--components", help="Comma list of components-per-tab counts")
_DCS = typer.Option("2", "--dcs", help="Comma list of #data-collections counts")
_CONNECT = typer.Option(
    "joins",
    "--connect",
    help="Comma list: independent,joins,links,links-adversarial "
    "(links = realistic 3-DC topology; links-adversarial = unique join key)",
)
_VISU = typer.Option("figure,table", "--visu", help="Comma list: figure,table,advanced_viz")
_OUTPUT = typer.Option(DEFAULT_OUTPUT, "--output", help="Output root (gitignored)")
_SAMPLES = typer.Option(
    DEFAULT_N_SAMPLES,
    "--samples",
    help=(
        "Join-key cardinality of the linked topology (distinct sample_id). "
        "Deliberately independent of the size tier — rows scale through the "
        "per-sample fan-out, the join key does not."
    ),
)
_PROFILE_LABEL = typer.Option(
    "",
    "--profile-label",
    help="Name for the hardware/CPU profile these numbers describe (e.g. mbp-m1max-4cpu)",
)
_REUSE_INGEST = typer.Option(
    False,
    "--reuse-ingest",
    help=(
        "Re-import the dashboard against the already-ingested project and skip "
        "the reset + ingest. For iterating on the dashboard itself; the run then "
        "reports no ingest timing. Falls back to a full ingest if the project "
        "does not exist."
    ),
)


@app.command()
def generate(
    sizes: str = _SIZES,
    components: str = _COMPONENTS,
    dcs: str = _DCS,
    connect: str = _CONNECT,
    visu: str = _VISU,
    output: str = _OUTPUT,
    samples: int = _SAMPLES,
    force: bool = typer.Option(False, "--force", help="Regenerate data even if a manifest exists"),
) -> None:
    """Generate datasets + project/dashboard configs for the matrix (no server)."""
    from benchmark.configgen import write_configs
    from benchmark.runner import prepare_dataset

    cells = _spec(sizes, components, dcs, connect, visu).expand()
    out = Path(output)
    typer.echo(f"Generating {len(cells)} cell(s) under {out}/ ...")
    for cell in cells:
        # Same helper the runner uses, so pre-staging here and running later
        # reuse the same directory instead of silently regenerating.
        dataset_dir, facts = prepare_dataset(cell, out, n_samples=samples, force=force)
        write_configs(cell, dataset_dir, out / "configs" / cell.slug, n_samples=samples)
        typer.echo(f"  ✓ {cell.slug}: {facts.summary}")
    typer.echo("Done.")


@app.command()
def run(
    cli_config: str = typer.Option(..., "--cli-config", help="Path to depictio CLI config YAML"),
    server_mode: str = typer.Option(
        "celery_off", "--server-mode", help="Label for this matrix half"
    ),
    sizes: str = _SIZES,
    components: str = _COMPONENTS,
    dcs: str = _DCS,
    connect: str = _CONNECT,
    visu: str = _VISU,
    output: str = _OUTPUT,
    cross_filter: bool = typer.Option(
        False, "--cross-filter", help="Also render links cells with a filter payload"
    ),
    force_datagen: bool = typer.Option(False, "--force-datagen", help="Regenerate data"),
    repeats: int = typer.Option(
        1, "--repeats", help="Passes over each cell's components (>1 separates warm from cold)"
    ),
    dashboard_load: bool = typer.Option(
        False,
        "--dashboard-load",
        help="Also fire all components at once (real dashboard cold open, under contention)",
    ),
    filter_rounds: int = typer.Option(
        0,
        "--filter-rounds",
        help=(
            "Filter changes to time on the warm dashboard (each uses a NEW value, "
            "so the filtered cache can't answer it). 0 disables the phase."
        ),
    ),
    depictio_bin: str = typer.Option(
        "",
        "--depictio-bin",
        help=(
            "Python interpreter whose `depictio` is THIS worktree (the CLI runs as "
            "`<interp> -m depictio.cli`). Empty = the interpreter running the benchmark. "
            "Do NOT pass a `bin/depictio` console script: it imports the main checkout, "
            "not the worktree, so CLI changes are measured against the wrong source — "
            "the run hard-fails if the resolved source is outside the worktree."
        ),
    ),
    samples: int = _SAMPLES,
    profile_label: str = _PROFILE_LABEL,
    reuse_ingest: bool = _REUSE_INGEST,
) -> None:
    """Ingest + render the matrix against a live stack; append to results.jsonl."""
    from benchmark.profile import collect_profile, describe
    from benchmark.runner import run_matrix

    cells = _spec(sizes, components, dcs, connect, visu).expand()
    profile = collect_profile(profile_label or f"{server_mode}-unlabelled")
    typer.echo(f"Running {len(cells)} cell(s) [server_mode={server_mode}] ...")
    for line in describe(profile):
        typer.echo(f"  {line}")
    results = run_matrix(
        cells,
        cli_config_path=cli_config,
        output_root=output,
        server_mode=server_mode,
        cross_filter=cross_filter,
        force_datagen=force_datagen,
        repeats=repeats,
        dashboard_load=dashboard_load,
        filter_rounds=filter_rounds,
        depictio_bin=depictio_bin,
        n_samples=samples,
        profile=profile,
        reuse_ingest=reuse_ingest,
    )
    typer.echo(f"Results appended to {results}")


@app.command()
def ingest(
    cli_config: str = typer.Option(..., "--cli-config", help="Path to depictio CLI config YAML"),
    kinds: str = typer.Option(
        "table,multiqc,images", "--kinds", help="Comma list: table,multiqc,images"
    ),
    sizes: str = typer.Option("10mb,100mb,1gb", "--sizes", help="Table byte sizes"),
    multiqc_counts: str = typer.Option("1,5,25", "--multiqc-counts", help="MultiQC file counts"),
    image_counts: str = typer.Option("1000,10000", "--image-counts", help="Image counts"),
    dcs: str = typer.Option("1", "--dcs", help="Table #DCs (multi-DC ingestion path)"),
    multiqc_fixture: str = typer.Option(
        "small", "--multiqc-fixture", help="small (2.6M) | large (24M)"
    ),
    output: str = _OUTPUT,
    force_datagen: bool = typer.Option(False, "--force-datagen", help="Regenerate data"),
    streaming: bool = typer.Option(
        False, "--streaming", help="Ingest tables via the streamed Delta write (before/after)"
    ),
    depictio_bin: str = typer.Option(
        "",
        "--depictio-bin",
        help=(
            "Python interpreter whose `depictio` is THIS worktree (the CLI runs as "
            "`<interp> -m depictio.cli`). Empty = the interpreter running the benchmark. "
            "Do NOT pass a `bin/depictio` console script: it imports the main checkout, "
            "not the worktree, so CLI changes are measured against the wrong source — "
            "the run hard-fails if the resolved source is outside the worktree."
        ),
    ),
) -> None:
    """Ingestion-only benchmark across DC types (table / multiqc / images)."""
    from benchmark.runner import run_ingest_matrix

    spec = IngestSpec(
        kinds=parse_kinds(kinds),
        table_sizes=parse_sizes(sizes),
        multiqc_counts=parse_ints(multiqc_counts),
        image_counts=parse_ints(image_counts),
        n_dcs=parse_ints(dcs),
    )
    cells = spec.expand()
    typer.echo(f"Ingesting {len(cells)} cell(s) [{kinds}] ...")
    results = run_ingest_matrix(
        cells,
        cli_config_path=cli_config,
        output_root=output,
        multiqc_fixture=multiqc_fixture,
        force_datagen=force_datagen,
        streaming=streaming,
        depictio_bin=depictio_bin,
    )
    typer.echo(f"Results appended to {results}")


@app.command()
def report(output: str = _OUTPUT) -> None:
    """Build results.csv + REPORT.md + plots from results.jsonl."""
    from benchmark.report import build_report

    path = build_report(output)
    typer.echo(f"Wrote {path}")


@app.command("blog-metrics")
def blog_metrics(output: str = _OUTPUT) -> None:
    """Build blog_metrics.json + BLOG_SNIPPET.md from results.jsonl.

    Absolute numbers for the current build — no baseline, so no speedup claims.
    """
    from benchmark.blog_metrics import build_blog_metrics

    json_path, snippet_path = build_blog_metrics(output)
    typer.echo(f"Wrote {json_path}")
    typer.echo(f"Wrote {snippet_path}")


@app.command()
def all(
    cli_config: str = typer.Option(..., "--cli-config", help="Path to depictio CLI config YAML"),
    server_mode: str = typer.Option("celery_off", "--server-mode"),
    sizes: str = _SIZES,
    components: str = _COMPONENTS,
    dcs: str = _DCS,
    connect: str = _CONNECT,
    visu: str = _VISU,
    output: str = _OUTPUT,
    cross_filter: bool = typer.Option(False, "--cross-filter"),
    force_datagen: bool = typer.Option(False, "--force-datagen"),
    repeats: int = typer.Option(1, "--repeats"),
    dashboard_load: bool = typer.Option(False, "--dashboard-load"),
    filter_rounds: int = typer.Option(0, "--filter-rounds"),
    depictio_bin: str = typer.Option(
        "",
        "--depictio-bin",
        help=(
            "Python interpreter whose `depictio` is THIS worktree (runs `<interp> -m "
            "depictio.cli`). Empty = the benchmark's own interpreter. Not a console script."
        ),
    ),
    samples: int = _SAMPLES,
    profile_label: str = _PROFILE_LABEL,
    reuse_ingest: bool = _REUSE_INGEST,
) -> None:
    """generate (implicit) -> run -> report in one shot."""
    # Every parameter must be forwarded explicitly: ``run`` is Typer-decorated,
    # so an omitted argument resolves to its OptionInfo sentinel, not to the
    # value shown in the help text.
    run(
        cli_config=cli_config,
        server_mode=server_mode,
        sizes=sizes,
        components=components,
        dcs=dcs,
        connect=connect,
        visu=visu,
        output=output,
        cross_filter=cross_filter,
        force_datagen=force_datagen,
        repeats=repeats,
        dashboard_load=dashboard_load,
        filter_rounds=filter_rounds,
        depictio_bin=depictio_bin,
        samples=samples,
        profile_label=profile_label,
        reuse_ingest=reuse_ingest,
    )
    report(output=output)
    blog_metrics(output=output)


def main() -> None:
    app()


if __name__ == "__main__":
    main()
