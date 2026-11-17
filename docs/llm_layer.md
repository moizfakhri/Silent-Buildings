# Phase 7: the LLM layer

Everything here runs **offline** against deterministic stubs. A live model is used only when `ANTHROPIC_API_KEY` is present (environment or `.env`); the key in this checkout is empty,
so **no live model has been run and no live numbers exist**. Stub results below are harness checks, not model results, and are labelled that way everywhere.

Code: `src/nycdistress/llm/` (`client`, `sandbox`, `schema`, `gold`, `text2sql`, `biography`, `retrieval`), `pipelines/{build_marts,llm_eval,llm_retrieval_experiment,llm_text_features_experiment}.py`.
Tests: `tests/test_llm_*.py` (29 tests). Make targets: `make marts`, `make llm-eval`, `make llm-live`, `make llm-experiments`.

## Components

### (a) Text-to-SQL over DuckDB marts (structured data, not RAG)

- **Marts** (`data/processed/marts.duckdb`, 442 MB, gitignored, built in seconds): `buildings`, `building_snapshots` (1.6M rows: scores, flags, 12-month counts and next-12-month outcomes), `hpd_violations` (4.4M), `hpd_complaints` (3.8M),
  `omo_charges`, `litigations`, `vacate_orders`, `aep_programs`, `dob_violations`, `evictions`. Deliberately absent: litigation respondents (owner names), eviction marshals and court numbers, registration contacts.
- **Schema docs and prompt** (`schema.py`, `text2sql.py`): every column described, notes on the latest snapshot date and the meaning of the scores, seven few-shot examples that are not among the gold questions (a test enforces that).
- **Read-only sandbox** (`sandbox.py`), defences in layers: database opened read-only; DuckDB external access (files, network, extensions) disabled and the configuration locked; DuckDB's own parser must see exactly one `SELECT`; a keyword deny list as defence in depth;
  1,000-row cap, 3 GB memory cap, 20 s wall-clock timeout that interrupts the query. Tests try DROP, COPY, ATTACH, INSTALL, PRAGMA, SET, multi-statement and file-reading queries, an unbounded cross join, writes on the raw connection, and re-enabling external access: all are refused or fail.
- **Gold set**: 58 questions with hand-written reference SQL across counts, filters, aggregates, group-bys, top-k with tie-breaks, joins, distinct counts, text matching and snapshot/time-window questions (`gold.py`). Every reference query executes and returns a non-trivial result (tested).
  One reference query had a flaw found while building the set (a NULL district group); it was fixed and the question now says to ignore buildings without a district.
- **Metric**: execution accuracy, i.e. the predicted query's result equals the reference result (same columns, floats to 4 decimals, order only when asked). One automatic repair round after an error is allowed and recorded.

### (b) Building biographies with citations and a verifier

Evidence for a building is gathered by deterministic SQL and given ids (`bld:<bbl>`, `snap:<bbl>:<date>`, `viol:<id>`, `omo:<id>`, `lit:<id>`, `vac:<bbl>:<n>`, `aep:<bbl>:<date>`). A biography has at most 8 sentences; each states its facts and cites the supporting ids in brackets;
it ends with a fixed disclaimer. The **verifier is code, not a model**: every cited id must exist; every number in a sentence must appear in a cited record (integers exactly, decimals within rounding); no uncited factual sentence; no blame language (owner, landlord, neglect, fault, ...).
Violation records whose own text speaks of owners (registration violations) are kept out of the evidence, and apartment-level locations are stripped from violation text, so a biography stays at building level. A language model gets one repair round with the verifier's complaints.

### (c) RAG gates (fixed rules, measured)

RAG goes in only where it beats a plain SQL baseline. Two gates were run, offline:

| gate | question | result | decision |
|---|---|---|---|
| **E1: evidence retrieval** over HPD violation text | within one building's records, retrieve those about a condition ("no heat or hot water", "rats mice and roaches", ...). Ground truth is structured (HPD order-number families), independent of the text. BM25 and TF-IDF with natural-language queries (3 paraphrases each) vs the plain SQL baseline (ILIKE any hand-written keyword, newest first); 400 buildings, 2,317 building-condition pairs | precision@10: **SQL keywords 0.668** [0.659, 0.676], BM25 0.526 [0.517, 0.536], TF-IDF 0.501 [0.493, 0.509], random 0.091. BM25 minus SQL = **-0.141** [-0.149, -0.133] | **Not adopted.** Rule: adopt only if BM25 beats SQL by 0.03 with the paired interval above 0. SQL wins 6 of 8 conditions (plumbing 0.53 vs 0.18, because "toilet" is "WATER CLOSET" in the records); retrieval wins only lead paint (0.79 vs 0.67) |
| **E2: text-derived severity features** | 11 features from violation text (counts by 10 keyword categories in the prior 12 months, hazard share) added to the Phase 3 features; LightGBM, same walk-forward folds and purge | test PR-AUC gain **+0.0010** [+0.0005, +0.0016] on any serious event, folds positive 2 of 4 (+0.0002, -0.0003, -0.0002, +0.0010); on the primary outcome +0.0007 [-0.0002, +0.0018] | **Not adopted.** Rule: gain at least +0.005 with the interval above 0 and positive in at least 3 of 4 folds. The gain is detectable but negligible |

Caveats on E1: the SQL keyword lists were written by me knowing the corpus vocabulary, which is what a SQL user with domain knowledge does, and it favours SQL over natural-language queries; an embedding model might close part of the gap but none was run (no model download was done). The ground truth families were read by me from the canonical wording of the 60 most common order numbers (which cover about 96% of records).
**Housing Maintenance Code retrieval was not attempted**: no clean machine-readable public copy was at hand and E1 gives little reason to expect a gain, so the biography cites record ids and states what the violation classes mean in the code comments only.
The biography's retrieval-selected evidence variant exists and is wired into the live evaluation, but with E1 negative it is not the default; the SQL-only evidence selection (class C first, then newest) is.

## Results available without a key (harness checks, NOT model results)

| check | result |
|---|---|
| text-to-SQL harness, oracle stub (returns the reference SQL) | execution accuracy 1.000 (must be 100%) |
| text-to-SQL harness, "always SELECT 1" stub | 0.000 (must be about 0%) |
| text-to-SQL, crude keyword stub (2 generic patterns, not a model) | 0.034 (2 of 58) |
| biography, deterministic template (evidence-only baseline) | 40 of 40 pass the verifier |
| biography verifier on corrupted copies | 40 of 40 numeric corruptions caught; 40 of 40 invented ids caught (and tests cover uncited, wrong-record, blame-word and rounding-tolerance cases) |

The two stubs bracket the metric and show the harness can fail. They say nothing about how well a language model writes SQL or biographies.

## Live evaluation: pending

To run it (costs API credits; needs `uv pip install anthropic` or `pip install -e ".[llm]"`, and a key):

```bash
echo 'ANTHROPIC_API_KEY=...' >> .env          # the file is gitignored; the key is never printed or written elsewhere
make llm-live                                  # text-to-SQL on the 58 gold questions + 40 biographies with SQL-only and retrieval evidence
python pipelines/llm_eval.py --live --limit 10 --n-bio 5      # a cheap smoke run first
```
It writes `reports/phase7/llm_live.json`: execution accuracy overall and by category (with the repair round counted), the share of questions whose query executed, and for each evidence strategy the mean sentence-level faithfulness, mean attempts and biographies with remaining issues.
The model id defaults to `claude-sonnet-5-5` and can be set with `NYC_LLM_MODEL`.
**Execution accuracy, faithfulness and any retrieval-vs-SQL biography comparison with a live model are therefore not reported here.**

## Limits

- The gold set is written by the same author as the schema docs and the marts; a live model will expose ambiguity in my wording. Execution accuracy counts a query as right only if its result matches.
- The verifier checks that statements are supported by cited records and that numbers match; it cannot judge whether a true sentence is a fair summary, and it does not catch an omission.
- Per-building biographies are model-assisted descriptions of public record counts plus research estimates, with the disclaimer; they are not assessments of any owner or tenant.
