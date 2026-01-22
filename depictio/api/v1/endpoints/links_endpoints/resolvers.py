"""
Pluggable resolver classes for DC link value resolution.

This module implements the resolver pattern for mapping values from source DCs
to target DCs. Each resolver handles a specific resolution strategy:

- DirectResolver: 1:1 mapping (same value in source and target)
- SampleMappingResolver: Expand canonical IDs to sample name variants
- PatternResolver: Template substitution for file patterns
- RegexResolver: Match using regex patterns
- WildcardResolver: Glob-style matching

Resolvers are stateless and can be used concurrently.
"""

import fnmatch
import re
from abc import ABC, abstractmethod
from typing import Any

from depictio.api.v1.configs.logging_init import logger
from depictio.models.models.links import LinkConfig


class BaseLinkResolver(ABC):
    """Base class for link resolvers.

    Resolvers are responsible for mapping source values to target identifiers.
    Each resolver implements a specific resolution strategy.
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Return the resolver name (matches link_config.resolver value)."""
        pass

    @abstractmethod
    def resolve(
        self,
        source_values: list[Any],
        link_config: LinkConfig,
        target_known_values: list[str] | None = None,
    ) -> tuple[list[str], list[str]]:
        """Resolve source values to target identifiers.

        Args:
            source_values: List of values from the source DC filter
            link_config: Configuration for this link
            target_known_values: Optional list of known values in the target DC
                                (used by regex/wildcard resolvers)

        Returns:
            Tuple of (resolved_values, unmapped_values)
            - resolved_values: List of target identifiers
            - unmapped_values: Source values that could not be mapped
        """
        pass


class DirectResolver(BaseLinkResolver):
    """Direct 1:1 mapping resolver.

    Maps source values directly to target values without transformation.
    Use when source and target DCs use identical identifiers.

    Example:
        Source: ["S1", "S2"]
        Target: ["S1", "S2"]
    """

    @property
    def name(self) -> str:
        return "direct"

    def resolve(
        self,
        source_values: list[Any],
        link_config: LinkConfig,
        target_known_values: list[str] | None = None,
    ) -> tuple[list[str], list[str]]:
        """Pass through source values as target values."""
        resolved = [str(v) for v in source_values]
        logger.debug(f"DirectResolver: Resolved {len(resolved)} values directly")
        return resolved, []


class SampleMappingResolver(BaseLinkResolver):
    """Expand canonical sample IDs to their variants using mapping dict.

    This resolver is specifically designed for MultiQC integration where
    sample names may have variants (e.g., paired-end suffixes, tool annotations).

    Uses the sample_mappings dict from link_config.mappings or fetched from
    the target DC (MultiQC report metadata).

    Example:
        Source: ["S1", "S2"]
        Mappings: {"S1": ["S1_R1", "S1_R2"], "S2": ["S2_R1"]}
        Resolved: ["S1_R1", "S1_R2", "S2_R1"]
    """

    @property
    def name(self) -> str:
        return "sample_mapping"

    def resolve(
        self,
        source_values: list[Any],
        link_config: LinkConfig,
        target_known_values: list[str] | None = None,
    ) -> tuple[list[str], list[str]]:
        """Expand canonical IDs to sample name variants."""
        resolved: list[str] = []
        unmapped: list[str] = []

        mappings = link_config.mappings or {}

        for val in source_values:
            str_val = str(val)

            # Handle case sensitivity
            lookup_val = str_val if link_config.case_sensitive else str_val.lower()

            # Find mapping (case-insensitive lookup if configured)
            found_mapping = None
            if link_config.case_sensitive:
                found_mapping = mappings.get(str_val)
            else:
                # Case-insensitive lookup
                for key, variants in mappings.items():
                    if key.lower() == lookup_val:
                        found_mapping = variants
                        break

            if found_mapping:
                resolved.extend(found_mapping)
                logger.debug(
                    f"SampleMappingResolver: Expanded '{str_val}' to {len(found_mapping)} variants"
                )
            else:
                # No mapping found - include the original value as fallback
                resolved.append(str_val)
                unmapped.append(str_val)
                logger.debug(f"SampleMappingResolver: No mapping for '{str_val}' - using as-is")

        logger.info(
            f"SampleMappingResolver: Resolved {len(source_values)} source values "
            f"to {len(resolved)} target values ({len(unmapped)} unmapped)"
        )
        return resolved, unmapped


class PatternResolver(BaseLinkResolver):
    """Substitute values into pattern template.

    Use for file path patterns where sample IDs need to be substituted
    into a template pattern.

    Example:
        Source: ["S1", "S2"]
        Pattern: "{sample}.bam"
        Resolved: ["S1.bam", "S2.bam"]
    """

    @property
    def name(self) -> str:
        return "pattern"

    def resolve(
        self,
        source_values: list[Any],
        link_config: LinkConfig,
        target_known_values: list[str] | None = None,
    ) -> tuple[list[str], list[str]]:
        """Substitute source values into pattern template."""
        if not link_config.pattern:
            logger.warning("PatternResolver: No pattern configured, falling back to direct")
            return [str(v) for v in source_values], []

        resolved = []
        for val in source_values:
            # Substitute {sample} with the value
            substituted = link_config.pattern.format(sample=str(val))
            resolved.append(substituted)

        logger.info(
            f"PatternResolver: Substituted {len(source_values)} values "
            f"into pattern '{link_config.pattern}'"
        )
        return resolved, []


class RegexResolver(BaseLinkResolver):
    """Match target values using regex patterns derived from source values.

    Builds regex patterns from source values and matches against known
    target values. Useful for flexible matching with variants.

    Example:
        Source: ["S1"]
        Target known values: ["S1_R1", "S1_R2", "S2_R1"]
        Pattern built: "^S1.*$"
        Resolved: ["S1_R1", "S1_R2"]
    """

    @property
    def name(self) -> str:
        return "regex"

    def resolve(
        self,
        source_values: list[Any],
        link_config: LinkConfig,
        target_known_values: list[str] | None = None,
    ) -> tuple[list[str], list[str]]:
        """Match target values using regex patterns."""
        if not target_known_values:
            logger.warning("RegexResolver: No target values provided, returning source as-is")
            return [str(v) for v in source_values], []

        resolved: list[str] = []
        unmapped: list[str] = []
        flags = 0 if link_config.case_sensitive else re.IGNORECASE

        for val in source_values:
            str_val = str(val)
            # Build regex pattern - escape special chars and add prefix match
            pattern = f"^{re.escape(str_val)}.*$"

            try:
                compiled = re.compile(pattern, flags)
                matches = [tv for tv in target_known_values if compiled.match(tv)]

                if matches:
                    resolved.extend(matches)
                    logger.debug(f"RegexResolver: '{str_val}' matched {len(matches)} values")
                else:
                    unmapped.append(str_val)
                    logger.debug(f"RegexResolver: No matches for '{str_val}'")
            except re.error as e:
                logger.warning(f"RegexResolver: Invalid pattern for '{str_val}': {e}")
                unmapped.append(str_val)

        # Remove duplicates while preserving order
        resolved = list(dict.fromkeys(resolved))

        logger.info(
            f"RegexResolver: Resolved {len(source_values)} source values "
            f"to {len(resolved)} unique target values ({len(unmapped)} unmapped)"
        )
        return resolved, unmapped


class WildcardResolver(BaseLinkResolver):
    """Match target values using glob-style wildcard patterns.

    Uses fnmatch for simpler pattern matching than regex.
    Automatically appends '*' to source values to match variants.

    Example:
        Source: ["S1"]
        Target known values: ["S1_R1.bam", "S1_R2.bam", "S2_R1.bam"]
        Resolved: ["S1_R1.bam", "S1_R2.bam"]
    """

    @property
    def name(self) -> str:
        return "wildcard"

    def resolve(
        self,
        source_values: list[Any],
        link_config: LinkConfig,
        target_known_values: list[str] | None = None,
    ) -> tuple[list[str], list[str]]:
        """Match target values using glob-style wildcards."""
        if not target_known_values:
            logger.warning("WildcardResolver: No target values provided, returning source as-is")
            return [str(v) for v in source_values], []

        resolved: list[str] = []
        unmapped: list[str] = []

        for val in source_values:
            str_val = str(val)
            # Build wildcard pattern
            pattern = f"{str_val}*"

            matches = fnmatch.filter(target_known_values, pattern)

            if matches:
                resolved.extend(matches)
                logger.debug(f"WildcardResolver: '{str_val}' matched {len(matches)} values")
            else:
                unmapped.append(str_val)
                logger.debug(f"WildcardResolver: No matches for '{str_val}'")

        # Remove duplicates while preserving order
        resolved = list(dict.fromkeys(resolved))

        logger.info(
            f"WildcardResolver: Resolved {len(source_values)} source values "
            f"to {len(resolved)} unique target values ({len(unmapped)} unmapped)"
        )
        return resolved, unmapped


# Resolver registry - singleton instances
_RESOLVERS: dict[str, BaseLinkResolver] = {
    "direct": DirectResolver(),
    "sample_mapping": SampleMappingResolver(),
    "pattern": PatternResolver(),
    "regex": RegexResolver(),
    "wildcard": WildcardResolver(),
}


def get_resolver(resolver_type: str) -> BaseLinkResolver:
    """Get a resolver by type name.

    Args:
        resolver_type: Name of the resolver (direct, sample_mapping, pattern, regex, wildcard)

    Returns:
        The resolver instance

    Raises:
        ValueError: If resolver type is not registered
    """
    resolver = _RESOLVERS.get(resolver_type)
    if resolver is None:
        valid_types = ", ".join(_RESOLVERS.keys())
        raise ValueError(f"Unknown resolver type: {resolver_type}. Valid types: {valid_types}")
    return resolver


def list_resolvers() -> list[str]:
    """List all available resolver types."""
    return list(_RESOLVERS.keys())
