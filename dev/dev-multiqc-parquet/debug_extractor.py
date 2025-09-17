#!/usr/bin/env python3

import polars as pl
from multiqc_extractor import DataType, ExtractedData

def debug_extraction():
    """Debug the extraction process with detailed output."""
    
    parquet_path = "/Users/tweber/Gits/workspaces/MultiQC-MegaQC/MultiQC_TestData/multiqc_output_complete_v1_30_0/multiqc_data/BETA-multiqc.parquet"
    
    print("=" * 80)
    print("DEBUG EXTRACTION PROCESS")
    print("=" * 80)
    
    # Load data
    df = pl.read_parquet(parquet_path)
    
    # Get plot_input_row data
    plot_row_df = df.filter(pl.col("type") == "plot_input_row")
    print(f"Total plot_input_row records: {plot_row_df.shape[0]}")
    
    unique_anchors = plot_row_df.select("anchor").unique().to_series().to_list()
    print(f"Total unique anchors: {len(unique_anchors)}")
    
    # Test a few anchors manually
    test_anchors = ['cellranger-vdj-annot-table', 'picard_variantcallingmetrics_table', 'fastqc_top_overrepresented_sequences_table']
    
    for test_anchor in test_anchors:
        print(f"\n=== TESTING: {test_anchor} ===")
        
        anchor_df = plot_row_df.filter(pl.col("anchor") == test_anchor)
        print(f"Rows for this anchor: {anchor_df.shape[0]}")
        
        if anchor_df.shape[0] > 0:
            # Extract samples and data points
            samples = []
            data_points = []
            
            for row in anchor_df.to_dicts():
                sample = row['sample']
                metric = row['metric'] 
                value = row['val_raw']
                
                # Same condition as in extractor
                if sample and metric:
                    if sample not in samples:
                        samples.append(sample)
                    
                    data_points.append({
                        "sample": sample,
                        "metric": metric,
                        "value": value,
                        "type": "datatable_cell"
                    })
            
            print(f"Samples found: {len(samples)}")
            print(f"Data points: {len(data_points)}")
            
            # Determine data type
            if len(samples) > 0 and len(data_points) > 0:
                data_type = DataType.TABLE_DATA
                print(f"Data type: {data_type.value}")
                print(f"✅ SHOULD BE EXTRACTED")
            else:
                data_type = DataType.UNKNOWN
                print(f"Data type: {data_type.value}")
                print(f"❌ WOULD NOT BE EXTRACTED")
                
            # Create the ExtractedData object to see if there are issues
            try:
                extracted = ExtractedData(
                    anchor=test_anchor,
                    data_type=data_type,
                    sample_names=samples,
                    data_points=data_points,
                    metadata={
                        "total_rows": anchor_df.shape[0],
                        "structure_type": "plot_input_row",
                        "datatable": True
                    }
                )
                print(f"ExtractedData object created successfully")
            except Exception as e:
                print(f"ERROR creating ExtractedData: {e}")
        else:
            print(f"No data found for {test_anchor}")

if __name__ == "__main__":
    debug_extraction()