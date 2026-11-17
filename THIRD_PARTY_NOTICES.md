# Third-party notices

The project's own code and documents are MIT licensed (see `LICENSE`). The following third-party code is vendored in the repository and keeps its own license; each license text sits next to the file.

| Component | Version | License | Files | License text |
|---|---|---|---|---|
| MapLibre GL JS | 4.7.1 | BSD-3-Clause | `app/web/vendor/maplibre-gl.js`, `maplibre-gl.css` | `app/web/vendor/maplibre-gl.LICENSE.txt` |
| PMTiles (JavaScript reference implementation) | 3.2.0 | BSD-3-Clause (Copyright 2021 Protomaps LLC) | `app/web/vendor/pmtiles.js` | `app/web/vendor/pmtiles.LICENSE.txt` |

Both files were fetched once from the npm registry at the pinned versions. The MapLibre license text came in its package. The PMTiles npm package ships no license file, so its text was copied from the upstream repository's `LICENSE` (github.com/protomaps/PMTiles, default branch, 2026-11-14; no 3.2.0 tag exists at the paths tried). It states that the BSD-3 license covers the reference implementations and that the PMTiles specification itself is public domain or CC0.

Python dependencies (DuckDB, pandas, LightGBM, scikit-learn, SHAP, statsmodels, and others) are installed from PyPI, not vendored, and are covered by their own licenses.

## Data

No data is redistributed in this repository except small aggregate report tables and a one-district sample of model estimates (`app/web/data/sample/`). The underlying data come from NYC Open Data (data.cityofnewyork.us), published by HPD, DOB, DOF, DCP and the 311 system, under the City's open data terms of use. Anyone re-pulling it is bound by those terms, and by the dataset-specific notes on each dataset's page (DOF sales and DCP PLUTO/footprint data carry their own disclaimers). This project is independent and not affiliated with or endorsed by the City of New York.
