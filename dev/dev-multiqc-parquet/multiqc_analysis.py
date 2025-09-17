#!/usr/bin/env python3
"""
MultiQC Parquet Data Structure Analysis
=====================================

Autonomous analysis of MultiQC parquet data to understand patterns and structures
for developing a generic ingestion module.
"""

import polars as pl
import json
from pprint import pprint
from collections import defaultdict
from typing import Dict, List, Any

def analyze_multiqc_parquet():
    """Main analysis function to understand MultiQC parquet structure."""
    
    # Load the complete MultiQC parquet file
    parquet_path = "/Users/tweber/Gits/workspaces/MultiQC-MegaQC/MultiQC_TestData/multiqc_output_complete_v1_30_0/multiqc_data/BETA-multiqc.parquet"
    
    print("Loading MultiQC parquet file...")
    df = pl.read_parquet(parquet_path)
    
    print(f"Dataset shape: {df.shape}")
    print(f"Columns: {df.columns}")
    print("\nDataset overview:")
    print(df.head())
    
    # Analyze the structure
    analysis_report = {
        "general_stats": None,
        "plot_input_data": {},
        "non_plot_input_data": {},
        "anchor_summary": {}
    }
    
    # 1. Extract general statistics
    print("\n" + "="*50)
    print("1. GENERAL STATISTICS ANALYSIS")
    print("="*50)
    
    general_stats_df = df.filter(pl.col("anchor") == "general_stats_table")
    print(f"General stats rows: {general_stats_df.shape[0]}")
    if general_stats_df.shape[0] > 0:
        print("General stats structure:")
        print(general_stats_df.head())
        analysis_report["general_stats"] = {
            "row_count": general_stats_df.shape[0],
            "columns": general_stats_df.columns,
            "sample_count": len(general_stats_df.select("sample").unique())
        }
    
    # 2. Analyze plot_input data
    print("\n" + "="*50)
    print("2. PLOT INPUT DATA ANALYSIS")
    print("="*50)
    
    plot_input_df = df.filter(pl.col("type") == "plot_input")
    print(f"Plot input rows: {plot_input_df.shape[0]}")
    
    if plot_input_df.shape[0] > 0:
        print("Plot input structure:")
        print(plot_input_df.select(["sample", "anchor", "metric", "val_raw", "val_raw_type"]).head())
        
        # Group by anchor to understand different plot types
        anchor_groups = plot_input_df.group_by("anchor").agg([
            pl.col("sample").n_unique().alias("sample_count"),
            pl.col("metric").n_unique().alias("metric_count"),
            pl.col("val_raw_type").unique().alias("val_types")
        ])
        
        print("\nPlot input anchors summary:")
        print(anchor_groups)
        
        analysis_report["plot_input_data"] = {
            "total_rows": plot_input_df.shape[0],
            "anchors": anchor_groups.to_dicts()
        }
    
    # 3. Analyze non-plot_input data (the complex nested JSON part)
    print("\n" + "="*50)
    print("3. NON-PLOT INPUT DATA ANALYSIS")
    print("="*50)
    
    non_plot_df = df.filter(pl.col("type") != "plot_input")
    print(f"Non-plot input rows: {non_plot_df.shape[0]}")
    
    if non_plot_df.shape[0] > 0:
        print("Non-plot input structure:")
        print(non_plot_df.head())
        
        # Analyze each anchor type in non-plot data
        unique_anchors = non_plot_df.select("anchor").unique().to_series().to_list()
        print(f"\nUnique anchors in non-plot data: {len(unique_anchors)}")
        
        for anchor in unique_anchors[:10]:  # Analyze first 10 anchors
            print(f"\n--- Analyzing anchor: {anchor} ---")
            anchor_df = non_plot_df.filter(pl.col("anchor") == anchor)
            
            # Get a sample of plot_input_data to understand structure
            if "plot_input_data" in anchor_df.columns:
                sample_data = anchor_df.select("plot_input_data").head(1).to_series().to_list()
                if sample_data and sample_data[0]:
                    try:
                        parsed_data = json.loads(sample_data[0])
                        print(f"  - Structure type: {type(parsed_data)}")
                        
                        if isinstance(parsed_data, dict):
                            print(f"  - Keys: {list(parsed_data.keys())}")
                            # Analyze first few entries
                            for key in list(parsed_data.keys())[:3]:
                                sample_entry = parsed_data[key]
                                print(f"    - {key}: {type(sample_entry)}")
                                if isinstance(sample_entry, dict):
                                    print(f"      - Sub-keys: {list(sample_entry.keys())[:5]}")
                                elif isinstance(sample_entry, list) and sample_entry:
                                    print(f"      - List length: {len(sample_entry)}, first item: {type(sample_entry[0])}")
                        elif isinstance(parsed_data, list):
                            print(f"  - List length: {len(parsed_data)}")
                            if parsed_data:
                                print(f"  - First item type: {type(parsed_data[0])}")
                                if isinstance(parsed_data[0], dict):
                                    print(f"  - First item keys: {list(parsed_data[0].keys())}")
                        
                        analysis_report["non_plot_input_data"][anchor] = {
                            "data_type": type(parsed_data).__name__,
                            "structure_info": _analyze_json_structure(parsed_data)
                        }
                        
                    except json.JSONDecodeError as e:
                        print(f"  - JSON decode error: {e}")
                        analysis_report["non_plot_input_data"][anchor] = {
                            "error": "JSON decode failed"
                        }
    
    # 4. Create comprehensive anchor summary
    print("\n" + "="*50)
    print("4. COMPREHENSIVE ANCHOR SUMMARY")
    print("="*50)
    
    all_anchors = df.select("anchor").unique().to_series().to_list()
    
    for anchor in all_anchors:
        anchor_df = df.filter(pl.col("anchor") == anchor)
        types = anchor_df.select("type").unique().to_series().to_list()
        
        analysis_report["anchor_summary"][anchor] = {
            "total_rows": anchor_df.shape[0],
            "types": types,
            "has_plot_input": "plot_input" in types,
            "has_other_types": len([t for t in types if t != "plot_input"]) > 0
        }
        
        print(f"{anchor:30} | Rows: {anchor_df.shape[0]:4} | Types: {', '.join(types)}")
    
    return analysis_report

def _analyze_json_structure(data: Any, max_depth: int = 3, current_depth: int = 0) -> Dict[str, Any]:
    """Recursively analyze JSON structure to understand data patterns."""
    if current_depth >= max_depth:
        return {"max_depth_reached": True}
    
    if isinstance(data, dict):
        structure = {
            "type": "dict",
            "keys_count": len(data),
            "sample_keys": list(data.keys())[:5],
            "key_types": {}
        }
        
        # Analyze types of values for first few keys
        for key in list(data.keys())[:3]:
            value = data[key]
            if isinstance(value, (dict, list)):
                structure["key_types"][key] = _analyze_json_structure(value, max_depth, current_depth + 1)
            else:
                structure["key_types"][key] = {"type": type(value).__name__}
        
        return structure
    
    elif isinstance(data, list):
        structure = {
            "type": "list",
            "length": len(data),
            "item_types": []
        }
        
        if data:
            # Analyze first few items
            for item in data[:3]:
                if isinstance(item, (dict, list)):
                    structure["item_types"].append(_analyze_json_structure(item, max_depth, current_depth + 1))
                else:
                    structure["item_types"].append({"type": type(item).__name__})
        
        return structure
    
    else:
        return {"type": type(data).__name__, "value_sample": str(data)[:50]}

def save_analysis_report(report: Dict[str, Any], output_path: str):
    """Save the analysis report to a JSON file."""
    with open(output_path, 'w') as f:
        json.dump(report, f, indent=2, default=str)
    print(f"\nAnalysis report saved to: {output_path}")

if __name__ == "__main__":
    print("Starting MultiQC Parquet Analysis...")
    
    try:
        report = analyze_multiqc_parquet()
        
        # Save the report
        output_path = "/Users/tweber/Gits/workspaces/depictio-workspace/depictio/dev/dev-multiqc-parquet/multiqc_analysis_report.json"
        save_analysis_report(report, output_path)
        
        print("\n" + "="*60)
        print("ANALYSIS COMPLETE")
        print("="*60)
        print("Check the generated report for detailed structure analysis.")
        
    except Exception as e:
        print(f"Error during analysis: {e}")
        import traceback
        traceback.print_exc()