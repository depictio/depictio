#!/usr/bin/env python3

import polars as pl
import json
from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, List, Tuple, Optional

class DataType(Enum):
    HISTOGRAM_BAR = "histogram_bar"
    LINE_SCATTER = "line_scatter"
    TABLE_DATA = "table_data"
    UNKNOWN = "unknown"

@dataclass
class PlotData:
    anchor: str
    data_type: DataType
    sample_names: List[str]
    data_points: List[Dict[str, Any]]
    metadata: Dict[str, Any]

def analyze_json_structure(data: Any) -> Tuple[DataType, Dict[str, Any]]:
    """Test the analyze function with librarian data."""
    
    if isinstance(data, dict):
        # Pattern: Heatmap data with rows, xcats, ycats
        if 'rows' in data and 'xcats' in data and 'ycats' in data:
            rows = data['rows']
            xcats = data['xcats'] 
            ycats = data['ycats']
            if isinstance(rows, list) and isinstance(xcats, list) and isinstance(ycats, list):
                return DataType.HISTOGRAM_BAR, {  # Use HISTOGRAM_BAR for heatmap data
                    "heatmap_matrix": True,
                    "rows_count": len(rows),
                    "xcats_count": len(xcats),
                    "ycats_count": len(ycats),
                    "structure": "heatmap_matrix"
                }
    
    return DataType.UNKNOWN, {}

def extract_samples_from_json(actual_data: Any, data_type: DataType) -> Tuple[List[str], List[Dict[str, Any]]]:
    """Test extraction with librarian data."""
    samples = []
    data_points = []
    
    # Handle heatmap data (detected as HISTOGRAM_BAR)
    if data_type == DataType.HISTOGRAM_BAR and isinstance(actual_data, dict):
        # Check for heatmap pattern (rows, xcats, ycats)
        if 'rows' in actual_data and 'xcats' in actual_data and 'ycats' in actual_data:
            # Pattern: Heatmap data with rows matrix
            rows = actual_data['rows']
            xcats = actual_data['xcats'] 
            ycats = actual_data['ycats']
            
            if isinstance(rows, list) and isinstance(xcats, list) and isinstance(ycats, list):
                for row_idx, row_data in enumerate(rows):
                    if row_idx < len(ycats) and isinstance(row_data, list):
                        sample_name = ycats[row_idx]
                        samples.append(sample_name)
                        
                        for col_idx, value in enumerate(row_data):
                            if col_idx < len(xcats) and value is not None:
                                metric_name = xcats[col_idx]
                                data_points.append({
                                    "sample": sample_name,
                                    "metric": metric_name,
                                    "value": value,
                                    "type": "heatmap_cell"
                                })
    
    return samples, data_points

# Test with actual librarian data
parquet_path = "/Users/tweber/Gits/workspaces/MultiQC-MegaQC/MultiQC_TestData/multiqc_output_complete_v1_30_0/multiqc_data/BETA-multiqc.parquet"
df = pl.read_parquet(parquet_path)

anchor = "librarian-library-type-plot"
plot_df = df.filter(pl.col("anchor") == anchor)
plot_df = plot_df.filter(pl.col("type") == "plot_input")

if plot_df.shape[0] > 0:
    plot_data_raw = plot_df.select("plot_input_data").head(1).to_series().to_list()[0]
    
    if plot_data_raw:
        raw_json = json.loads(plot_data_raw)
        
        print("=== TESTING ANALYSIS FUNCTION ===")
        data_type, metadata = analyze_json_structure(raw_json)
        print(f"Detected data type: {data_type.value}")
        print(f"Metadata: {metadata}")
        
        print("\n=== TESTING EXTRACTION FUNCTION ===")
        samples, data_points = extract_samples_from_json(raw_json, data_type)
        print(f"Samples: {len(samples)} - {samples}")
        print(f"Data points: {len(data_points)}")
        if data_points:
            print("First 3 data points:")
            for dp in data_points[:3]:
                print(f"  {dp}")
                
        if len(samples) > 0 and len(data_points) > 0:
            print("\n✅ EXTRACTION SUCCESSFUL!")
        else:
            print("\n❌ EXTRACTION FAILED!")