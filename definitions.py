"""
Project-wide definitions.

Override paths by creating definitions_private.py in the repo root.
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
    RESULT_DIR = os.path.join(PROJECT_DIR, "results")
    DATASET_DIR = os.path.join(PROJECT_DIR, "datasets")
