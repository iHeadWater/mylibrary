"""
Author: Wenyu Ouyang
Date: 2025-01-03 13:31:33
LastEditTime: 2025-01-03 13:47:41
LastEditors: Wenyu Ouyang
Description: This is a script to read data of google floodhub paper
FilePath: \hydro_ai_papers\google_floodhub\paper_data.py
Copyright (c) 2023-2024 Wenyu Ouyang. All rights reserved.
"""

import os
import sys
import tarfile
from pathlib import Path

sys.path.append(os.path.dirname(Path(os.path.abspath(__file__)).parent))
from definitions import DATASET_DIR


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
