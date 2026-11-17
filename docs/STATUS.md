# Project status and how to resume

Last updated: 2026-11-16. All eight phases are done and the project is published at https://github.com/moizfakhri/Silent-Buildings. Raw data, model binaries and building-level score files stay local (gitignored).

## Done

| Phase | What | Where | Re-run |
|---|---|---|---|
| 1 | 12 NYC Open Data tables pulled to raw Parquet (Bronx+Brooklyn from 2018; 13.9M rows), audited | `data/raw/`, `docs/data_audit.md`, `docs/DATASETS.md` | `make ingest`, `make audit` |
| 2 | Spine (101,749 lots), 82 as-of features, forward labels, quarterly 2019-01 to 2025-10, leakage tests | `data/processed/{spine,features,labels}.parquet`, `docs/labels_and_features.md` | `make features` (11 s) |
| 3 | Walk-forward baselines, LightGBM and logistic, bootstrap CIs, SHAP | `data/processed/phase3/`, `scores_phase3.parquet`, `reports/phase3/`, `docs/modeling_phase3.md` | `make model`, `make evaluate`, `make report` |
| 4 | Silent distress: condition model, loudness, gaps, validation. Verdict: strong form not supported | `data/processed/phase4/`, `scores_phase4.parquet`, `reports/phase4/`, `docs/silent_distress_phase4.md` | `make silent`, `make report4` |
| 6 | 3D map: footprints, tiles, static MapLibre site | `app/web`, `app/web/data` (tiles gitignored), `docs/map.md`, `docs/img` | `make ingest NAMES=building_footprints`, `make map`, `make serve` |
| 7 | LLM layer (offline): marts, sandboxed text-to-SQL, gold set, biographies + verifier, RAG gates (both negative). Live model eval pending (no API key) | `src/nycdistress/llm`, `docs/llm_layer.md`, `reports/phase7/`, `data/processed/marts.duckdb` | `make marts`, `make llm-eval`, `make llm-experiments`, `make llm-live` (needs key) |
| 5 | Sale study. ACRIS Master extract unusable (about 8% of deeds), pivot to DOF sales; staggered event study, 8,500 treated vs 70,157 never-sold. Verdict: small rise in violations and complaints after sales, no detectable serious-event change, no detectable silent-vs-loud difference | `src/nycdistress/{sales,did}.py`, `pipelines/{sales_feasibility,sales_study,report_phase5}.py`, `reports/phase5/`, `docs/sales_phase5.md` | `make ingest NAMES="dof_sales"`, `make marts`, `make sales-feasibility`, `make sales` |

| 8 | Polish: README rewrite, paper-style report, methodology log, 7 executed notebooks, license note, publish check | `README.md`, `docs/{REPORT,METHODOLOGY_LOG,LICENSE_NOTE,PUBLISH_CHECKLIST}.md`, `notebooks/`, `pipelines/publish_check.py` | `make notebooks`, `make publish-check` |

## Next

Nothing is queued. Possible extensions:

1. Live LLM evaluation (`make llm-live`): needs an `ANTHROPIC_API_KEY` in `.env`; the harness is tested offline against stubs.
2. ACS demographics for the silent areas, an owner-portfolio analysis with a complete ACRIS extract, a PyMC hierarchical model.

Publication decisions: the real one-district map sample is kept; the raw ACRIS pulls were deleted; the earlier exploration folders are gitignored; the license is MIT (`LICENSE`, `THIRD_PARTY_NOTICES.md`). See `docs/PUBLISH_CHECKLIST.md`.

Changes made in the pre-publication review (2026-11-16): the map's district view now colours district averages on its own scale (zero-centred for the complaint gap; it was min-max scaled before, which shifted the neutral colour), the sample mode says it is a sample, the selected building is highlighted and views are linkable; the sale study's silent-minus-not-silent point estimate is now the difference of the two estimates rather than the mean of the bootstrap draws (-2.0 points instead of -2.1, interval unchanged).

## How to resume if a session dies

```bash
cd <the project folder>
make test && make lint          # should be green
ls data/processed data/processed/phase4 reports docs
```
Check the "Next" list above and the newest files under `docs/`, `app/`, `pipelines/`. Every pipeline is resumable (existing outputs are skipped). Raw pulls resume from cursor files.

## Limits on what is published

No secrets in any committed file (`.env` is gitignored); no raw data, model binaries or full building-level score files in git (only the one-district map sample); no owner, buyer, tenant or contact names anywhere. `make publish-check` verifies this.

## Decisions log (short)

- Primary outcome for Phase 4: vacate order or DOB physical-hazard violation (core codes IMEGNCY, UB, FISPHAZ, EGNCY); changed from the wide definition after seeing event-rate instability (see Phase 4 doc, section 5).
- Time-split validation only, with a 12 month purge gap. Condition model uses `static_*` + `prior_*` only.
- Phase 5: ACRIS Master open-data extract unusable (8% of deeds); DOF sales used; whole-building arms-length sales only.
- Full list of decisions with timing (before or after seeing data): `docs/METHODOLOGY_LOG.md`.
- The honest verdict carried everywhere: mostly, silence reflects ordinary risk; the no-access censoring is real (about 16% of closed problems) but shows no hidden extra risk; predicted condition still predicts later complaints among never-complaining buildings (IRR 1.70 per SD).
