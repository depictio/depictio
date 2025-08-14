#!/usr/bin/env python3
"""
Create detailed extraction report with raw JSON and processed tables
"""

import polars as pl
import json
import csv
from pathlib import Path
from typing import Dict, List, Any, Tuple
from multiqc_extractor import MultiQCExtractor, DataType

def create_detailed_extraction_reports(extractor: MultiQCExtractor, output_base_dir: str):
    """Create detailed reports for successful and unsuccessful extractions."""
    
    output_path = Path(output_base_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    
    # Create main directories
    successful_dir = output_path / "successful_extractions"
    unsuccessful_dir = output_path / "unsuccessful_extractions"
    
    successful_dir.mkdir(exist_ok=True)
    unsuccessful_dir.mkdir(exist_ok=True)
    
    print("Creating detailed extraction reports...")
    
    # Get all extraction results
    plot_data = extractor.extract_plot_input_data()
    
    successful_extractions = []
    unsuccessful_extractions = []
    
    print(f"Processing {len(plot_data)} plot_input anchors...")
    
    # Process each anchor
    for i, data in enumerate(plot_data):
        if i % 50 == 0:
            print(f"  Progress: {i}/{len(plot_data)} anchors processed")
            
        anchor_name = data.anchor
        safe_anchor = anchor_name.replace("/", "_").replace(":", "_").replace(" ", "_")
        
        # Determine if extraction was successful
        is_successful = len(data.sample_names) > 0 and data.data_type != DataType.UNKNOWN
        
        if is_successful:
            # Create folder for this successful extraction
            anchor_dir = successful_dir / safe_anchor
            anchor_dir.mkdir(exist_ok=True)
            
            # Get raw JSON from parquet
            plot_df = extractor.df.filter(pl.col("anchor") == anchor_name)
            plot_df = plot_df.filter(pl.col("type") == "plot_input")
            
            if plot_df.shape[0] > 0:
                # Extract raw JSON
                plot_data_raw = plot_df.select("plot_input_data").head(1).to_series().to_list()[0]
                
                if plot_data_raw:
                    try:
                        # Save pretty-formatted raw JSON
                        raw_json = json.loads(plot_data_raw)
                        json_file = anchor_dir / "raw_data.json"
                        with open(json_file, 'w') as f:
                            json.dump(raw_json, f, indent=2, default=str)
                        
                        # Create processed table CSV
                        if data.data_points:
                            csv_file = anchor_dir / "processed_table.csv"
                            
                            # Convert data points to CSV format
                            csv_data = []
                            for point in data.data_points:
                                row = {
                                    "sample": point.get("sample", ""),
                                    "metric": point.get("metric", ""),
                                    "value": point.get("value", ""),
                                    "type": point.get("type", "")
                                }
                                
                                # Add additional fields based on data type
                                if "x" in point:
                                    row["x"] = point["x"]
                                if "y" in point:
                                    row["y"] = point["y"]
                                if "index" in point:
                                    row["index"] = point["index"]
                                
                                # Convert all values to strings for consistency
                                for key, value in row.items():
                                    if value is not None:
                                        row[key] = str(value)
                                    else:
                                        row[key] = ""
                                
                                csv_data.append(row)
                            
                            if csv_data:
                                # Write CSV file
                                fieldnames = set()
                                for row in csv_data:
                                    fieldnames.update(row.keys())
                                fieldnames = sorted(list(fieldnames))
                                
                                with open(csv_file, 'w', newline='') as f:
                                    writer = csv.DictWriter(f, fieldnames=fieldnames)
                                    writer.writeheader()
                                    writer.writerows(csv_data)
                        
                        # Create metadata file
                        metadata_file = anchor_dir / "metadata.json"
                        metadata = {
                            "anchor": anchor_name,
                            "data_type": data.data_type.value,
                            "samples_count": len(data.sample_names),
                            "data_points_count": len(data.data_points),
                            "sample_names": data.sample_names[:10],  # First 10 samples
                            "extraction_metadata": data.metadata
                        }
                        
                        with open(metadata_file, 'w') as f:
                            json.dump(metadata, f, indent=2, default=str)
                        
                        # Add to successful list
                        successful_extractions.append({
                            "anchor": anchor_name,
                            "data_type": data.data_type.value,
                            "samples_count": len(data.sample_names),
                            "data_points_count": len(data.data_points),
                            "folder": str(anchor_dir),
                            "structure_info": data.metadata.get("structure_info", {})
                        })
                        
                    except json.JSONDecodeError as e:
                        # JSON parse error - should be in unsuccessful
                        unsuccessful_extractions.append({
                            "anchor": anchor_name,
                            "reason": "JSON parse error",
                            "error": str(e),
                            "data_type": "parse_error"
                        })
        else:
            # Unsuccessful extraction
            reason = "Unknown pattern"
            if data.data_type == DataType.UNKNOWN:
                reason = "Unknown data pattern"
            elif len(data.sample_names) == 0:
                reason = "No samples extracted"
            
            unsuccessful_extractions.append({
                "anchor": anchor_name,
                "reason": reason,
                "data_type": data.data_type.value if data.data_type != DataType.UNKNOWN else "unknown",
                "structure_info": data.metadata.get("structure_info", {}),
                "metadata": data.metadata
            })
    
    print(f"\\n✅ Processed all anchors:")
    print(f"   - Successful: {len(successful_extractions)}")
    print(f"   - Unsuccessful: {len(unsuccessful_extractions)}")
    
    # Create summary files
    successful_summary_file = successful_dir / "successful_extractions_summary.json"
    with open(successful_summary_file, 'w') as f:
        json.dump({
            "total_successful": len(successful_extractions),
            "extractions": successful_extractions
        }, f, indent=2, default=str)
    
    unsuccessful_summary_file = unsuccessful_dir / "unsuccessful_extractions_summary.json"
    with open(unsuccessful_summary_file, 'w') as f:
        json.dump({
            "total_unsuccessful": len(unsuccessful_extractions),
            "extractions": unsuccessful_extractions
        }, f, indent=2, default=str)
    
    # Create human-readable CSV summaries
    successful_csv = successful_dir / "successful_extractions_list.csv"
    with open(successful_csv, 'w', newline='') as f:
        if successful_extractions:
            fieldnames = ["anchor", "data_type", "samples_count", "data_points_count", "folder", "structure_info"]
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for item in successful_extractions:
                # Convert structure_info to string for CSV
                item_copy = item.copy()
                item_copy["structure_info"] = json.dumps(item["structure_info"])
                writer.writerow(item_copy)
    
    unsuccessful_csv = unsuccessful_dir / "unsuccessful_extractions_list.csv"
    with open(unsuccessful_csv, 'w', newline='') as f:
        if unsuccessful_extractions:
            fieldnames = ["anchor", "reason", "data_type", "structure_info"]
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for item in unsuccessful_extractions:
                # Convert structure_info to string for CSV
                item_copy = {
                    "anchor": item["anchor"],
                    "reason": item["reason"],
                    "data_type": item["data_type"],
                    "structure_info": json.dumps(item["structure_info"])
                }
                writer.writerow(item_copy)
    
    print(f"\\n📁 Created detailed reports:")
    print(f"   - Successful extractions: {successful_dir}")
    print(f"     * {len(successful_extractions)} folders with raw JSON + processed tables")
    print(f"     * Summary: {successful_summary_file}")
    print(f"     * List: {successful_csv}")
    print(f"   - Unsuccessful extractions: {unsuccessful_dir}")
    print(f"     * Summary: {unsuccessful_summary_file}")
    print(f"     * List: {unsuccessful_csv}")
    
    return successful_extractions, unsuccessful_extractions

def main():
    """Main execution function."""
    
    parquet_path = "/Users/tweber/Gits/workspaces/MultiQC-MegaQC/MultiQC_TestData/multiqc_output_complete_v1_30_0/multiqc_data/BETA-multiqc.parquet"
    output_dir = "/Users/tweber/Gits/workspaces/depictio-workspace/depictio/dev/dev-multiqc-parquet/detailed_extraction_reports"
    
    print("=" * 80)
    print("CREATING DETAILED MULTIQC EXTRACTION REPORTS")
    print("=" * 80)
    
    # Initialize extractor
    print("Initializing MultiQC extractor...")
    extractor = MultiQCExtractor(parquet_path)
    
    # Create detailed reports
    successful, unsuccessful = create_detailed_extraction_reports(extractor, output_dir)
    
    print("\\n" + "=" * 80)
    print("DETAILED REPORTS COMPLETE")
    print("=" * 80)
    print(f"📊 Summary:")
    print(f"   • Successful extractions: {len(successful)} ({len(successful)/565*100:.1f}%)")
    print(f"   • Unsuccessful extractions: {len(unsuccessful)} ({len(unsuccessful)/565*100:.1f}%)")
    print(f"   • Each successful extraction has:")
    print(f"     - raw_data.json (pretty-formatted original JSON)")
    print(f"     - processed_table.csv (extracted/structured data)")
    print(f"     - metadata.json (extraction info)")

if __name__ == "__main__":
    main()