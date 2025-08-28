#!/usr/bin/env python3

import polars as pl
import json
from multiqc_extractor import MultiQCExtractor, DataType

def debug_librarian():
    # Load extractor
    extractor = MultiQCExtractor("/Users/tweber/Gits/workspaces/MultiQC-MegaQC/MultiQC_TestData/multiqc_output_complete_v1_30_0/multiqc_data/BETA-multiqc.parquet")
    
    anchor = "librarian-library-type-plot"
    print(f"=== Debugging {anchor} ===\n")
    
    # Get raw data
    plot_df = extractor.df.filter(pl.col("anchor") == anchor)
    plot_df = plot_df.filter(pl.col("type") == "plot_input")
    
    if plot_df.shape[0] > 0:
        plot_data_raw = plot_df.select("plot_input_data").head(1).to_series().to_list()[0]
        
        if plot_data_raw:
            raw_json = json.loads(plot_data_raw)
            
            print("Raw JSON structure:")
            print(f"Top level keys: {list(raw_json.keys())}")
            print(f"Has 'rows': {'rows' in raw_json}")
            print(f"Has 'xcats': {'xcats' in raw_json}")
            print(f"Has 'ycats': {'ycats' in raw_json}")
            
            if 'rows' in raw_json:
                print(f"Rows type: {type(raw_json['rows'])}, length: {len(raw_json['rows'])}")
                print(f"First row: {raw_json['rows'][0]}")
            
            if 'xcats' in raw_json:
                print(f"Xcats: {raw_json['xcats']}")
            
            if 'ycats' in raw_json:
                print(f"Ycats: {raw_json['ycats']}")
                
            # Test analysis
            data_type, metadata = extractor._analyze_json_structure(raw_json)
            print(f"\nAnalyzed data type: {data_type.value}")
            print(f"Metadata: {metadata}")
            
            # Test extraction directly
            samples, data_points = extractor._extract_samples_from_json(raw_json, data_type)
            print(f"\nExtraction results:")
            print(f"Samples: {len(samples)} - {samples}")
            print(f"Data points: {len(data_points)}")
            
            if data_points:
                print("First few data points:")
                for dp in data_points[:5]:
                    print(f"  {dp}")
        
        else:
            print("No plot_input_data found")
    else:
        print("No plot_input rows found")

if __name__ == "__main__":
    debug_librarian()