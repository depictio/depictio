"""Classification of unknown barcodes, shared by the demultiplexing recipes.

An unknown barcode that matches an index in use points at a swapped or
mis-assigned index; one with no usable index is a poly-G or N read. bcl2fastq and
BCL Convert report their unknown barcodes in different shapes but classify them
identically, and recipes may not import each other, so the rule lives here.
"""

from __future__ import annotations

SWAP_BOTH = "Both indexes in use"
SWAP_I7 = "Only i7 in use"
SWAP_I5 = "Only i5 in use"
SWAP_NONE = "Neither index in use"
SWAP_NO_INDEX = "Poly-G or N index"


def no_index(seq: str) -> bool:
    """A read with no usable index: all G (two-colour dark cycles) or any N."""
    return bool(seq) and ("N" in seq or set(seq) == {"G"})


def classify(i7: str, i5: str, used_i7: set[str], used_i5: set[str]) -> tuple[bool, bool, str]:
    """(i7 in use, i5 in use, swap class) of one unknown barcode."""
    i7_in = i7 in used_i7
    i5_in = bool(i5) and i5 in used_i5
    if no_index(i7) or no_index(i5):
        return i7_in, i5_in, SWAP_NO_INDEX
    if i7_in and i5_in:
        return i7_in, i5_in, SWAP_BOTH
    if i7_in:
        return i7_in, i5_in, SWAP_I7
    if i5_in:
        return i7_in, i5_in, SWAP_I5
    return i7_in, i5_in, SWAP_NONE
