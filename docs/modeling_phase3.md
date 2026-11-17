# Phase 3: validated baseline models

Output format of this document: Markdown. The tables under "Results" are generated from `reports/phase3/*.csv`
by `make report`; the text around them is hand written. Everything below was produced by the code in this
repository (`src/nycdistress/{splits,modeling,evaluation}.py`, `pipelines/{train,evaluate,shap,report}_phase3.py`).

## 1. The short, honest read

- **A fitted model beats the naive rule, clearly, out of time.** On the final test slice (the last four snapshots,
  2025-01-01 to 2025-10-01, scored once) LightGBM with all features reaches PR-AUC 0.645 against 0.558 for "number of HPD
  violations in the prior 12 months" (paired difference +0.087, 95% CI [0.083, 0.090]) and ROC-AUC 0.928 against 0.863. It wins at
  **all 16** out-of-time evaluation snapshots across three walk-forward folds plus the test slice (gap 0.083 to 0.110 PR-AUC, mean 0.095).
- **The gain is real but not dramatic at the very top of the ranking.** Precision in each snapshot's top 1% goes from 87.0% to 91.8%
  and in the top 5% from 68.6% to 72.7%. Most of the improvement is in ranking depth (AUC, PR-AUC), not in the handful of obvious
  buildings. The violation rule is a strong baseline because HPD enforcement is rule driven off violation counts (see section 6).
- **Most of the gain is available to a linear model.** Logistic regression gets PR-AUC 0.630 (+0.071 over the rule); LightGBM adds
  another +0.015 (paired 95% CI [0.013, 0.018]). Real, small.
- **Neither complaints nor violations is indispensable, because they substitute for each other.** Removing `loud_*` costs only 0.006
  PR-AUC; removing `viol_*` costs 0.022; removing both (static fields, evictions, DOB, earlier city/court events) still reaches PR-AUC 0.578,
  which is +0.020 over the rule (CI [0.015, 0.026]) but not better on every metric (precision at the top 5% is 67.1% vs 68.6%, and it is
  ahead of the rule on that metric in only 7 of 16 snapshots). SHAP shares (complaints 40%, violations 24%) overstate what each group
  uniquely adds, because the two are correlated and SHAP splits credit between them. The ablations are the cleaner evidence.
- **The model finds events the violation rule cannot see, but less than the first slice suggests.** Among buildings with no class C
  violation and at most 2 violations in the prior 12 months (`quiet`, 82% of rows, 2.1% event rate) the rule is useless (ROC-AUC 0.53)
  and the model has ROC-AUC 0.83 and PR-AUC 0.138. But `quiet` still contains buildings with a large backlog of old open violations (one
  SHAP example has 546). In the stricter `clean_record` slice (no violation, no open violation, no complaint, and no earlier city or court
  event; 116,195 rows, 0.68% event rate) the model's ROC-AUC is 0.755 and PR-AUC 0.033, about 5 times the base rate, and it comes mostly from static
  building attributes (class, borough, age, size) plus evictions, DOB history and older (beyond 12 month) records; the model trained without any violation, complaint or earlier-event
  feature does about as well there (ROC-AUC 0.741). That is the honest size of "signal without any record".
- **Probabilities are well calibrated** (ECE 0.006, Brier 0.046), slightly high: the mean prediction is 9.0% against an observed 8.5%, and
  the top decile predicts 0.61 against 0.56 observed. No recalibration was applied.
- **It generalises to places it has not seen.** Holding out whole community districts (five groups of six) in addition to the time gap leaves the
  score unchanged (ROC-AUC 0.933 both ways; PR-AUC 0.659 with districts held out against 0.660 without).
- **What it does not show:** it predicts city *enforcement events*, not physical condition, and a high score mostly means the city is
  already heavily engaged with the building. It is not evidence of "silent distress" by itself; that needs Phase 4 (condition model
  without complaint features compared with observed complaints).

## 2. Design

**Data.** `data/processed/features.parquet` and `labels.parquet` from Phase 2: 2,809,580 rows of (bbl, snapshot_date), 28 quarterly
snapshots 2019-01-01 to 2025-10-01, Bronx and Brooklyn residential lots with 3+ units, 82 as-of features.

**Targets.** Primary `label_serious_any` (any vacate order, AEP selection, OMO emergency repair charge or new HPD litigation in the
next 12 months). Also modelled separately: `label_omo`, `label_litigation`, and `label_vacate_or_aep` (the rare, harder pair requested as an
extra; vacate and AEP alone are too rare to model, so they are only reported descriptively from the any-event score).

**Strictly temporal validation with a purge gap.** A row at snapshot t has a label over (t, t + 12 months]. A training row is only usable
if its label window has ended before validation starts: t + 12 months <= first validation snapshot. So there are always three snapshots
(12 months) dropped between the last training snapshot and the first validation snapshot. Walk-forward folds with an expanding window:

| fold | trained on snapshots up to | dropped | evaluated on |
|---|---|---|---|
| fold1 | 2021-01-01 | 2021-04 to 2021-10 | 2022-01-01 to 2022-10-01 |
| fold2 | 2022-01-01 | 2022-04 to 2022-10 | 2023-01-01 to 2023-10-01 |
| fold3 | 2023-01-01 | 2023-04 to 2023-10 | 2024-01-01 to 2024-10-01 |
| **test** | 2024-01-01 | 2024-04 to 2024-10 | **2025-01-01 to 2025-10-01 (the last four usable snapshots, scored once)** |

Never a random split. Inside each fold, LightGBM early-stops on the four most recent training quarters, with another 12 month purge
between its own inner training slice and that early-stopping slice; it is then refit on the whole training window with 1.1 x the best
iteration count. `tests/test_splits.py` checks with real date arithmetic that no training row's label window overlaps validation, that the gap
is exactly 12 months, that the test slice is the last four snapshots, and that a leaky split is rejected.

**Models.** (1) Baselines with nothing to fit: violations in the prior 12 months (`viol_n_12m`), complaint problems in the prior 12 months
(`loud_prob_n_12m`), and "most recent earlier event" (the inverse of months since the latest earlier litigation, OMO, vacate or AEP event).
(2) Logistic regression (L2, C = 1, lbfgs) on log-transformed, imputed and standardised features with explicit missing indicators.
(3) LightGBM (learning rate 0.05, 63 leaves, min 200 rows per leaf, 80% feature and row subsampling, L2 5, up to 2,000 rounds, patience 100).
Hyperparameters were fixed in advance, not tuned on any evaluation slice. The only change was before the full run: after a one-off smoke
test on fold1 (not the test slice) the learning rate went from 0.08 to 0.05 and the patience from 50 to 100. Models train on every row (no negative subsampling).

**Feature sets (ablations).** `all` (82 features); `no_viol` (drops `viol_*`, 66); `no_loud` (drops `loud_*`, 47); `static_prior`
(drops both: static PLUTO fields, evictions, DOB violations, earlier city/court events; 31). `static_prior` is what the Phase 4 condition model may see.

**NULL windows are explicit, never silently zero-filled.** Features whose window starts before a source's first covered date are NULL
(Phase 2): all 36 month windows in 2019 and 2020, 311 windows until 2021 and 2023. LightGBM receives NaN and learns a missing direction. Logistic
regression gets a 0/1 `isnull_<column>` indicator for every column with NULLs in the training rows, then the median of the non-null training
values (all statistics from training rows only; checked in `tests/test_modeling.py`). In fold1 every 36 month column is NULL in all training
rows, so no model can learn from them there; they are constant for the logistic model and never used by LightGBM.

**Evaluation.** ROC-AUC, PR-AUC (average precision), precision, recall and lift at the top 1% and 5% of buildings *within each snapshot*
(pooled over the four snapshots) and at the top 500, 1,000 and 2,500 buildings per snapshot (in `metrics_*.csv`), Brier score and expected
calibration error (10 equal-mass bins), a 10-bin calibration table, per-snapshot and per-borough breakdowns. **Confidence intervals are a
cluster bootstrap by building** (200 resamples of buildings with replacement, so a building's four snapshots move together; the same resamples
are applied to every model, so differences between models are paired). They measure sampling variation across buildings, not variation from retraining.
The weighted metrics behind the bootstrap are tested against scikit-learn and against repeating rows (`tests/test_evaluation.py`; the tests found and fixed a real NaN bug in
zero-weight tie groups before it reached any result).

**Borough and "quiet" slices.** Bronx and Brooklyn are reported separately (base rates differ 2.8x). Because the violation rule is so strong overall,
three slices look at buildings it cannot rank: `quiet` (no class C violation and at most 2 violations in the prior 12 months), `zero_viol` (no violation at all in 12
months) and `clean_record` (nothing on record). Disclosure: the `quiet` and `zero_viol` thresholds were chosen after looking at how many rows and events each threshold
keeps in the test slice (not at any model's performance); `clean_record` was added after a SHAP example showed `quiet` still includes large backlogs.

**Spatial block check.** On fold3, LightGBM (all features) is trained and early-stopped five times, each time without any row from a group of six community districts
(30 districts, balanced by row count), and scored only on the held-out districts in the evaluation slice, so both time and place are unseen.

**SHAP.** Exact TreeSHAP (LightGBM `pred_contrib`, log-odds scale) on a random 100,000 of the 405,768 test rows, with feature-group rollups
(features are summed inside a group before taking the absolute value) and four example buildings from the latest snapshot.

## 3. Results

<!-- BEGIN GENERATED -->

### Headline: final test slice, any serious event

Train on snapshots up to 2024-01-01, score the last four snapshots (2025-01-01 to 2025-10-01), touched once. Base rate 8.5%. 95% intervals are cluster bootstraps by building (200 resamples, the same resamples for every model, so the difference column is paired). Precision at top 1% / 5% is measured inside each snapshot and pooled.

| model | ROC-AUC | PR-AUC | precision top 1% | precision top 5% | lift top 5% | PR-AUC minus violation rule | Brier / ECE |
|---|---|---|---|---|---|---|---|
| rule: violations in last 12m | 0.863 [0.860, 0.867] | 0.558 [0.550, 0.567] | 87.0% [85.6%, 88.4%] | 68.6% [67.6%, 69.4%] | 8.11x | (reference) | - |
| rule: complaints in last 12m | 0.883 [0.880, 0.886] | 0.552 [0.543, 0.562] | 83.6% [82.3%, 85.1%] | 66.9% [66.0%, 67.9%] | 7.92x | -0.006 [-0.012, -0.001] | - |
| rule: most recent earlier event | 0.860 [0.857, 0.864] | 0.454 [0.446, 0.464] | 69.9% [68.6%, 71.2%] | 58.5% [57.7%, 59.5%] | 6.92x | -0.104 [-0.111, -0.098] | - |
| logistic (all features) | 0.925 [0.923, 0.928] | 0.630 [0.622, 0.639] | 89.3% [88.2%, 90.6%] | 71.8% [71.0%, 72.6%] | 8.49x | 0.071 [0.068, 0.075] | 0.0471 / 0.0085 |
| logistic (without viol_*) | 0.921 [0.919, 0.923] | 0.608 [0.601, 0.618] | 87.8% [86.4%, 89.1%] | 70.0% [69.2%, 70.9%] | 8.28x | 0.050 [0.047, 0.054] | 0.0485 / 0.0089 |
| logistic (without loud_*) | 0.919 [0.916, 0.922] | 0.621 [0.614, 0.630] | 89.0% [87.9%, 90.2%] | 71.5% [70.8%, 72.3%] | 8.46x | 0.063 [0.060, 0.066] | 0.0480 / 0.0110 |
| logistic (static + prior only) | 0.899 [0.896, 0.902] | 0.567 [0.558, 0.576] | 86.4% [85.0%, 87.6%] | 66.5% [65.6%, 67.6%] | 7.86x | 0.008 [0.003, 0.013] | 0.0518 / 0.0093 |
| LightGBM (all features) | 0.928 [0.926, 0.931] | 0.645 [0.638, 0.653] | 91.8% [90.8%, 92.9%] | 72.7% [71.9%, 73.5%] | 8.59x | 0.087 [0.083, 0.090] | 0.0461 / 0.0058 |
| LightGBM (without viol_*) | 0.923 [0.921, 0.926] | 0.623 [0.615, 0.631] | 90.7% [89.4%, 91.8%] | 70.6% [69.9%, 71.4%] | 8.35x | 0.064 [0.061, 0.069] | 0.0477 / 0.0045 |
| LightGBM (without loud_*) | 0.923 [0.921, 0.926] | 0.639 [0.632, 0.647] | 91.6% [90.6%, 92.6%] | 72.2% [71.4%, 73.1%] | 8.54x | 0.081 [0.077, 0.084] | 0.0467 / 0.0088 |
| LightGBM (static + prior only) | 0.903 [0.900, 0.906] | 0.578 [0.570, 0.587] | 88.8% [87.6%, 89.9%] | 67.1% [66.2%, 68.0%] | 7.93x | 0.020 [0.015, 0.026] | 0.0510 / 0.0041 |

### Other targets (final test slice)

**OMO / emergency repair charge** (base rate 6.5%)

| model | ROC-AUC | PR-AUC | precision top 5% | lift top 5% | PR-AUC minus violation rule |
|---|---|---|---|---|---|
| rule: violations in last 12m | 0.874 [0.870, 0.879] | 0.475 [0.464, 0.485] | 55.7% [54.6%, 56.7%] | 8.60x | (reference) |
| logistic (all features) | 0.928 [0.925, 0.931] | 0.542 [0.533, 0.553] | 59.3% [58.3%, 60.3%] | 9.16x | 0.067 [0.063, 0.071] |
| LightGBM (all features) | 0.931 [0.929, 0.934] | 0.574 [0.566, 0.585] | 60.7% [59.8%, 61.6%] | 9.37x | 0.099 [0.095, 0.105] |
| LightGBM (without viol_*) | 0.924 [0.922, 0.927] | 0.539 [0.529, 0.549] | 57.6% [56.8%, 58.5%] | 8.90x | 0.064 [0.058, 0.070] |
| LightGBM (without loud_*) | 0.927 [0.924, 0.930] | 0.570 [0.561, 0.580] | 60.4% [59.6%, 61.3%] | 9.33x | 0.095 [0.091, 0.100] |
| LightGBM (static + prior only) | 0.903 [0.900, 0.906] | 0.498 [0.488, 0.509] | 54.8% [53.9%, 55.8%] | 8.46x | 0.023 [0.016, 0.029] |

**HPD litigation** (base rate 3.6%)

| model | ROC-AUC | PR-AUC | precision top 5% | lift top 5% | PR-AUC minus violation rule |
|---|---|---|---|---|---|
| rule: violations in last 12m | 0.862 [0.857, 0.868] | 0.354 [0.341, 0.367] | 35.3% [34.2%, 36.3%] | 9.91x | (reference) |
| logistic (all features) | 0.923 [0.920, 0.926] | 0.421 [0.406, 0.433] | 38.6% [37.5%, 39.6%] | 10.84x | 0.067 [0.060, 0.074] |
| LightGBM (all features) | 0.927 [0.923, 0.930] | 0.429 [0.415, 0.442] | 39.0% [37.9%, 40.0%] | 10.95x | 0.074 [0.068, 0.081] |
| LightGBM (without viol_*) | 0.926 [0.922, 0.929] | 0.423 [0.408, 0.434] | 38.7% [37.6%, 39.7%] | 10.86x | 0.069 [0.061, 0.076] |
| LightGBM (without loud_*) | 0.922 [0.918, 0.925] | 0.418 [0.404, 0.429] | 38.2% [37.2%, 39.3%] | 10.73x | 0.063 [0.057, 0.069] |
| LightGBM (static + prior only) | 0.910 [0.907, 0.914] | 0.389 [0.374, 0.401] | 36.2% [35.3%, 37.4%] | 10.16x | 0.034 [0.026, 0.043] |

**vacate order or AEP selection** (base rate 0.5%)

| model | ROC-AUC | PR-AUC | precision top 5% | lift top 5% | PR-AUC minus violation rule |
|---|---|---|---|---|---|
| rule: violations in last 12m | 0.840 [0.825, 0.856] | 0.091 [0.076, 0.106] | 5.8% [5.4%, 6.4%] | 10.85x | (reference) |
| logistic (all features) | 0.873 [0.859, 0.887] | 0.139 [0.117, 0.159] | 5.7% [5.2%, 6.2%] | 10.63x | 0.048 [0.034, 0.063] |
| LightGBM (all features) | 0.887 [0.876, 0.898] | 0.163 [0.139, 0.188] | 6.1% [5.6%, 6.5%] | 11.33x | 0.072 [0.054, 0.091] |
| LightGBM (without viol_*) | 0.884 [0.871, 0.896] | 0.153 [0.133, 0.172] | 5.9% [5.4%, 6.3%] | 10.91x | 0.062 [0.044, 0.078] |
| LightGBM (without loud_*) | 0.885 [0.872, 0.897] | 0.165 [0.139, 0.190] | 6.1% [5.6%, 6.6%] | 11.27x | 0.074 [0.054, 0.091] |
| LightGBM (static + prior only) | 0.876 [0.862, 0.889] | 0.150 [0.130, 0.173] | 5.8% [5.3%, 6.3%] | 10.78x | 0.059 [0.042, 0.076] |

### What each feature group contributes (LightGBM, final test slice)

`PR-AUC minus violation rule` is paired against the violations-in-the-last-12-months rule.

| target | LightGBM features | PR-AUC | minus violation rule |
|---|---|---|---|
| any serious event | all features | 0.645 [0.638, 0.653] | 0.087 [0.083, 0.090] |
| any serious event | without viol_* | 0.623 [0.615, 0.631] | 0.064 [0.061, 0.069] |
| any serious event | without loud_* | 0.639 [0.632, 0.647] | 0.081 [0.077, 0.084] |
| any serious event | static + prior only | 0.578 [0.570, 0.587] | 0.020 [0.015, 0.026] |
| OMO / emergency repair charge | all features | 0.574 [0.566, 0.585] | 0.099 [0.095, 0.105] |
| OMO / emergency repair charge | without viol_* | 0.539 [0.529, 0.549] | 0.064 [0.058, 0.070] |
| OMO / emergency repair charge | without loud_* | 0.570 [0.561, 0.580] | 0.095 [0.091, 0.100] |
| OMO / emergency repair charge | static + prior only | 0.498 [0.488, 0.509] | 0.023 [0.016, 0.029] |
| HPD litigation | all features | 0.429 [0.415, 0.442] | 0.074 [0.068, 0.081] |
| HPD litigation | without viol_* | 0.423 [0.408, 0.434] | 0.069 [0.061, 0.076] |
| HPD litigation | without loud_* | 0.418 [0.404, 0.429] | 0.063 [0.057, 0.069] |
| HPD litigation | static + prior only | 0.389 [0.374, 0.401] | 0.034 [0.026, 0.043] |
| vacate order or AEP selection | all features | 0.163 [0.139, 0.188] | 0.072 [0.054, 0.091] |
| vacate order or AEP selection | without viol_* | 0.153 [0.133, 0.172] | 0.062 [0.044, 0.078] |
| vacate order or AEP selection | without loud_* | 0.165 [0.139, 0.190] | 0.074 [0.054, 0.091] |
| vacate order or AEP selection | static + prior only | 0.150 [0.130, 0.173] | 0.059 [0.042, 0.076] |

### By borough (any serious event, final test slice)

| slice | rows / events | model | base rate | ROC-AUC | PR-AUC | precision top 5% | lift top 5% |
|---|---|---|---|---|---|---|---|
| bronx | 92,232 / 15,575 | rule: violations in last 12m | 16.9% | 0.874 [0.869, 0.879] | 0.668 [0.656, 0.681] | 84.6% [83.3%, 86.1%] | 5.01x |
| bronx | 92,232 / 15,575 | logistic (all features) | 16.9% | 0.915 [0.912, 0.920] | 0.717 [0.706, 0.729] | 87.2% [85.8%, 88.3%] | 5.16x |
| bronx | 92,232 / 15,575 | LightGBM (all features) | 16.9% | 0.919 [0.916, 0.923] | 0.734 [0.724, 0.745] | 88.4% [87.3%, 89.5%] | 5.23x |
| bronx | 92,232 / 15,575 | LightGBM (without viol_*) | 16.9% | 0.914 [0.911, 0.919] | 0.716 [0.704, 0.727] | 86.1% [84.7%, 87.3%] | 5.10x |
| bronx | 92,232 / 15,575 | LightGBM (without loud_*) | 16.9% | 0.916 [0.912, 0.920] | 0.730 [0.720, 0.741] | 88.2% [87.1%, 89.5%] | 5.22x |
| bronx | 92,232 / 15,575 | LightGBM (static + prior only) | 16.9% | 0.897 [0.892, 0.902] | 0.682 [0.670, 0.693] | 84.3% [82.7%, 85.5%] | 4.99x |
| brooklyn | 313,536 / 18,740 | rule: violations in last 12m | 6.0% | 0.840 [0.834, 0.845] | 0.461 [0.449, 0.472] | 54.5% [53.2%, 55.6%] | 9.11x |
| brooklyn | 313,536 / 18,740 | logistic (all features) | 6.0% | 0.918 [0.915, 0.921] | 0.548 [0.537, 0.560] | 58.2% [57.0%, 59.4%] | 9.73x |
| brooklyn | 313,536 / 18,740 | LightGBM (all features) | 6.0% | 0.921 [0.918, 0.924] | 0.564 [0.552, 0.575] | 59.3% [58.3%, 60.6%] | 9.92x |
| brooklyn | 313,536 / 18,740 | LightGBM (without viol_*) | 6.0% | 0.916 [0.913, 0.919] | 0.536 [0.523, 0.547] | 56.6% [55.5%, 57.8%] | 9.47x |
| brooklyn | 313,536 / 18,740 | LightGBM (without loud_*) | 6.0% | 0.915 [0.912, 0.919] | 0.556 [0.544, 0.567] | 58.8% [57.8%, 60.1%] | 9.84x |
| brooklyn | 313,536 / 18,740 | LightGBM (static + prior only) | 6.0% | 0.890 [0.886, 0.894] | 0.482 [0.468, 0.494] | 52.8% [51.5%, 54.0%] | 8.83x |

### Buildings the violation rule would not flag (any serious event, final test slice)

`quiet` = no class C violation and at most 2 violations in the prior 12 months; `zero_viol` = no violation at all in the prior 12 months; `clean_record` = nothing on record: no violation in 12 months, none still open, no complaint in 12 months, and no earlier OMO charge, litigation, vacate order or AEP selection (so only static fields can speak). `quiet` still includes buildings with a large backlog of OLD open violations, so it is not a clean test of silence; `clean_record` is.

| slice | rows / events | model | base rate | ROC-AUC | PR-AUC | precision top 5% | lift top 5% |
|---|---|---|---|---|---|---|---|
| quiet | 334,428 / 7,174 | rule: violations in last 12m | 2.1% | 0.531 [0.522, 0.541] | 0.023 [0.022, 0.024] | 3.2% [2.8%, 3.5%] | 1.50x |
| quiet | 334,428 / 7,174 | logistic (all features) | 2.1% | 0.823 [0.815, 0.833] | 0.130 [0.123, 0.139] | 14.9% [14.3%, 15.7%] | 6.96x |
| quiet | 334,428 / 7,174 | LightGBM (all features) | 2.1% | 0.830 [0.823, 0.838] | 0.138 [0.130, 0.146] | 15.6% [14.9%, 16.3%] | 7.25x |
| quiet | 334,428 / 7,174 | LightGBM (without viol_*) | 2.1% | 0.827 [0.820, 0.835] | 0.132 [0.124, 0.138] | 14.8% [14.1%, 15.5%] | 6.90x |
| quiet | 334,428 / 7,174 | LightGBM (without loud_*) | 2.1% | 0.811 [0.803, 0.819] | 0.118 [0.110, 0.126] | 14.1% [13.4%, 14.9%] | 6.58x |
| quiet | 334,428 / 7,174 | LightGBM (static + prior only) | 2.1% | 0.799 [0.791, 0.807] | 0.111 [0.104, 0.118] | 13.3% [12.5%, 14.0%] | 6.20x |
| zero_viol | 159,791 / 3,025 | rule: violations in last 12m | 1.9% | 0.500 [0.500, 0.500] | 0.019 [0.018, 0.020] | 5.6% [4.9%, 6.3%] | 2.97x |
| zero_viol | 159,791 / 3,025 | logistic (all features) | 1.9% | 0.841 [0.829, 0.853] | 0.123 [0.112, 0.134] | 13.6% [12.5%, 14.6%] | 7.19x |
| zero_viol | 159,791 / 3,025 | LightGBM (all features) | 1.9% | 0.848 [0.835, 0.859] | 0.135 [0.121, 0.148] | 14.3% [13.3%, 15.3%] | 7.55x |
| zero_viol | 159,791 / 3,025 | LightGBM (without viol_*) | 1.9% | 0.845 [0.833, 0.857] | 0.130 [0.117, 0.143] | 13.9% [12.9%, 14.8%] | 7.32x |
| zero_viol | 159,791 / 3,025 | LightGBM (without loud_*) | 1.9% | 0.830 [0.818, 0.842] | 0.113 [0.102, 0.123] | 13.0% [11.9%, 14.1%] | 6.86x |
| zero_viol | 159,791 / 3,025 | LightGBM (static + prior only) | 1.9% | 0.823 [0.811, 0.837] | 0.111 [0.100, 0.122] | 12.5% [11.5%, 13.4%] | 6.62x |
| clean_record | 116,195 / 787 | rule: violations in last 12m | 0.7% | 0.500 [0.500, 0.500] | 0.007 [0.006, 0.008] | 2.2% [1.6%, 2.8%] | 3.25x |
| clean_record | 116,195 / 787 | logistic (all features) | 0.7% | 0.748 [0.723, 0.776] | 0.031 [0.026, 0.042] | 4.0% [3.4%, 4.8%] | 5.87x |
| clean_record | 116,195 / 787 | LightGBM (all features) | 0.7% | 0.755 [0.732, 0.781] | 0.033 [0.026, 0.042] | 4.0% [3.3%, 4.7%] | 5.94x |
| clean_record | 116,195 / 787 | LightGBM (without viol_*) | 0.7% | 0.753 [0.729, 0.780] | 0.034 [0.026, 0.045] | 3.9% [3.2%, 4.6%] | 5.69x |
| clean_record | 116,195 / 787 | LightGBM (without loud_*) | 0.7% | 0.745 [0.720, 0.771] | 0.031 [0.024, 0.040] | 4.0% [3.3%, 4.6%] | 5.92x |
| clean_record | 116,195 / 787 | LightGBM (static + prior only) | 0.7% | 0.741 [0.713, 0.771] | 0.032 [0.024, 0.043] | 4.0% [3.3%, 4.7%] | 5.84x |

### Is LightGBM better than the logistic regression? (any serious event, all features, final test slice, paired)

| metric | LightGBM minus logistic [95% CI] |
|---|---|
| roc_auc | 0.0028 [0.0023, 0.0034] |
| pr_auc | 0.0152 [0.0128, 0.0175] |
| p_top5pct | 0.0087 [0.0050, 0.0127] |
| p_top1pct | 0.0251 [0.0164, 0.0342] |

### Walk-forward folds (any serious event)

Evaluation snapshots: fold1: 2022-01-01 to 2022-10-01 (trained up to 2021-01-01); fold2: 2023-01-01 to 2023-10-01 (trained up to 2022-01-01); fold3: 2024-01-01 to 2024-10-01 (trained up to 2023-01-01); test: 2025-01-01 to 2025-10-01 (trained up to 2024-01-01).

| fold | model | ROC-AUC | PR-AUC | precision top 5% | base rate |
|---|---|---|---|---|---|
| fold1 | rule: violations in last 12m | 0.846 | 0.527 | 65.7% | 8.1% |
| fold1 | logistic (all features) | 0.915 | 0.611 | 69.3% | 8.1% |
| fold1 | LightGBM (all features) | 0.918 | 0.626 | 70.9% | 8.1% |
| fold1 | LightGBM (without loud_*) | 0.909 | 0.616 | 70.2% | 8.1% |
| fold1 | LightGBM (static + prior only) | 0.894 | 0.562 | 65.4% | 8.1% |
| fold2 | rule: violations in last 12m | 0.847 | 0.549 | 68.6% | 8.5% |
| fold2 | logistic (all features) | 0.924 | 0.635 | 72.7% | 8.5% |
| fold2 | LightGBM (all features) | 0.928 | 0.653 | 74.0% | 8.5% |
| fold2 | LightGBM (without loud_*) | 0.923 | 0.645 | 73.4% | 8.5% |
| fold2 | LightGBM (static + prior only) | 0.907 | 0.605 | 70.2% | 8.5% |
| fold3 | rule: violations in last 12m | 0.870 | 0.569 | 68.9% | 8.2% |
| fold3 | logistic (all features) | 0.930 | 0.643 | 72.8% | 8.2% |
| fold3 | LightGBM (all features) | 0.933 | 0.660 | 73.5% | 8.2% |
| fold3 | LightGBM (without loud_*) | 0.930 | 0.653 | 73.0% | 8.2% |
| fold3 | LightGBM (static + prior only) | 0.911 | 0.598 | 68.3% | 8.2% |
| test | rule: violations in last 12m | 0.863 | 0.558 | 68.6% | 8.5% |
| test | logistic (all features) | 0.925 | 0.630 | 71.8% | 8.5% |
| test | LightGBM (all features) | 0.928 | 0.645 | 72.7% | 8.5% |
| test | LightGBM (without loud_*) | 0.923 | 0.639 | 72.2% | 8.5% |
| test | LightGBM (static + prior only) | 0.903 | 0.578 | 67.1% | 8.5% |

### Rare events scored with the any-serious-event model (descriptive, final test slice)

| event | events | score used | ROC-AUC | PR-AUC | recall in top 1% | recall in top 5% | lift top 5% |
|---|---|---|---|---|---|---|---|
| label_vacate | 1,511 | rule: violations in last 12m | 0.780 | 0.027 | 12.7% | 38.7% | 7.74x |
| label_vacate | 1,511 | LightGBM (all features) | 0.845 | 0.031 | 13.6% | 39.2% | 7.85x |
| label_vacate | 1,511 | LightGBM (without loud_*) | 0.838 | 0.030 | 13.2% | 40.0% | 8.01x |
| label_vacate | 1,511 | LightGBM (static + prior only) | 0.830 | 0.028 | 13.6% | 37.7% | 7.53x |
| label_aep | 705 | rule: violations in last 12m | 0.972 | 0.103 | 48.9% | 89.2% | 17.84x |
| label_aep | 705 | LightGBM (all features) | 0.983 | 0.115 | 53.9% | 90.4% | 18.07x |
| label_aep | 705 | LightGBM (without loud_*) | 0.984 | 0.136 | 57.2% | 92.1% | 18.41x |
| label_aep | 705 | LightGBM (static + prior only) | 0.982 | 0.115 | 54.0% | 88.4% | 17.67x |
| label_vacate_or_aep | 2,181 | rule: violations in last 12m | 0.840 | 0.091 | 23.8% | 54.2% | 10.85x |
| label_vacate_or_aep | 2,181 | LightGBM (all features) | 0.888 | 0.101 | 25.8% | 54.9% | 10.98x |
| label_vacate_or_aep | 2,181 | LightGBM (without loud_*) | 0.884 | 0.109 | 26.5% | 56.0% | 11.20x |
| label_vacate_or_aep | 2,181 | LightGBM (static + prior only) | 0.878 | 0.097 | 25.7% | 53.3% | 10.65x |
| label_omo | 26,293 | rule: violations in last 12m | 0.874 | 0.475 | 11.4% | 43.0% | 8.60x |
| label_omo | 26,293 | LightGBM (all features) | 0.930 | 0.556 | 12.6% | 45.6% | 9.12x |
| label_omo | 26,293 | LightGBM (without loud_*) | 0.926 | 0.556 | 12.8% | 45.4% | 9.09x |
| label_omo | 26,293 | LightGBM (static + prior only) | 0.903 | 0.487 | 11.8% | 41.5% | 8.31x |
| label_litigation | 14,452 | rule: violations in last 12m | 0.862 | 0.354 | 16.3% | 49.6% | 9.91x |
| label_litigation | 14,452 | LightGBM (all features) | 0.922 | 0.404 | 17.2% | 52.7% | 10.54x |
| label_litigation | 14,452 | LightGBM (without loud_*) | 0.917 | 0.391 | 16.6% | 51.8% | 10.36x |
| label_litigation | 14,452 | LightGBM (static + prior only) | 0.907 | 0.369 | 16.5% | 49.4% | 9.87x |

### Spatial hold-out (fold3, any serious event, LightGBM, all features)

| setup | rows | ROC-AUC | PR-AUC | precision top 5% | lift top 5% |
|---|---|---|---|---|---|
| time_only (all districts seen in training) | 404,508 | 0.933 | 0.660 | 73.5% | 8.97x |
| time + place held out (district groups) | 404,508 | 0.933 | 0.659 | 73.5% | 8.97x |

### SHAP: share of the score's attribution by feature group (any serious event, final test slice)

Mean absolute group SHAP (features summed within the group first), as a share of the total. Log-odds scale.

| LightGBM features | static | viol_* | loud_* | evict_* | dob_* | prior_* |
|---|---|---|---|---|---|---|
| all features | 18% | 24% | 40% | 0% | 1% | 16% |
| without viol_* | 21% | - | 52% | 1% | 2% | 24% |
| without loud_* | 26% | 50% | - | 1% | 2% | 20% |
| static + prior only | 40% | - | - | 3% | 3% | 55% |

Top 12 features (all features): `loud_prob_n_12m` (0.54), `static_bldgclass` (0.24), `prior_omo_months_since` (0.22), `viol_open_n` (0.20), `static_borough` (0.14), `viol_open_c_n` (0.13), `loud_311_n_36m` (0.12), `viol_open_b_n` (0.12), `prior_omo_n` (0.10), `loud_cmpl_n_12m` (0.07), `viol_c_n_3m` (0.06), `loud_prob_n_36m` (0.05)

Top 12 features (without loud_*): `viol_open_b_n` (0.33), `static_bldgclass` (0.27), `prior_omo_months_since` (0.25), `static_borough` (0.18), `viol_open_n` (0.17), `viol_c_n_12m` (0.15), `viol_open_c_n` (0.15), `viol_b_n_12m` (0.11), `static_unitsres` (0.09), `prior_omo_n` (0.09), `viol_n_12m` (0.07), `viol_b_n_36m` (0.07)

Example buildings (latest test snapshot, top 6 contributions each):

| example | bbl | score | rank | event | feature | value | SHAP |
|---|---|---|---|---|---|---|---|
| highest-scoring true positive | example building 1 | 0.99 | 1 | 1 | loud_prob_n_12m | 294.0 | 1.9 |
| highest-scoring true positive | example building 1 | 0.99 | 1 | 1 | viol_open_n | 563.0 | 0.758 |
| highest-scoring true positive | example building 1 | 0.99 | 1 | 1 | prior_omo_months_since | 1.0 | 0.613 |
| highest-scoring true positive | example building 1 | 0.99 | 1 | 1 | viol_c_n_3m | 17.0 | 0.512 |
| highest-scoring true positive | example building 1 | 0.99 | 1 | 1 | viol_open_c_n | 197.0 | 0.486 |
| highest-scoring true positive | example building 1 | 0.99 | 1 | 1 | prior_omo_n_12m | 13.0 | 0.42 |
| silent: event in a 'quiet' building the violation rule misses, still in the model's top 5% | example building 2 | 0.64 | 3984 | 1 | prior_omo_months_since | 3.0 | 1.457 |
| silent: event in a 'quiet' building the violation rule misses, still in the model's top 5% | example building 2 | 0.64 | 3984 | 1 | prior_omo_n | 128.0 | 0.749 |
| silent: event in a 'quiet' building the violation rule misses, still in the model's top 5% | example building 2 | 0.64 | 3984 | 1 | viol_open_b_n | 306.0 | 0.661 |
| silent: event in a 'quiet' building the violation rule misses, still in the model's top 5% | example building 2 | 0.64 | 3984 | 1 | viol_open_c_n | 77.0 | 0.571 |
| silent: event in a 'quiet' building the violation rule misses, still in the model's top 5% | example building 2 | 0.64 | 3984 | 1 | viol_open_n | 546.0 | 0.431 |
| silent: event in a 'quiet' building the violation rule misses, still in the model's top 5% | example building 2 | 0.64 | 3984 | 1 | loud_prob_n_12m | 0.0 | -0.273 |
| high-scoring false positive | example building 3 | 0.98 | 73 | 0 | loud_prob_n_12m | 107.0 | 1.845 |
| high-scoring false positive | example building 3 | 0.98 | 73 | 0 | viol_open_n | 347.0 | 0.76 |
| high-scoring false positive | example building 3 | 0.98 | 73 | 0 | prior_omo_months_since | 2.0 | 0.624 |
| high-scoring false positive | example building 3 | 0.98 | 73 | 0 | viol_c_n_3m | 13.0 | 0.497 |
| high-scoring false positive | example building 3 | 0.98 | 73 | 0 | viol_open_c_n | 122.0 | 0.494 |
| high-scoring false positive | example building 3 | 0.98 | 73 | 0 | viol_open_b_n | 128.0 | 0.403 |
| missed event (positive with a low score) | example building 4 | 0.00 | 101182 | 1 | static_bldgclass | R6 | -0.506 |
| missed event (positive with a low score) | example building 4 | 0.00 | 101182 | 1 | loud_prob_n_12m | 0.0 | -0.407 |
| missed event (positive with a low score) | example building 4 | 0.00 | 101182 | 1 | viol_open_n | 0.0 | -0.197 |
| missed event (positive with a low score) | example building 4 | 0.00 | 101182 | 1 | loud_311_n_36m | 0.0 | -0.159 |
| missed event (positive with a low score) | example building 4 | 0.00 | 101182 | 1 | prior_omo_months_since | nan | -0.158 |
| missed event (positive with a low score) | example building 4 | 0.00 | 101182 | 1 | static_borough | BK | -0.148 |

### Training runtime and early stopping

64 (fold, target, feature set) fits. LightGBM seconds per fit: median 8, max 19; logistic regression: median 6, max 18. Best iteration (early stopping on a later purged slice): median 82, range 42 to 184.

<!-- END GENERATED -->

## 4. Figures (`reports/phase3/figures/`)

- `headline_ablation.png`: PR-AUC and ROC-AUC with bootstrap intervals for every model and feature set (any serious event, test slice).
- `calibration.png`: reliability curves by decile (test slice).
- `per_snapshot.png`: PR-AUC and precision at top 5% at each of the 16 out-of-time evaluation snapshots.
- `slices.png`: PR-AUC by slice (all, Bronx, Brooklyn, quiet, zero violations, clean record).
- `shap_groups.png`: feature-group SHAP attribution for the four feature sets.
- `shap_beeswarm.png`: the 15 most important features of the all-features model.
- `shap_example_waterfall.png`: the contributions behind the highest-scoring true positive.

## 5. Other outputs

- `data/processed/scores_phase3.parquet` (gitignored): `bbl, snapshot_date, fold, score, score_no_loud, score_no_viol, score_static_prior`, the LightGBM
  any-serious-event probabilities, **out of time**, for the 16 evaluation snapshots 2022-01-01 to 2025-10-01 (1,614,360 rows; the `fold` column says which model produced a row).
  Snapshots before 2022 were only ever training data, so they have no out-of-sample score. `score_no_loud` and `score_static_prior` are the versions for the Phase 4 and map work.
- `reports/phase3/*.csv` and `*.json`: every table in this document and more (all top-k and recall columns, all folds, all slices, calibration deciles).
  Trained models (`data/processed/phase3/models/`) and predictions (`data/processed/phase3/preds/`) are gitignored; the small tables and figures can be committed.
- Runtime on this laptop (10 cores): training 64 (fold, target, feature set) fits took 17 minutes, the spatial check 1.2 minutes, evaluation with bootstrap 5 minutes, SHAP 1.5 minutes.
  `make features` (Phase 2) is 11 seconds.

## 6. Caveats

1. **The target is partly circular with the violation history.** AEP selects buildings by their number of open class B and C violations, and emergency repair
   (OMO) charges follow uncorrected hazardous violations; OMO is about 78% of `label_serious_any`. So a high violation count predicts the label almost by
   construction, which is why the rule is hard to beat. Scored with the any-serious-event model, 90% of AEP selections fall in the top 5%, but the
   violation rule alone already puts 89% there.
2. **A score is not a measure of hidden condition.** The model predicts that the city will take an enforcement action. Buildings whose tenants complain
   more, and buildings HPD inspects more, get more actions. `viol_*` is of mixed provenance (many violations follow a complaint) and the data does not say
   which, so removing `loud_*` does not make a model complaint free. Only `static_prior` is, and it is the weakest model. Phase 4 has to build on that, not on this.
3. **Structural proxies.** The most important single static features in SHAP are `static_bldgclass` and `static_borough`. Borough carries a 2.8x difference in base rates and building
   class codes mark building type and tenure. Any use of these scores for targeting needs a fairness review (by borough, class and neighbourhood) before it is trusted.
4. **Drift.** PR-AUC peaked at the 2024-01-01 snapshot (0.681) and eased to 0.633 by 2025-10-01 for the best model, and the rule moved the same way, so the gap is stable (always above 0.08).
   The test base rate (8.5%) is below the average of the training period, which is why the predictions run slightly high.
5. **Intervals are conditional on the trained models.** The bootstrap resamples buildings, not training runs, and it does not cover temporal drift. The four folds (above) show the fold-to-fold range.
6. **Test discipline.** The final model was trained once, with no tuning on the test slice. I did look at test-slice composition when choosing the `quiet` thresholds and I added a slice and a LightGBM-versus-logistic comparison after seeing the first results
   (neither changes any model). Results for rare labels (vacate or AEP, 2,181 events) have wide intervals.
7. **Inherited from Phase 2:** the spine is chosen with today's PLUTO; open violations at t are approximate and undercounted before 2018; vacate uses the effective date; features are NULL where
   history does not exist. See `docs/labels_and_features.md`.

## 7. Reproduce

```bash
make features   # Phase 2 tables (11 s)
make model      # train all folds, targets and feature sets, then the spatial check (about 20 min, resumable)
make evaluate   # metrics with bootstrap CIs, calibration, scores_phase3.parquet, SHAP (about 7 min)
make report     # refresh the tables in this document and the figures
make test       # 108 tests, including the purge/leakage tests; make lint
```
