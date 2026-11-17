# The buildings NYC can't hear: testing "silent distress" in complaint-driven housing enforcement

Output format: Markdown, paper style. All numbers are produced by the code in this repository and can be traced to `reports/` (CSV, JSON, figures); 95% intervals are cluster bootstraps by building unless stated.
Phase documents hold the detail: `docs/{data_audit,labels_and_features,modeling_phase3,silent_distress_phase4,sales_phase5,map,llm_layer}.md`. Choices and their timing: `docs/METHODOLOGY_LOG.md`.

## Abstract

New York City's housing enforcement learns about bad buildings mostly from tenant complaints. If complaints are the sensor, a building whose sensor is silent could be hiding trouble. We built a building-quarter panel for 101,442 Bronx and Brooklyn residential lots (3+ units, 2.8M building-snapshots, 82 as-of features) from 12 NYC Open Data tables and tested that idea in four steps.
(1) A LightGBM model predicts a city enforcement event in the next 12 months better than the obvious rule "violations in the last year" at every one of 16 out-of-time snapshots (final test slice PR-AUC 0.645 vs 0.558; paired difference +0.087, CI 0.083 to 0.090), but the label is partly circular with violation history.
(2) A condition model that never sees complaint information was used to flag buildings whose predicted condition is bad but whose complaint record is empty. **These silent buildings are not riskier than predicted**: observed/predicted 0.84 [0.76, 0.91] on the least tenant-driven outcome, and 35% fewer events than matched louder buildings (relative risk 0.65 [0.59, 0.74]; 0.79 [0.70, 0.89] after covariate adjustment).
(3) The mechanism the hypothesis rested on is real, about 16% of closed complaint problems end with "inspector not able to gain access", but access-blocked buildings show no hidden extra risk (0.84 [0.68, 0.99]). A weaker form survives: among buildings with no complaint in the prior year, predicted condition still predicts next-year complaints (IRR 1.70 per SD [1.65, 1.76]).
(4) A staggered event study of 8,500 whole-building sales finds a modest rise in recorded violations (+1.5 percentage points on a 21% base) and complaints (+1.6 on 10%) after a sale, no detectable change in serious events (+0.3 [-0.1, +0.7]), and no detectable difference for silent buildings (453 buildings, wide intervals); complaints were already drifting upward before sales, so the result is not cleanly causal.
**Mostly, silence reflects ordinary risk.** We also built a 3D map and an offline LLM layer; retrieval (RAG) lost both pre-declared gates and is not used.

## 1. Question and why it is hard

**Question.** Which buildings are probably in serious trouble but are not generating complaints, and does the absence of complaints hide danger?

Recorded problems (complaints, violations, litigation) mix three things: real condition, the propensity to report, and the chance of being inspected. The problem is therefore one of selectively observed outcomes. Two further traps shape the design:
(a) enforcement is rule driven off violation counts (AEP selects by open class B and C violations; emergency repairs follow uncorrected hazardous violations), so a violation count predicts most city-side outcomes almost by construction; (b) the outcomes that could validate a "silent" flag are mostly downstream of a complaint, so a silent building will have fewer of them even if its physical problems are the same.
We designed around both: the condition model excludes complaint-derived features by test and assertion, and the validation separates tenant-driven from less tenant-driven outcomes and reports both.

Adjacent tools (JustFix Who Owns What, ANHD Displacement Alert Project, HPD watch lists) and published work on 311 reporting bias are listed in `docs/PROJECT_PLAN.md` from a title-and-abstract skim; they were not read in full and should be verified before being cited.

## 2. Data

Twelve tables from data.cityofnewyork.us, pulled with a resumable keyset-paged client to Parquet (13.9M rows; Bronx and Brooklyn, 2018 onward; PLUTO lots; building footprints for the map; DOF sales for the sale study):
HPD violations (4.7M rows), HPD complaints and problems (4.1M), 311 HPD requests (2.9M, from 2020), evictions, HPD litigations, emergency repair (OMO) charges, vacate orders, AEP selections, registrations and contacts, DOB violations, PLUTO. Join key: the 10-digit BBL.
Audit findings (`docs/data_audit.md`): keys are clean (duplicates only in registrations, contacts and AEP); 99.6% of violation and complaint BBLs join to PLUTO (the three citywide tables match 60 to 78% because they include other boroughs); some date columns contain impossible values (year 9202, 2040) that are filtered by stated rules.
**15.7% of HPD problem rows (16.7% of distinct complaints) are closed as "inspector not able to gain access"**; 13.9% in the Bronx and 17.7% in Brooklyn.
HPD violation descriptions are mostly unique (50.7% distinct after normalising), DOB descriptions are heavily templated.

## 3. Methods

### 3.1 Panel, features and labels
Unit: building lot x quarterly snapshot, 28 snapshots from 2019-01-01 to 2025-10-01. Spine: PLUTO lots in the Bronx or Brooklyn with 3+ residential units and land use 2, 3 or 4 (101,749 lots).
Features (82) see only what was known at the snapshot. Every event date is assigned to the quarter bucket ending at or after it, so feature windows `(t - w, t]` and label windows `(t, t + 12 months]` never share a bucket. A window reaching before a source's first date is NULL, not 0. The "no access" features key on the **closure** date, because the outcome text is only known when a problem closes.
Labels: vacate order, OMO charge, AEP selection, new litigation, their union ("any serious event"), plus a rarer vacate-or-AEP label and, for Phase 4, DOB physical-hazard violations.
Leakage is guarded by an as-of invariance test, a window test, a brute-force pandas oracle that must equal the SQL on every column, and mutation checks (deliberately breaking the SQL must fail the tests). The oracle found 0 mismatches on real buildings and the label identities held on 2.4M snapshot pairs.

### 3.2 Prediction (Phase 3)
Logistic regression and LightGBM, strictly temporal walk-forward folds with a 12 month purge gap (fold ends 8, 12, 16, 20 of 28 snapshots), and a final test slice (the last four snapshots) scored once. Baselines: violations in the last 12 months, complaints in the last 12 months, most recent earlier event. Metrics: PR-AUC, ROC-AUC, precision at the top 1% and 5%, calibration (ECE, Brier). SHAP via LightGBM contributions. A community-district hold-out repeats the fit with five groups of six districts left out.

### 3.3 Silent distress (Phase 4)
A LightGBM **condition model on static and earlier-city-event features only** (never violations or complaints) produces an out-of-time probability `p_hat` for 16 snapshots. Loudness is the complaint rate per unit, shrunk with a Poisson-gamma (empirical Bayes) model. **Silent** = top decile of the within-borough percentile of `p_hat` minus the within-borough percentile of loudness (10% by construction); a second definition uses the lower tail of a negative-binomial model.
Primary outcome: a vacate order or a core DOB physical-hazard violation (codes IMEGNCY, UB, FISPHAZ, EGNCY) in the next 12 months. Validation: (i) calibration within groups (observed/predicted, level corrected), (ii) coarsened exact matching with ATT weights on predicted condition, borough, size and year built, plus a covariate-adjusted Poisson with robust errors, (iii) later complaint volume, (iv) access-blocked buildings (at least 3 closed problems, at least half closed for no access), (v) heterogeneity, (vi) a placebo that shuffles the flag inside matching cells.

### 3.4 Sales (Phase 5)
Treated: first arms-length whole-building sale (DOF annualized sales; four building categories; no apartment number; price at least $100,000 and $25,000 per unit) in 2020Q1 to 2024Q3 with 8 quarters before and after and no other sale in the window (8,500 buildings). Controls: 70,157 buildings with no whole-building sale row at all. Estimator: staggered-adoption event study (Callaway and Sant'Anna style, implemented here and tested by simulation) with never-treated controls reweighted to the treated mix of borough, size, era and 2018-19 violation level, cluster bootstrap (400 draws), a joint pre-trend test, and a linear pre-trend extrapolation as sensitivity. Outcomes: any violation, class C violation, complaint problem, serious event; counts winsorized at the 99.5th percentile. The ACRIS deed extract was abandoned after a pre-declared coverage rule failed (it holds about 8% of recent deeds).

### 3.5 Map and LLM layer (Phases 6 and 7)
A static MapLibre/PMTiles site shows 120,705 footprints at real heights with five neutral layers, a snapshot slider, filters and a disclaimer; the default view is district averages. The LLM layer is a read-only DuckDB sandbox for text-to-SQL (58 gold questions), building biographies with record-id citations and a code verifier, and two pre-declared RAG gates.

## 4. Results

### 4.1 Prediction beats the obvious rule, modestly (Phase 3)
Final test slice, any serious event (base rate 8.5%):

| model | ROC-AUC | PR-AUC | precision top 5% |
|---|---|---|---|
| violations in last 12m (rule) | 0.863 [0.860, 0.867] | 0.558 [0.550, 0.567] | 68.6% |
| logistic regression | 0.925 [0.923, 0.928] | 0.630 [0.622, 0.639] | 71.8% |
| LightGBM | 0.928 [0.926, 0.931] | 0.645 [0.638, 0.653] | 72.7% |

LightGBM beats the rule at all 16 out-of-time snapshots (PR-AUC gap 0.083 to 0.110) and logistic regression gets most of the gain; LightGBM adds +0.015 [0.013, 0.018]. Removing complaint features costs 0.006 PR-AUC, removing violation features 0.022, removing both still leaves 0.578 (+0.020 over the rule, [0.015, 0.026]); the groups substitute for each other.
Among buildings the rule would not flag (`quiet`: no class C violation, at most 2 violations; 82% of rows) the rule has ROC-AUC 0.53 and the model 0.83. Probabilities are well calibrated (ECE 0.006, Brier 0.046) and slightly high. Holding out whole community districts leaves ROC-AUC unchanged (0.933).
**This is a prediction of city enforcement events, not of physical condition**, and a high score mostly means the city is already engaged.

### 4.2 Silent buildings are not riskier than predicted (Phase 4)
The silent group is about 10% of building-snapshots (161,546 of 1,614,360) and carries 949 of 8,945 primary events (10.6%), its fair share.

| comparison (primary outcome) | estimate [95% CI] |
|---|---|
| observed / predicted events, silent group (level corrected) | 0.84 [0.76, 0.91] |
| relative risk vs matched not-silent buildings | 0.65 [0.59, 0.74] |
| same, covariate-adjusted | 0.79 [0.70, 0.89] |
| same, flag shuffled inside matching cells (placebo) | 1.00 [0.93, 1.07] |
| same, 311 instead of HPD complaints | 0.68 |
| same, rental buildings only | 0.65 |
| same, residual-based silent definition | 0.75 (observed/predicted 0.71 [0.63, 0.79]) |

Folds give 0.77, 0.65, 0.54, 0.64. For outcomes that begin with a tenant complaint (emergency repairs, litigation, AEP) the relative risks are 0.25 to 0.36, **which is largely mechanical**: those events are rare where nobody complains. The primary outcome is the least tenant-driven available and still sits below 1, but it is not independent of the reporting system, so it cannot fully separate "complaints reveal real condition" from "complaints trigger the enforcement that defines the outcome".

### 4.3 The access-blocked mechanism is real and shows no hidden risk
At least 3 closed problems and at least half closed for no access (9.8% of eligible buildings). Against matched buildings with similar complaint histories and better access: later primary events 0.84 [0.68, 0.99], later violations 0.81, later complaints 0.91. When a closure stops a violation from being written, fewer violations is also what the chain predicts. No evidence of hidden high risk.

### 4.4 A weaker form of the hypothesis survives
Among buildings with **no complaint at all** in the prior year (311,335 rows in the test slice), a +1 SD higher predicted condition predicts more next-year complaints: IRR 1.70 [1.65, 1.76], controlling for size and community district. Silent buildings' complaint rate rises from about 0 to 0.12 problems per unit over the next year, but compared with matched buildings with the same prior complaint level they are **not** louder later (0.96 [0.87, 1.05]): the rise is what regression to the mean predicts. Suppression and noise cannot be told apart here.

### 4.5 What happens after a sale (Phase 5)
Primary specification, change in the share of building-quarters with the event, averaged over 8 post-sale quarters (the treated buildings' pre-sale mean is in parentheses):

| outcome | avg post effect [95% CI] | after removing the linear pre-trend [95% CI] | pre-trend p |
|---|---|---|---|
| any HPD violation (21%) | +0.0153 [+0.0082, +0.0231] | +0.0142 [+0.0057, +0.0228] | 0.11 |
| any class C violation (5.9%) | +0.0091 [+0.0049, +0.0141] | +0.0062 [-0.0003, +0.0133] | 0.019 |
| any complaint problem (10%) | +0.0161 [+0.0102, +0.0212] | +0.0113 [+0.0032, +0.0182] | 0.14 |
| any serious event (3.3%) | +0.0033 [-0.0008, +0.0071] | -0.0002 [-0.0049, +0.0049] | 0.41 |

The effects are the same size with unweighted never-sold controls and with not-yet-sold controls. Silent buildings (453 treated vs 7,016 controls) do not respond detectably differently from the rest (4,027 treated): silent minus not-silent for any violation -2.0 points [-5.7, +1.6], for any serious event +0.9 points [-0.5, +2.2].

### 4.6 Map and LLM layer
The map was verified in a browser (tiles over Range requests, layers, slider, filters, click panel, dark mode, sample fallback, no console errors). The offline harness checks (not model results): the oracle stub scores 1.000 on 58 questions, an always-`SELECT 1` stub 0.000 and a crude keyword stub 0.034, the biography verifier catches 40 of 40 corrupted numbers and 40 of 40 invented ids. Gate E1 (retrieval over violation text): SQL keywords 0.668 vs BM25 0.526 precision@10, difference -0.141 [-0.149, -0.133]. Gate E2 (text-derived features): +0.001 PR-AUC [0.0005, 0.0016], 2 of 4 folds positive, against a +0.005 threshold. Neither is adopted. No live model was run; live accuracy is pending.

## 5. Limitations

1. **Prediction targets city actions, not condition.** A model that predicts where HPD will act is not a model of hidden physical decay.
2. **Circularity.** Enforcement is driven by violation counts; this is why the baseline rule is strong and why the silent-validation outcomes are partly downstream of complaints.
3. **The silent flag depends on a model** with ROC-AUC 0.80 to 0.85 and PR-AUC 0.03 to 0.05 against a 0.55% base rate: informative, far from precise. `prior_*` events are themselves downstream of old complaints, so the condition score is not fully independent of tenants.
4. **Silence is the norm** (77% of building-snapshots have no complaint in a year); "silent" is defined by a gap, and the silent group is mostly large (30 units vs 11) professionally managed buildings.
5. **Residual imbalance after matching** (standardised difference 0.19 to 0.21 on size) probably biases the ratio toward 1, so the estimates are if anything conservative; this is not proven.
6. **The sale study is observational.** Sale timing is not random, pre-sale complaints and class C violations drift upward, only deed-type sales are visible (LLC interest transfers are not), there is no buyer information, and recorded activity after a sale can mean more active management as well as more trouble. The silent subgroup is small.
7. **Inherited approximations:** the spine uses today's PLUTO; open-violation counts are approximate and undercounted before 2018; static fields are current-state; source tables are edited in place; the AEP table ends in early 2026.
8. **No demographic data** were used; nothing here says whether silent areas differ by income or language.
9. **LLM layer:** no live model was run; the gold set was written by the same author as the schema docs; E1 favours SQL because the keyword lists were written with knowledge of the corpus.
10. **Intervals** condition on the fitted models (the bootstrap resamples buildings, not training runs) and do not cover temporal drift beyond the folds shown.

## 6. Ethics and fairness

- **Not a verdict on any owner or tenant.** Scores are model estimates for research. They must not be used to prioritise or deprioritise inspections without a separate fairness review: borough and building class are strong static features and carry a 2.8x difference in base rates.
- **Who is "silent"** is 10% of every borough by construction; across community districts the share ranges from 2.5% to 16.8%, and the residual flag is three times as common in the Bronx (5.1%) as in Brooklyn (1.7%). Reading silent as "disadvantaged" or "neglected" is not supported by the evidence here.
- **Privacy.** No owner, buyer or tenant names appear in any output. The marts exclude litigation respondents, eviction marshals and registration contacts. Per-building scores and tiles are gitignored (see the publication note in `docs/PUBLISH_CHECKLIST.md` about the committed one-district sample). The biography generator refuses blame language and excludes owner-worded records.
- **Honest reporting.** The strong hypothesis failed; the write-ups lead with that. Choices made after seeing data are listed in `docs/METHODOLOGY_LOG.md` and in each phase document.

## 7. Reproducibility

`make setup ingest features model evaluate silent report4 marts sales map test` rebuilds everything from the public sources (a full pull takes hours, the models about 40 minutes, Phase 4 about 17 minutes, the sale study about a minute). `make notebooks` re-executes the seven narrative notebooks from committed outputs only. 170 tests run on synthetic fixtures with no real data. Dataset verification log: `docs/DATASETS.md`.
