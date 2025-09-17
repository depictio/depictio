#!/usr/bin/env python3

import polars as pl
import json

# Simple test to extract and view the librarian data
parquet_path = "/Users/tweber/Gits/workspaces/MultiQC-MegaQC/MultiQC_TestData/multiqc_output_complete_v1_30_0/multiqc_data/BETA-multiqc.parquet"

# Load the data
df = pl.read_parquet(parquet_path)

# Find librarian data
anchor = "librarian-library-type-plot"
plot_df = df.filter(pl.col("anchor") == anchor)
plot_df = plot_df.filter(pl.col("type") == "plot_input")

if plot_df.shape[0] > 0:
    plot_data_raw = plot_df.select("plot_input_data").head(1).to_series().to_list()[0]
    
    if plot_data_raw:
        raw_json = json.loads(plot_data_raw)
        
        print("=== LIBRARIAN RAW DATA ===")
        print(f"Top level keys: {list(raw_json.keys())}")
        
        # Check for heatmap pattern
        has_rows = 'rows' in raw_json
        has_xcats = 'xcats' in raw_json
        has_ycats = 'ycats' in raw_json
        
        print(f"Has rows: {has_rows}")
        print(f"Has xcats: {has_xcats}")
        print(f"Has ycats: {has_ycats}")
        
        if has_rows and has_xcats and has_ycats:
            print(f"Rows count: {len(raw_json['rows'])}")
            print(f"Xcats count: {len(raw_json['xcats'])}")
            print(f"Ycats count: {len(raw_json['ycats'])}")
            print(f"First row: {raw_json['rows'][0]}")
            print(f"Xcats: {raw_json['xcats']}")
            print(f"Ycats: {raw_json['ycats']}")
            
            print("\n=== EXTRACTION TEST ===")
            samples = []
            data_points = []
            
            rows = raw_json['rows']
            xcats = raw_json['xcats'] 
            ycats = raw_json['ycats']
            
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
            
            print(f"Extracted {len(samples)} samples: {samples}")
            print(f"Extracted {len(data_points)} data points")
            print("First 5 data points:")
            for dp in data_points[:5]:
                print(f"  {dp}")
        else:
            print("Not a heatmap pattern")
    else:
        print("No plot_input_data found")
else:
    print("No plot_input rows found")