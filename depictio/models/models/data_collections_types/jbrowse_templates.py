"""JBrowse2 track configuration templates and validation.

Provides built-in templates for BED, BigWig, and MultiQuantitativeTrack types,
plus Pydantic validation models to ensure populated templates are valid JBrowse2 JSON.
"""

from __future__ import annotations

import copy
import re

from pydantic import BaseModel, ConfigDict, field_validator, model_validator

# ---------------------------------------------------------------------------
# Default track templates (use {placeholder} substitution)
# ---------------------------------------------------------------------------

BED_TRACK_TEMPLATE: dict = {
    "type": "FeatureTrack",
    "trackId": "{trackId}",
    "name": "{name}",
    "assemblyNames": ["{assemblyName}"],
    "category": ["{category}"],
    "adapter": {
        "type": "BedTabixAdapter",
        "bedGzLocation": {
            "locationType": "UriLocation",
            "uri": "{uri}",
        },
        "index": {
            "location": {
                "locationType": "UriLocation",
                "uri": "{indexUri}",
            }
        },
    },
}

BIGWIG_TRACK_TEMPLATE: dict = {
    "type": "QuantitativeTrack",
    "trackId": "{trackId}",
    "name": "{name}",
    "assemblyNames": ["{assemblyName}"],
    "category": ["{category}"],
    "adapter": {
        "type": "BigWigAdapter",
        "bigWigLocation": {
            "locationType": "UriLocation",
            "uri": "{uri}",
        },
    },
    "displays": [
        {
            "type": "LinearWiggleDisplay",
            "displayId": "{trackId}-LinearWiggleDisplay",
            "renderers": {
                "XYPlotRenderer": {
                    "type": "XYPlotRenderer",
                    "color": "{color}",
                }
            },
        }
    ],
}

MULTI_BIGWIG_TRACK_TEMPLATE: dict = {
    "type": "MultiQuantitativeTrack",
    "trackId": "{trackId}",
    "name": "{name}",
    "assemblyNames": ["{assemblyName}"],
    "category": ["{category}"],
    "adapter": {
        "type": "MultiWiggleAdapter",
        "subadapters": [],
    },
    "displays": [
        {
            "type": "MultiLinearWiggleDisplay",
            "displayId": "{trackId}-MultiLinearWiggleDisplay",
            "height": 70,
            "rendererTypeNameState": "xyplot",
        }
    ],
}

MULTI_BIGWIG_SUB_ADAPTER_TEMPLATE: dict = {
    "name": "{subTrackName}",
    "type": "BigWigAdapter",
    "bigWigLocation": {
        "locationType": "UriLocation",
        "uri": "{uri}",
    },
    "color": "{color}",
}

# ---------------------------------------------------------------------------
# Default assemblies
# ---------------------------------------------------------------------------

DEFAULT_ASSEMBLIES: dict[str, dict] = {
    "hg38": {
        "name": "GRCh38",
        "sequence": {
            "type": "ReferenceSequenceTrack",
            "trackId": "GRCh38-ReferenceSequenceTrack",
            "adapter": {
                "type": "BgzipFastaAdapter",
                "fastaLocation": {
                    "uri": "https://s3.amazonaws.com/jbrowse.org/genomes/GRCh38/fasta/GRCh38.fa.gz",
                },
                "faiLocation": {
                    "uri": "https://s3.amazonaws.com/jbrowse.org/genomes/GRCh38/fasta/GRCh38.fa.gz.fai",
                },
                "gziLocation": {
                    "uri": "https://s3.amazonaws.com/jbrowse.org/genomes/GRCh38/fasta/GRCh38.fa.gz.gzi",
                },
            },
        },
        "aliases": ["hg38"],
        "refNameAliases": {
            "adapter": {
                "type": "RefNameAliasAdapter",
                "location": {
                    "uri": "https://s3.amazonaws.com/jbrowse.org/genomes/GRCh38/hg38_aliases.txt",
                },
            },
        },
    },
}

# ---------------------------------------------------------------------------
# Template population
# ---------------------------------------------------------------------------

_PLACEHOLDER_RE = re.compile(r"\{[a-zA-Z_][a-zA-Z0-9_]*\}")


def populate_template_recursive(
    template: dict | list | str | int | float | bool | None, values: dict
) -> dict | list | str | int | float | bool | None:
    """Recursively substitute ``{placeholder}`` strings in *template* with *values*."""
    if isinstance(template, dict):
        return {k: populate_template_recursive(v, values) for k, v in template.items()}
    if isinstance(template, list):
        return [populate_template_recursive(item, values) for item in template]
    if isinstance(template, str):
        result = template
        for key, value in values.items():
            placeholder = f"{{{key}}}"
            if placeholder in result:
                result = result.replace(placeholder, str(value))
        return result
    return template


def _find_unfilled_placeholders(obj: object) -> list[str]:
    """Return all ``{placeholder}`` patterns still present in *obj*."""
    found: list[str] = []
    if isinstance(obj, str):
        found.extend(_PLACEHOLDER_RE.findall(obj))
    elif isinstance(obj, dict):
        for v in obj.values():
            found.extend(_find_unfilled_placeholders(v))
    elif isinstance(obj, list):
        for item in obj:
            found.extend(_find_unfilled_placeholders(item))
    return found


# ---------------------------------------------------------------------------
# Validation models
# ---------------------------------------------------------------------------

_VALID_TRACK_TYPES = {"FeatureTrack", "QuantitativeTrack", "MultiQuantitativeTrack"}


class JBrowse2TrackConfig(BaseModel):
    """Validates a populated JBrowse2 track configuration JSON."""

    model_config = ConfigDict(extra="allow")

    type: str
    trackId: str
    name: str
    assemblyNames: list[str]
    adapter: dict
    category: list[str] | None = None
    displays: list[dict] | None = None

    @field_validator("type")
    @classmethod
    def validate_track_type(cls, v: str) -> str:
        if v not in _VALID_TRACK_TYPES:
            raise ValueError(f"track type must be one of {_VALID_TRACK_TYPES}, got '{v}'")
        return v

    @field_validator("adapter")
    @classmethod
    def validate_adapter_has_type(cls, v: dict) -> dict:
        if "type" not in v:
            raise ValueError("adapter must have a 'type' key")
        return v

    @field_validator("trackId")
    @classmethod
    def validate_track_id_not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("trackId must not be empty")
        return v

    @model_validator(mode="after")
    def validate_no_unfilled_placeholders(self) -> JBrowse2TrackConfig:
        data = self.model_dump()
        unfilled = _find_unfilled_placeholders(data)
        if unfilled:
            raise ValueError(f"Template has unfilled placeholders: {unfilled}")
        return self


class JBrowse2SessionConfig(BaseModel):
    """Validates a full JBrowse2 session configuration."""

    model_config = ConfigDict(extra="allow")

    assemblies: list[dict]
    tracks: list[JBrowse2TrackConfig]
    defaultSession: dict | None = None

    @field_validator("assemblies")
    @classmethod
    def validate_assemblies_not_empty(cls, v: list[dict]) -> list[dict]:
        if not v:
            raise ValueError("At least one assembly is required")
        return v


# ---------------------------------------------------------------------------
# Public helpers
# ---------------------------------------------------------------------------


def get_track_template(track_type: str, override: dict | None = None) -> dict:
    """Return the built-in template for *track_type*, or *override* if provided."""
    if override is not None:
        return copy.deepcopy(override)
    templates = {
        "bed": BED_TRACK_TEMPLATE,
        "bigwig": BIGWIG_TRACK_TEMPLATE,
        "multi_bigwig": MULTI_BIGWIG_TRACK_TEMPLATE,
    }
    if track_type not in templates:
        raise ValueError(f"Unknown track type '{track_type}'. Must be one of: {list(templates)}")
    return copy.deepcopy(templates[track_type])


def populate_and_validate_template(template: dict, values: dict) -> JBrowse2TrackConfig:
    """Populate *template* with *values* and validate the result."""
    populated = populate_template_recursive(template, values)
    return JBrowse2TrackConfig.model_validate(populated)


def build_session_config(
    assembly_name: str,
    tracks: list[JBrowse2TrackConfig],
    default_session: dict | None = None,
) -> JBrowse2SessionConfig:
    """Build and validate a full JBrowse2 session config."""
    if assembly_name not in DEFAULT_ASSEMBLIES:
        raise ValueError(
            f"Unknown assembly '{assembly_name}'. Available: {list(DEFAULT_ASSEMBLIES)}"
        )
    assembly = copy.deepcopy(DEFAULT_ASSEMBLIES[assembly_name])
    session_data = {
        "assemblies": [assembly],
        "tracks": [t.model_dump() for t in tracks],
    }
    if default_session is not None:
        session_data["defaultSession"] = default_session
    return JBrowse2SessionConfig.model_validate(session_data)
