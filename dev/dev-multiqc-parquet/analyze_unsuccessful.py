#!/usr/bin/env python3

import polars as pl
import json
from multiqc_extractor import MultiQCExtractor, DataType
from collections import Counter

def analyze_unsuccessful_patterns():
    """Deep analysis of the 128 unsuccessful extractions."""
    
    parquet_path = "/Users/tweber/Gits/workspaces/MultiQC-MegaQC/MultiQC_TestData/multiqc_output_complete_v1_30_0/multiqc_data/BETA-multiqc.parquet"
    extractor = MultiQCExtractor(parquet_path)
    
    print("=" * 80)
    print("DEEP ANALYSIS OF UNSUCCESSFUL EXTRACTIONS")
    print("=" * 80)
    
    # Get all extraction results
    plot_data = extractor.extract_plot_input_data()
    
    unsuccessful = []
    successful = []
    
    for data in plot_data:
        if len(data.sample_names) == 0 or data.data_type == DataType.UNKNOWN:
            unsuccessful.append(data)
        else:
            successful.append(data)
    
    print(f"Total unsuccessful: {len(unsuccessful)}")
    print(f"Total successful: {len(successful)}")
    
    # Analyze unsuccessful patterns
    print("\n" + "=" * 60)
    print("UNSUCCESSFUL PATTERN ANALYSIS")
    print("=" * 60)
    
    pattern_counts = Counter()
    
    for i, data in enumerate(unsuccessful):
        if i >= 10:  # Analyze first 10 in detail
            break
            
        print(f"\n--- ANCHOR {i+1}: {data.anchor} ---")
        print(f"Data type detected: {data.data_type.value}")
        print(f"Metadata: {data.metadata}")
        
        # Get raw JSON to analyze structure
        plot_df = extractor.df.filter(pl.col("anchor") == data.anchor)
        plot_df = plot_df.filter(pl.col("type") == "plot_input")
        
        if plot_df.shape[0] > 0:
            plot_data_raw = plot_df.select("plot_input_data").head(1).to_series().to_list()[0]
            if plot_data_raw:
                try:
                    raw_json = json.loads(plot_data_raw)
                    print(f"JSON structure:")
                    print(f"  Top level keys: {list(raw_json.keys())}")
                    
                    # Categorize the structure
                    if isinstance(raw_json, dict):
                        if 'dt' in raw_json and 'show_table_by_default' in raw_json:
                            pattern_counts["DataTable_config"] += 1
                            print(f"  Pattern: DataTable configuration")
                            if 'dt' in raw_json:
                                dt = raw_json['dt']
                                if isinstance(dt, dict) and 'data' in dt:
                                    print(f"  Has dt.data: {len(dt['data'])} rows")
                                    if len(dt['data']) > 0:
                                        print(f"  First row keys: {list(dt['data'][0].keys())}")
                        
                        elif 'data' in raw_json:
                            inner_data = raw_json['data']
                            print(f"  Has 'data' key, type: {type(inner_data)}")
                            if isinstance(inner_data, list) and len(inner_data) > 0:
                                print(f"  Data list length: {len(inner_data)}")
                                print(f"  First item type: {type(inner_data[0])}")
                                if isinstance(inner_data[0], dict):
                                    print(f"  First item keys: {list(inner_data[0].keys())}")
                            pattern_counts["data_key_structure"] += 1
                        
                        elif 'datasets' in raw_json:
                            datasets = raw_json['datasets']
                            print(f"  Has 'datasets' key, type: {type(datasets)}")
                            if isinstance(datasets, dict):
                                print(f"  Dataset keys: {list(datasets.keys())[:3]}...")
                            pattern_counts["datasets_structure"] += 1
                        
                        else:
                            # Check for sample-like keys
                            sample_keys = [k for k in raw_json.keys() 
                                         if not k.startswith('_') 
                                         and k not in ['anchor', 'creation_date', 'plot_type', 'pconfig']]
                            print(f"  Sample-like keys: {sample_keys[:5]}...")
                            if len(sample_keys) > 0:
                                first_value = raw_json[sample_keys[0]]
                                print(f"  First value type: {type(first_value)}")
                                if isinstance(first_value, dict):
                                    print(f"  First value keys: {list(first_value.keys())}")
                            pattern_counts["other_dict_structure"] += 1
                    
                    elif isinstance(raw_json, list):
                        print(f"  List structure, length: {len(raw_json)}")
                        if len(raw_json) > 0:
                            print(f"  First item type: {type(raw_json[0])}")
                            if isinstance(raw_json[0], dict):
                                print(f"  First item keys: {list(raw_json[0].keys())}")
                        pattern_counts["list_structure"] += 1
                    
                    else:
                        print(f"  Non-dict/list structure: {type(raw_json)}")
                        pattern_counts["other_type"] += 1
                        
                except json.JSONDecodeError as e:
                    print(f"  JSON parse error: {e}")
                    pattern_counts["json_error"] += 1
    
    print(f"\n" + "=" * 60)
    print("PATTERN SUMMARY")
    print("=" * 60)
    for pattern, count in pattern_counts.most_common():
        print(f"{pattern}: {count}")
    
    # Look for specific problematic anchors that might have extractable data
    print(f"\n" + "=" * 60)
    print("POTENTIALLY EXTRACTABLE ANCHORS")
    print("=" * 60)
    
    potentially_extractable = []
    for data in unsuccessful:
        if data.data_type == DataType.TABLE_DATA:
            # These might have actual data in dt.data
            potentially_extractable.append(data.anchor)
    
    print(f"Found {len(potentially_extractable)} table_data anchors that might be extractable:")
    for anchor in potentially_extractable[:10]:
        print(f"  - {anchor}")
    
    return unsuccessful, pattern_counts

if __name__ == "__main__":
    analyze_unsuccessful_patterns()