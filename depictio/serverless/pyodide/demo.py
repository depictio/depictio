"""Build the Python-runtime demo bundle (CI: serverless-ci ``bundles`` job).

The other demos are committed manifests the JS-only build injects; this one
carries tens of MB of Pyodide assets fetched and verified at build time, so it
is built here, by producer B, straight to HTML:

    DEPICTIO_CONTEXT=cli uv run python -m depictio.serverless.pyodide.demo \\
        depictio/viewer/dist-static/site/demo-python-runtime.html
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import polars as pl

REPO_ROOT = Path(__file__).resolve().parents[3]
EXAMPLES = REPO_ROOT / "depictio" / "serverless" / "examples"
SHOWCASE = REPO_ROOT / "depictio" / "projects" / "init" / "advanced_viz_showcase" / "data"
SPEC = EXAMPLES / "python_runtime.yaml"


def data_dir(root: Path) -> Path:
    from depictio.serverless.examples.generate_demo_manifest import penguins_frame

    peng = root / "penguin_species_analysis"
    peng.mkdir(parents=True)
    penguins_frame().write_parquet(peng / "joined_penguins_complete.parquet")
    demo = root / "python_demo"
    demo.mkdir()
    for tag in ("group_compare_demo", "embedding_features"):
        pl.read_csv(SHOWCASE / f"{tag}.tsv", separator="\t").write_parquet(demo / f"{tag}.parquet")
    return root


def build(out: Path) -> None:
    from depictio.serverless.producer_b import build_static

    with tempfile.TemporaryDirectory() as tmp:
        result = build_static(SPEC, data_dir(Path(tmp)), out, python_runtime="on")
    tiers = {r.component_id: r.tier.value for r in result.tier_rows}
    addon = next(a for a in result.manifest.addons if a.name == "pyodide")
    print(
        f"wrote {out} ({out.stat().st_size / 1e6:.1f} MB, Pyodide {addon.version}: "
        f"{', '.join(addon.packages)})"
    )
    print("tiers:", tiers)


if __name__ == "__main__":
    build(Path(sys.argv[1]) if len(sys.argv) > 1 else Path("demo-python-runtime.html"))
