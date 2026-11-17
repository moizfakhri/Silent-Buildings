# Methodology and decision log

Every non-obvious choice, why it was made, and whether it was made **before** or **after** seeing the data it affects. Choices made after seeing results are marked **[after]**; they are also listed in the phase documents. Nothing was tuned on a final test slice.
Per-phase detail lives in the phase documents; this is the one place to read all the choices in order.

## Scope and framing

| Decision | Why | Timing |
|---|---|---|
| Question: do buildings the complaint system cannot hear hide distress? | Every existing tool ranks buildings by recorded problems, which mix condition with who complains and who gets inspected | before |
| Bronx and Brooklyn, 2018 onward, residential lots with 3+ units | The set HPD regulates; the two boroughs with the most complaint volume; keeps the pull to hours not days | before |
| The hypothesis is allowed to fail, and the write-ups lead with the failure | A confirmation-seeking write-up would be easy here: the map is attractive and the gap layer looks like a finding | before |
| During the build: local folder only, nothing published. Throughout: no owner names, no building-level scores in anything meant for git (other than the one-district map sample) | Project owner's limits; the map and reports are for research, not for judging owners or tenants | before |

## Phase 1: data

| Decision | Why | Timing |
|---|---|---|
| Socrata keyset paging on `:id` with `$select=:*,*`, Parquet parts and a `.cursor` sidecar | Offset paging breaks on live-edited tables; keyset is resumable and gap-free | before |
| BBL join: the source's stored `bbl` first, else built from borough, block, lot | The stored one handles condo billing lots; the two differ in 0.42% of violation rows | **[after]** measured in the audit |
| Complaint text "not able to gain access" read as a censoring signal | 15.7% of problem rows (16.7% of distinct complaints), higher in Brooklyn than the Bronx; the seed of the censoring idea | before (hypothesis), measured in the audit |
| Nested values (building footprint geometry) are JSON-serialised before string conversion | The first footprint pull stored Python `repr`; fixed in the puller with a regression test | **[after]** a bug found in Phase 6 |

## Phase 2: spine, features, labels

| Decision | Why | Timing |
|---|---|---|
| Quarter-bucket convention (an event on a snapshot date belongs to the bucket that ends there) | One rule that makes "feature window" and "label window" disjoint by construction | before |
| A window that reaches before a source's first date is NULL, not 0 | "No events" and "not observed" must not look alike | before |
| No-access features use the **closure** date, never the receipt date | The outcome text is only known when a problem closes; the receipt date leaks the future | before |
| Excluded PLUTO assessed value, exemptions, owner fields, `yearalter` | PLUTO is a current-state release; at a 2019 snapshot they would show 2026 values | before |
| Registrations and contacts not used as features | Same reason: a registration today says nothing about t | before |
| Last snapshot 2025-10-01 | The latest whose 12-month label window ends inside the data | before |
| Spine chosen with today's PLUTO, accepted as an approximation | Historical PLUTO releases are not on Socrata; documented risk | before |
| Tests: synthetic fixture with hand-placed edge dates, a brute-force pandas oracle that must match the SQL on every column, mutation checks | Leakage is the failure mode that makes every later number meaningless | before |

## Phase 3: baselines and models

| Decision | Why | Timing |
|---|---|---|
| Strict temporal walk-forward folds with a 12 month purge gap; final test slice is the last four snapshots, scored once | Random splits leak across time; the label looks 12 months ahead, so training labels must have ended before the evaluation snapshot | before |
| Baseline is the plain rule "violations in the last 12 months" (plus two other rules) | If a model cannot beat it, the model is not worth shipping | before |
| Cluster bootstrap by building | Rows from the same building are not independent | before |
| Added the `quiet` slice and the LightGBM-vs-logistic paired comparison, and a rarer `vacate_or_aep` label | Added after the first results showed where the rule was strong; none changes any fitted model | **[after]** disclosed in the Phase 3 doc |
| Community-district hold-out (five groups of six) | Tests generalisation to places the model has not seen | before |
| No recalibration | ECE 0.006 already; mean prediction slightly high because the test base rate is lower | before |

## Phase 4: silent distress

| Decision | Why | Timing |
|---|---|---|
| Condition model on `static_*` + `prior_*` only, with a test and an assertion that no complaint feature can enter | The point is a condition score that does not depend on who complains | before |
| Silent = top decile of (within-borough percentile of predicted condition minus within-borough percentile of shrunk complaint rate) | A gap definition with a fixed 10% size cannot be tuned to find an effect | before |
| Second silent definition: negative-binomial residual lower tail | A different construction, so the result is not an artefact of one definition | before |
| Complaint rate shrunk with a Poisson-gamma (empirical Bayes) model by marginal likelihood within snapshot x borough x size | Small buildings with zero complaints should not look "quieter" than large ones by chance | before |
| Primary outcome switched from the wide to the **core** DOB-hazard definition | The wide rate swings between 0.24% and 2.1% across snapshots (batch issuance of one code); chose on event-rate stability and calibration before any gap result existed | **[after]** event rates, before gaps |
| Finer-matching and covariate-adjusted comparisons added | The balance table showed silent buildings still larger inside the pre-specified cells; both are reported next to the original | **[after]** outcome ratios were already visible |
| Rental-only and co-op/condo exclusion checks | Co-op and condo owners do not file HPD tenant complaints | **[after]** composition only, no outcomes |
| Access-blocked = at least 3 closed problems and at least half closed for no access | Cutoff chosen from the distribution of the share (median 0.11, 90th percentile 0.47) | before outcomes |
| Placebo: shuffle the silent flag inside matching cells (200 shuffles) | Shows the ratio is not produced by the matching procedure itself (placebo ratio 1.00) | before |
| Verdict wording led with the failure of the strong hypothesis | See Scope | before |
| PyMC hierarchical model **not** run | The two-stage models answer the question; it would change the uncertainty of district effects, not the verdict | **[after]** time-boxed |

## Phase 5: sales

| Decision | Why | Timing |
|---|---|---|
| Feasibility spike with a stated rule (source recent volume at least 60% of an independent count, and at least 800 matched arms-length sales with a full window) | So the study only runs if the data can support it, and the rule was not bent after the fact | before |
| ACRIS Master open-data extract abandoned (8% coverage); DOF annualized sales used | Fails the rule; DOF is complete 2016-2025 and has no party names | **[after]** the spike result |
| Whole-building sales only (four categories, no apartment number, price at least $100k and $25k per unit) | The first count (117k) included condo, parking and co-op rows; those are not building ownership changes. Fixed before any outcome was looked at | **[after]** the first count, before outcomes |
| Own staggered event study (Callaway and Sant'Anna style), controls reweighted to the treated stratum mix, cluster bootstrap, pre-trend Wald test, linear pre-trend extrapolation as the sensitivity | No package install needed; documented simpler alternative to HonestDiD; verified by simulation tests (known effect, null, injected pre-trend, composition bias) | before |
| Primary specification declared in the script header; two robustness controls | So the headline cannot be picked from the three after the fact | before |
| Silent split only for sales from 2022Q2 and the 2022-01-01 snapshot flag | The Phase 4 scores are out-of-time only from 2022 | forced by the data |
| No owner or buyer names read or written | Privacy; entity-level aggregates were an option but not needed | before |

## Phase 6: map

| Decision | Why | Timing |
|---|---|---|
| Static site: MapLibre GL JS 4.7.1 and PMTiles 3.2.0, vendored and pinned, no basemap, no external requests | Works offline, reproducible, nothing to host | before |
| Default view is 30 district averages; building detail from zoom 12 to 13.4 | The first thing a viewer sees should not be a building-by-building scorecard | before |
| Neutral layer names, a disclaimer on first load and in the footer, an "i" help text per layer | The gap layer must not read as "neglected" | before |
| Score series packed as 16 three-digit numbers per building | Moving the slider slices a string instead of reloading data | before |
| A one-district sample is committed as a fallback | The page works without the 93 MB tile file. **Flag:** it holds per-building model scores for one district; see `PUBLISH_CHECKLIST.md` | before |

## Phase 7: LLM layer

| Decision | Why | Timing |
|---|---|---|
| Text-to-SQL over DuckDB marts rather than RAG | The data is structured; retrieval is the wrong tool for counts and joins | before |
| Read-only sandbox in layers (read-only file, external access off and locked, DuckDB parses exactly one SELECT, deny list, row/memory/time caps) | A model-written query must not read files or change anything | before |
| Biography verifier is code, not a model; no-blame language rule; owner-worded records excluded from evidence | A fluent paragraph is not evidence; no claims about owners | before |
| Two RAG gates with fixed adoption rules | Adopt retrieval only where it beats a plain SQL baseline | before |
| Both gates failed; RAG is not used | E1: SQL keywords 0.668 vs BM25 0.526 precision@10; E2: +0.001 PR-AUC | measured |
| No live model run | No API key configured; live numbers are marked pending everywhere | constraint |

## Tooling decisions

- DuckDB over Parquet for all heavy joins (a feature build of about 10 s on 14M rows); no cluster.
- Tests use synthetic fixtures and an oracle, so they need no real data (`make test`, 170 tests).
- No git commands are run by the project's pipelines; `pipelines/publish_check.py` approximates `.gitignore` with `pathspec` and runs nothing external.
- Port 8777 for the map server, because 8765 was in use by an unrelated process that was left alone.

## Deferred or not done (and why)

- **Live LLM evaluation** (needs a key): `make llm-live`.
- **ACS / demographic data** (out of scope): whether silent areas differ by income or language is the obvious next question, and nothing here answers it.
- **PyMC hierarchical model**, **embedding-based retrieval**, **Housing Maintenance Code retrieval**: not needed for any verdict.
- **Owner portfolio analysis** (needs a complete ACRIS extract and entity resolution with care about naming individuals).
- **Heterogeneity of the sale effect by buyer type** (same reason).
