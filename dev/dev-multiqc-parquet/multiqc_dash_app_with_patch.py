#!/usr/bin/env python3
"""Dash app for displaying MultiQC plots with dynamic sample filtering using Dash Patch."""

import collections

import dash
import dash_mantine_components as dmc
import multiqc
import plotly.graph_objects as go
from dash import ALL, MATCH, Patch, dcc, html
from dash.dependencies import Input, Output, State

# Initialize MultiQC and load data
multiqc.reset()

# Load parquet files
fastqc_parquet = "/Users/tweber/Gits/workspaces/MultiQC-MegaQC/MultiQC_TestData/multiqc_output_fastqc_v1_31_0_single/multiqc_data/multiqc.parquet"
fastqc_parquet = "/Users/tweber/Gits/workspaces/MultiQC-MegaQC/MultiQC_TestData/multiqc_output_fastqc_v1_31_0/multiqc_data/multiqc.parquet"
fastp_parquet = "/Users/tweber/Gits/workspaces/MultiQC-MegaQC/MultiQC_TestData/multiqc_output_fastqc_v1_31_0_barcode01/multiqc_data/multiqc.parquet"

multiqc.parse_logs(fastqc_parquet)
# multiqc.parse_logs(fastp_parquet)

# Get available samples
all_samples = multiqc.list_samples()
print(f"Loaded {len(all_samples)} samples: {all_samples}")

# Get all plots
plots_dict = collections.OrderedDict(multiqc.list_plots())
from pprint import pprint

pprint(plots_dict)
# plots_dict = multiqc.list_plots()

# Initialize Dash app
app = dash.Dash(__name__)


def generate_initial_plots():
    """Generate all plots initially with all samples."""
    all_plot_items = []
    plot_configs = []  # Store plot configurations for later use

    # Define plots to exclude
    excluded_plots = ["Adapter Content", "Top overrepresented sequences"]

    for module_name, plot_list in plots_dict.items():
        for plot_item in plot_list:
            try:
                if isinstance(plot_item, str):
                    # Simple plot
                    plot_name = plot_item
                    dataset_id = ""
                    title = plot_item
                else:
                    # Dict plot - use first sub-plot
                    main_name, sub_plots = next(iter(plot_item.items()))
                    plot_name = main_name
                    dataset_id = sub_plots[0] if isinstance(sub_plots, list) and len(sub_plots) > 0 else ""
                    title = f"{main_name} - {dataset_id}" if dataset_id else main_name

                # Skip excluded plots
                if plot_name in excluded_plots:
                    continue

                plot_obj = multiqc.get_plot(module_name, plot_name)
                if hasattr(plot_obj, 'get_figure'):
                    fig = plot_obj.get_figure(dataset_id=dataset_id)
                    plot_id = f'{module_name}-{plot_name.replace(" ", "-")}-{dataset_id.replace(" ", "-")}' if dataset_id else f'{module_name}-{plot_name.replace(" ", "-")}'

                    plot_configs.append({
                        'id': plot_id,
                        'module': module_name,
                        'name': title,
                        'trace_count': len(fig.data) if hasattr(fig, 'data') else 0
                    })

                    all_plot_items.append({
                        'title': title,
                        'figure': fig,
                        'id': plot_id,
                        'metadata': analyze_plot_structure(fig)
                    })
            except Exception as e:
                plot_name = plot_item if isinstance(plot_item, str) else str(plot_item)
                print(f"Error processing plot {plot_name}: {e}")

    # Create DMC grid with 3 plots per row
    grid_children = []
    for i in range(0, len(all_plot_items), 3):
        row_items = all_plot_items[i:i+3]
        cols = []

        for plot_item in row_items:
            print(f"Adding plot: {plot_item['title']} with ID {plot_item['id']} and metadata keys: {list(plot_item['metadata'].keys())}")
            # Extract metadata for display
            metadata = plot_item['metadata']
            if isinstance(metadata, dict) and 'summary' in metadata:
                summary = metadata['summary']
                metadata_display = [
                    dmc.Text(f"Traces: {summary['traces']}", size="xs", c="dimmed"),
                    dmc.Text(f"Types: {summary['types']}", size="xs", c="dimmed"),
                    dmc.Text(f"Samples: {summary['samples_in_traces']}", size="xs", c="dimmed") if summary['samples_in_traces'] > 0 else None
                ]
                metadata_display = [item for item in metadata_display if item is not None]
            else:
                metadata_display = [dmc.Text("No metadata", size="xs", c="dimmed")]


            cols.append(
                dmc.GridCol([
                    dmc.Card([
                        dmc.CardSection([
                            dmc.Text(plot_item['title'], fw=500, size="sm", mb=5, ta="center"),
                            dmc.Group(metadata_display, gap=5, justify="center")
                        ], withBorder=True, inheritPadding=False, py="xs", px="sm"),
                        dmc.CardSection([
                            dcc.Graph(
                                id={'type': 'multiqc-plot', 'index': plot_item['id']},
                                figure=plot_item['figure'],
                                style={'height': '300px'}
                            )
                        ], inheritPadding=False, p=0),
                        # Store metadata about plot structure
                        dmc.Box(
                            id={'type': 'plot-metadata', 'index': plot_item['id']},
                            style={'display': 'none'},
                            children=str(metadata)
                        )
                    ], withBorder=True, shadow="sm", radius="md", p=0)
                ], span=4)
            )

        # Fill remaining columns if less than 3 plots in row
        while len(cols) < 3:
            cols.append(dmc.GridCol(span=4))

        grid_children.append(dmc.Grid(cols, gutter="md"))

    return dmc.Stack(grid_children, gap="md")


def analyze_plot_structure(fig):
    """Analyze how samples are represented in the plot and store original data."""
    if not fig or not hasattr(fig, 'data'):
        return {"original_data": [], "summary": "No data"}

    # Store complete original data for each trace
    original_data = []
    trace_types = []
    sample_mapping = []

    for i, trace in enumerate(fig.data):
        trace_info = {
            'index': i,
            'type': trace.type if hasattr(trace, 'type') else '',
            'name': trace.name if hasattr(trace, 'name') else '',
            'orientation': trace.orientation if hasattr(trace, 'orientation') else 'v',
            'original_x': tuple(trace.x) if hasattr(trace, 'x') and trace.x is not None and isinstance(trace.x, tuple) else (list(trace.x) if hasattr(trace, 'x') and trace.x is not None else []),
            'original_y': tuple(trace.y) if hasattr(trace, 'y') and trace.y is not None and isinstance(trace.y, tuple) else (list(trace.y) if hasattr(trace, 'y') and trace.y is not None else []),
            'original_z': tuple(trace.z) if hasattr(trace, 'z') and trace.z is not None and isinstance(trace.z, tuple) else (list(trace.z) if hasattr(trace, 'z') and trace.z is not None else []),
        }
        original_data.append(trace_info)

        # Collect metadata for display
        trace_types.append(trace.type if hasattr(trace, 'type') else 'unknown')
        if hasattr(trace, 'name') and trace.name:
            sample_mapping.append(trace.name)

    # Create summary for display
    unique_types = list(set(trace_types))
    summary = {
        'traces': len(original_data),
        'types': ', '.join(unique_types),
        'samples_in_traces': len(sample_mapping),
        'sample_names': ', '.join(sample_mapping[:3]) + ('...' if len(sample_mapping) > 3 else '')
    }

    return {
        'original_data': original_data,
        'summary': summary
    }


# Build layout
app.layout = dmc.MantineProvider([
    dmc.Container([
        dmc.Title("MultiQC FastQC Dashboard with Dynamic Filtering", order=1),

        # Sample filter dropdown
        dmc.Group([
            dmc.Text("Select Samples:", fw=500),
            dcc.Dropdown(
                id='sample-filter',
                options=[{'label': s, 'value': s} for s in all_samples],
                value=all_samples,
                multi=True,
                placeholder="Select samples to display",
                style={'minWidth': 300}
            )
        ], style={'margin': '20px'}),

        # Info about filtering
        dmc.Box(id='filter-info', style={'margin': '20px'}),

        # Container for plots
        dmc.Box(id='plots-container', children=generate_initial_plots())
    ], fluid=True, style={'maxWidth': 'none', 'width': '100%', 'padding': '20px'})
], theme={'primaryColor': 'blue'}, forceColorScheme='light')


# Callback to update plots using Patch
@app.callback(
    Output({'type': 'multiqc-plot', 'index': ALL}, 'figure'),
    # Output('filter-info', 'children'),
    Input('sample-filter', 'value'),
    State({'type': 'multiqc-plot', 'index': ALL}, 'figure'),
    State({'type': 'plot-metadata', 'index': ALL}, 'children'),
    prevent_initial_call=True
)
def update_plots_with_patch(selected_samples, current_figures, plot_metadata):
    """Update plots dynamically using Dash Patch."""
    print(f"\n=== PATCH CALLBACK TRIGGERED ===")
    print(f"Selected samples: {selected_samples}")
    print(f"Selected samples type: {type(selected_samples)}")
    print(f"Number of figures: {len(current_figures)}")

    if not selected_samples:
        print("No samples selected, returning no_update")
        return [dash.no_update] * len(current_figures), "Please select at least one sample"

    patched_figures = []

    for fig_idx, (fig, metadata) in enumerate(zip(current_figures, plot_metadata)):
        print(f"\nProcessing figure {fig_idx} with title '{fig['layout']['title']['text'] if 'layout' in fig and 'title' in fig['layout'] else 'N/A'}'")
        print(f"  Figure exists: {fig is not None}")

        if not fig:
            print(f"  No figure data, skipping")
            patched_figures.append(dash.no_update)
            continue

        # Create a Patch object for this figure
        patched_fig = Patch()
        figure_replaced = False  # Track if we replaced the figure with full version

        # Parse metadata to get original trace data
        try:
            if metadata:
                # Define safe environment for eval with nan and None
                safe_dict = {'nan': float('nan'), 'None': None}
                metadata_dict = eval(metadata, {"__builtins__": {}}, safe_dict)
            else:
                metadata_dict = {}
            original_traces = metadata_dict.get('original_data', []) if isinstance(metadata_dict, dict) else []
            print(f"  Found {len(original_traces)} original traces in metadata")
        except Exception as e:
            print(f"  Error parsing metadata: {e}")
            original_traces = []

        # Update trace visibility and data based on selected samples using original data
        for i, trace_info in enumerate(original_traces):
            if i >= len(fig['data']):
                continue

            trace_name = trace_info.get('name', '')
            trace_type = trace_info.get('type', '')
            orientation = trace_info.get('orientation', 'v')
            original_x = trace_info.get('original_x', [])
            original_y = trace_info.get('original_y', [])
            original_z = trace_info.get('original_z', [])

            print(f"    Trace {i}: name='{trace_name}', type='{trace_type}', orientation='{orientation}'")
            print(f"      Original data lengths: x={len(original_x)}, y={len(original_y)}")

            # Method 1: Direct trace name matching (works for line plots like GC Content)
            if trace_name in all_samples:
                is_visible = trace_name in selected_samples
                print(f"      Direct name match: setting visible={is_visible}")
                patched_fig['data'][i]['visible'] = is_visible

            # Method 2: Handle bar plots
            elif trace_type == 'bar':
                print(f"      Processing bar plot with orientation '{orientation}'")
                if orientation == 'h':
                    # Horizontal bars: samples are in Y-axis
                    if original_y and original_x:
                        # Filter from original data based on selected samples AND valid X values (no NaN)
                        print(f"        Before filtering: {len(original_y)} samples")
                        print(f"        Available samples in Y: {[y for y in original_y if y in all_samples][:5]}")

                        filtered_indices = [
                            idx for idx, sample in enumerate(original_y)
                            if sample in selected_samples and
                            idx < len(original_x) and
                            str(original_x[idx]).lower() != 'nan' and
                            original_x[idx] is not None
                        ]
                        print(f"        Filtered indices: {filtered_indices}")

                        if filtered_indices:
                            new_y = [original_y[idx] for idx in filtered_indices]
                            new_x = [original_x[idx] for idx in filtered_indices]
                            print(f"        New data: Y={new_y}, X={new_x}")
                            # Convert to tuple if original was tuple (to match Plotly expectation)
                            patched_fig['data'][i]['y'] = tuple(new_y) if isinstance(original_y, tuple) else new_y
                            patched_fig['data'][i]['x'] = tuple(new_x) if isinstance(original_x, tuple) else new_x
                            patched_fig['data'][i]['visible'] = True
                            print(f"        Applied patch successfully")
                        else:
                            print(f"        No valid data after filtering - hiding trace")
                            patched_fig['data'][i]['visible'] = False
                else:
                    # Vertical bars: samples are in X-axis
                    if original_x and original_y:
                        # Filter from original data based on selected samples AND valid Y values (no NaN)
                        filtered_indices = [
                            idx for idx, sample in enumerate(original_x)
                            if sample in selected_samples and
                            idx < len(original_y) and
                            str(original_y[idx]).lower() != 'nan' and
                            original_y[idx] is not None
                        ]
                        if filtered_indices:
                            new_x = [original_x[idx] for idx in filtered_indices]
                            new_y = [original_y[idx] for idx in filtered_indices]
                            # Convert to tuple if original was tuple (to match Plotly expectation)
                            patched_fig['data'][i]['x'] = tuple(new_x) if isinstance(original_x, tuple) else new_x
                            patched_fig['data'][i]['y'] = tuple(new_y) if isinstance(original_y, tuple) else new_y
                            patched_fig['data'][i]['visible'] = True
                        else:
                            patched_fig['data'][i]['visible'] = False

            # Method 3: Handle heatmaps - Return full figure (Patch doesn't handle Y-axis properly)
            elif trace_type == 'heatmap':
                print("      Processing heatmap - using full figure replacement")
                if original_y:
                    print(f"        Before filtering: {len(original_y)} Y values")
                    print(f"        Available samples in Y: {[y for y in original_y if y in all_samples][:5]}")

                    # Filter Y-axis (samples) and corresponding Z data from original data
                    print(f"        Original Y samples: {original_y}")
                    print(f"        Selected samples for filtering: {selected_samples}")
                    filtered_indices = [idx for idx, sample in enumerate(original_y) if sample in selected_samples]
                    print(f"        Filtered indices: {filtered_indices}")
                    print(f"        Samples that will remain: {[original_y[idx] for idx in filtered_indices]}")

                    if filtered_indices:
                        new_y = [original_y[idx] for idx in filtered_indices]
                        print(f"        New Y data: {new_y}")

                        # For heatmaps, replace with full figure instead of Patch
                        import copy
                        full_fig = copy.deepcopy(fig)

                        # Update the heatmap data properly
                        full_fig['data'][i]['y'] = tuple(new_y) if isinstance(original_y, tuple) else new_y

                        if original_z:
                            new_z = [original_z[idx] for idx in filtered_indices]
                            print(f"        New Z data rows: {len(new_z)}")
                            full_fig['data'][i]['z'] = tuple(new_z) if isinstance(original_z, tuple) else new_z

                        # Ensure proper heatmap axis configuration
                        # Force Plotly to use the y data as axis labels by clearing any conflicting layout
                        if 'layout' in full_fig and 'yaxis' in full_fig['layout']:
                            # Clear any pre-set tickvals/ticktext that might override the y data
                            if 'tickvals' in full_fig['layout']['yaxis']:
                                del full_fig['layout']['yaxis']['tickvals']
                            if 'ticktext' in full_fig['layout']['yaxis']:
                                del full_fig['layout']['yaxis']['ticktext']
                            # Ensure y-axis shows all ticks
                            full_fig['layout']['yaxis']['type'] = 'category'

                        print(f"        Final Y data being set: {full_fig['data'][i]['y']}")
                        print(f"        Y data type: {type(full_fig['data'][i]['y'])}")

                        # Mark that we replaced the figure
                        patched_figures.append(full_fig)
                        figure_replaced = True
                        print("        Replaced with full figure for heatmap")
                        break  # Skip normal patch processing for this figure
                    else:
                        print("        No valid data after filtering - hiding heatmap")
                        patched_fig['data'][i]['visible'] = False

            # Method 4: Handle other plot types where we might need to hide traces
            else:
                # For scatter plots and others, check if trace represents a single sample
                if any(sample in trace_name for sample in all_samples):
                    # Check if any selected sample is in the trace name
                    patched_fig['data'][i]['visible'] = any(sample in trace_name for sample in selected_samples)
                # If no clear sample association, keep trace visible
                else:
                    patched_fig['data'][i]['visible'] = True

        # Only append the patched figure if we didn't replace it with a full figure
        if not figure_replaced:
            patched_figures.append(patched_fig)

    print("\n=== PATCH CALLBACK COMPLETE ===")
    print(f"Returning {len(patched_figures)} patched figures")

    return patched_figures


if __name__ == '__main__':
    print("\nStarting Dash app on http://localhost:8052")
    print("Use the dropdown to filter samples dynamically!")
    app.run(debug=True, host='0.0.0.0', port=8052)