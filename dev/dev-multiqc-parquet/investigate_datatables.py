#!/usr/bin/env python3

import polars as pl
import json
from multiqc_extractor import MultiQCExtractor

def investigate_datatable_structure():
    """Investigate the structure of DataTable configurations."""
    
    parquet_path = "/Users/tweber/Gits/workspaces/MultiQC-MegaQC/MultiQC_TestData/multiqc_output_complete_v1_30_0/multiqc_data/BETA-multiqc.parquet"
    extractor = MultiQCExtractor(parquet_path)
    
    # Look at a few specific DataTable anchors
    datatable_anchors = [
        "deeptools_coverage_metrics_table",
        "fastqc_top_overrepresented_sequences_table", 
        "checkm-first-table",
        "samtools-ampliconclip-pct-table"
    ]
    
    for anchor in datatable_anchors:
        print("=" * 80)
        print(f"INVESTIGATING: {anchor}")
        print("=" * 80)
        
        # Get raw JSON
        plot_df = extractor.df.filter(pl.col("anchor") == anchor)
        plot_df = plot_df.filter(pl.col("type") == "plot_input")
        
        if plot_df.shape[0] > 0:
            plot_data_raw = plot_df.select("plot_input_data").head(1).to_series().to_list()[0]
            if plot_data_raw:
                try:
                    raw_json = json.loads(plot_data_raw)
                    
                    print(f"Top level keys: {list(raw_json.keys())}")
                    print(f"show_table_by_default: {raw_json.get('show_table_by_default')}")
                    
                    if 'dt' in raw_json:
                        dt = raw_json['dt']
                        print(f"\ndt keys: {list(dt.keys())}")
                        
                        if 'data' in dt:
                            data_rows = dt['data']
                            print(f"dt.data type: {type(data_rows)}")
                            print(f"dt.data length: {len(data_rows)}")
                            
                            if len(data_rows) > 0:
                                print(f"First row: {data_rows[0]}")
                                if isinstance(data_rows[0], dict):
                                    print(f"First row keys: {list(data_rows[0].keys())}")
                                
                                # Check if we have actual sample data
                                sample_columns = []
                                for row in data_rows[:3]:  # Check first few rows
                                    if isinstance(row, dict):
                                        for key, value in row.items():
                                            if not key.startswith('_') and key not in ['Sample', 'sample']:
                                                if isinstance(value, (int, float, str)) and str(value) != 'nan':
                                                    if key not in sample_columns:
                                                        sample_columns.append(key)
                                
                                print(f"Potential data columns: {sample_columns[:10]}")
                        
                        if 'headers' in dt:
                            headers = dt['headers']
                            print(f"dt.headers: {headers}")
                    
                    print(f"\n--- EXTRACTION ATTEMPT ---")
                    
                    # Try to extract data from dt.data structure
                    if 'dt' in raw_json and 'data' in raw_json['dt']:
                        data_rows = raw_json['dt']['data']
                        
                        samples = []
                        data_points = []
                        
                        for row in data_rows:
                            if isinstance(row, dict):
                                # Find the sample identifier
                                sample_id = None
                                for key in ['Sample', 'sample', 'Sample Name', 'sample_name']:
                                    if key in row:
                                        sample_id = str(row[key])
                                        break
                                
                                # If no explicit sample column, use first non-underscore key
                                if not sample_id:
                                    for key, value in row.items():
                                        if not key.startswith('_'):
                                            sample_id = str(value)
                                            break
                                
                                if sample_id:
                                    samples.append(sample_id)
                                    
                                    # Extract all data columns
                                    for key, value in row.items():
                                        if not key.startswith('_') and key not in ['Sample', 'sample', 'Sample Name', 'sample_name']:
                                            if isinstance(value, (int, float, str)) and str(value) != 'nan':
                                                data_points.append({
                                                    "sample": sample_id,
                                                    "metric": key,
                                                    "value": value,
                                                    "type": "datatable_cell"
                                                })
                        
                        print(f"Extracted {len(set(samples))} unique samples")
                        print(f"Extracted {len(data_points)} data points")
                        
                        if data_points:
                            print("First 5 data points:")
                            for dp in data_points[:5]:
                                print(f"  {dp}")
                        
                        if len(data_points) > 0:
                            print(f"✅ EXTRACTABLE - {len(data_points)} data points found!")
                        else:
                            print(f"❌ NO DATA EXTRACTED")
                    
                    print()
                    
                except json.JSONDecodeError as e:
                    print(f"JSON parse error: {e}")

if __name__ == "__main__":
    investigate_datatable_structure()