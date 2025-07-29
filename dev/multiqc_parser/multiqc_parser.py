import json
import os

import pandas as pd


class MultiQCParser:
    def __init__(self, json_file):
        """Initialize the parser with a MultiQC JSON file path"""
        with open(json_file, "r") as f:
            self.data = json.load(f)

        self.metadata = self._extract_metadata()
        self.modules = self._get_modules()
        self.samples = self._get_samples()

    def _extract_metadata(self):
        """Extract report metadata"""
        metadata = {}
        for key, value in self.data.items():
            if key.startswith("config_") or key == "report_creation_date":
                metadata[key] = value
        return metadata

    def _get_modules(self):
        """Get list of all modules in the report"""
        if "report_saved_raw_data" in self.data:
            return list(self.data["report_saved_raw_data"].keys())
        return []

    def _get_samples(self):
        """Get a deduplicated list of all samples across all modules"""
        samples = set()
        if "report_saved_raw_data" in self.data:
            for module in self.data["report_saved_raw_data"]:
                samples.update(self.data["report_saved_raw_data"][module].keys())
        return list(samples)

    def get_raw_data(self, module=None, sample=None, metric=None):
        """
        Extract raw data with flexible filtering:
        - If no parameters are specified, return all data
        - Otherwise, filter by module, sample, and/or metric
        """
        if "report_saved_raw_data" not in self.data:
            return {}

        results = {}

        # Filter the modules to process
        modules_to_process = [module] if module else self.modules

        for mod in modules_to_process:
            if mod not in self.data["report_saved_raw_data"]:
                continue

            results[mod] = {}

            # Filter the samples to process
            samples_to_process = (
                [sample] if sample else self.data["report_saved_raw_data"][mod].keys()
            )

            for samp in samples_to_process:
                if samp not in self.data["report_saved_raw_data"][mod]:
                    continue

                # Filter the metrics to include
                if metric:
                    if metric in self.data["report_saved_raw_data"][mod][samp]:
                        results[mod][samp] = {
                            metric: self.data["report_saved_raw_data"][mod][samp][metric]
                        }
                else:
                    results[mod][samp] = self.data["report_saved_raw_data"][mod][samp]

        return results

    def get_plot_data(self, plot_id=None):
        """Extract plot data for specified plot ID or all plots"""
        if "report_plot_data" not in self.data:
            return {}

        if plot_id:
            if plot_id in self.data["report_plot_data"]:
                return {plot_id: self.data["report_plot_data"][plot_id]}
            return {}

        return self.data["report_plot_data"]

    def get_general_stats(self):
        """Extract general stats data"""
        results = {}

        if "report_general_stats_data" in self.data:
            results["data"] = self.data["report_general_stats_data"]

        if "report_general_stats_headers" in self.data:
            results["headers"] = self.data["report_general_stats_headers"]

        return results

    def to_pandas(self, module=None):
        """
        Convert the raw data to pandas DataFrames:
        - One DataFrame per module
        - Samples as rows, metrics as columns
        """
        dfs = {}

        modules_to_process = [module] if module else self.modules

        for mod in modules_to_process:
            if mod not in self.data["report_saved_raw_data"]:
                continue

            # Get all metrics across all samples for this module
            all_metrics = set()
            for sample in self.data["report_saved_raw_data"][mod]:
                all_metrics.update(self.data["report_saved_raw_data"][mod][sample].keys())

            # Prepare data for DataFrame
            df_data = []
            for sample in self.data["report_saved_raw_data"][mod]:
                sample_data = {"sample": sample}
                for metric in all_metrics:
                    sample_data[metric] = self.data["report_saved_raw_data"][mod][sample].get(
                        metric, None
                    )
                df_data.append(sample_data)

            if df_data:
                dfs[mod] = pd.DataFrame(df_data).set_index("sample")

        return dfs

    def export_to_csv(self, output_dir, module=None):
        """Export all data to CSV files, one per module"""
        os.makedirs(output_dir, exist_ok=True)

        dfs = self.to_pandas(module)

        for mod, df in dfs.items():
            output_file = os.path.join(output_dir, f"{mod}.csv")
            df.to_csv(output_file)

        return list(dfs.keys())
