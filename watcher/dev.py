import os
import re
import pandas as pd
import parmap
from multiprocessing import cpu_count

# Define your parameters here:
DIRECTORY = "/Users/tweber/SSHFS_scratch/DATA/MC_DATA/GENECORE_REPROCESSING_2021_2022"
PATTERN = ".*\.info_raw$"
DIRECTORY_PATTERN = ".*counts.*"  # Only search in directories that contain 'counts'
FILE_FORMAT = "tsv"  # 'csv', 'tsv', 'excel', etc.
COMPRESSION = None  # 'gzip', 'bz2', 'zip', etc. or None
SKIP_ROWS = 13  # Number of rows to skip
PARQUET_FILE = "dataframe.parquet"  # Path to the parquet file


def find_files(directory, pattern, directory_pattern):
    """Find files in a directory that match a certain pattern."""
    directory_regex = re.compile(directory_pattern)
    file_regex = re.compile(pattern)

    matches = []

    subdirectories = [
        os.path.join(directory, d)
        for d in os.listdir(directory)
        if os.path.isdir(os.path.join(directory, d))
    ]

    result_list = parmap.starmap(
        find_files_in_directory,
        list(zip(subdirectories)),
        file_regex,
        directory_regex,
        pm_processes=cpu_count(),
        pm_pbar=True,
    )

    for result in result_list:
        matches.extend(result)

    return matches


def find_files_in_directory(directory, file_regex, directory_regex):
    matches = []

    for dirpath, dirs, files in os.walk(directory):
        if directory_regex.match(dirpath):
            matches.extend(
                [
                    os.path.join(dirpath, file)
                    for file in files
                    if file_regex.match(file)
                ]
            )

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

    df["file"] = file_path  # Add a column with the file name

    return df


def main():
    df_all = pd.DataFrame()

    matching_files = find_files(DIRECTORY, PATTERN, DIRECTORY_PATTERN)
    for file in matching_files:
        print(f"Reading file: {file}")
        df = read_file(file, FILE_FORMAT, COMPRESSION, SKIP_ROWS)
        df_all = pd.concat([df_all, df])  # Add new data to the dataframe

    df_all.to_parquet(PARQUET_FILE, compression="gzip")


if __name__ == "__main__":
    main()
