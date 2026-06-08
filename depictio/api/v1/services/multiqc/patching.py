"""Apply sample-selection filtering to Plotly figure dicts.

Extracted from depictio.dash.modules.multiqc_component.callbacks.core so the
celery prerender tasks (and any future API endpoint) can patch figures
without dragging in Dash callback machinery.
"""

import copy
import re

# Strip read-pair / lane / replicate suffixes (HG001_R1 -> HG001) so a base
# sample name selected in an interactive component still matches MultiQC's
# suffixed mapping keys.
_SAMPLE_SUFFIX_RE = re.compile(r"_(?:R\d+|L\d+|REP\d+|TECH\d+)$", re.IGNORECASE)


def expand_canonical_samples_to_variants(
    canonical_samples: list[str], sample_mappings: dict[str, list[str]]
) -> list[str]:
    """Expand canonical sample IDs to all their MultiQC variants using stored mappings.

    Lookup tries exact key first, then falls back to base-name match
    (stripping ``_R1`` / ``_R2`` / ``_REP1`` / ``_L001`` style suffixes from
    the mapping keys). Without the fallback, an interactive MultiSelect on
    a sample column emitting a base name like ``HG001`` matches nothing in
    a mapping keyed by ``HG001_R1`` / ``HG001_R2`` (MultiQC's own keying
    when read-pair suffixes are present), so plot patching shows nothing.

    When no mappings are available, returns canonical samples unchanged.
    """
    if not sample_mappings:
        return canonical_samples

    # Pre-bucket keys by suffix-stripped base. Mappings come pre-aggregated
    # across reports, so the same base can show up in multiple suffixed
    # keys (HG001_R1 + HG001_R2) — union their variants.
    base_to_variants: dict[str, list[str]] = {}
    for key, variants in sample_mappings.items():
        base = _SAMPLE_SUFFIX_RE.sub("", key).lower()
        base_to_variants.setdefault(base, []).extend(variants)

    expanded_samples: list[str] = []
    for canonical_id in canonical_samples:
        variants = sample_mappings.get(canonical_id)
        if variants:
            expanded_samples.extend(variants)
            continue

        fallback = base_to_variants.get(canonical_id.lower())
        if fallback:
            expanded_samples.extend(dict.fromkeys(fallback))
            continue

        expanded_samples.append(canonical_id)

    return expanded_samples


def patch_multiqc_figures(
    figures: list[dict],
    selected_samples: list[str],
    metadata: dict | None = None,
    trace_metadata: dict | None = None,
) -> list[dict]:
    """Apply sample filtering to MultiQC figures based on interactive selections."""
    if not figures or not selected_samples:
        return figures

    patched_figures = []

    for fig in figures:
        patched_fig = copy.deepcopy(fig)

        original_traces = []
        if trace_metadata and "original_data" in trace_metadata:
            original_traces = trace_metadata["original_data"]

        for i, trace in enumerate(patched_fig.get("data", [])):
            trace_type = trace.get("type", "").lower()
            trace_name = trace.get("name", "")

            if i < len(original_traces):
                trace_info = original_traces[i]
                original_x = trace_info.get("original_x", [])
                original_y = trace_info.get("original_y", [])
                original_z = trace_info.get("original_z", [])
                orientation = trace_info.get("orientation", "v")
            else:
                original_x = list(trace.get("x", []))
                original_y = list(trace.get("y", []))
                original_z = list(trace.get("z", []))
                orientation = trace.get("orientation", "v")

            if trace_type in ["bar", "box", "violin"]:
                if orientation == "h":
                    sample_axis = original_y
                    value_axis = original_x
                    sample_key = "y"
                    value_key = "x"
                else:
                    sample_axis = original_x
                    value_axis = original_y
                    sample_key = "x"
                    value_key = "y"

                filtered_samples = []
                filtered_values = []
                for j, sample in enumerate(sample_axis):
                    if sample in selected_samples:
                        filtered_samples.append(sample)
                        if j < len(value_axis):
                            filtered_values.append(value_axis[j])

                trace[sample_key] = filtered_samples
                trace[value_key] = filtered_values

            elif trace_type == "heatmap":
                if original_x and original_z:
                    x_indices = [j for j, x in enumerate(original_x) if str(x) in selected_samples]
                    y_indices = (
                        [j for j, y in enumerate(original_y) if str(y) in selected_samples]
                        if original_y
                        else []
                    )

                    if y_indices and len(y_indices) >= len(x_indices):
                        trace["y"] = [original_y[j] for j in y_indices]
                        if isinstance(original_z, list) and original_z:
                            trace["z"] = [original_z[j] for j in y_indices if j < len(original_z)]
                    elif x_indices:
                        trace["x"] = [original_x[j] for j in x_indices]
                        if isinstance(original_z, list) and original_z:
                            trace["z"] = [
                                [row[j] for j in x_indices if j < len(row)] for row in original_z
                            ]

            elif trace_type in ["scatter", "scattergl"]:
                if trace_name:
                    trace["visible"] = trace_name in selected_samples
                else:
                    filtered_x = []
                    filtered_y = []
                    for j, x_val in enumerate(original_x):
                        if (
                            str(x_val) in selected_samples
                            or str(original_y[j] if j < len(original_y) else "") in selected_samples
                        ):
                            filtered_x.append(x_val)
                            if j < len(original_y):
                                filtered_y.append(original_y[j])
                    if filtered_x:
                        trace["x"] = filtered_x
                        trace["y"] = filtered_y

        patched_figures.append(patched_fig)

    return patched_figures
