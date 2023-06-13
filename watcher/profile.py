import time
import os

DIRECTORY = "/Users/tweber/SSHFS_scratch/DATA/MC_DATA/GENECORE_REPROCESSING_2021_2022"

start = time.time()
dir_list = (dirpath for dirpath, dirs, files in os.walk(DIRECTORY))
print(f"os.walk took {time.time() - start} seconds")
