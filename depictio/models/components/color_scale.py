"""A sequential colour scale over the distinct values of one column.

``color_by`` hands every value of a column its own categorical colour. That is
the wrong picture for an ordered column (a timepoint, a dose, a passage): five
unrelated hues say nothing about which sample is later. ``color_scale`` colours
the same values along a ramp instead, in the order of ``order_by`` (or the
natural sort of the values themselves), so "darker" reads as "later".

Shared by the genome browser tile (a column of the tracks manifest) and the
genome view tile (a column of its rows). The React twin is ``ColorScaleSpec``
and ``SEQUENTIAL_SCHEMES`` in ``packages/depictio-react-core/src/
categoryColors.ts``; the scheme names must stay in step.
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

#: Ramps the viewer knows. Keep in step with ``SEQUENTIAL_SCHEMES`` (React).
ColorScheme = Literal["viridis", "magma", "blues", "greens", "oranges", "purples"]


class ColorScale(BaseModel):
    """``color_scale: {column, order_by, scheme}``."""

    model_config = ConfigDict(extra="forbid")

    column: str = Field(
        ...,
        min_length=1,
        description="Column whose distinct values are coloured along the ramp, "
        "e.g. the timepoint. Replaces ``color_by`` on the same tile.",
    )
    order_by: str | None = Field(
        default=None,
        description="Column giving the order of the values (a day number, a dose). "
        "Read as numbers when every value is one, else sorted naturally. Unset: "
        "the values themselves are sorted naturally (``T2`` before ``T10``).",
    )
    scheme: ColorScheme = Field(
        default="viridis",
        description="The ramp: viridis, magma (perceptual), or the single-hue "
        "blues, greens, oranges, purples.",
    )
