"""Multiple sequence alignments as the protein module's MSA table.

Protein pipelines write their alignments in four shapes:

- nf-core/proteinfold ``<target>_<engine>_msa.tsv``: one alignment row per
  line, every residue an integer code, of the HHblits alphabet
  (``ACDEFGHIKLMNPQRSTVWYX-``, AlphaFold's ``HHBLITS_AA_TO_ID`` order) for the
  monomer engines but of AlphaFold's residue-type order
  (``ARNDCQEGHILKMFPSTWYVX-``) for AlphaFold2 multimer. ``best_alphabet``
  tells them apart against the query's known sequence;
- A3M (MMseqs2, ColabFold, HHblits): FASTA where lowercase letters are
  insertions relative to the query, so rows only line up once they are dropped;
- Stockholm (hmmalign, Pfam): ``name sequence`` lines, possibly interleaved in
  blocks, insert columns lowercase with ``.`` padding when written by HMMER;
- aligned FASTA (FAMSA, ClipKIT, MAFFT): every row already the same length.

Each parser returns ``[(seq_id, aligned_sequence), ...]`` in file order, and
``msa_frame`` turns one alignment into the canonical table the ``msa`` kind
and ``molecule_3d`` (``layout: structure_msa``) read: rank 0 is the first row
(the query or reference), identity and coverage are measured against it, and
the rows are capped in rank order.

Shared here because every protein template (proteinfold, proteinfamilies,
proteinannotator) needs the same table, and recipes may not import each other.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence

import polars as pl

#: Residue alphabet of the integer-coded proteinfold MSA, index = code.
HHBLITS_ALPHABET = "ACDEFGHIKLMNPQRSTVWYX-"
#: AlphaFold's residue-type order, used by the AlphaFold2 multimer features.
AF_RESTYPE_ALPHABET = "ARNDCQEGHILKMFPSTWYVX-"

#: Canonical MSA table schema (see the protein module contract).
MSA_SCHEMA: dict[str, type[pl.DataType]] = {
    "msa_id": pl.Utf8,
    "seq_id": pl.Utf8,
    "rank": pl.Int64,
    "aligned_sequence": pl.Utf8,
    "identity": pl.Float64,
    "coverage": pl.Float64,
}

#: Default number of rows kept per alignment.
DEFAULT_CAP = 500

#: Optional column of the MSA table: the chain layout of a multi-chain
#: reference row (``MsaConfig.chains_col``), null on every other row.
CHAINS_COLUMN = "chains"

_GAPS = frozenset("-.")

Record = tuple[str, str]


def _codes(row: Sequence[int | str] | str) -> list[int]:
    cells = row.split() if isinstance(row, str) else list(row)
    return [int(c) for c in cells if c is not None and not (isinstance(c, str) and not c.strip())]


def best_alphabet(
    rows: Iterable[Sequence[int | str] | str],
    reference: str,
    candidates: Sequence[str] = (HHBLITS_ALPHABET, AF_RESTYPE_ALPHABET),
) -> str:
    """The candidate alphabet under which the first row reads as ``reference``.

    ``reference`` is the query's one-letter sequence (from the structure or the
    input FASTA; chain separators ignored). Ties, and an empty reference, keep
    the first candidate.
    """
    first = next((codes for codes in (_codes(r) for r in rows) if codes), [])
    ref = "".join(c for c in reference.upper() if c.isalpha())
    if not first or not ref:
        return candidates[0]

    def matches(alphabet: str) -> int:
        decoded = [alphabet[c] if 0 <= c < len(alphabet) else "?" for c in first]
        ungapped = [c for c in decoded if c not in _GAPS]
        return sum(1 for a, b in zip(ungapped, ref, strict=False) if a == b)

    return max(candidates, key=matches)


def decode_hhblits_rows(
    rows: Iterable[Sequence[int | str] | str], alphabet: str = HHBLITS_ALPHABET
) -> list[str]:
    """Decode integer-coded alignment rows into residue strings.

    A row is either a sequence of codes (ints or digit strings) or one text
    line of whitespace-separated codes. Blank rows are skipped. A code outside
    the alphabet raises ``ValueError`` rather than shifting the alignment.
    """
    decoded: list[str] = []
    for row in rows:
        codes = _codes(row)
        if not codes:
            continue
        for index in codes:
            if not 0 <= index < len(alphabet):
                raise ValueError(f"MSA code {index} is outside the alphabet")
        decoded.append("".join(alphabet[index] for index in codes))
    return decoded


def _fasta_records(text: str) -> list[Record]:
    records: list[Record] = []
    name: str | None = None
    chunks: list[str] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith(">"):
            if name is not None:
                records.append((name, "".join(chunks)))
            header = line[1:].strip()
            name = header.split()[0] if header else f"seq{len(records) + 1}"
            chunks = []
        elif name is not None:
            chunks.append(line.replace(" ", ""))
    if name is not None:
        records.append((name, "".join(chunks)))
    return records


def parse_a3m(text: str) -> list[Record]:
    """Parse an A3M alignment, dropping the lowercase insertion columns.

    What remains of every row is one character per query (match) column, so
    all rows share the query's length. ``.`` is read as a gap.
    """
    records = []
    for name, seq in _fasta_records(text):
        kept = "".join("-" if c == "." else c for c in seq if not c.islower())
        records.append((name, kept))
    return records


def parse_stockholm(text: str, *, drop_inserts: bool | None = None) -> list[Record]:
    """Parse a Stockholm alignment (single or interleaved blocks).

    ``drop_inserts=None`` detects HMMER-style output (lowercase insert
    residues) and then drops lowercase letters and ``.`` padding, like A3M;
    otherwise ``.`` is read as an ordinary gap and every column is kept.
    """
    order: list[str] = []
    chunks: dict[str, list[str]] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or line == "//":
            continue
        parts = line.split()
        if len(parts) < 2:
            continue
        name, seq = parts[0], "".join(parts[1:])
        if name not in chunks:
            order.append(name)
            chunks[name] = []
        chunks[name].append(seq)
    raw_records = [(name, "".join(chunks[name])) for name in order]
    if drop_inserts is None:
        drop_inserts = any(c.islower() for _, seq in raw_records for c in seq)
    records = []
    for name, seq in raw_records:
        if drop_inserts:
            seq = "".join(c for c in seq if not c.islower() and c != ".")
        else:
            seq = seq.replace(".", "-")
        records.append((name, seq))
    return records


def parse_fasta_alignment(text: str) -> list[Record]:
    """Parse an aligned FASTA file; ``.`` is read as a gap."""
    return [(name, seq.replace(".", "-")) for name, seq in _fasta_records(text)]


def _identity_coverage(reference: str, row: str) -> tuple[float | None, float | None]:
    ref_columns = [i for i, c in enumerate(reference) if c not in _GAPS]
    if not ref_columns:
        return None, None
    covered = [i for i in ref_columns if row[i] not in _GAPS]
    coverage = len(covered) / len(ref_columns)
    if not covered:
        return 0.0, coverage
    matches = sum(1 for i in covered if row[i].upper() == reference[i].upper())
    return matches / len(covered), coverage


def _unique_ids(ids: Iterable[str]) -> list[str]:
    seen: dict[str, int] = {}
    unique = []
    for seq_id in ids:
        count = seen.get(seq_id, 0) + 1
        seen[seq_id] = count
        unique.append(seq_id if count == 1 else f"{seq_id}_{count}")
    return unique


def msa_frame(records: Sequence[Record], msa_id: str, cap: int = DEFAULT_CAP) -> pl.DataFrame:
    """One alignment as the canonical MSA table.

    ``records`` is ``[(seq_id, aligned_sequence), ...]`` with the query or
    reference first (it becomes rank 0). Rows are kept in order up to ``cap``;
    repeated ids get a ``_2``, ``_3`` suffix so a row click stays unambiguous.
    Rows of different lengths raise ``ValueError``: an alignment that does not
    line up would draw shifted columns silently.
    """
    kept = list(records[: max(cap, 0)])
    if not kept:
        return pl.DataFrame(schema=MSA_SCHEMA)
    lengths = {len(seq) for _, seq in kept}
    if len(lengths) > 1:
        raise ValueError(
            f"MSA {msa_id!r} rows differ in length ({sorted(lengths)}); drop insertions first"
        )
    reference = kept[0][1]
    identity: list[float | None] = []
    coverage: list[float | None] = []
    for _, seq in kept:
        ident, cov = _identity_coverage(reference, seq)
        identity.append(ident)
        coverage.append(cov)
    return pl.DataFrame(
        {
            "msa_id": [msa_id] * len(kept),
            "seq_id": _unique_ids(name for name, _ in kept),
            "rank": list(range(len(kept))),
            "aligned_sequence": [seq for _, seq in kept],
            "identity": identity,
            "coverage": coverage,
        },
        schema=MSA_SCHEMA,
    )


def chain_layout(spans: Sequence[tuple[str, int, int]]) -> str | None:
    """The chain layout string of a multi-chain reference, or None for one chain.

    ``spans`` lists ``(chain, first, last)`` in concatenation order, each in the
    chain's own residue numbering (the numbering the residue table and the
    structure use): ``A:1-664,B:665-1004`` or ``A:1-120,B:1-98``. The ``msa``
    kind reads it to translate a column of the concatenated reference into
    one chain's residue.
    """
    if len(spans) < 2:
        return None
    return ",".join(f"{chain}:{first}-{last}" for chain, first, last in spans)


def chain_layout_from_residues(
    residues: pl.DataFrame, reference_length: int | None = None
) -> str | None:
    """Chain layout of a structure's residue table (``chain``, ``position``).

    Chains in file order, each spanning its first to last residue number. None
    for a single chain, or when the layout could not line up with the
    reference: a chain with a gap or an insertion in its numbering, or a total
    residue count other than ``reference_length`` (the reference row's
    ungapped length), since a wrong layout would move every pick silently.
    """
    if residues.is_empty() or residues["chain"].n_unique() < 2:
        return None
    spans = (
        residues.group_by("chain", maintain_order=True)
        .agg(
            pl.col("position").min().alias("first"),
            pl.col("position").max().alias("last"),
            pl.len().alias("n"),
        )
        .rows()
    )
    if any(last - first + 1 != n for _, first, last, n in spans):
        return None
    if reference_length is not None and sum(n for *_, n in spans) != reference_length:
        return None
    return chain_layout([(chain, first, last) for chain, first, last, _ in spans])
