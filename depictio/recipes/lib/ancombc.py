"""ANCOM-BC at ingest, for the comparisons a pipeline did not run.

nf-core/ampliseq runs ANCOM-BC through QIIME2 (R ``ANCOMBC::ancombc``) with every
level of a metadata column tested against one reference, the alphabetical first. With
three or more levels the other pairs are missing (Naples vs Barcelona when Athens is
the reference), and a taxonomy the pipeline never saw (the merged SILVA + PR2 one) has
no result at all. This module computes them from the same counts.

Settings follow QIIME2's ``composition ancombc`` as nf-core/ampliseq 2.18.0 calls it
(``conf/modules.config``: ``--p-prv-cut 0.1 --p-lib-cut 500 --p-alpha 0.05
--p-conserve``): samples under 500 reads left out (``lib_cut``), taxa kept when present
in at least 10% of the samples (``prv_cut``), counts plus a pseudocount of 1, Holm
correction per contrast, and ``conserve`` on: each standard error is widened by the
spread of its contrast's bias estimate. scikit-bio's port
computes that spread (``_estimate_bias_em``) but adds it only for ANCOM-BC2, so it is
read back here and added. With it, a contrast the pipeline did run comes out with the
same estimates, standard errors and q-values as the pipeline's own slices.

Contrast names follow QIIME2: ``<column><level>`` against the reference the pipeline
used (``base``), and ``<column><b>_vs_<a>`` for any other pair, ``a`` the reference,
the pair ordered alphabetically.

Needs the ``stats`` extra (scikit-bio).
"""

from __future__ import annotations

import threading
from collections.abc import Iterable
from itertools import combinations
from unittest import mock

import numpy as np
import pandas as pd
import polars as pl

PRV_CUT = 0.10
LIB_CUT = 500
PSEUDOCOUNT = 1.0
COLUMNS = ("id", "contrast", "lfc", "p_val", "q_val", "w", "se")

# The conserve term is read by wrapping a module-level scikit-bio function for the
# length of one fit; two fits at once would read each other's values.
_LOCK = threading.Lock()


def available() -> bool:
    """Whether scikit-bio is installed (the ``stats`` extra)."""
    try:
        import skbio.stats.composition  # noqa: F401
    except ImportError:
        return False
    return True


def contrast_name(column: str, level: str, reference: str, base: str) -> str:
    """QIIME2's name for ``level`` against ``reference`` (see the module docstring)."""
    return f"{column}{level}" if reference == base else f"{column}{level}_vs_{reference}"


def _prepare(counts: pd.DataFrame, groups: pd.Series) -> tuple[pd.DataFrame, pd.Series]:
    """Samples with a group and at least ``LIB_CUT`` reads, and taxa past the prevalence
    cut, as ANCOM-BC is given them."""
    groups = groups.dropna().astype(str)
    samples = counts.index.intersection(groups.index)
    table = counts.loc[samples].astype(float)
    table = table.loc[table.sum(axis=1) >= LIB_CUT]
    samples = table.index
    table = table.loc[:, (table > 0).mean() >= PRV_CUT]
    return table, groups.loc[samples]


def fit(
    counts: pd.DataFrame, groups: pd.Series, reference: str, *, conserve: bool = True
) -> pl.DataFrame:
    """One ANCOM-BC fit: every other level against ``reference``.

    ``counts`` is samples x taxa, ``groups`` the level of each sample (indexed by
    sample). Returns ``id`` (taxon), ``level`` and lfc / se / w / p_val / q_val.
    """
    from scipy.stats import norm
    from skbio.stats.composition import _ancombc as core
    from skbio.stats.composition import ancombc
    from statsmodels.stats.multitest import multipletests

    table, grp = _prepare(counts, groups)
    # Object, not pandas 3's string dtype: patsy (the formula) cannot read the latter.
    metadata = pd.DataFrame({"grp": pd.Series(grp.tolist(), index=grp.index, dtype=object)})
    formula = f"C(grp, Treatment({reference!r}))"

    biases: list[tuple] = []
    real = core._estimate_bias_em

    def spy(*args, **kwargs):
        out = real(*args, **kwargs)
        biases.append(out)
        return out

    with _LOCK, mock.patch.object(core, "_estimate_bias_em", spy):
        result = ancombc(table + PSEUDOCOUNT, metadata, formula, p_adjust=None).result

    frames = []
    covariates = list(dict.fromkeys(result.index.get_level_values("Covariate")))
    for i, covariate in enumerate(covariates):
        prefix = "C(grp, Treatment("
        if "[T." not in covariate or not covariate.startswith(prefix):
            continue  # the intercept
        sub = result.xs(covariate, level="Covariate")
        se = sub["SE"].to_numpy(dtype=float)
        if conserve:
            se = se + float(np.sqrt(biases[i][2]))
        lfc = sub["Log(FC)"].to_numpy(dtype=float)
        w = lfc / se
        p = 2 * norm.sf(np.abs(w))
        q = np.full_like(p, np.nan)
        finite = np.isfinite(p)
        if finite.any():
            q[finite] = multipletests(p[finite], method="holm")[1]
        frames.append(
            pl.DataFrame(
                {
                    "id": [str(t) for t in sub.index],
                    "level": covariate.split("))[T.", 1)[1][:-1],
                    "lfc": lfc,
                    "se": se,
                    "w": w,
                    "p_val": p,
                    "q_val": q,
                }
            )
        )
    return pl.concat(frames) if frames else pl.DataFrame()


def levels_of(groups: pd.Series) -> list[str]:
    return sorted(groups.dropna().astype(str).unique())


def pairs(
    counts: pd.DataFrame,
    groups: pd.Series,
    column: str,
    *,
    base: str | None = None,
    skip: Iterable[str] = (),
    conserve: bool = True,
) -> pl.DataFrame:
    """Every pair of levels, but the contrasts named in ``skip``, in the long layout of
    the ANCOM-BC recipe (``COLUMNS``).

    ``base`` is the pipeline's reference (default: the alphabetical first): a pair
    holding it is named ``<column><level>``. One fit per reference that still has a
    contrast to give.
    """
    levels = levels_of(groups)
    base = base if base in levels else (levels[0] if levels else None)
    skip = set(skip)
    wanted: dict[str, dict[str, str]] = {}  # reference -> level -> contrast name
    for a, b in combinations(levels, 2):
        reference, level = (a, b) if base not in (a, b) else (base, b if a == base else a)
        name = contrast_name(column, level, reference, base)
        if name not in skip:
            wanted.setdefault(reference, {})[level] = name
    frames = []
    for reference, names in wanted.items():
        fitted = fit(counts, groups, reference, conserve=conserve)
        frames.append(
            fitted.filter(pl.col("level").is_in(list(names)))
            .with_columns(pl.col("level").replace_strict(names).alias("contrast"))
            .select(COLUMNS)
        )
    return pl.concat(frames) if frames else pl.DataFrame(schema=dict.fromkeys(COLUMNS, pl.Float64))


def base_of(contrasts: Iterable[str], column: str, levels: list[str]) -> str | None:
    """The reference a pipeline's contrasts were taken against: the one level of
    ``column`` its plain ``<column><level>`` contrasts never name."""
    named = {c[len(column) :] for c in contrasts if c.startswith(column) and "_vs_" not in c}
    rest = [level for level in levels if level not in named]
    return rest[0] if len(rest) == 1 else None


def from_barplot(barplot: pl.DataFrame, column: str) -> tuple[pd.DataFrame, pd.Series]:
    """Counts (samples x taxa) and groups from a QIIME2 barplot ``level-N.csv``: one
    row per sample (``index``), a column per taxon (a lineage, holding ``;``), then the
    metadata columns."""
    frame = barplot.to_pandas().set_index("index")
    taxa = [c for c in frame.columns if ";" in c]
    return frame[taxa], frame[column]


def collapse(feature_table: pl.DataFrame, lineages: pl.DataFrame) -> pd.DataFrame:
    """ASV counts summed per ``Kingdom;Phylum`` of ``lineages`` (``ID``, ``Kingdom``,
    ``Phylum``), as samples x taxa. An ASV with no Kingdom or no Phylum is left out:
    an "unclassified" row says nothing about who differs."""
    table = feature_table.rename({feature_table.columns[0]: "ID"})
    samples = [c for c in table.columns if c != "ID"]
    known = lineages.filter(
        pl.all_horizontal(pl.col(c).fill_null("") != "" for c in ("Kingdom", "Phylum"))
    ).select("ID", pl.concat_str(["Kingdom", "Phylum"], separator=";").alias("taxon"))
    collapsed = (
        table.with_columns(pl.col(samples).cast(pl.Float64))
        .join(known, on="ID", how="inner")
        .group_by("taxon")
        .agg(pl.col(samples).sum())
        .sort("taxon")
    )
    return collapsed.to_pandas().set_index("taxon").T
