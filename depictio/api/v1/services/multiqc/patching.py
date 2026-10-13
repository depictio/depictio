"""Apply sample-selection filtering to Plotly figure dicts.

Extracted from depictio.dash.modules.multiqc_component.callbacks.core so the
celery prerender tasks (and any future API endpoint) can patch figures
without dragging in Dash callback machinery.
"""

import copy

from depictio.api.v1.services.multiqc.sample_matching import expand_samples


def expand_canonical_samples_to_variants(
    canonical_samples: list[str], sample_mappings: dict[str, list[str]]
) -> list[str]:
    """Expand canonical sample IDs to all their MultiQC variants using stored mappings.

    Delegates to ``sample_matching.expand_samples`` — the shared, direction-
    agnostic lookup (exact key, variant identity, suffix-stripped key base,
    suffix-stripped source value; whitespace-stripped and case-insensitive
    throughout). Without the fallbacks, an interactive MultiSelect emitting a
    base name like ``HG001`` matches nothing in a mapping keyed by
    ``HG001_R1`` / ``HG001_R2``, so plot patching shows nothing.

    When no mappings are available, returns canonical samples unchanged.
    """
    if not sample_mappings:
        return canonical_samples

    resolved, _unmapped = expand_samples(canonical_samples, sample_mappings, case_sensitive=False)
    return resolved


def patch_multiqc_figures(
    figures: list[dict],
    selected_samples: list[str] | None,
    metadata: dict | None = None,
    trace_metadata: dict | None = None,
) -> list[dict]:
    """Apply sample filtering to MultiQC figures based on interactive selections.

    ``selected_samples`` semantics: ``None`` means "no sample filter" (figures
    returned untouched); an empty list means "active filters matched no
    sample" and every sample is filtered out — the two must not be conflated,
    or a filter that narrows to nothing silently renders everything.
    """
    if not figures or selected_samples is None:
        return figures
    selected_set = {str(s) for s in selected_samples}

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
                    if sample in selected_set:
                        filtered_samples.append(sample)
                        if j < len(value_axis):
                            filtered_values.append(value_axis[j])

                trace[sample_key] = filtered_samples
                trace[value_key] = filtered_values

            elif trace_type == "heatmap":
                if original_x and original_z:
                    x_indices = [j for j, x in enumerate(original_x) if str(x) in selected_set]
                    y_indices = (
                        [j for j, y in enumerate(original_y) if str(y) in selected_set]
                        if original_y
                        else []
                    )

                    if y_indices and len(y_indices) >= len(x_indices):
                        trace["y"] = [original_y[j] for j in y_indices]
                        if isinstance(original_z, list) and original_z:
                            trace["z"] = [original_z[j] for j in y_indices if j < len(original_z)]
                    else:
                        # Assign even when nothing matched — a selection that
                        # matches no sample must blank the heatmap, exactly
                        # like the bar/box/violin branches, not silently
                        # render the full matrix.
                        trace["x"] = [original_x[j] for j in x_indices]
                        if isinstance(original_z, list) and original_z:
                            trace["z"] = [
                                [row[j] for j in x_indices if j < len(row)] for row in original_z
                            ]

            elif trace_type in ["scatter", "scattergl"]:
                if trace_name:
                    trace["visible"] = trace_name in selected_set
                else:
                    filtered_x = []
                    filtered_y = []
                    for j, x_val in enumerate(original_x):
                        if (
                            str(x_val) in selected_set
                            or str(original_y[j] if j < len(original_y) else "") in selected_set
                        ):
                            filtered_x.append(x_val)
                            if j < len(original_y):
                                filtered_y.append(original_y[j])
                    if filtered_x:
                        trace["x"] = filtered_x
                        trace["y"] = filtered_y

        patched_figures.append(patched_fig)

    return patched_figures
