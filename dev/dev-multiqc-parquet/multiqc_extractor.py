#!/usr/bin/env python3
"""
MultiQC Data Extractor - Generic module for parsing MultiQC parquet data
========================================================================

Extracts data from MultiQC parquet files with different organizational patterns:
1. General statistics (anchor = 'general_stats_table')
2. Plot input data (type = 'plot_input') 
3. Complex nested JSON structures (type != 'plot_input')
"""

import polars as pl
import json
from typing import Dict, List, Any, Optional, Tuple
from dataclasses import dataclass
from enum import Enum

class DataType(Enum):
    GENERAL_STATS = "general_stats"
    PLOT_INPUT = "plot_input" 
    HISTOGRAM_BAR = "histogram_bar"
    LINE_SCATTER = "line_scatter"
    TABLE_DATA = "table_data"
    UNKNOWN = "unknown"

@dataclass
class ExtractedData:
    """Container for extracted data with metadata."""
    anchor: str
    data_type: DataType
    sample_names: List[str]
    data_points: List[Dict[str, Any]]
    metadata: Dict[str, Any]

class MultiQCExtractor:
    """Generic extractor for MultiQC parquet data."""
    
    def __init__(self, parquet_path: str):
        self.parquet_path = parquet_path
        self.df = pl.read_parquet(parquet_path)
        self.extraction_report = {}
    
    def extract_general_statistics(self) -> ExtractedData:
        """Extract general statistics table."""
        general_df = self.df.filter(pl.col("anchor") == "general_stats_table")
        
        if general_df.shape[0] == 0:
            return ExtractedData(
                anchor="general_stats_table",
                data_type=DataType.GENERAL_STATS,
                sample_names=[],
                data_points=[],
                metadata={"error": "No general statistics found"}
            )
        
        # Extract structured data from general stats
        data_points = []
        sample_names = set()
        
        for row in general_df.iter_rows(named=True):
            if row.get("sample"):
                sample_names.add(row["sample"])
                data_points.append({
                    "sample": row["sample"],
                    "metric": row.get("metric"),
                    "value": row.get("val_raw"),
                    "value_type": row.get("val_raw_type"),
                    "formatted_value": row.get("val_fmt")
                })
        
        return ExtractedData(
            anchor="general_stats_table",
            data_type=DataType.GENERAL_STATS,
            sample_names=list(sample_names),
            data_points=data_points,
            metadata={"total_rows": general_df.shape[0]}
        )
    
    def extract_plot_input_data(self) -> List[ExtractedData]:
        """Extract all plot_input type data from plot_input_data JSON."""
        plot_df = self.df.filter(pl.col("type") == "plot_input")
        
        if plot_df.shape[0] == 0:
            return []
        
        extracted_data = []
        unique_anchors = plot_df.select("anchor").unique().to_series().to_list()
        
        for anchor in unique_anchors:
            anchor_df = plot_df.filter(pl.col("anchor") == anchor)
            
            # Get the plot_input_data JSON
            plot_data_raw = anchor_df.select("plot_input_data").head(1).to_series().to_list()[0]
            
            if plot_data_raw:
                try:
                    parsed_data = json.loads(plot_data_raw)
                    data_type, structure_info = self._analyze_json_structure(parsed_data)
                    samples, data_points = self._extract_samples_from_json(parsed_data, data_type)
                    
                    extracted_data.append(ExtractedData(
                        anchor=anchor,
                        data_type=data_type,
                        sample_names=samples,
                        data_points=data_points,
                        metadata={
                            "total_rows": anchor_df.shape[0],
                            "structure_info": structure_info,
                            "json_parsed": True
                        }
                    ))
                except json.JSONDecodeError as e:
                    # If JSON parsing fails, create an entry with error info
                    extracted_data.append(ExtractedData(
                        anchor=anchor,
                        data_type=DataType.UNKNOWN,
                        sample_names=[],
                        data_points=[],
                        metadata={
                            "total_rows": anchor_df.shape[0],
                            "json_error": str(e),
                            "json_parsed": False
                        }
                    ))
            else:
                # No JSON data available
                extracted_data.append(ExtractedData(
                    anchor=anchor,
                    data_type=DataType.UNKNOWN,
                    sample_names=[],
                    data_points=[],
                    metadata={
                        "total_rows": anchor_df.shape[0],
                        "json_parsed": False,
                        "no_json_data": True
                    }
                ))
        
        return extracted_data
    
    def _analyze_json_structure(self, data: Any) -> Tuple[DataType, Dict[str, Any]]:
        """Analyze JSON structure to determine data type and extract patterns."""
        
        if isinstance(data, dict):
            # Check if this is a MultiQC plot structure with 'data' key
            if 'data' in data and 'anchor' in data:
                # This is a MultiQC plot structure - analyze the inner data
                inner_data = data['data']
                return self._analyze_json_structure(inner_data)
            
            # Pattern: somalier_relatedness_plot style with 'datasets' dict
            if 'datasets' in data:
                datasets = data['datasets']
                if isinstance(datasets, dict) and len(datasets) > 0:
                    # Sample the first dataset to check structure
                    first_key = next(iter(datasets.keys()))
                    first_dataset = datasets[first_key]
                    if isinstance(first_dataset, list) and len(first_dataset) > 0:
                        if isinstance(first_dataset[0], dict) and 'x' in first_dataset[0] and 'y' in first_dataset[0]:
                            return DataType.LINE_SCATTER, {
                                "datasets_dict": True,
                                "sample_pairs": list(datasets.keys())[:5],
                                "structure": "somalier_style_datasets"
                            }
            
            # Pattern: Sample-based data (sample names as keys)
            sample_like_keys = [k for k in data.keys() if isinstance(k, str) and not k.startswith('_')]
            if len(sample_like_keys) > 0:
                # Check if values are numeric or structured data (histogram/bar data)
                sample_values = [data[k] for k in sample_like_keys[:3]]
                if all(isinstance(v, (int, float, dict)) for v in sample_values):
                    return DataType.HISTOGRAM_BAR, {
                        "samples": sample_like_keys,
                        "value_types": [type(v).__name__ for v in sample_values[:3]],
                        "structure": "sample_keyed_dict"
                    }
        
        elif isinstance(data, list):
            if len(data) > 0:
                first_item = data[0]
                
                # Pattern: bbmap-qhist_plot style - nested list with sample objects
                if isinstance(first_item, list) and len(first_item) > 0:
                    nested_item = first_item[0]
                    if isinstance(nested_item, dict) and 'name' in nested_item and 'pairs' in nested_item:
                        return DataType.LINE_SCATTER, {
                            "nested_list_series": True,
                            "series_count": sum(len(sublist) for sublist in data if isinstance(sublist, list)),
                            "structure": "bbmap_qhist_style"
                        }
                
                if isinstance(first_item, dict):
                    item_keys = list(first_item.keys())
                    
                    # Pattern 1: Line/scatter plot data with x/y pairs
                    if 'pairs' in item_keys and 'name' in item_keys:
                        return DataType.LINE_SCATTER, {
                            "list_of_series": True,
                            "series_keys": item_keys,
                            "length": len(data),
                            "structure": "plotly_series"
                        }
                    
                    # Pattern 2: Sample-based data (sample names as keys in dict)
                    elif all(isinstance(k, str) for k in item_keys):
                        # Check if it looks like sample data
                        sample_like_keys = [k for k in item_keys if not k.startswith('_')]
                        if len(sample_like_keys) > 2:  # Reasonable number of samples
                            return DataType.HISTOGRAM_BAR, {
                                "list_of_sample_dicts": True,
                                "sample_keys": sample_like_keys[:5],
                                "length": len(data),
                                "structure": "list_of_sample_dicts"
                            }
                    
                    # Pattern 3: General table/record data
                    return DataType.TABLE_DATA, {
                        "list_of_records": True,
                        "record_keys": item_keys,
                        "length": len(data),
                        "structure": "generic_records"
                    }
        
        return DataType.UNKNOWN, {"raw_type": type(data).__name__}
    
    def _extract_samples_from_json(self, data: Any, data_type: DataType) -> Tuple[List[str], List[Dict[str, Any]]]:
        """Extract sample names and data points from JSON structure."""
        samples = []
        data_points = []
        
        # First, check if this is a MultiQC plot structure and extract the data
        if isinstance(data, dict) and 'data' in data:
            actual_data = data['data']
        else:
            actual_data = data
        
        if data_type == DataType.HISTOGRAM_BAR:
            if isinstance(actual_data, dict):
                # Pattern: Sample names as keys, values are metrics
                for sample, value in actual_data.items():
                    if not sample.startswith('_'):  # Skip metadata keys
                        samples.append(sample)
                        
                        if isinstance(value, dict):
                            # Multiple metrics per sample
                            for metric, metric_value in value.items():
                                data_points.append({
                                    "sample": sample,
                                    "metric": metric,
                                    "value": metric_value,
                                    "type": "sample_metric"
                                })
                        elif isinstance(value, (int, float)):
                            # Single value per sample
                            data_points.append({
                                "sample": sample,
                                "value": value,
                                "type": "single_value"
                            })
                        elif isinstance(value, list):
                            # Array data per sample
                            for i, val in enumerate(value):
                                data_points.append({
                                    "sample": sample,
                                    "index": i,
                                    "value": val,
                                    "type": "array_value"
                                })
            
            elif isinstance(actual_data, list):
                # Pattern: List of dictionaries with sample data
                for item in actual_data:
                    if isinstance(item, dict):
                        for sample, value in item.items():
                            if not sample.startswith('_'):
                                samples.append(sample)
                                
                                if isinstance(value, dict):
                                    for metric, metric_value in value.items():
                                        data_points.append({
                                            "sample": sample,
                                            "metric": metric,
                                            "value": metric_value,
                                            "type": "sample_metric"
                                        })
                                else:
                                    data_points.append({
                                        "sample": sample,
                                        "value": value,
                                        "type": "single_value"
                                    })
        
        elif data_type == DataType.LINE_SCATTER:
            if isinstance(actual_data, list):
                # Pattern 1: Plotly-style series data
                for series in actual_data:
                    if isinstance(series, dict):
                        sample = series.get('name', f"series_{len(samples)}")
                        samples.append(sample)
                        
                        # Extract x,y pairs if available
                        if 'pairs' in series:
                            pairs = series['pairs']
                            for pair in pairs:
                                if isinstance(pair, list) and len(pair) >= 2:
                                    data_points.append({
                                        "sample": sample,
                                        "x": pair[0],
                                        "y": pair[1],
                                        "type": "xy_pair",
                                        **{k: v for k, v in series.items() if k not in ['name', 'pairs']}
                                    })
                        else:
                            # Other series data
                            data_points.append({
                                "sample": sample,
                                "type": "series_data",
                                **series
                            })
                            
                # Pattern 2: bbmap-qhist_plot style - nested list with sample objects
                if len(actual_data) > 0 and isinstance(actual_data[0], list):
                    for sample_group in actual_data:
                        if isinstance(sample_group, list):
                            for sample_data in sample_group:
                                if isinstance(sample_data, dict) and 'name' in sample_data:
                                    sample_name = sample_data['name']
                                    samples.append(sample_name)
                                    
                                    if 'pairs' in sample_data:
                                        for pair in sample_data['pairs']:
                                            if isinstance(pair, list) and len(pair) >= 2:
                                                data_points.append({
                                                    "sample": sample_name,
                                                    "x": pair[0],
                                                    "y": pair[1],
                                                    "type": "xy_pair"
                                                })
                                    
            elif isinstance(actual_data, dict):
                # Pattern 3: somalier_relatedness_plot style - datasets dict
                if 'datasets' in actual_data:
                    datasets = actual_data['datasets']
                    for sample_key, points in datasets.items():
                        if isinstance(points, list) and len(points) > 0:
                            point = points[0]  # Usually one point per sample pair
                            if isinstance(point, dict):
                                samples.append(sample_key)
                                data_points.append({
                                    "sample": sample_key,
                                    "x": point.get('x'),
                                    "y": point.get('y'),
                                    "type": "scatter_point",
                                    **{k: v for k, v in point.items() if k not in ['x', 'y']}
                                })
        
        elif data_type == DataType.TABLE_DATA and isinstance(actual_data, list):
            # List of records/rows
            for record in actual_data:
                if isinstance(record, dict):
                    sample = record.get('sample', record.get('Sample', record.get('name', 'unknown')))
                    samples.append(sample)
                    data_points.append({
                        "sample": sample,
                        "type": "table_record",
                        **record
                    })
        
        return list(set(samples)), data_points
    
    def extract_plot_input_row_data(self, max_anchors: int = 50) -> List[ExtractedData]:
        """Extract data from plot_input_row type (tabular data)."""
        row_df = self.df.filter(pl.col("type") == "plot_input_row")
        
        if row_df.shape[0] == 0:
            return []
        
        extracted_data = []
        unique_anchors = row_df.select("anchor").unique().to_series().to_list()
        
        # Process each anchor (table)
        for anchor in unique_anchors[:max_anchors]:
            anchor_df = row_df.filter(pl.col("anchor") == anchor)
            
            data_points = []
            sample_names = set()
            metrics = set()
            
            for row in anchor_df.iter_rows(named=True):
                sample = row.get("sample")
                metric = row.get("metric")
                
                if sample:
                    sample_names.add(sample)
                if metric:
                    metrics.add(metric)
                    
                data_points.append({
                    "sample": sample,
                    "metric": metric,
                    "value": row.get("val_raw"),
                    "value_type": row.get("val_raw_type"),
                    "formatted_value": row.get("val_fmt"),
                    "dt_anchor": row.get("dt_anchor"),
                    "section_key": row.get("section_key")
                })
            
            extracted_data.append(ExtractedData(
                anchor=anchor,
                data_type=DataType.TABLE_DATA,
                sample_names=list(sample_names),
                data_points=data_points,
                metadata={
                    "total_rows": anchor_df.shape[0],
                    "unique_samples": len(sample_names),
                    "unique_metrics": len(metrics),
                    "metrics_list": list(metrics)[:10]  # First 10 metrics
                }
            ))
        
        return extracted_data

    
    def extract_all_data(self, max_row_anchors: int = 50) -> Dict[str, Any]:
        """Extract all data and create comprehensive report."""
        print("Extracting general statistics...")
        general_stats = self.extract_general_statistics()
        
        print("Extracting plot input data (with JSON parsing)...")
        plot_input_data = self.extract_plot_input_data()
        
        print("Extracting plot input row data (tabular)...")
        row_data = self.extract_plot_input_row_data(max_row_anchors)
        
        # Create comprehensive report
        report = {
            "general_statistics": {
                "anchor": general_stats.anchor,
                "data_type": general_stats.data_type.value,
                "sample_count": len(general_stats.sample_names),
                "data_points_count": len(general_stats.data_points),
                "sample_names": general_stats.sample_names[:10],  # First 10 samples
                "metadata": general_stats.metadata
            },
            "plot_input_data": [],
            "row_data": [],
            "summary": {
                "total_anchors_processed": 0,
                "data_type_distribution": {}
            }
        }
        
        # Process plot input data (now includes complex JSON parsing)
        for data in plot_input_data:
            report["plot_input_data"].append({
                "anchor": data.anchor,
                "data_type": data.data_type.value,
                "sample_count": len(data.sample_names),
                "data_points_count": len(data.data_points),
                "sample_names": data.sample_names[:10],
                "metadata": data.metadata
            })
        
        # Process row data (tabular)
        for data in row_data:
            report["row_data"].append({
                "anchor": data.anchor,
                "data_type": data.data_type.value,
                "sample_count": len(data.sample_names),
                "data_points_count": len(data.data_points),
                "sample_names": data.sample_names[:10],
                "metadata": data.metadata
            })
        
        # Count data types across all data
        data_type_counts = {}
        all_data = plot_input_data + row_data
        
        for data in all_data:
            dt = data.data_type.value
            data_type_counts[dt] = data_type_counts.get(dt, 0) + 1
        
        report["summary"]["total_anchors_processed"] = (
            1 +  # general stats
            len(plot_input_data) + 
            len(row_data)
        )
        report["summary"]["data_type_distribution"] = data_type_counts
        
        self.extraction_report = report
        return report

def main():
    """Main execution function."""
    parquet_path = "/Users/tweber/Gits/workspaces/MultiQC-MegaQC/MultiQC_TestData/multiqc_output_complete_v1_30_0/multiqc_data/BETA-multiqc.parquet"
    
    print("Initializing MultiQC extractor...")
    extractor = MultiQCExtractor(parquet_path)
    
    print("Extracting all data patterns...")
    report = extractor.extract_all_data(max_row_anchors=50)
    
    # Save detailed report
    output_path = "/Users/tweber/Gits/workspaces/depictio-workspace/depictio/dev/dev-multiqc-parquet/multiqc_extraction_report.json"
    with open(output_path, 'w') as f:
        json.dump(report, f, indent=2, default=str)
    
    print(f"\n{'='*60}")
    print("EXTRACTION REPORT SUMMARY")
    print(f"{'='*60}")
    
    # General Statistics
    gen_stats = report["general_statistics"]
    print(f"General Statistics:")
    print(f"  - Samples: {gen_stats['sample_count']}")
    print(f"  - Data Points: {gen_stats['data_points_count']}")
    
    # Plot Input Data (with JSON parsing)
    print(f"\nPlot Input Data (JSON parsed):")
    print(f"  - Anchors: {len(report['plot_input_data'])}")
    
    successful_extractions = [d for d in report["plot_input_data"] if d['sample_count'] > 0]
    print(f"  - Successful extractions: {len(successful_extractions)}")
    
    for data in successful_extractions[:10]:  # Show successful ones first
        print(f"    - {data['anchor']} ({data['data_type']}): {data['sample_count']} samples, {data['data_points_count']} points")
    
    # Row Data (Tabular)
    print(f"\nTabular Data (plot_input_row):")
    print(f"  - Anchors: {len(report['row_data'])}")
    for data in report["row_data"][:10]:  # Show first 10
        metadata = data.get('metadata', {})
        print(f"    - {data['anchor']}: {data['sample_count']} samples, {metadata.get('unique_metrics', 0)} metrics")
    
    print(f"\n  - Data Type Distribution:")
    for dtype, count in report["summary"]["data_type_distribution"].items():
        print(f"    - {dtype}: {count} anchors")
    
    print(f"\nDetailed report saved to: {output_path}")
    
    return extractor, report

if __name__ == "__main__":
    extractor, report = main()