"""Sample mapping utilities for MultiQC data processing."""

import re
from typing import Dict, List

from depictio.cli.cli_logging import logger


def build_sample_mapping(samples: List[str]) -> Dict[str, List[str]]:
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

    Returns:
        Dictionary mapping canonical sample ID to list of all its variants
        Example: {"SRR10070130": ["SRR10070130", "SRR10070130_1", "SRR10070130_2",
                                   "SRR10070130 - First read: Adapter 1", ...]}
    """
    # Pattern to extract canonical sample ID:
    # - Capture everything before optional suffixes (_1, _2) or tool annotations (- ...)
    # - Handles alphanumeric IDs with underscores, hyphens in the base name
    canonical_pattern = re.compile(r"^([A-Za-z0-9_-]+?)(?:_[12])?(?:\s*-\s*.+)?$")

    # Build mapping: canonical_id -> [variants]
    mapping: Dict[str, List[str]] = {}

    for sample in samples:
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
