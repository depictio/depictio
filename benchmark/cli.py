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

from benchmark.matrix import (
    MatrixSpec,
    parse_connect,
    parse_ints,
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
_CONNECT = typer.Option("joins", "--connect", help="Comma list: independent,joins,links")
_VISU = typer.Option("figure,table", "--visu", help="Comma list: figure,table,advanced_viz")
_OUTPUT = typer.Option(DEFAULT_OUTPUT, "--output", help="Output root (gitignored)")


@app.command()
def generate(
    sizes: str = _SIZES,
    components: str = _COMPONENTS,
    dcs: str = _DCS,
    connect: str = _CONNECT,
    visu: str = _VISU,
    output: str = _OUTPUT,
    force: bool = typer.Option(False, "--force", help="Regenerate data even if a manifest exists"),
) -> None:
    """Generate datasets + project/dashboard configs for the matrix (no server)."""
    from benchmark.configgen import write_configs
    from benchmark.datagen import generate_dataset

    cells = _spec(sizes, components, dcs, connect, visu).expand()
    out = Path(output)
    typer.echo(f"Generating {len(cells)} cell(s) under {out}/ ...")
    for cell in cells:
        dataset_dir = out / "data" / f"{cell.size}_dc{cell.n_dcs}"
        manifest = generate_dataset(cell.size_bytes, cell.n_dcs, dataset_dir, force=force)
        write_configs(cell, dataset_dir, out / "configs" / cell.slug)
        typer.echo(f"  ✓ {cell.slug}: {manifest.n_runs} runs, {manifest.rows_total} rows/DC")
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
    depictio_bin: str = typer.Option("depictio", "--depictio-bin", help="depictio CLI executable"),
) -> None:
    """Ingest + render the matrix against a live stack; append to results.jsonl."""
    from benchmark.runner import run_matrix

    cells = _spec(sizes, components, dcs, connect, visu).expand()
    typer.echo(f"Running {len(cells)} cell(s) [server_mode={server_mode}] ...")
    results = run_matrix(
        cells,
        cli_config_path=cli_config,
        output_root=output,
        server_mode=server_mode,
        cross_filter=cross_filter,
        force_datagen=force_datagen,
        depictio_bin=depictio_bin,
    )
    typer.echo(f"Results appended to {results}")


@app.command()
def report(output: str = _OUTPUT) -> None:
    """Build results.csv + REPORT.md + plots from results.jsonl."""
    from benchmark.report import build_report

    path = build_report(output)
    typer.echo(f"Wrote {path}")


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
    depictio_bin: str = typer.Option("depictio", "--depictio-bin"),
) -> None:
    """generate (implicit) -> run -> report in one shot."""
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
        depictio_bin=depictio_bin,
    )
    report(output=output)


def main() -> None:
    app()


if __name__ == "__main__":
    main()
