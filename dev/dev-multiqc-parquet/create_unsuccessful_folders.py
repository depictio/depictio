#!/usr/bin/env python3
"""
Create individual folders for unsuccessful extractions with their raw JSON data
"""

import polars as pl
import json
from pathlib import Path
from multiqc_extractor import MultiQCExtractor, DataType

def create_unsuccessful_folders(extractor: MultiQCExtractor, base_dir: str):
    """Create folders for unsuccessful extractions showing their raw JSON."""
    
    unsuccessful_dir = Path(base_dir) / "unsuccessful_extractions"
    folders_dir = unsuccessful_dir / "raw_data_folders"
    folders_dir.mkdir(exist_ok=True)
    
    print("Creating folders for unsuccessful extractions...")
    
    # Get all extraction results
    plot_data = extractor.extract_plot_input_data()
    
    unsuccessful_count = 0
    
    for i, data in enumerate(plot_data):
        if i % 50 == 0:
            print(f"  Progress: {i}/{len(plot_data)} anchors processed")
            
        anchor_name = data.anchor
        safe_anchor = anchor_name.replace("/", "_").replace(":", "_").replace(" ", "_")
        
        # Check if this is unsuccessful
        is_unsuccessful = len(data.sample_names) == 0 or data.data_type == DataType.UNKNOWN
        
        if is_unsuccessful:
            unsuccessful_count += 1
            
            # Create folder for this unsuccessful extraction
            anchor_dir = folders_dir / safe_anchor
            anchor_dir.mkdir(exist_ok=True)
            
            # Get raw JSON from parquet
            plot_df = extractor.df.filter(pl.col("anchor") == anchor_name)
            plot_df = plot_df.filter(pl.col("type") == "plot_input")
            
            if plot_df.shape[0] > 0:
                plot_data_raw = plot_df.select("plot_input_data").head(1).to_series().to_list()[0]
                
                if plot_data_raw:
                    try:
                        # Save pretty-formatted raw JSON
                        raw_json = json.loads(plot_data_raw)
                        json_file = anchor_dir / "raw_data.json"
                        with open(json_file, 'w') as f:
                            json.dump(raw_json, f, indent=2, default=str)
                        
                        # Create analysis file explaining why it failed
                        analysis_file = anchor_dir / "analysis.json"
                        analysis = {
                            "anchor": anchor_name,
                            "failure_reason": "Unknown data pattern" if data.data_type == DataType.UNKNOWN else "No samples extracted",
                            "data_type_detected": data.data_type.value,
                            "samples_found": len(data.sample_names),
                            "data_points_found": len(data.data_points),
                            "structure_info": data.metadata.get("structure_info", {}),
                            "json_structure_preview": {
                                "top_level_keys": list(raw_json.keys()) if isinstance(raw_json, dict) else f"Type: {type(raw_json).__name__}",
                                "data_key_present": "data" in raw_json if isinstance(raw_json, dict) else False,
                                "datasets_key_present": "datasets" in raw_json if isinstance(raw_json, dict) else False
                            }
                        }
                        
                        with open(analysis_file, 'w') as f:
                            json.dump(analysis, f, indent=2, default=str)
                            
                    except json.JSONDecodeError as e:
                        # Create error file
                        error_file = anchor_dir / "json_error.txt"
                        with open(error_file, 'w') as f:
                            f.write(f"JSON Parse Error: {str(e)}\n\n")
                            f.write("Raw data (first 1000 chars):\n")
                            f.write(plot_data_raw[:1000])
    
    print(f"\n✅ Created {unsuccessful_count} folders for unsuccessful extractions")
    print(f"   Location: {folders_dir}")
    print(f"   Each folder contains:")
    print(f"     - raw_data.json (original JSON from parquet)")
    print(f"     - analysis.json (failure analysis and structure info)")

def main():
    """Main execution function."""
    
    parquet_path = "/Users/tweber/Gits/workspaces/MultiQC-MegaQC/MultiQC_TestData/multiqc_output_complete_v1_30_0/multiqc_data/BETA-multiqc.parquet"
    output_dir = "/Users/tweber/Gits/workspaces/depictio-workspace/depictio/dev/dev-multiqc-parquet/detailed_extraction_reports"
    
    print("=" * 80)
    print("CREATING UNSUCCESSFUL EXTRACTION FOLDERS")
    print("=" * 80)
    
    # Initialize extractor
    extractor = MultiQCExtractor(parquet_path)
    
    # Create folders
    create_unsuccessful_folders(extractor, output_dir)
    
    print("\n" + "=" * 80)
    print("UNSUCCESSFUL FOLDERS COMPLETE")
    print("=" * 80)

if __name__ == "__main__":
    main()