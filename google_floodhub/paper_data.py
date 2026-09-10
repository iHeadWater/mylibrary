"""
Author: Wenyu Ouyang
Date: 2025-01-03 13:31:33
LastEditTime: 2025-01-03 15:29:26
LastEditors: Wenyu Ouyang
Description: This is a script to read data of google floodhub paper
FilePath: \hydro_ai_papers\google_floodhub\paper_data.py
Copyright (c) 2023-2024 Wenyu Ouyang. All rights reserved.
"""

import os
import sys
import tarfile
from pathlib import Path

import numpy as np
import pandas as pd

from hydrodataset.grdc_caravan import GrdcCaravan
from hydrodatasource.reader.grdc import Grdc

sys.path.append(os.path.dirname(Path(os.path.abspath(__file__)).parent))
from definitions import DATASET_DIR, RESULT_DIR


# First, please download paper zip files as follows:
# - gauge_groups_for_paper.tgz
# - metadata.tgz
# - metrics.tgz
def check_google_floodhub_paper_dir(google_flood_paper_dir):
    required_files = ["gauge_groups_for_paper.tgz", "metadata.tgz", "metrics.tgz"]
    missing_files = [
        f
        for f in required_files
        if not os.path.exists(os.path.join(google_flood_paper_dir, f))
    ]

    if missing_files:
        print(f"Missing files: {', '.join(missing_files)}")
    else:
        print("All required files are present.")


def unzip_google_floodhub_paper(google_flood_paper_dir):
    print("Unzipping files, this may take a few minutes...")
    for file_name in ["gauge_groups_for_paper.tgz", "metadata.tgz", "metrics.tgz"]:
        file_path = os.path.join(google_flood_paper_dir, file_name)
        if os.path.exists(file_path):
            with tarfile.open(file_path, "r:gz") as tar:
                tar.extractall(path=google_flood_paper_dir)
                print(f"Extracted {file_name}")
        else:
            print(f"{file_name} does not exist in the directory.")


google_flood_paper_dir = os.path.join(DATASET_DIR, "google-flood-paper")
check_google_floodhub_paper_dir(google_flood_paper_dir)
# Check if the extracted directories exist
extracted_dirs = ["gauge_groups_for_paper", "metadata", "metrics"]
missing_dirs = [
    d
    for d in extracted_dirs
    if not os.path.exists(os.path.join(google_flood_paper_dir, d))
]

# If any extracted directories are missing, unzip the files
if missing_dirs:
    print(f"Missing extracted directories: {', '.join(missing_dirs)}")
    unzip_google_floodhub_paper(google_flood_paper_dir)
else:
    print("All required directories are present.")

# read attributes data
metadata_dir = os.path.join(google_flood_paper_dir, "metadata")
basin_attr_file = os.path.join(metadata_dir, "basin_attributes.csv")
basin_attr = pd.read_csv(basin_attr_file, index_col=0)
print(basin_attr.index)
basin_ids = basin_attr.index.tolist()
print(basin_ids)
assert all(x < y for x, y in zip(basin_ids, basin_ids[1:])), "Basin IDs are not sorted."

grdc_filter_file = os.path.join(
    google_flood_paper_dir, "gauge_groups_for_paper", "dual_lstm", "grdc_filtered.txt"
)
grdc_filter = pd.read_csv(grdc_filter_file, header=None)
grdc_filter_ids = grdc_filter[0].tolist()
assert all(
    x < y for x, y in zip(grdc_filter_ids, grdc_filter_ids[1:])
), "GRDC filter IDs are not sorted."
print(grdc_filter_ids)
# Find IDs that are in basin_ids but not in grdc_filter_ids
unique_basin_ids = [id for id in basin_ids if id not in grdc_filter_ids]

# Print the two unique basin IDs
print(f"The first two unique basin IDs are: {unique_basin_ids}")
# we see these two basins data, they both have long record, don't know why they are excluded

grdc_caravan_dir = os.path.join(DATASET_DIR, "GRDC-Caravan")
# Initialize GrdcCaravan object and read streamflow data
grdc_caravan = GrdcCaravan(grdc_caravan_dir)
grdc_caravan_ids = grdc_caravan.read_site_info()["gauge_id"].tolist()
grdc_dir = os.path.join(DATASET_DIR, "GRDC")
# Initialize Grdc object and read streamflow data
grdc = Grdc(grdc_dir)
grdc_data = grdc.read_site_info()["grdc_no"].tolist()
grdc_data_prefixed = ["GRDC_" + str(grdc_no) for grdc_no in grdc_data]
# Find intersection of basin_ids and grdc_data_prefixed
intersection_grdc_data = np.intersect1d(basin_ids, grdc_data_prefixed)

# Find intersection of basin_ids and grdc_caravan_ids
intersection_grdc_caravan = np.intersect1d(basin_ids, grdc_caravan_ids)

# Find IDs that are in basin_ids but not in grdc_data_prefixed
unique_basin_ids_not_in_grdc_data = [
    id for id in basin_ids if id not in grdc_data_prefixed
]
# Find IDs that are in unique_basin_ids_not_in_grdc_data but in grdc_caravan_ids
unique_basin_ids_in_grdc_caravan = [
    id for id in unique_basin_ids_not_in_grdc_data if id in grdc_caravan_ids
]

print(
    f"Unique basin IDs not in GRDC data but in GRDC Caravan: {unique_basin_ids_in_grdc_caravan}"
)

# Combine intersection_grdc_data and unique_basin_ids_in_grdc_caravan
combined_ids = np.union1d(intersection_grdc_data, unique_basin_ids_in_grdc_caravan)
# Sort the combined IDs
combined_ids = np.sort(combined_ids)
# Create a DataFrame and save to CSV
combined_ids_df = pd.DataFrame(combined_ids, columns=["id"])
if not os.path.exists(RESULT_DIR):
    os.makedirs(RESULT_DIR)
combined_ids_df.to_csv(os.path.join(RESULT_DIR, "googleflood_ids.csv"), index=False)

print("CSV file 'googleflood_ids.csv' has been created.")
