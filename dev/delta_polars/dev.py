import polars as pl

data_frames = []


for file_info in files:
    file_path = file_info["file_location"]

    # Read the file using Polars and the given config
    config = data_collection_config["config"]
    df = pl.read_csv(
        file_path,
        **config["pandas_kwargs"],
    )
    raw_cols = df.columns
    df = df.with_column(pl.lit(file_info["run_id"]).alias("depictio_run_id"))
    df = df.select(["depictio_run_id"] + raw_cols)
    data_frames.append(df)

# Aggregate data
aggregated_df = pl.concat(data_frames)

# Write aggregated dataframe to Delta Lake
delta_table_path = (
    f"delta_table_path/{data_collection.workflow_id}/{data_collection.data_collection_id}"
)
aggregated_df.write_delta(delta_table_path)
