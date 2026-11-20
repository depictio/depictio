"""CLI tests for `depictio dashboard build-static` (serverless producer B)."""

from pathlib import Path

import polars as pl
import pytest
from typer.testing import CliRunner

from depictio.cli.cli.commands.dashboard import app

runner = CliRunner()

REPO_ROOT = Path(__file__).resolve().parents[4]
EXAMPLE_SPEC = REPO_ROOT / "depictio" / "serverless" / "examples" / "penguins.yaml"
ISLAND_REGIONS_CSV = (
    REPO_ROOT / "depictio" / "serverless" / "examples" / "data" / "island_regions.csv"
)
PENGUINS_DATA = REPO_ROOT / "depictio" / "projects" / "init" / "penguins" / "data"


@pytest.fixture
def data_dir(tmp_path: Path) -> Path:
    """The example's documented data layout, derived from the repo CSVs: the
    joined penguins frame plus the linked island → region lookup."""
    parts = []
    for run in sorted(p for p in PENGUINS_DATA.iterdir() if p.is_dir()):
        demo = pl.read_csv(run / "demographic_data.csv")
        phys = pl.read_csv(run / "physical_features.csv")
        parts.append(demo.join(phys, on="individual_id", how="inner"))
    dc_dir = tmp_path / "data" / "penguin_species_analysis"
    dc_dir.mkdir(parents=True)
    pl.concat(parts).write_parquet(dc_dir / "joined_penguins_complete.parquet")
    pl.read_csv(ISLAND_REGIONS_CSV).write_parquet(dc_dir / "island_regions.parquet")
    return tmp_path / "data"


def test_check_prints_tier_table_and_writes_nothing(data_dir: Path, tmp_path: Path) -> None:
    out = tmp_path / "bundle.html"
    result = runner.invoke(
        app,
        [
            "build-static",
            "--spec",
            str(EXAMPLE_SPEC),
            "--data",
            str(data_dir),
            "--out",
            str(out),
            "--check",
        ],
    )
    assert result.exit_code == 0, result.output
    assert not out.exists()
    # Tier table + summary (rich may wrap long cells, so assert on short tokens)
    assert "frozen" in result.output
    assert "live" in result.output
    # 12 components: 10 planned live (incl. the 2 advanced_viz data-path kinds,
    # live since phase 4, and the linked collection's filter + table) + the 2
    # figures preflight can only promise frozen.
    assert "12 component(s)" in result.output
    assert "10 live, 2 frozen" in result.output
    # The example's one cross-DC link: both endpoints are component DCs, so it
    # resolves against the bundled Parquet in the browser (tier A).
    assert "1 link(s): 1 tier A" in result.output
    assert "nothing written" in result.output.lower()


def test_check_needs_no_data_dir(tmp_path: Path) -> None:
    # Preflight classifies from the spec alone — an empty data dir is fine.
    result = runner.invoke(
        app,
        ["build-static", "--spec", str(EXAMPLE_SPEC), "--data", str(tmp_path), "--check"],
    )
    assert result.exit_code == 0, result.output


def test_build_writes_bundle(data_dir: Path, tmp_path: Path) -> None:
    from depictio.serverless.producer_b import TEMPLATE_PATH

    if not TEMPLATE_PATH.exists():
        pytest.skip("dist-static/static.html not built (run `pnpm run build:static`)")
    out = tmp_path / "bundle.html"
    result = runner.invoke(
        app,
        [
            "build-static",
            "--spec",
            str(EXAMPLE_SPEC),
            "--data",
            str(data_dir),
            "--out",
            str(out),
        ],
    )
    assert result.exit_code == 0, result.output
    assert out.exists()
    assert "Static bundle written" in result.output
    assert "__BUNDLE_MANIFEST__" not in out.read_text()


def test_missing_spec_errors(tmp_path: Path) -> None:
    result = runner.invoke(
        app,
        ["build-static", "--spec", str(tmp_path / "nope.yaml"), "--data", str(tmp_path)],
    )
    assert result.exit_code == 1
    assert "not found" in result.output


def test_unknown_mode_errors(data_dir: Path) -> None:
    result = runner.invoke(
        app,
        [
            "build-static",
            "--spec",
            str(EXAMPLE_SPEC),
            "--data",
            str(data_dir),
            "--mode",
            "multi-file",
        ],
    )
    assert result.exit_code == 1
    assert "unknown mode" in result.output


def test_missing_data_errors_with_expected_path(tmp_path: Path) -> None:
    empty = tmp_path / "empty"
    empty.mkdir()
    result = runner.invoke(
        app,
        ["build-static", "--spec", str(EXAMPLE_SPEC), "--data", str(empty)],
    )
    assert result.exit_code == 1
    assert "joined_penguins_complete" in result.output
