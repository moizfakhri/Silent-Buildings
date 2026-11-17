PY := .venv/bin/python

.PHONY: setup ingest audit features baseline model evaluate report silent report4 map serve marts llm-eval llm-live llm-experiments sales-feasibility sales notebooks publish-check test lint

# Create the venv (if missing) and install the project with dev and model tools (needs uv).
setup:
	test -d .venv || uv venv --python 3.12 .venv
	uv pip install --python $(PY) -e ".[dev,model,map]"

# Full resumable Socrata pull to data/raw/ (set SOCRATA_APP_TOKEN for higher rate limits).
# Pass NAMES="hpd_aep pluto" to pull a subset, ARGS="--limit-pages 1" for a smoke test.
ingest:
	$(PY) -u pipelines/ingest/pull_socrata.py $(ARGS) $(NAMES)

# Write docs/data_audit.md from data/raw/.
audit:
	$(PY) pipelines/audit.py

# Phase 2: spine + as-of features + forward labels -> data/processed/*.parquet (gitignored).
features:
	$(PY) pipelines/build_features.py

# Sanity-check baseline only (not a model result); needs `make features` first.
baseline:
	$(PY) pipelines/baseline_smoke.py

# Phase 3: train logistic regression and LightGBM, walk-forward with a purge gap, plus the
# community-district hold-out check. Resumable (existing predictions are skipped; add ARGS=--force).
# Writes data/processed/phase3/ (gitignored). About 40 minutes.
model:
	$(PY) -u pipelines/train_phase3.py $(ARGS)
	$(PY) -u pipelines/train_phase3.py --spatial

# Phase 3: metrics with bootstrap CIs, calibration, scores_phase3.parquet, SHAP -> reports/phase3/.
evaluate:
	$(PY) -u pipelines/evaluate_phase3.py $(ARGS)
	$(PY) -u pipelines/shap_phase3.py

# Regenerate the generated tables and figures: docs/labels_and_features.md (Phase 2) and
# docs/modeling_phase3.md + reports/phase3/figures (Phase 3, needs `make evaluate` first).
report:
	$(PY) pipelines/report_features.py
	test ! -f reports/phase3/metrics_test_ci.csv || $(PY) pipelines/report_phase3.py

# Phase 4: condition models (out of time, no complaint features), loudness, silent-distress gaps, validation.
# Writes scores_phase4.parquet (gitignored) and reports/phase4/*.csv. About 17 minutes.
silent:
	$(PY) -u pipelines/train_phase4.py
	$(PY) -u pipelines/silent_phase4.py
	$(PY) -u pipelines/validate_phase4.py $(ARGS)

# Phase 4 figures and the generated tables in docs/silent_distress_phase4.md.
report4:
	$(PY) pipelines/report_phase4.py

# Phase 6: the 3D map data (needs footprints: make ingest NAMES=building_footprints, and tippecanoe). About 2 minutes.
map:
	$(PY) pipelines/build_map.py

# Serve the map locally (http://127.0.0.1:8777, loopback only; needs Range support for the tiles).
serve:
	$(PY) app/web/serve.py 8777

# Phase 7: DuckDB marts for the LLM layer (data/processed/marts.duckdb, gitignored). A few seconds.
marts:
	$(PY) pipelines/build_marts.py

# Phase 7: offline harness checks with deterministic stubs (NOT model results).
llm-eval:
	$(PY) pipelines/llm_eval.py

# Phase 7: live model evaluation. Needs ANTHROPIC_API_KEY in the environment or .env and `uv pip install anthropic`. Costs API credits.
llm-live:
	$(PY) pipelines/llm_eval.py --live

# Phase 7: the two RAG gates (retrieval vs SQL keywords; text-derived features vs out-of-time PR-AUC). About 10 minutes, offline.
llm-experiments:
	$(PY) pipelines/llm_retrieval_experiment.py
	$(PY) pipelines/llm_text_features_experiment.py

# Phase 5: is a sale study feasible? (ACRIS coverage vs DOF sales, attrition, cohorts). Needs `make ingest NAMES="dof_sales"`, `make marts` and, for the ACRIS coverage rows,
# `python pipelines/ingest/pull_acris.py` (the local ACRIS pulls were deleted on 2026-11-14; the study itself does not use ACRIS).
sales-feasibility:
	$(PY) pipelines/sales_feasibility.py

# Phase 5: staggered event study after whole-building sales, plus figures and tables -> reports/phase5/. About 1 minute.
sales:
	$(PY) -u pipelines/sales_study.py
	$(PY) pipelines/report_phase5.py

# Phase 8: re-execute the narrative notebooks (they read only committed outputs in reports/, docs/ and app/web/data).
notebooks:
	cd notebooks && ../$(PY) build_notebooks.py

# Phase 8: what would be tracked, size, secrets, data files, personal details. Runs no git command and publishes nothing.
publish-check:
	$(PY) pipelines/publish_check.py

test:
	$(PY) -m pytest -q

lint:
	$(PY) -m ruff check src tests pipelines
