"""`rank_at`: positional rank of a collapsed lineage, tolerant of a Domain+Kingdom top."""

import polars as pl

from depictio.recipes.lib.lineage import rank_at


def _ranks(lineage: str, n: int = 3) -> list[str]:
    df = pl.DataFrame({"l": [lineage]})
    return df.select([rank_at(pl.col("l"), i).alias(str(i)) for i in range(n)]).row(0)


def test_seven_rank_lineage_is_read_in_place():
    assert _ranks("Bacteria;Pseudomonadota;Gammaproteobacteria") == (
        "Bacteria",
        "Pseudomonadota",
        "Gammaproteobacteria",
    )


def test_repeated_domain_kingdom_is_dropped_so_ranks_do_not_shift():
    # sbdi-gtdb: Domain;Kingdom;Phylum;Class
    assert _ranks("Bacteria;Bacteria;Pseudomonadota;Gammaproteobacteria") == (
        "Bacteria",
        "Pseudomonadota",
        "Gammaproteobacteria",
    )


def test_blank_and_missing_ranks_are_unclassified():
    assert _ranks("Archaea;;") == ("Archaea", "Unclassified", "Unclassified")
    assert _ranks("Archaea") == ("Archaea", "Unclassified", "Unclassified")
