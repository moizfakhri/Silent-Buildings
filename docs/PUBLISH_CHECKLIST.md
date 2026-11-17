# Publish checklist

Status: **published on 2026-11-16** at https://github.com/moizfakhri/Silent-Buildings, after the checks below. The list is kept as the record of what was checked and decided; run it again before any later push that adds data or outputs.

Run the automated part any time (it applies `.gitignore` with `pathspec`, runs no git command, and writes `reports/publish_check.json`):

```bash
make publish-check
```

Result at the time of writing: 196 files would be tracked, about 10.2 MB; no secrets found; no data files (Parquet, DuckDB, PMTiles) tracked; no e-mail addresses or home-folder paths; no name-like columns in committed CSVs.

## 1. Secrets

- [x] **DONE** `.env` is gitignored (`.env`, `.env.*` ignored; `.env.example` allowed and holds only empty key names).
- [x] **DONE** Scan of every would-be-tracked text file for well-known key patterns, assigned secrets, and any value from the local `.env` (values are never printed): none found.
- [x] **DONE (2026-11-16)** The git history was started clean on top of the repository's initial commit, so it contains only files that passed this check. Commits use a GitHub no-reply address.
- [ ] If a Socrata token or an Anthropic key was ever pasted into a chat, a note or a terminal log, rotate it before publishing.

## 2. No raw data, no model binaries

- [x] **DONE** `data/raw/`, `data/interim/`, `data/processed/`, `*.parquet`, `*.duckdb`, `*.csv`, `*.pmtiles` and `app/web/data/facts/` are ignored. `!reports/**/*.csv` re-includes only the small report tables (largest 0.97 MB, aggregate rows).
- [x] **DONE** No model binaries exist outside `data/processed/` (gitignored).
- [x] **DONE** Largest would-be-tracked files: `app/web/data/sample/facts.json` 1.3 MB, `sample/buildings.geojson` 1.0 MB, `reports/phase3/metrics_test_ci.csv` 1.0 MB, `docs/img/map_slider.gif` 0.9 MB, `app/web/vendor/maplibre-gl.js` 0.8 MB.
- [x] **DONE** `.pytest_cache/` and `.ruff_cache/` were not ignored; added to `.gitignore` during this check.

## 3. No personal data

- [x] **DONE** No owner, buyer, tenant, marshal or registrant names in any committed output. The marts exclude litigation respondents, eviction marshals, registration contacts. The sale study read no party names (DOF sales have none).
- [x] **DONE** `reports/phase3/shap_examples.csv` and `docs/modeling_phase3.md` used four real building lot ids as SHAP examples; they were replaced by "example building 1..4" (the key sits in the gitignored `data/processed/phase3/shap_example_keys.csv`, and `pipelines/shap_phase3.py` now writes opaque labels).
- [x] **DONE** `docs/img/map_building_panel.jpg` showed a real lot id with its scores; the id was painted over (the unredacted original is not in the repository).
- [x] **DONE** No home-folder paths or e-mail addresses in tracked files (the one path in `docs/STATUS.md` was removed).
- [x] **DECIDED (owner, 2026-11-14): keep the real one-district sample.** `app/web/data/sample/` holds model scores and public record counts for 1,191 real buildings in one Bronx community district so the map's fallback page works without the tile file. I had recommended a synthetic sample; the owner chose the real one. The sample scores are **model estimates for research, not findings about any owner or tenant**; the map says so on first load ("This map shows model estimates for research, not findings about any owner or tenant") and in its footer, and the README and `docs/map.md` repeat it, together with the Phase 4 verdict that a high gap is not hidden danger.
- [x] **Follows from the decision above:** the screenshots and GIF in `docs/img/` (real buildings coloured by model estimates; the one panel screenshot has its lot id painted over) and the per-building public record counts in the sample facts stay.
- [x] **DONE (owner's instruction, 2026-11-14): the raw ACRIS pulls (`data/raw/acris_master`, `acris_legals`, `acris_parties`) were deleted**, party names included.

## 4. Unrelated or earlier material in the folder

- [x] **DONE (owner's instruction, 2026-11-14):** `rats_vs_trash_bins/`, `street-redesign-safety/` and `NYC_OpenData_Dataset_Ranking.md` are now in `.gitignore`, so they stay on disk but are excluded from git.
- [x] **DONE** The empty `evals/` placeholder was removed.

## 5. Size

- [x] **DONE** About 10.2 MB would be tracked (limit for a comfortable GitHub repo: well under 100 MB, no single file over 100 MB). Notebooks with saved outputs are 1.6 MB in total.
- [x] **DONE (2026-11-16)** `git count-objects -vH` checked after the commits were made.

## 6. Content and claims

- [x] **DONE** README leads with the verdict: mostly, silence reflects ordinary risk; negative and weak-positive results are stated plainly; choices made after seeing data are listed.
- [x] **DONE** The map carries a disclaimer on first load and in the footer; layer names are neutral; the default view is district averages.
- [x] **DONE (2026-11-16)** README rewritten and re-read for claims about owners, landlords or tenants: it makes none.
- [x] **DONE** The README states the project is independent and not affiliated with the City of New York and names the dataset publishers (HPD, DOB, DOF, DCP, 311).

## 7. License

- [x] **DECIDED (owner, 2026-11-14): MIT.** `LICENSE` is in the project root (holder "Moiz Fakhri", editable); the PMTiles BSD-3 text is next to its vendored file, MapLibre's was already; `THIRD_PARTY_NOTICES.md` lists both. See `docs/LICENSE_NOTE.md`.

## 8. Final gates before the first push

```bash
make test            # 170 tests, synthetic fixtures, no real data
make lint
make publish-check   # must exit 0 with no secrets and no data files
make notebooks       # optional: re-execute the notebooks from committed outputs
```

These gates were run before the first push on 2026-11-16.
