import os
import re
import pandas as pd

# Define your parameters here:
DIRECTORY = "/Users/tweber/Downloads/WORKFLOW_RESULTS"
PATTERN = ".*\.info_raw$"
FILE_FORMAT = "tsv"  # 'csv', 'tsv', 'excel', etc.
COMPRESSION = None  # 'gzip', 'bz2', 'zip', etc. or None
SKIP_ROWS = 13  # Number of rows to skip
PARQUET_FILE = "dataframe.parquet"  # Path to the parquet file


def find_files(directory, pattern):
    """Find files in directory that match a certain pattern."""
    regex = re.compile(pattern)
    matches = []

    directory = os.path.expanduser(directory)  # Expand the '~' to the complete path

    for root, dirs, files in os.walk(directory):
        for basename in files:
            if regex.match(basename):
                filename = os.path.join(root, basename)
                matches.append(filename)
    return matches


def read_file(file_path, file_format, compression, skip_rows):
    """Read file using pandas."""
    if file_format == "csv":
        df = pd.read_csv(file_path, compression=compression, skiprows=skip_rows)
    elif file_format == "tsv":
        df = pd.read_csv(
            file_path, sep="\t", compression=compression, skiprows=skip_rows
        )
    elif file_format == "excel":
        df = pd.read_excel(file_path, skiprows=skip_rows)
    else:
        print(f"Unsupported file format: {file_format}")
        return None

    return df


def main():
    # Load previous dataframe
    if os.path.exists(PARQUET_FILE):
        df_all = pd.read_parquet(PARQUET_FILE)
        if "file" not in df_all.columns:
            df_all["file"] = []
    else:
        df_all = pd.DataFrame(columns=["file"])

    matching_files = find_files(DIRECTORY, PATTERN)
    for file in matching_files:
        if file not in df_all["file"].tolist():  # Only read new files
            print(f"Reading file: {file}")
            df = read_file(file, FILE_FORMAT, COMPRESSION, SKIP_ROWS)
            df["file"] = file  # Add a column with the file name
            df_all = pd.concat([df_all, df]).reset_index(
                drop=True
            )  # Add new data to the dataframe

    print(df_all)

    # Save the updated dataframe
    df_all.to_parquet(PARQUET_FILE, compression="gzip")


if __name__ == "__main__":
    main()
