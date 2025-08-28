"""
MultiQC Data Extraction Templates
"""

import polars as pl
import json
from typing import Dict, List, Any

# GENERAL_STATISTICS EXTRACTION

def extract_general_statistics(df: pl.DataFrame) -> pl.DataFrame:
    """Extract general statistics table."""
    return df.filter(pl.col("anchor") == "general_stats_table").select([
        "sample", "metric", "val_raw", "val_raw_type", "val_fmt"
    ])
        

# PLOT_INPUT_ROW EXTRACTION

def extract_table_data(df: pl.DataFrame, anchor: str) -> pl.DataFrame:
    """Extract tabular data for a specific anchor."""
    return df.filter(
        (pl.col("type") == "plot_input_row") & 
        (pl.col("anchor") == anchor)
    ).select([
        "sample", "metric", "val_raw", "val_raw_type", "val_fmt", 
        "dt_anchor", "section_key"
    ])
        

# JSON_EXTRACTION EXTRACTION

def extract_json_data(df: pl.DataFrame, anchor: str) -> List[Dict[str, Any]]:
    """Extract and parse JSON structured data."""
    import json
    
    plot_df = df.filter(
        (pl.col("type") == "plot_input") & 
        (pl.col("anchor") == anchor)
    )
    
    if plot_df.shape[0] == 0:
        return []
    
    plot_data_raw = plot_df.select("plot_input_data").head(1).to_series().to_list()[0]
    if not plot_data_raw:
        return []
    
    try:
        parsed_data = json.loads(plot_data_raw)
        
        # Extract actual data (handle MultiQC structure)
        if isinstance(parsed_data, dict) and 'data' in parsed_data:
            actual_data = parsed_data['data']
        else:
            actual_data = parsed_data
        
        # Process based on structure
        extracted_points = []
        
        if isinstance(actual_data, dict):
            # Sample-keyed data
            for sample, value in actual_data.items():
                if not sample.startswith('_'):
                    if isinstance(value, dict):
                        for metric, metric_value in value.items():
                            extracted_points.append({
                                "sample": sample,
                                "metric": metric,
                                "value": metric_value
                            })
                    else:
                        extracted_points.append({
                            "sample": sample,
                            "value": value
                        })
        
        elif isinstance(actual_data, list):
            # Handle different list structures
            for item in actual_data:
                if isinstance(item, dict):
                    if 'pairs' in item:  # Plotly series
                        sample = item.get('name', 'unknown')
                        for pair in item['pairs']:
                            if len(pair) >= 2:
                                extracted_points.append({
                                    "sample": sample,
                                    "x": pair[0],
                                    "y": pair[1]
                                })
                    else:
                        # Regular dict items
                        for sample, value in item.items():
                            if not sample.startswith('_'):
                                extracted_points.append({
                                    "sample": sample,
                                    "value": value
                                })
        
        return extracted_points
    
    except json.JSONDecodeError:
        return []
        

