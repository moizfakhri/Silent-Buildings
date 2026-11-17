"""Build the Phase 2 spine, as-of features and forward labels into data/processed/.

Usage:
    python pipelines/build_features.py                  # everything
    python pipelines/build_features.py 10_staging 20_spine   # only some SQL steps (they need earlier ones in the same run)
"""
import sys

from nycdistress.build import build

if __name__ == "__main__":
    build(only=sys.argv[1:] or None)
