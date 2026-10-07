"""FDR cutoff read from a recipe's parameters.

The splicing recipes (DEXSeq, edgeR diffSplice) take an optional ``fdr`` parameter
and fall back on 0.05 when it is missing or outside (0, 1). Recipes may not import
each other, so the parsing lives here.
"""

from __future__ import annotations

DEFAULT_FDR = 0.05


def fdr_cutoff(params: dict[str, str] | None) -> float:
    raw = str((params or {}).get("fdr") or "").strip()
    try:
        value = float(raw)
    except ValueError:
        return DEFAULT_FDR
    return value if 0 < value < 1 else DEFAULT_FDR
