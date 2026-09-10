"""
Author: Wenyu Ouyang
Date: 2024-12-29 15:12:55
LastEditTime: 2024-12-29 20:38:51
LastEditors: Wenyu Ouyang
Description: some project-wide definitions
FilePath: \HydroForecastEval\definitions.py
Copyright (c) 2023-2024 Wenyu Ouyang. All rights reserved.
"""

# NOTE: create a file in root directory -- definitions_private.py,
# then copy the code after 'except ImportError:' to definitions_private.py
# and modify the paths as your own paths in definitions_private.py
import os

try:
    import definitions_private

    PROJECT_DIR = definitions_private.PROJECT_DIR
    RESULT_DIR = definitions_private.RESULT_DIR
    DATASET_DIR = definitions_private.DATASET_DIR
except ImportError:
    PROJECT_DIR = os.getcwd()
    RESULT_DIR = r"C:\Users\wenyu\code\hydro_ai_papers"
    DATASET_DIR = r"C:\Users\wenyu\code\hydro_ai_papers"
