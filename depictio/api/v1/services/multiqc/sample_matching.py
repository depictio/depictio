"""Single source of truth for matching sample identifiers against MultiQC mappings.

Sample ``mappings`` come from ``build_sample_mapping`` at ingest time
(``depictio/cli/cli/utils/sample_mapping.py``): canonical IDs mapped to the
variant names MultiQC actually uses in plot traces. The matching problem is
the reverse direction — given a value from a *source* data collection (a
metadata table column, an interactive selection), find the variant names it
corresponds to.

Historically this logic existed in three diverging copies
(``SampleMappingResolver``, ``patching.expand_canonical_samples_to_variants``
and the frontend's ``availableValues.tsx``), each with different
normalization; this module is the one implementation the backend copies now
delegate to.

Matching tries, in order (first hit wins):

1. **exact** — the value is a mapping key. A key with an empty variant list
   (synthesized from ``canonical_samples`` when no explicit mapping exists)
   still counts as matched: the sample is known, its only "variant" is itself.
2. **variant** — the value is itself one of the variant names (e.g. the
   metadata table stores read-level ids like ``SRR001_1`` while the mapping
   is keyed by the canonical ``SRR001``). Resolves to the variant itself.
3. **base** — the value equals a mapping key once read-pair / lane /
   replicate suffixes (``_R1`` / ``_L001`` / ``_REP1`` / ``_TECH1``) are
   stripped from the *keys*; variants from every key sharing the base are
   aggregated.
4. **source-suffix** — same stripping applied to the *value* (``HG001_R1``
   selected against a mapping keyed ``HG001``), then retried as exact/base.
5. **passthrough** — nothing matched; the (whitespace-stripped) value is
   returned as-is and reported unmapped.

All lookups strip surrounding whitespace on both sides; case folding is
applied on both sides when ``case_sensitive`` is False. The restricted
suffix pattern is deliberate — bare ``_<digits>`` endings like
``Sample_2024`` / ``Patient_42`` are legitimate IDs and must not collapse
onto a shared base.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

# Read-pair / lane / replicate / technical-replicate suffixes. Kept in sync
# with the frontend copy in ``packages/depictio-react-core/src/availableValues.tsx``.
SAMPLE_SUFFIX_RE = re.compile(r"_(?:R\d+|L\d+|REP\d+|TECH\d+)$", re.IGNORECASE)


def strip_sample_suffix(name: str) -> str:
    """Strip a trailing ``_R1`` / ``_L001`` / ``_REP1`` / ``_TECH1`` style suffix."""
    return SAMPLE_SUFFIX_RE.sub("", name)


@dataclass
class SampleMatch:
    """Outcome of matching one source value against the mappings."""

    source: str
    matched: bool
    via: str  # "exact" | "variant" | "base" | "source-suffix" | "passthrough"
    targets: list[str] = field(default_factory=list)


class SampleLookup:
    """Pre-indexed view of a ``{canonical: [variants]}`` mapping dict.

    Build once per mapping dict, then match any number of values against it.
    Indexes are deterministic: keys are processed in dict order and variant
    lists are merged in encounter order, so two processes holding the same
    mapping produce identical answers.
    """

    def __init__(self, mappings: dict[str, list[str]] | None, case_sensitive: bool = False):
        self.case_sensitive = bool(case_sensitive)
        # normalized key -> (canonical key, merged variants)
        self._exact: dict[str, tuple[str, list[str]]] = {}
        # normalized variant -> variant (identity lookup)
        self._variants: dict[str, str] = {}
        # normalized suffix-stripped base -> (keys sharing it, merged variants)
        self._base: dict[str, tuple[list[str], list[str]]] = {}

        for raw_key, raw_variants in (mappings or {}).items():
            key = str(raw_key).strip()
            if not key:
                continue
            variants = [str(v).strip() for v in (raw_variants or []) if str(v).strip()]

            nk = self._norm(key)
            if nk in self._exact:
                merged = self._exact[nk][1]
                for v in variants:
                    if v not in merged:
                        merged.append(v)
            else:
                self._exact[nk] = (key, list(variants))

            for v in variants:
                self._variants.setdefault(self._norm(v), v)

            base = self._norm(strip_sample_suffix(key))
            keys, bucket = self._base.setdefault(base, ([], []))
            keys.append(key)
            for v in variants:
                if v not in bucket:
                    bucket.append(v)

    def _norm(self, value: str) -> str:
        return value if self.case_sensitive else value.lower()

    def _targets_for_key(self, entry: tuple[str, list[str]]) -> list[str]:
        # The canonical key is itself a target alongside its variants: plot
        # traces use variant names, but General-Stats-style tables keyed by
        # the canonical ID must also keep matching. A key with no recorded
        # variants (canonical-only mapping) resolves to just itself.
        key, variants = entry
        return list(dict.fromkeys([key, *variants]))

    def _targets_for_base(self, entry: tuple[list[str], list[str]]) -> list[str]:
        keys, variants = entry
        return list(dict.fromkeys([*keys, *variants]))

    def match(self, value: Any) -> SampleMatch:
        """Match one source value; see the module docstring for the try order."""
        source = str(value).strip()
        nv = self._norm(source)

        exact = self._exact.get(nv)
        if exact is not None:
            return SampleMatch(source, True, "exact", self._targets_for_key(exact))

        variant = self._variants.get(nv)
        if variant is not None:
            return SampleMatch(source, True, "variant", [variant])

        base_hit = self._base.get(nv)
        if base_hit is not None:
            return SampleMatch(source, True, "base", self._targets_for_base(base_hit))

        stripped = self._norm(strip_sample_suffix(source))
        if stripped != nv:
            exact = self._exact.get(stripped)
            if exact is not None:
                return SampleMatch(source, True, "source-suffix", self._targets_for_key(exact))
            base_hit = self._base.get(stripped)
            if base_hit is not None:
                return SampleMatch(source, True, "source-suffix", self._targets_for_base(base_hit))

        return SampleMatch(source, False, "passthrough", [source])


def match_samples(
    values: list[Any],
    mappings: dict[str, list[str]] | None,
    case_sensitive: bool = False,
) -> list[SampleMatch]:
    """Match every value, returning per-value detail (for debug/inspect UIs)."""
    lookup = SampleLookup(mappings, case_sensitive=case_sensitive)
    return [lookup.match(v) for v in values]


def expand_samples(
    values: list[Any],
    mappings: dict[str, list[str]] | None,
    case_sensitive: bool = False,
) -> tuple[list[str], list[str]]:
    """Expand source values to target identifiers.

    Returns ``(resolved, unmapped)`` — ``resolved`` is order-preserving and
    deduplicated; unmapped values pass through into ``resolved`` so a filter
    on the target still sees them (they may be literal target names the
    mapping simply doesn't know about).
    """
    resolved: list[str] = []
    unmapped: list[str] = []
    seen: set[str] = set()
    for m in match_samples(values, mappings, case_sensitive=case_sensitive):
        if not m.matched:
            unmapped.append(m.source)
        for t in m.targets:
            if t not in seen:
                seen.add(t)
                resolved.append(t)
    return resolved, unmapped
