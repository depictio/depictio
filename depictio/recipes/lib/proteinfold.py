"""Where a nf-core/proteinfold output sits: engine, mode, target and entity.

proteinfold writes one directory per prediction engine, some engines with a
mode level below it (AlphaFold2 ``standard`` / ``split_msa_prediction``):

    <engine>[/<mode>]/top_ranked_structures/<target>.pdb
    <engine>[/<mode>]/<target>/<target>_plddt.tsv
    <engine>[/<mode>]/<target>/<target>_<engine>_msa.tsv
    <engine>[/<mode>]/<target>/paes/<target>_<k>_pae.tsv

Every per-structure table joins the structure objects on ``entity``, the id the
``indexed_file`` DC gives each PDB. That id is whatever ``STRUCTURE_SAMPLE_REGEX``
captures from the PDB path, sanitised by ``sample_from_path``; the recipes
rebuild the PDB path of an (engine, mode, target) and run it through the very
same function, so the two can never drift. The template's ``sample_regex``
must equal ``STRUCTURE_SAMPLE_REGEX`` (a test checks it).

Shared here because every proteinfold recipe needs it, and recipes may not
import each other.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

import polars as pl

from depictio.models.models.data_collections_types.indexed_file import sample_from_path
from depictio.recipes.lib.protein_structure import plddt_band_expr, residues_from_pdb

#: Output directories of the prediction engines proteinfold runs.
ENGINE_DIRS: frozenset[str] = frozenset(
    {
        "alphafold2",
        "alphafold3",
        "boltz",
        "colabfold",
        "esmfold",
        "helixfold3",
        "rosettafold_all_atom",
        "rosettafold2na",
    }
)

#: Mode directories between an engine and its outputs.
MODE_DIRS: frozenset[str] = frozenset({"standard", "split_msa_prediction"})

#: Directory holding the top-ranked model of every target.
TOP_DIR = "top_ranked_structures"

#: The ``indexed_file`` sample regex of the structures DC. It has no
#: ``sample`` group, so the id is its named groups joined with ``__``:
#: ``<engine>__<target>``, with the mode between them unless it is the default
#: (``alphafold2__split_msa_prediction__T1``), so two engines or two modes of
#: one engine never share an id.
STRUCTURE_SAMPLE_REGEX = (
    r"(?P<engine>[^/]+)/(?:standard/|(?P<mode>split_msa_prediction)/)?"
    r"top_ranked_structures/(?P<target>[^/]+?)\.(?:pdb|cif|mmcif)(?:\.gz)?$"
)

RAW_LINE_COL = "raw_line"
SOURCE_PATH_COL = "source_path"

#: Read kwargs of a glob source scanned one text line per row.
RAW_LINE_READ_KWARGS: dict[str, object] = {
    "separator": "\x1e",
    "has_header": False,
    "new_columns": [RAW_LINE_COL],
    "quote_char": None,
    "infer_schema_length": 0,
    "raise_if_empty": False,
}


@dataclass(frozen=True)
class OutputLocation:
    """The engine, mode and target an output file belongs to."""

    engine_dir: str
    mode: str
    target: str

    @property
    def engine(self) -> str:
        """Reader-facing engine name: the mode is shown unless it is the default."""
        if not self.mode or self.mode == "standard":
            return self.engine_dir
        return f"{self.engine_dir} ({self.mode.replace('_', ' ')})"

    @property
    def entity(self) -> str:
        return structure_entity(self.engine_dir, self.mode, self.target)


def structure_entity(engine_dir: str, mode: str, target: str) -> str:
    """The indexed_file id of the top-ranked structure of (engine, mode, target)."""
    prefix = f"{engine_dir}/{mode}" if mode else engine_dir
    return sample_from_path(f"{prefix}/{TOP_DIR}/{target}.pdb", STRUCTURE_SAMPLE_REGEX)


def _parts(path: str) -> list[str]:
    return [p for p in str(path).replace("\\", "/").split("/") if p]


def _engine_index(parts: list[str]) -> int:
    for i in range(len(parts) - 2, -1, -1):
        if parts[i] in ENGINE_DIRS:
            return i
    raise ValueError(f"No proteinfold engine directory in {'/'.join(parts)!r}")


def locate_structure(path: str) -> OutputLocation:
    """Location of ``<engine>[/<mode>]/top_ranked_structures/<target>.pdb``."""
    parts = _parts(path)
    i = _engine_index(parts)
    mode = parts[i + 1] if parts[i + 1] in MODE_DIRS else ""
    target = re.sub(r"\.(?:pdb|cif|mmcif)(?:\.gz)?$", "", parts[-1], flags=re.IGNORECASE)
    return OutputLocation(parts[i], mode, target)


def locate_target_file(path: str) -> OutputLocation:
    """Location of a file under ``<engine>[/<mode>]/<target>/`` (any depth below)."""
    parts = _parts(path)
    i = _engine_index(parts)
    rest = parts[i + 1 : -1]
    mode = rest[0] if rest and rest[0] in MODE_DIRS else ""
    below = rest[1:] if mode else rest
    if not below:
        raise ValueError(f"No target directory in {path!r}")
    return OutputLocation(parts[i], mode, below[0])


def raw_blocks(raw: pl.DataFrame) -> list[tuple[str, list[str]]]:
    """``(source_path, lines)`` per file of a raw-line glob source."""
    blocks = []
    for (path,), block in raw.group_by(SOURCE_PATH_COL, maintain_order=True):
        lines = [str(line) for line in block[RAW_LINE_COL].to_list() if line is not None]
        blocks.append((str(path), lines))
    return blocks


def top_model_residues(raw_pdb: pl.DataFrame) -> pl.DataFrame:
    """Residue table of every top-ranked structure, with engine and target.

    Columns: entity, engine, target, chain, position, residue, value (pLDDT on
    a 0-100 scale), category (AlphaFold confidence band), series (the engine,
    suffixed with the chain on multi-chain structures, so one curve per chain).
    """
    frames = []
    for path, lines in raw_blocks(raw_pdb):
        loc = locate_structure(path)
        residues = residues_from_pdb("\n".join(lines) + "\n", loc.entity)
        if residues.is_empty():
            continue
        multi_chain = residues["chain"].n_unique() > 1
        frames.append(
            residues.with_columns(
                pl.lit(loc.engine).alias("engine"),
                pl.lit(loc.target).alias("target"),
                (
                    pl.lit(loc.engine) + pl.lit(" chain ") + pl.col("chain")
                    if multi_chain
                    else pl.lit(loc.engine)
                ).alias("series"),
            )
        )
    columns = {
        "entity": pl.Utf8,
        "engine": pl.Utf8,
        "target": pl.Utf8,
        "chain": pl.Utf8,
        "position": pl.Int64,
        "residue": pl.Utf8,
        "value": pl.Float64,
        "category": pl.Utf8,
        "series": pl.Utf8,
    }
    if not frames:
        return pl.DataFrame(schema=columns)
    return (
        pl.concat(frames, how="vertical")
        .with_columns(plddt_band_expr("value", "category"))
        .select(list(columns))
        .cast(columns)
        .sort(["target", "engine", "chain", "position"])
    )


def _rank_order(labels: list[str]) -> dict[str, int]:
    """Model rank ids (``rank_0``, ``1``, ...) to 1-based ranks, 1 = top model.

    Engines number their models from 0 (AlphaFold2, ESMFold) or from 1
    (ColabFold); ordering the ids numerically and counting from 1 puts every
    engine on the same scale, with the top-ranked structure at 1.
    """

    def key(label: str) -> tuple[int, str]:
        digits = re.findall(r"\d+", label)
        return (int(digits[-1]) if digits else 0, label)

    return {label: i + 1 for i, label in enumerate(sorted(set(labels), key=key))}


def plddt_long(raw_plddt: pl.DataFrame) -> pl.DataFrame:
    """Per-residue pLDDT of every model, from the ``<target>_plddt.tsv`` tables.

    The tables hold one row per residue (``Positions``, 0-based over the chains
    in order) and one ``rank_<k>`` column per model. Columns: entity, engine,
    target, model_rank (1 = top), residue_index (1-based over the chains in
    order), plddt.
    """
    rows: list[dict[str, object]] = []
    for path, lines in raw_blocks(raw_plddt):
        cells = [line.rstrip("\r").split("\t") for line in lines if line.strip()]
        if len(cells) < 2:
            continue
        header, body = cells[0], cells[1:]
        loc = locate_target_file(path)
        ranks = _rank_order(header[1:])
        for row in body:
            try:
                index = int(float(row[0])) + 1
            except (ValueError, IndexError):
                continue
            for label, cell in zip(header[1:], row[1:], strict=False):
                try:
                    value = float(cell)
                except ValueError:
                    continue
                rows.append(
                    {
                        "entity": loc.entity,
                        "engine": loc.engine,
                        "target": loc.target,
                        "model_rank": ranks[label],
                        "residue_index": index,
                        "plddt": value,
                    }
                )
    schema = {
        "entity": pl.Utf8,
        "engine": pl.Utf8,
        "target": pl.Utf8,
        "model_rank": pl.Int64,
        "residue_index": pl.Int64,
        "plddt": pl.Float64,
    }
    return pl.DataFrame(rows, schema=schema)


def model_scores_long(raw_scores: pl.DataFrame | None) -> pl.DataFrame:
    """pTM, ipTM and ipSAE per model, from the two-column ``<target>_<metric>.tsv``.

    ``raw_scores`` is the raw scan (``model``, ``score``, ``source_path``);
    empty files (ipTM and ipSAE of a single-chain target) contribute nothing.
    Columns: entity, model_rank, metric (ptm / iptm / ipsae), score.
    """
    schema = {
        "entity": pl.Utf8,
        "model_rank": pl.Int64,
        "metric": pl.Utf8,
        "score": pl.Float64,
    }
    if raw_scores is None or raw_scores.is_empty() or "score" not in raw_scores.columns:
        return pl.DataFrame(schema=schema)
    rows: list[dict[str, object]] = []
    for (path,), block in raw_scores.group_by(SOURCE_PATH_COL, maintain_order=True):
        match = re.search(r"_(ptm|iptm|ipsae)\.tsv$", str(path))
        if not match or "_chainwise_" in str(path):
            continue
        loc = locate_target_file(str(path))
        block = block.filter(pl.col("model").is_not_null() & pl.col("score").is_not_null())
        ranks = _rank_order([str(m) for m in block["model"].to_list()])
        for model, score in zip(block["model"].to_list(), block["score"].to_list(), strict=True):
            try:
                value = float(score)
            except (TypeError, ValueError):
                continue
            rows.append(
                {
                    "entity": loc.entity,
                    "model_rank": ranks[str(model)],
                    "metric": match.group(1),
                    "score": value,
                }
            )
    return pl.DataFrame(rows, schema=schema)


def decimate(
    df: pl.DataFrame, by: list[str], x: str, y: str, max_points: int = 200
) -> pl.DataFrame:
    """At most ``max_points`` rows per ``by`` group: means over equal x windows.

    Groups already under the cap pass unchanged. ``x`` becomes the window's
    middle position (rounded), ``y`` its mean; other columns keep their first
    value in the window.
    """
    if df.is_empty():
        return df
    sizes = df.group_by(by).len()
    if int(sizes["len"].max() or 0) <= max_points:
        return df
    others = [c for c in df.columns if c not in {*by, x, y}]
    ordered = df.sort([*by, x]).with_columns(
        (pl.int_range(pl.len()).over(by) * max_points // pl.len().over(by)).alias("_window")
    )
    return (
        ordered.group_by([*by, "_window"], maintain_order=True)
        .agg(
            pl.col(x).mean().round(0).cast(df.schema[x]).alias(x),
            pl.col(y).mean().cast(df.schema[y]).alias(y),
            *[pl.col(c).first() for c in others],
        )
        .select(df.columns)
    )
