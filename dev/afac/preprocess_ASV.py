import pandas as pd
import sys

# Load the data
file_path = sys.argv[1]  # Replace with your file path
df = pd.read_csv(file_path, sep='\t')

# Define the columns to pivot
pivot_columns = [f"{letter}{number}" for letter in "ABCDEFGH" for number in range(1, 13)]


# Melt the dataframe
df_melted = df.melt(id_vars=[col for col in df.columns if col not in pivot_columns],
                    value_vars=[col for col in pivot_columns if col in df.columns],
                    var_name='Sample',
                    value_name='Value')

# Optionally, you can pivot the melted dataframe to get back to a wider format
# df_pivot = df_melted.pivot_table(index=[col for col in df.columns if col not in pivot_columns],
#                                  columns='Sample',
#                                  values='Value')

# Save the transformed data
sample = file_path.split('Sequencing/')[1].split("/")[0]
print(sample)
output_path = "/".join(file_path.split("/")[:-1]) + "/" + sample + ".ASV.reformated.tsv"
df_melted.to_csv(output_path, sep='\t', index=False)

print(df_melted.head())
print("Data transformation complete. File saved to:", output_path)
