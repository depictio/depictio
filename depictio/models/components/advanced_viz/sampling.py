"""How much of a data collection each viz_kind may be reduced to.

``POST /advanced_viz/data`` used to draw one uniform hash sample for every
caller. That is the right answer for a marker cloud — a scatter of 17 M points
and a scatter of 10 000 points drawn from the same distribution look the same —
and the wrong answer for the kinds whose renderer aggregates the rows it is
given. ``StackedTaxonomyRenderer`` sums abundance per (sample, taxon) and ranks
taxa top-N; ``DaBarplotRenderer`` takes a top-N signed LFC. Hand either a
1-in-1700 sample and the bars are not coarse, they are wrong: the sums are off
by the stride and the top-N is drawn from whichever features happened to
survive the hash.

So the reduction strategy is a property of the kind, not of the frame, and it
belongs here beside the role vocabulary in ``schemas.py`` rather than inside
the endpoint.

``roles`` matter for the same reason kinds do: ``tail`` needs to know *which*
column carries the significance it must not throw away, and only the kind knows
that. See ``TAIL_ROLE``.
"""

from __future__ import annotations

from typing import Literal

from depictio.models.components.types import AdvancedVizKind

SamplingPolicy = Literal["hash", "none", "tail"]

#: Which reduction each kind's renderer can survive.
#:
#: ``hash``  — uniform scan-level sample. The renderer draws one mark per row
#:             and reads no aggregate off the frame, so a uniform subset is a
#:             faithful (if lower-resolution) picture.
#: ``none``  — never sample. The renderer aggregates client-side, so any subset
#:             changes the reported values rather than their resolution.
#: ``tail``  — keep the distribution's tail whole, stride the dense middle. For
#:             the DE-style plots the tail *is* the content: a uniform 10 k of
#:             17 M rows keeps ~0.06 % of the significant hits, i.e. none.
KIND_SAMPLING_POLICY: dict[AdvancedVizKind, SamplingPolicy] = {
    # Point clouds — uniform is faithful.
    "embedding": "hash",
    "qq": "hash",
    "lollipop": "hash",
    "coverage_track": "hash",
    # Tail-carrying point clouds.
    "volcano": "tail",
    "ma": "tail",
    "manhattan": "tail",
    # Client-side aggregation — a sample is a wrong answer.
    "stacked_taxonomy": "none",
    "rarefaction": "none",
    "da_barplot": "none",
    "enrichment": "none",
    "sunburst": "none",
    "dot_plot": "none",
    "oncoplot": "none",
    "upset_plot": "none",
    "complex_heatmap": "none",
    "sankey": "none",
    "phylogenetic": "none",
    # File-backed — the renderer never calls /advanced_viz/data.
    "molecule_3d": "none",
}

#: The role whose tail a ``tail`` kind must keep, and whether the interesting
#: end is the small or the large one.
#:
#: ``"low"``   — small values are the tail (a raw p-value column).
#: ``"high"``  — large values are the tail (a −log10 score).
#: ``"both"``  — both ends (a signed log fold change, where the tail is large
#:               ``|x|`` in either direction).
#: ``"auto"``  — decided at read time from the column's observed range, because
#:               the same role is published as both a p-value and a −log10 score
#:               depending on the pipeline. See ``resolve_tail_direction``.
TailDirection = Literal["low", "high", "both", "auto"]

TAIL_ROLE: dict[AdvancedVizKind, tuple[str, TailDirection]] = {
    "volcano": ("significance", "auto"),
    "ma": ("log2_fold_change", "both"),
    "manhattan": ("score", "auto"),
}

# Both tables are declared over ``AdvancedVizKind`` so a new kind that forgets
# an entry is visible to the type checker and to
# ``test_advanced_viz_sampling``. Lookups arrive as plain strings off the
# request payload, hence the widened views — and they are comprehensions rather
# than ``dict(...)`` because ty rejects that overload against a Literal key type.
_POLICY_BY_NAME: dict[str, SamplingPolicy] = {k: v for k, v in KIND_SAMPLING_POLICY.items()}
_TAIL_BY_NAME: dict[str, tuple[str, TailDirection]] = {k: v for k, v in TAIL_ROLE.items()}


def policy_for_kind(viz_kind: str | None) -> SamplingPolicy:
    """Reduction policy for ``viz_kind``, defaulting to the historical one.

    An absent or unrecognised kind gets ``hash`` — the behaviour every caller
    had before this table existed. A renderer that has not been taught to send
    its kind therefore keeps working exactly as it did, and a new kind added to
    ``AdvancedVizKind`` without an entry here degrades to a sample rather than
    to an unbounded load.
    """
    if not viz_kind:
        return "hash"
    return _POLICY_BY_NAME.get(viz_kind, "hash")


def tail_role_for_kind(viz_kind: str | None) -> tuple[str, TailDirection] | None:
    """The ``(role, direction)`` a ``tail`` kind keeps, or None if it has none."""
    if not viz_kind:
        return None
    return _TAIL_BY_NAME.get(viz_kind)


def resolve_tail_direction(
    declared: TailDirection, lo: float | None, hi: float | None
) -> Literal["low", "high", "both"]:
    """Pin an ``auto`` direction using the column's observed range.

    A significance column arrives either as a raw p-value or as its −log10, and
    the two want opposite ends of the distribution. The range separates them
    without a second convention to keep in sync: p-values live in [0, 1] and
    −log10 scores do not stay there for any dataset with a single hit below
    p = 0.1.

    A −log10 column that happens to fit in [0, 1] is read as ``"low"``, which
    is harmless: every value in it is below 1, i.e. p > 0.1, so the frame has
    no significant rows for either end to keep. An unreadable range (all-null,
    or no rows) lands on ``"low"`` for the same reason — there is nothing to
    preserve, and the caller's cap bounds the result either way.
    """
    if declared != "auto":
        return declared
    if lo is None or hi is None:
        return "low"
    return "low" if 0.0 <= lo and hi <= 1.0 else "high"
