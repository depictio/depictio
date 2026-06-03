"""Pre-compute canonical-DC seed TSVs for the ampliseq reference dataset.

The reference-dataset resolver (db_init_reference_datasets.resolve_template_for_init)
converts ``source: transformed`` DCs into file scans pointing at
``{data_root}/{dc_tag}.tsv``. When the seed file is missing the DC is silently
dropped — which makes any advanced_viz tile binding to that DC return 404 at
runtime.

This script runs every recipe in-process on the committed source TSVs
(ancombc_results.tsv, taxonomy_rel_abundance.tsv, alpha_rarefaction.tsv,
taxonomy_composition.tsv, input/Metadata_full.tsv) and writes the resulting
canonical TSVs alongside them.

Usage (from repo root):
    .venv/bin/python depictio/projects/nf-core/ampliseq/2.16.0/generate_canonical_seeds.py
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import polars as pl

REPO_ROOT = Path(__file__).resolve().parents[5]
sys.path.insert(0, str(REPO_ROOT))

DATA_ROOT = Path(__file__).resolve().parent
RECIPES_DIR = DATA_ROOT.parent / "recipes"
# Module-owned recipes now live in the catalog module folders (e.g. the qiime2
# canonical reshapes), so look there too — pipeline-keyed recipes still win.
CATALOG_DIR = REPO_ROOT / "depictio" / "catalog"


def _load_recipe(name: str):
    path = RECIPES_DIR / f"{name}.py"
    if not path.exists():
        # Fall back to a module-owned recipe co-located in a catalog module folder.
        matches = sorted(CATALOG_DIR.glob(f"*/{name}.py"))
        if not matches:
            raise FileNotFoundError(
                f"Recipe '{name}' not found under {RECIPES_DIR} or {CATALOG_DIR}"
            )
        path = matches[0]
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _read_tsv(path: Path) -> pl.DataFrame:
    return pl.read_csv(path, separator="\t")


def _read_qiime2_metadata_tsv(path: Path) -> pl.DataFrame:
    """Read a QIIME2 per-sample metadata.tsv, skipping the `#q2:types` row.

    QIIME2 prepends a second header row declaring categorical/numeric per
    column. polars.read_csv would read this row as data and coerce numeric
    columns to Utf8 — so we manually drop it first.
    """
    raw = pl.read_csv(path, separator="\t", infer_schema_length=0)
    return raw.filter(~pl.col(raw.columns[0]).str.starts_with("#q2:types")).with_columns(
        [
            pl.col(c).cast(pl.Float64, strict=False)
            for c in raw.columns
            if c in ("shannon_entropy", "faith_pd", "observed_features", "pielou_evenness")
        ]
    )


def main() -> None:
    # --- Source DCs (TSVs already committed at data_root) -----------------
    ancombc_results = _read_tsv(DATA_ROOT / "ancombc_results.tsv")
    taxonomy_rel_abundance = _read_tsv(DATA_ROOT / "taxonomy_rel_abundance.tsv")
    taxonomy_composition = _read_tsv(DATA_ROOT / "taxonomy_composition.tsv")
    metadata = _read_tsv(DATA_ROOT / "input" / "Metadata_full.tsv")

    # --- QIIME2 multi-metric source files (Phase E) ----------------------
    qiime2_root = DATA_ROOT / "data" / "qiime2"
    rarefaction_shannon = pl.read_csv(qiime2_root / "alpha-rarefaction" / "shannon.csv")
    rarefaction_observed = pl.read_csv(qiime2_root / "alpha-rarefaction" / "observed_features.csv")
    rarefaction_faith_pd = pl.read_csv(qiime2_root / "alpha-rarefaction" / "faith_pd.csv")
    alpha_div_shannon = _read_qiime2_metadata_tsv(
        qiime2_root / "diversity" / "alpha_diversity" / "shannon_vector" / "alpha-diversity.tsv"
    )
    alpha_div_observed = _read_qiime2_metadata_tsv(
        qiime2_root
        / "diversity"
        / "alpha_diversity"
        / "observed_features_vector"
        / "alpha-diversity.tsv"
    )
    alpha_div_faith_pd = _read_qiime2_metadata_tsv(
        qiime2_root / "diversity" / "alpha_diversity" / "faith_pd_vector" / "alpha-diversity.tsv"
    )
    alpha_div_evenness = _read_qiime2_metadata_tsv(
        qiime2_root / "diversity" / "alpha_diversity" / "evenness_vector" / "alpha-diversity.tsv"
    )
    qiime2_taxonomy = pl.read_csv(qiime2_root / "taxonomy" / "taxonomy.tsv", separator="\t")
    rel_asv = pl.read_csv(
        qiime2_root / "rel_abundance_tables" / "rel-table-ASV.tsv",
        separator="\t",
        skip_rows=1,
    )

    # Per-rank relative-abundance tables (QIIME2 collapse output). Level 2 is
    # Phylum, level 6 is Genus. The header line ``# Constructed from biom
    # file`` is a comment — `skip_rows=1` skips it so polars reads the real
    # `#OTU ID` header on the next line.
    rel_root = qiime2_root / "rel_abundance_tables"
    rel_phylum = pl.read_csv(rel_root / "rel-table-2.tsv", separator="\t", skip_rows=1)
    rel_class = pl.read_csv(rel_root / "rel-table-3.tsv", separator="\t", skip_rows=1)
    rel_order = pl.read_csv(rel_root / "rel-table-4.tsv", separator="\t", skip_rows=1)
    rel_family = pl.read_csv(rel_root / "rel-table-5.tsv", separator="\t", skip_rows=1)
    rel_genus = pl.read_csv(rel_root / "rel-table-6.tsv", separator="\t", skip_rows=1)

    # --- Tier 0: taxonomy_heatmap (also missing — chicken/egg for embedding_pcoa
    # and complex_heatmap_canonical). Generated from rel_abundance + metadata.
    taxonomy_heatmap = _load_recipe("taxonomy_heatmap").transform(
        {"rel_abundance": taxonomy_rel_abundance, "metadata": metadata}
    )
    taxonomy_heatmap.write_csv(DATA_ROOT / "taxonomy_heatmap.tsv", separator="\t")
    print(f"  -> taxonomy_heatmap.tsv ({taxonomy_heatmap.shape})")

    # --- Tier 1: existing canonical DCs (pre-PR) ---------------------------
    volcano_canonical = _load_recipe("volcano_canonical").transform({"ancombc": ancombc_results})
    volcano_canonical.write_csv(DATA_ROOT / "volcano_canonical.tsv", separator="\t")
    print(f"  -> volcano_canonical.tsv ({volcano_canonical.shape})")

    stacked_taxonomy_canonical = _load_recipe("stacked_taxonomy_canonical").transform(
        {
            "phylum": rel_phylum,
            "class_": rel_class,
            "order": rel_order,
            "family": rel_family,
            "genus": rel_genus,
            "metadata": metadata,
        }
    )
    stacked_taxonomy_canonical.write_csv(
        DATA_ROOT / "stacked_taxonomy_canonical.tsv", separator="\t"
    )
    print(f"  -> stacked_taxonomy_canonical.tsv ({stacked_taxonomy_canonical.shape})")

    embedding_pcoa = _load_recipe("embedding_pcoa").transform(
        {"taxonomy_heatmap": taxonomy_heatmap, "metadata": metadata}
    )
    embedding_pcoa.write_csv(DATA_ROOT / "embedding_pcoa.tsv", separator="\t")
    print(f"  -> embedding_pcoa.tsv ({embedding_pcoa.shape})")

    # --- Tier 1 (this PR): new canonical DCs -------------------------------
    da_barplot = _load_recipe("da_barplot_canonical").transform({"ancombc": ancombc_results})
    da_barplot.write_csv(DATA_ROOT / "da_barplot_canonical.tsv", separator="\t")
    print(f"  -> da_barplot_canonical.tsv ({da_barplot.shape})")

    rarefaction = _load_recipe("rarefaction_canonical").transform(
        {
            "shannon": rarefaction_shannon,
            "observed_features": rarefaction_observed,
            "faith_pd": rarefaction_faith_pd,
            "metadata": metadata,
        }
    )
    rarefaction.write_csv(DATA_ROOT / "rarefaction_canonical.tsv", separator="\t")
    print(f"  -> rarefaction_canonical.tsv ({rarefaction.shape})")

    alpha_diversity_multi = _load_recipe("alpha_diversity_multi_canonical").transform(
        {
            "shannon": alpha_div_shannon,
            "observed_features": alpha_div_observed,
            "faith_pd": alpha_div_faith_pd,
            "evenness": alpha_div_evenness,
        }
    )
    alpha_diversity_multi.write_csv(
        DATA_ROOT / "alpha_diversity_multi_canonical.tsv", separator="\t"
    )
    print(f"  -> alpha_diversity_multi_canonical.tsv ({alpha_diversity_multi.shape})")

    complex_heatmap = _load_recipe("complex_heatmap_canonical").transform(
        {"heatmap": taxonomy_heatmap}
    )
    complex_heatmap.write_csv(DATA_ROOT / "complex_heatmap_canonical.tsv", separator="\t")
    print(f"  -> complex_heatmap_canonical.tsv ({complex_heatmap.shape})")

    sunburst = _load_recipe("sunburst_canonical").transform(
        {"genus": rel_genus, "metadata": metadata}
    )
    sunburst.write_csv(DATA_ROOT / "sunburst_canonical.tsv", separator="\t")
    print(f"  -> sunburst_canonical.tsv ({sunburst.shape})")

    sankey = _load_recipe("sankey_canonical").transform({"genus": rel_genus, "metadata": metadata})
    sankey.write_csv(DATA_ROOT / "sankey_canonical.tsv", separator="\t")
    print(f"  -> sankey_canonical.tsv ({sankey.shape})")

    # --- Tier 2 (this PR): derivation canonical DCs ------------------------
    upset = _load_recipe("upset_canonical").transform(
        {"rel_abundance": taxonomy_rel_abundance, "metadata": metadata}
    )
    upset.write_csv(DATA_ROOT / "upset_canonical.tsv", separator="\t")
    print(f"  -> upset_canonical.tsv ({upset.shape})")

    qq = _load_recipe("qq_canonical").transform({"ancombc": ancombc_results})
    qq.write_csv(DATA_ROOT / "qq_canonical.tsv", separator="\t")
    print(f"  -> qq_canonical.tsv ({qq.shape})")

    ma = _load_recipe("ma_canonical").transform(
        {"ancombc": ancombc_results, "composition": taxonomy_composition}
    )
    ma.write_csv(DATA_ROOT / "ma_canonical.tsv", separator="\t")
    print(f"  -> ma_canonical.tsv ({ma.shape})")

    bray_curtis = _load_recipe("bray_curtis_canonical").transform(
        {"rel_abundance": taxonomy_rel_abundance}
    )
    bray_curtis.write_csv(DATA_ROOT / "bray_curtis_canonical.tsv", separator="\t")
    print(f"  -> bray_curtis_canonical.tsv ({bray_curtis.shape})")

    tree_metadata = _load_recipe("tree_metadata_canonical").transform(
        {"taxonomy": qiime2_taxonomy, "asv_abundance": rel_asv, "metadata": metadata}
    )
    tree_metadata.write_csv(DATA_ROOT / "phylogenetic_tree_metadata_canonical.tsv", separator="\t")
    print(f"  -> phylogenetic_tree_metadata_canonical.tsv ({tree_metadata.shape})")

    print("Done.")


if __name__ == "__main__":
    main()
