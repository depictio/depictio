"""Sample mapping utilities for MultiQC data processing.

Two ways a MultiQC sample name reaches its canonical id:

* **Pattern only** (``build_sample_mapping(samples)``): the historical
  behaviour. Read-pair suffixes and MultiQC's `` - annotation`` tail are
  dropped with a regex; everything else is its own canonical id.
* **Against the samples hub** (``hub_ids=...``): when the ids of the run's
  samples table are known, each MultiQC name is attached to the hub id it
  belongs to (``canonicalize_to_hub``). This is what joins sarek's per-tool
  names (``NA12878_75M.deepvariant_VEP.ann``, ``NA12878_75M-1_1``) and
  methylseq's Trim Galore names (``<sample>_1_val_1``) back to the hub
  without a hand-written ``mappings`` list. Explicit ``mappings`` still win.
"""

import re
from collections.abc import Iterable
from typing import Dict, List

from depictio.cli.cli_logging import logger
from depictio.recipes.lib.sample_ids import strip_stage_suffixes

#: MultiQC's tool-annotation tail ("S1 - First read: Adapter 1"). The hyphen
#: must have whitespace on both sides so hyphens inside names survive.
_ANNOTATION_RE = re.compile(r"\s+-\s+.+$")

#: Trailing read / lane / trimming tokens written by FastQC, Trim Galore,
#: fastp and Cutadapt. Applied repeatedly (``S1_1_val_1`` -> ``S1_1`` -> ``S1``).
#: Bare ``_<digits>`` endings other than a read number (``Sample_2024``) are
#: deliberately not stripped: they are legitimate ids.
_READ_SUFFIX_RE = re.compile(
    r"(?:_val_[12]|_trimmed|_R[12](?:_\d{3})?|_L\d{3}|_[12]|\.(?:fastq|fq)(?:\.gz)?)$",
    re.IGNORECASE,
)

#: Characters after which a hub id counts as a whole-token prefix of a
#: MultiQC name: ``NA12878_75M`` prefixes ``NA12878_75M.md`` and
#: ``NA12878_75M-1_1`` but not ``NA12878_75MX``.
_TOKEN_BOUNDARY = frozenset("._- ")


def strip_multiqc_suffixes(name: str) -> str:
    """Drop annotation, read / lane / trimming and stage suffixes until stable.

    Never returns an empty string.
    """
    current = _ANNOTATION_RE.sub("", str(name).strip()) or str(name).strip()
    while True:
        nxt = strip_stage_suffixes(current)
        nxt = _READ_SUFFIX_RE.sub("", nxt) or nxt
        if nxt == current:
            return current
        current = nxt


def canonicalize_to_hub(name: str, hub_ids: Iterable[str]) -> str | None:
    """The hub sample id a MultiQC sample name belongs to, or None.

    Tried in order, first hit wins:

    1. the name (without its `` - annotation`` tail) is a hub id;
    2. the name equals a hub id once read / lane / trimming / stage suffixes
       are stripped (``strip_multiqc_suffixes``, which reuses
       ``depictio.recipes.lib.sample_ids.strip_stage_suffixes``);
    3. a hub id is a prefix of the name at a token boundary (``.``, ``_``,
       ``-`` or space). When several hub ids qualify they are necessarily
       nested (``S1`` and ``S1_2`` for ``S1_2.md``) and the longest wins, the
       only reading that does not merge two samples.
    """
    hubs = hub_ids if isinstance(hub_ids, (set, frozenset)) else set(hub_ids)
    if not hubs:
        return None
    raw = str(name).strip()
    base = _ANNOTATION_RE.sub("", raw) or raw
    if base in hubs:
        return base
    stripped = strip_multiqc_suffixes(base)
    if stripped in hubs:
        return stripped
    best: str | None = None
    for hub in hubs:
        if (
            hub
            and len(base) > len(hub)
            and base.startswith(hub)
            and base[len(hub)] in _TOKEN_BOUNDARY
            and (best is None or len(hub) > len(best))
        ):
            best = hub
    return best


def remap_mappings_to_hub(
    mappings: Dict[str, List[str]], hub_ids: Iterable[str]
) -> Dict[str, List[str]]:
    """Re-key an ingest-time ``{canonical: [variants]}`` mapping by hub id.

    Each variant (and each key) is attached to ``canonicalize_to_hub``'s answer;
    what matches no hub id keeps its original key, so nothing is dropped.
    Lets a resolver that knows the hub's ids (the link's source column) fix a
    mapping built at ingest time without re-ingesting the report.
    """
    hubs = set(hub_ids)
    out: Dict[str, List[str]] = {}
    for key, variants in (mappings or {}).items():
        for name in [key, *(variants or [])]:
            target = canonicalize_to_hub(name, hubs) or key
            bucket = out.setdefault(target, [])
            if name not in bucket:
                bucket.append(name)
    return out


def build_sample_mapping(
    samples: List[str],
    hub_ids: Iterable[str] | None = None,
    explicit_mappings: Dict[str, List[str]] | None = None,
) -> Dict[str, List[str]]:
    """
    Build mapping from canonical sample IDs to all their MultiQC variants.

    MultiQC tools generate various sample name patterns:
    - Base: SRR10070130
    - Paired-end: SRR10070130_1, SRR10070130_2
    - Tool annotations: SRR10070130 - First read: Adapter 1
    - Combined: SRR10070130_1 - illumina_small_rna_3'_adapter

    This function extracts canonical IDs and maps them to all variants.

    Args:
        samples: List of all sample names from MultiQC report
        hub_ids: Optional ids of the run's samples table. When given, names
            are attached to their hub id first (``canonicalize_to_hub``); the
            pattern below only handles what no hub id claims.
        explicit_mappings: Optional hand-written ``{hub_id: [names]}`` (a
            link's ``mappings``). A name listed there is attached to that key
            before any canonicalisation, so explicit mappings keep working.

    Returns:
        Dictionary mapping canonical sample ID to list of all its variants
        Example: {"SRR10070130": ["SRR10070130", "SRR10070130_1", "SRR10070130_2",
                                   "SRR10070130 - First read: Adapter 1", ...]}
    """
    # Pattern to extract canonical sample ID:
    # - Capture everything before optional suffixes (_1, _2) or tool annotations
    # - Handles alphanumeric IDs with underscores AND hyphens in the base name
    #
    # The tool-annotation delimiter is MultiQC's " - " — a hyphen with whitespace
    # on both sides ("SRR10070130 - First read: Adapter 1"). Requiring the spaces
    # (``\s+-\s+``, not ``\s*-\s*``) is what lets a hyphen INSIDE a sample name
    # (e.g. "run01-SRR10070130", "sample-01") stay part of the canonical ID
    # instead of collapsing everything after the first bare hyphen.
    canonical_pattern = re.compile(r"^([A-Za-z0-9_-]+?)(?:_[12])?(?:\s+-\s+.+)?$")

    # Build mapping: canonical_id -> [variants]
    mapping: Dict[str, List[str]] = {}

    explicit_owner: Dict[str, str] = {}
    for key, variants in (explicit_mappings or {}).items():
        for variant in variants or []:
            explicit_owner.setdefault(str(variant), str(key))
    hubs = set(hub_ids or [])

    for sample in samples:
        owner = explicit_owner.get(sample) or (canonicalize_to_hub(sample, hubs) if hubs else None)
        if owner is not None:
            mapping.setdefault(owner, []).append(sample)
            continue

        # Extract canonical ID
        match = canonical_pattern.match(sample)
        if match:
            canonical_id = match.group(1)

            # Initialize list if this is the first variant for this canonical ID
            if canonical_id not in mapping:
                mapping[canonical_id] = []

            # Add this variant to the canonical ID's list
            mapping[canonical_id].append(sample)
        else:
            # If pattern doesn't match, treat the sample name as its own canonical ID
            # This handles edge cases with unexpected formats
            logger.debug(f"Sample '{sample}' didn't match canonical pattern, using as-is")
            if sample not in mapping:
                mapping[sample] = []
            mapping[sample].append(sample)

    # Log mapping statistics
    logger.info(
        f"Built sample mapping: {len(mapping)} canonical IDs, {len(samples)} total variants"
    )
    for canonical_id, variants in mapping.items():
        if len(variants) > 1:
            logger.debug(f"  {canonical_id} → {len(variants)} variants: {variants[:3]}...")

    return mapping
