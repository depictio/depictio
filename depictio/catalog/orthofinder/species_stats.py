"""How much of each proteome OrthoFinder placed, from ``Statistics_PerSpecies.tsv``.

The file holds several tables one after the other, separated by blank lines;
the first has one column per species and one row per statistic ("Number of
genes", "Percentage of genes in orthogroups", ...). That table is transposed
into one row per species. The species names are OrthoFinder's, the proteome
file names without their extension, which a pipeline sets to its assembly ids.

Input: ``Comparative_Genomics_Statistics/Statistics_PerSpecies.tsv``, one line
per row (a separator the file cannot contain).

Output schema:
    genome : Utf8                              species, as OrthoFinder names it
    genes : Int64                              genes in its proteome
    genes_in_orthogroups : Int64               of which placed in an orthogroup
    unassigned_genes : Int64                   placed in none
    genes_in_orthogroups_pct : Float64         placed share, percent
    unassigned_genes_pct : Float64             unplaced share, percent
    orthogroups : Int64                        orthogroups holding the species
    orthogroups_pct : Float64                  their share of all orthogroups, percent
    species_specific_orthogroups : Int64       orthogroups of this species alone
    genes_in_species_specific : Int64          genes in them
    genes_in_species_specific_pct : Float64    their share of the genes, percent
"""

from __future__ import annotations

import polars as pl

from depictio.models.models.transforms import RecipeSource

RAW_LINE_COL = "raw_line"

# INPUT SCHEMA: the columns each source must contain, checked before transform().
SOURCES: list[RecipeSource] = [
    RecipeSource(
        ref="stats",
        glob_pattern="**/Comparative_Genomics_Statistics/Statistics_PerSpecies.tsv",
        format="csv",
        read_kwargs={
            "separator": "\x1e",
            "has_header": False,
            "new_columns": [RAW_LINE_COL],
            "quote_char": None,
            "infer_schema_length": 0,
        },
        input_schema={RAW_LINE_COL: pl.Utf8},
    )
]

# OUTPUT SCHEMA: the columns transform() returns, checked after it.
OUTPUT_SCHEMA: dict[str, type[pl.DataType]] = {
    "genome": pl.Utf8,
    "genes": pl.Int64,
    "genes_in_orthogroups": pl.Int64,
    "unassigned_genes": pl.Int64,
    "genes_in_orthogroups_pct": pl.Float64,
    "unassigned_genes_pct": pl.Float64,
    "orthogroups": pl.Int64,
    "orthogroups_pct": pl.Float64,
    "species_specific_orthogroups": pl.Int64,
    "genes_in_species_specific": pl.Int64,
    "genes_in_species_specific_pct": pl.Float64,
}

#: OrthoFinder's row label -> output column.
ROWS: dict[str, str] = {
    "Number of genes": "genes",
    "Number of genes in orthogroups": "genes_in_orthogroups",
    "Number of unassigned genes": "unassigned_genes",
    "Percentage of genes in orthogroups": "genes_in_orthogroups_pct",
    "Percentage of unassigned genes": "unassigned_genes_pct",
    "Number of orthogroups containing species": "orthogroups",
    "Percentage of orthogroups containing species": "orthogroups_pct",
    "Number of species-specific orthogroups": "species_specific_orthogroups",
    "Number of genes in species-specific orthogroups": "genes_in_species_specific",
    "Percentage of genes in species-specific orthogroups": "genes_in_species_specific_pct",
}


def _number(text: str) -> float | None:
    try:
        return float(text.strip())
    except ValueError:
        return None


def transform(sources: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """Transpose the first table of the file into one row per species."""
    lines = [str(x) for x in sources["stats"].get_column(RAW_LINE_COL).to_list() if x]
    species: list[str] = []
    values: dict[str, dict[str, float | None]] = {}
    for line in lines:
        cells = line.rstrip("\r\n").split("\t")
        if not species:
            if cells and cells[0].strip() == "" and len(cells) > 1:
                species = [c.strip() for c in cells[1:]]
            continue
        label = cells[0].strip()
        if label == "" or label.startswith("Number of genes per-species"):
            break
        if label in ROWS:
            values[ROWS[label]] = {
                sp: _number(v) for sp, v in zip(species, cells[1:], strict=False)
            }
    if not species or "genes" not in values:
        raise ValueError("orthofinder_species_stats: no per-species table in the file")
    rows = [
        {"genome": sp, **{col: values.get(col, {}).get(sp) for col in ROWS.values()}}
        for sp in species
    ]
    frame = pl.DataFrame(
        rows, schema={c: (pl.Utf8 if c == "genome" else pl.Float64) for c in OUTPUT_SCHEMA}
    )
    return frame.select([pl.col(c).cast(t) for c, t in OUTPUT_SCHEMA.items()]).sort("genome")
