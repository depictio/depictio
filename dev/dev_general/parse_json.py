import os, sys
import json
import pandas as pd


def process_folder(folder_path):
    # Initialize a dictionary to hold the field counts
    field_counts = {}

    # Initialize a list to hold the file paths
    file_paths = []

    # Iterate over the files in the folder
    for filename in os.listdir(folder_path):
        if filename.endswith(".json"):
            file_path = os.path.join(folder_path, filename)
            file_paths.append(file_path)

            # Load the JSON file
            with open(file_path, "r") as f:
                json_data = json.load(f)

                # Update the field counts
                for field in json_data:
                    if field not in field_counts:
                        field_counts[field] = 1
                    else:
                        field_counts[field] += 1

    # Convert the field counts dictionary to a Pandas DataFrame
    field_counts_df = pd.DataFrame(list(field_counts.items()), columns=["Field", "Count"])

    # Calculate the percentage of files that contain each field
    num_files = len(file_paths)
    field_counts_df["Percentage"] = field_counts_df["Count"] / num_files * 100

    # Return the DataFrame
    return field_counts_df


f = ""
result_df = process_folder(f)
print(result_df)
