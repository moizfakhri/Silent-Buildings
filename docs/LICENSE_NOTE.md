# License note

**Decided (owner, 2026-11-14): MIT.** The `LICENSE` file at the project root holds the standard MIT text, copyright 2026, holder "Moiz Fakhri".

| Part | License |
|---|---|
| Code (`src/`, `pipelines/`, `tests/`, `app/web/*.{html,css,js,py}`, `notebooks/`), docs, figures and report tables | MIT, as above |
| Vendored MapLibre GL JS 4.7.1 and PMTiles 3.2.0 | BSD-3-Clause each, with their own license text next to the files; see `THIRD_PARTY_NOTICES.md` |
| Data | None is in the repository (raw and processed data, tiles and per-building shards are gitignored). NYC Open Data terms of use apply to anyone who re-pulls it |

Where the PMTiles text came from: the npm package ships none, so `app/web/vendor/pmtiles.LICENSE.txt` is the upstream repository's `LICENSE` file (Protomaps, default branch, fetched 2026-11-14; no 3.2.0 tag was found at the paths tried). MapLibre's text came in its package.

Data attribution and the "not affiliated with the City of New York" statement are in the README and `THIRD_PARTY_NOTICES.md`. Nothing here uses a City logo or presents itself as an official tool; keep it that way.
