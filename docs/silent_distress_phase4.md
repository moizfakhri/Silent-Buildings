# Phase 4: silent distress

Output format: Markdown. Tables in section 3 are generated from `reports/phase4/*.csv` by `make report4`; the text is hand written.
Code: `src/nycdistress/silent.py`, `pipelines/{train,silent,validate,report}_phase4.py`. Building-level scores stay in gitignored
`data/processed/`; this document and `reports/phase4/` hold only aggregate and geography-level numbers.

## 1. The verdict

**The data do not support "silent distress" in its strong form, and give weak support to a milder form.**

- **Silent buildings are not riskier than their profile predicts; they are somewhat safer.** I fitted a condition model from features with no complaint
  provenance (static fields and earlier city/court events) and flagged buildings whose predicted condition is bad but whose complaint record is empty
  (top decile of a within-borough percentile gap). Among them the observed rate of the primary outcome (a vacate order or a DOB physical-hazard violation in the next
  12 months) is **16% below the model's prediction** (observed/predicted 0.84, 95% CI 0.76 to 0.91, 949 events). Against matched not-silent buildings with the same predicted condition they have **35% fewer events**
  (relative risk 0.65, CI 0.59 to 0.74), or 21% fewer after covariate adjustment (0.79, CI 0.70 to 0.89). The silent group's event rate (0.59%) is about the same as the average building (0.55%), even though its predicted risk is 31% higher.
  If the absence of complaints hid extra danger, this ratio would be at or above 1. It is below 1.
- **For outcomes that start with a tenant complaint the shortfall is huge (relative risk 0.25 to 0.36), and that part is mechanical:** OMO charges, litigation and AEP selection only happen after the complaint
  to violation to enforcement chain starts, so they are rare where nobody complains. The primary outcome is the least tenant-driven one available and still shows 0.65, but it is not free of the chain (vacate orders usually follow
  an HPD inspection; DOB hazard violations often follow a 311 report). So the primary result cannot separate "complaints reveal real condition" from "complaints trigger the enforcement that defines the outcome".
- **The result is not an artefact of how I matched or flagged.** Same sign and similar size across the four folds (0.77, 0.65, 0.54, 0.64), in rental buildings only (0.65), with finer matching cells (0.65), with 311 instead of HPD
  complaints (0.68), and with the model-residual definition of silence (0.75). Shuffling the silent flag inside the matching cells gives 1.00 (95% range 0.93 to 1.07).
- **What does support a milder version.** (a) Among buildings with **no complaint at all** in the prior year, the non-complaint condition score still predicts complaints in the next year (incidence rate ratio 1.70 per standard deviation, CI 1.65 to 1.76, final test slice,
  controlling for size and community district): there is signal for latent demand. (b) Silent buildings' complaint rate rises from about 0 to 0.12 problems per unit over the next year, 28% of the way to what their condition model expects (0.44),
  but compared with matched buildings that had the same prior complaint level they are **not** louder later (ratio 0.96, CI 0.87 to 1.05), so this rise is what regression to the mean predicts. I cannot tell suppression from noise with these data.
- **Access-blocked buildings** (at least 3 closed problems, at least half closed for no access) do **not** show later trouble beyond comparable buildings: against matched buildings with similar complaint histories and better access they have fewer later events
  (primary 0.84, CI 0.68 to 0.99), fewer later violations (0.81, CI 0.78 to 0.85) and slightly fewer later complaints (0.91). With a closure that blocks a violation from ever being written, fewer violations is also what the chain predicts. No evidence of hidden high risk.
- **Effect heterogeneity is weak.** Bronx 0.58 (CI 0.45 to 0.73) and Brooklyn 0.70 (0.58 to 0.82) are compatible; across 26 community districts there is no evidence the primary-outcome ratio varies (Q test p = 0.71; the any-serious-event ratio varies a little, p = 0.045).

**Size of whatever is there:** the silent group is about 10% of building-snapshots; it contains 949 primary events out of 8,945 (10.6%), i.e. it carries its fair share of risk and no more. If there are hidden high-risk buildings,
this approach does not isolate them; it isolates a large group of mostly big, complaint-free buildings with an ordinary event rate.

## 2. Definitions (fixed before any outcome was examined, unless marked)

- **Out-of-time condition score p_hat.** LightGBM on `static_*` and `prior_*` features only (earlier OMO, litigation, vacate and AEP events; never `viol_*`, `loud_*` or the time flag). Same walk-forward folds and 12 month purge as Phase 3: the score of an evaluation snapshot comes from a model trained only
  on snapshots whose label windows had ended. 16 evaluation snapshots, 2022-01-01 to 2025-10-01. A test (`test_condition_model_can_never_see_complaint_provenance_features`) and an assertion in the trainer keep complaint-derived columns out.
  Variant `cond_plus` adds `dob_*` and `evict_*`. **Used: `cond_core`**, because `cond_plus` was no better on folds 1 to 3 (PR-AUC 0.0453 vs 0.0450 on the primary outcome) and `dob_*` features would mechanically predict an outcome that includes DOB violations.
  Calibration rule (fixed in advance, applied on folds 1 to 3 only): use the isotonic-calibrated probability only if it lowers calibration error. For the primary outcome the raw probability won, so p_hat is raw; its level matches the base rate (0.53% to 0.57% observed, 0.40% to 0.54% predicted).
- **Primary outcome:** a vacate order or a DOB violation of type IMEGNCY (immediate emergency), UB (unsafe building), FISPHAZ (hazardous facade) or EGNCY (emergency) issued in (t, t + 12 months]. Wide variant adds AEUHAZ1 (failure to certify correction of an immediately hazardous class-1 violation).
  **Choice made after seeing data:** I first declared the wide definition primary, then switched to the core one after seeing that the wide rate swings between 0.24% and 2.1% across snapshots (batch issuance of AEUHAZ1) and its predicted level drifts (2.7% predicted vs 0.9% observed in fold1). That decision used event rates and calibration only, before any gap or silent group existed. The wide definition is reported alongside.
  Sensitivity outcomes: any serious event, OMO, litigation, vacate or AEP. This reduces but does not remove the complaint-chain problem.
- **Loudness:** complaint problems in the prior 12 months per residential unit, shrunk with a Poisson-gamma (empirical Bayes) model fitted by marginal likelihood within snapshot x borough x size band: posterior mean (a + y) / (b + units). Small buildings are pulled harder to their group's mean; a zero count gets a positive rate that is lower for big buildings. 311 requests are handled the same way, separately.
- **Gap, definition (a), primary:** within-(snapshot, borough) percentile of p_hat minus within-(snapshot, borough) percentile of loudness. **Silent** = top decile of this gap (10% by construction).
- **Gap, definition (b):** a negative-binomial GLM per snapshot of the observed complaint count on logit(p_hat), log units and community district (offset log units, dispersion by moments); `gap_resid` = log((expected + 0.5) / (observed + 0.5)) with an interval from the uncertainty of the expectation;
  `silent_resid` = observed count in the lower 5% tail of the model's predictive distribution. It flags about 2.5% of building-snapshots (a count can only sit in the lower tail when many complaints were expected). The two definitions overlap little (Jaccard 0.12 on average, rank correlation 0.65 of the gaps), and the second is 26% co-ops and condos, so it is the more tenure-driven.
- **Access-blocked:** at least 3 problems closed in the prior 12 months and at least half of them closed with the "inspector not able to gain access" text (closure-date-safe Phase 2 features). The 0.5 cutoff was chosen from the distribution of the share (median 0.11, 90th percentile 0.47) before outcomes were examined; 9.8% of eligible buildings, 1.5% of all rows.
- **Validation outcomes** are events in (t, t + 12 months], plus the complaint and violation counts observed at t + 12 months (the Phase 2 features of the snapshot a year later). None is used to build a score; `test_build_scores_uses_only_values_known_at_the_snapshot_and_never_outcomes` feeds adversarial outcome columns and shows the scores do not move.
- **Statistics:** 95% intervals are cluster bootstraps by building (200 resamples), all snapshots pooled unless stated. Matching is coarsened exact matching with ATT weighting; `balance` below reports covariate balance.

## 3. Results

<!-- BEGIN GENERATED -->

### Power: events per evaluation fold

The primary outcome has about 2,200 events per fold (949 inside the silent group over all folds), enough for the matched comparison to have usable intervals when snapshots are pooled; single folds have wider intervals (about 190 to 290 events in the silent group). The wide definition's event count varies by a factor of 2 between folds (administrative batches).

| fold | building-snapshots | silent rows | primary events | primary events in silent group | wide events | any serious events | vacate or AEP events |
|---|---|---|---|---|---|---|---|
| fold1 | 401,088 | 40,163 | 2,280 | 290 | 3,503 | 32,609 | 1,902 |
| fold2 | 402,968 | 40,313 | 2,256 | 253 | 5,574 | 34,140 | 1,764 |
| fold3 | 404,536 | 40,459 | 2,128 | 193 | 4,876 | 33,143 | 1,952 |
| test | 405,768 | 40,611 | 2,281 | 213 | 2,546 | 34,315 | 2,181 |
| all | 1,614,360 | 161,546 | 8,945 | 949 | 16,499 | 134,207 | 7,799 |

### The condition model (static + earlier city/court events only), primary outcome

| fold | base rate | mean predicted | ROC-AUC | PR-AUC | lift top 5% | ECE |
|---|---|---|---|---|---|---|
| fold1 | 0.57% | 0.40% | 0.849 | 0.044 | 7.6x | 0.0019 |
| fold2 | 0.56% | 0.49% | 0.837 | 0.045 | 8.4x | 0.0008 |
| fold3 | 0.53% | 0.53% | 0.827 | 0.046 | 7.8x | 0.0006 |
| test | 0.56% | 0.54% | 0.805 | 0.031 | 6.6x | 0.0008 |

### 1. Calibration within groups: are silent buildings as risky as the condition model says?

Observed event rate divided by the condition model's mean prediction, pooled over 16 out-of-time snapshots. 'Level corrected' rescales each snapshot's predictions so the average building is exactly 1.00 (the event base rate drifts between snapshots). 1.00 means the complaint record adds no information beyond predicted condition; below 1.00 means silent buildings have fewer events than predicted. 95% CI: cluster bootstrap by building.

**primary: vacate or DOB hazard (core)**

| group | events | observed | predicted | observed / predicted | level corrected |
|---|---|---|---|---|---|
| silent (rank gap, top decile) | 949 | 0.59% | 0.63% | 0.93 [0.84, 1.01] | 0.84 [0.76, 0.91] |
| not silent | 7,996 | 0.55% | 0.48% | 1.15 [1.10, 1.19] | 1.02 [1.01, 1.03] |
| silent (model residual) | 852 | 2.14% | 2.71% | 0.79 [0.70, 0.87] | 0.71 [0.63, 0.79] |
| silent (311 loudness) | 981 | 0.61% | 0.63% | 0.96 [0.86, 1.04] | 0.86 [0.78, 0.93] |
| silent, excluding co-ops and condos | 728 | 0.50% | 0.54% | 0.93 [0.82, 1.04] | 0.83 [0.74, 0.92] |
| access-blocked | 251 | 1.00% | 0.82% | 1.23 [1.03, 1.46] | 1.11 [0.93, 1.31] |

**vacate or DOB hazard (wide)**

| group | events | observed | predicted | observed / predicted | level corrected |
|---|---|---|---|---|---|
| silent (rank gap, top decile) | 1,986 | 1.23% | 1.88% | 0.65 [0.60, 0.71] | 0.93 [0.86, 1.00] |
| not silent | 14,513 | 1.00% | 1.42% | 0.70 [0.68, 0.72] | 1.01 [1.00, 1.02] |
| silent (model residual) | 1,752 | 4.40% | 6.12% | 0.72 [0.66, 0.77] | 0.95 [0.89, 1.01] |
| silent (311 loudness) | 2,000 | 1.24% | 1.90% | 0.65 [0.60, 0.71] | 0.93 [0.86, 1.00] |
| silent, excluding co-ops and condos | 1,422 | 0.97% | 1.53% | 0.64 [0.57, 0.70] | 0.92 [0.83, 1.00] |
| access-blocked | 404 | 1.62% | 2.37% | 0.68 [0.59, 0.79] | 1.00 [0.87, 1.14] |

**any serious event**

| group | events | observed | predicted | observed / predicted | level corrected |
|---|---|---|---|---|---|
| silent (rank gap, top decile) | 6,345 | 3.93% | 6.51% | 0.60 [0.57, 0.63] | 0.60 [0.57, 0.62] |
| not silent | 127,862 | 8.80% | 8.44% | 1.04 [1.04, 1.05] | 1.03 [1.03, 1.04] |
| silent (model residual) | 5,921 | 14.86% | 21.58% | 0.69 [0.67, 0.71] | 0.69 [0.66, 0.71] |
| silent (311 loudness) | 6,643 | 4.11% | 6.67% | 0.62 [0.58, 0.64] | 0.61 [0.58, 0.63] |
| silent, excluding co-ops and condos | 5,419 | 3.71% | 6.23% | 0.60 [0.56, 0.62] | 0.59 [0.56, 0.61] |
| access-blocked | 5,173 | 20.68% | 16.98% | 1.22 [1.18, 1.26] | 1.21 [1.18, 1.25] |

**OMO charge**

| group | events | observed | predicted | observed / predicted | level corrected |
|---|---|---|---|---|---|
| silent (rank gap, top decile) | 4,268 | 2.64% | 5.00% | 0.53 [0.50, 0.55] | 0.55 [0.52, 0.57] |
| not silent | 98,606 | 6.79% | 6.79% | 1.00 [0.99, 1.01] | 1.04 [1.04, 1.04] |
| silent (model residual) | 3,976 | 9.98% | 16.39% | 0.61 [0.58, 0.63] | 0.63 [0.61, 0.66] |
| silent (311 loudness) | 4,516 | 2.79% | 5.13% | 0.54 [0.52, 0.57] | 0.56 [0.54, 0.59] |
| silent, excluding co-ops and condos | 3,699 | 2.53% | 4.85% | 0.52 [0.49, 0.55] | 0.54 [0.51, 0.57] |
| access-blocked | 3,881 | 15.52% | 13.55% | 1.15 [1.11, 1.19] | 1.19 [1.15, 1.24] |

### 2. Matched comparison: silent vs not silent buildings with the same predicted condition

Coarsened exact matching inside cells of snapshot x borough x size band x building class x age band x predicted-risk decile (controls reweighted to the silent group). Relative risk = event rate of silent buildings divided by that of matched not-silent buildings. Outcomes that start with a tenant complaint (OMO, litigation, AEP, hence 'any serious') are mechanically rarer where nobody complains, so they are shown in a separate column group.

| silent definition | silent rows matched | primary | wide DOB hazard | any serious (chain) | OMO (chain) | litigation (chain) | vacate or AEP |
|---|---|---|---|---|---|---|---|
| rank gap (pre-specified) | 160,172 | 0.65 [0.59, 0.74] | 0.74 [0.67, 0.81] | 0.29 [0.28, 0.30] | 0.25 [0.24, 0.27] | 0.26 [0.24, 0.28] | 0.36 [0.29, 0.44] |
| rank gap, finer cells | 158,998 | 0.65 [0.56, 0.74] | 0.74 [0.68, 0.83] | 0.29 [0.28, 0.31] | 0.26 [0.24, 0.27] | 0.26 [0.23, 0.28] | 0.37 [0.30, 0.44] |
| rank gap, rental buildings only | 145,058 | 0.65 [0.56, 0.74] | 0.72 [0.64, 0.81] | 0.30 [0.29, 0.32] | 0.26 [0.25, 0.28] | 0.27 [0.25, 0.29] | 0.38 [0.31, 0.46] |
| rank gap on 311 loudness | 160,231 | 0.68 [0.60, 0.76] | 0.74 [0.67, 0.80] | 0.30 [0.29, 0.32] | 0.27 [0.25, 0.28] | 0.26 [0.24, 0.28] | 0.39 [0.32, 0.47] |
| model residual | 39,479 | 0.75 [0.66, 0.86] | 0.72 [0.66, 0.78] | 0.36 [0.34, 0.37] | 0.31 [0.29, 0.32] | 0.32 [0.30, 0.34] | 0.34 [0.29, 0.41] |
| model residual, finer cells | 38,948 | 0.71 [0.63, 0.81] | 0.70 [0.62, 0.76] | 0.35 [0.34, 0.37] | 0.30 [0.29, 0.32] | 0.31 [0.29, 0.33] | 0.33 [0.28, 0.39] |
| model residual, rental only | 29,312 | 0.72 [0.62, 0.84] | 0.68 [0.60, 0.75] | 0.36 [0.34, 0.38] | 0.30 [0.28, 0.32] | 0.33 [0.30, 0.35] | 0.37 [0.29, 0.44] |

Primary outcome, silent group: 0.58% vs 0.90% in matched not-silent buildings (937 events in the silent group, 99.1% of silent rows matched).

By fold (rank-gap silent, pre-specified matching):

| fold | silent events (primary) | primary | any serious | OMO |
|---|---|---|---|---|
| fold1 | 285 | 0.77 [0.62, 1.00] | 0.28 [0.26, 0.31] | 0.26 [0.24, 0.29] |
| fold2 | 251 | 0.65 [0.51, 0.81] | 0.30 [0.28, 0.32] | 0.27 [0.24, 0.29] |
| fold3 | 190 | 0.54 [0.40, 0.68] | 0.29 [0.27, 0.31] | 0.23 [0.21, 0.25] |
| test | 211 | 0.64 [0.49, 0.82] | 0.30 [0.28, 0.32] | 0.25 [0.23, 0.28] |

Stratified by the number of complaint problems in the prior 12 months (silent vs not silent inside the stratum; only a handful of silent buildings have complaints):

| prior complaint problems | silent rows | primary | any serious |
|---|---|---|---|
| 0 | 159,584 | 1.07 [0.84, 1.49] | 1.24 [1.11, 1.40] |
| 1-3 | 1,535 | 1.57 [1.01, 2.52] | 1.15 [0.90, 1.42] |
| 4-11 | 297 | 2.49 [1.26, 4.53] | 1.35 [1.17, 1.68] |

Covariate-adjusted risk ratio (Poisson regression, log link, standard errors clustered by building; controls: predicted condition, size, age, borough, class, snapshot):

| flag | outcome | risk ratio [95% CI] |
|---|---|---|
| silent | primary: vacate or DOB hazard (core) | 0.79 [0.70, 0.89] |
| silent | vacate or DOB hazard (wide) | 0.82 [0.75, 0.90] |
| silent | any serious event | 0.38 [0.36, 0.40] |
| silent | OMO charge | 0.33 [0.32, 0.35] |
| silent_resid | primary: vacate or DOB hazard (core) | 0.70 [0.62, 0.80] |
| silent_resid | vacate or DOB hazard (wide) | 0.65 [0.59, 0.71] |
| silent_resid | any serious event | 0.33 [0.31, 0.34] |
| silent_resid | OMO charge | 0.28 [0.26, 0.29] |

Covariate balance (standardised mean differences; below 0.10 is conventional):

| covariate | before matching | after (pre-specified) | after (finer cells) | residual flag: before | residual flag: after |
|---|---|---|---|---|---|
| p_hat | 0.14 | -0.08 | -0.08 | 1.01 | 0.06 |
| p_hat decile | 1.09 | 0.00 | 0.00 | 2.19 | 0.00 |
| log units | 0.32 | 0.21 | 0.19 | 1.64 | 0.11 |
| age | 0.09 | -0.02 | -0.02 | -0.21 | -0.02 |
| Bronx | 0.00 | 0.00 | 0.00 | 0.53 | -0.00 |
| co-op or condo | 0.07 | 0.06 | 0.05 | 0.51 | 0.25 |
| prior complaint rate per unit (NOT matched on) | -0.29 | -0.71 | -0.73 | -0.27 | -1.19 |
| zero prior complaints (NOT matched on) | 0.76 | 1.56 | 1.61 | 0.01 | 1.59 |

### 3. Does silence precede later loudness?

| matching cells | outcome | silent | matched not silent | ratio [95% CI] |
|---|---|---|---|---|
| strata A (as the main comparison) | next-12m complaint problems per unit | 0.123 | 0.571 | 0.22 [0.20, 0.23] |
| strata A (as the main comparison) | change from prior-12m rate | 0.123 | -0.149 | -0.83 [-0.96, -0.74] |
| strata A + prior complaint bucket | next-12m complaint problems per unit | 0.119 | 0.124 | 0.96 [0.87, 1.05] |
| strata A + prior complaint bucket | change from prior-12m rate | 0.119 | 0.123 | 0.96 [0.88, 1.05] |
| strata A | next-12m 311 requests per unit | 0.108 | 0.487 | 0.22 [0.21, 0.24] |

Complaint problems per unit per year, descriptive:

| group | prior 12 months | expected from predicted condition (cross-sectional model) | next 12 months |
|---|---|---|---|
| silent | 0.000 | 0.436 | 0.123 |
| not_silent | 0.296 | 0.286 | 0.300 |
| silent_resid | 0.016 | 1.419 | 0.174 |

Negative-binomial regression of next-12-month complaint problems, final test slice (incidence rate ratios; controls: community district, snapshot, size; cluster-robust by building):

| sample | rows | term | IRR [95% CI] |
|---|---|---|---|
| all buildings in the test slice | 405,768 | predicted condition (p_hat), per +1 SD of logit | 1.63 [1.58, 1.67] |
| all buildings in the test slice | 405,768 | log(1 + prior-12m complaint problems) | 2.17 [2.14, 2.21] |
| buildings with zero complaint problems in the prior 12 months | 311,335 | predicted condition (p_hat), per +1 SD of logit | 1.70 [1.65, 1.76] |

### 4. Access-blocked buildings

Buildings with at least 3 problems closed in the last 12 months and at least half of them closed for no access, against buildings with at least 3 closed problems and a lower no-access share, matched on snapshot, borough, size, number of closed problems, prior complaint bucket and predicted-risk tercile.

| outcome in the next 12 months | access-blocked | matched comparison | ratio [95% CI] |
|---|---|---|---|
| primary | 0.01002 | 0.01191 | 0.84 [0.68, 0.99] |
| wide | 0.01618 | 0.01927 | 0.84 [0.72, 0.96] |
| serious_any | 0.207 | 0.2452 | 0.84 [0.81, 0.88] |
| omo | 0.1554 | 0.1921 | 0.81 [0.77, 0.85] |
| vacate_or_aep | 0.00833 | 0.01119 | 0.74 [0.59, 0.88] |
| litigation | 0.08201 | 0.09057 | 0.91 [0.84, 0.96] |
| next-12m complaint problems per unit | 0.8517 | 0.9374 | 0.91 [0.87, 0.95] |
| violations issued in next 12m (count) | 9.023 | 11.07 | 0.81 [0.78, 0.85] |
| class C violations in next 12m (count) | 2.784 | 3.602 | 0.77 [0.73, 0.81] |

### 5. Heterogeneity

| borough | outcome | relative risk [95% CI] |
|---|---|---|
| BK | primary: vacate or DOB hazard (core) | 0.70 [0.58, 0.82] |
| BK | any serious event | 0.28 [0.26, 0.30] |
| BK | OMO charge | 0.26 [0.24, 0.28] |
| BX | primary: vacate or DOB hazard (core) | 0.58 [0.45, 0.73] |
| BX | any serious event | 0.31 [0.29, 0.33] |
| BX | OMO charge | 0.24 [0.22, 0.27] |

| outcome | community districts | pooled RR | Q | df | p-value | district RR range |
|---|---|---|---|---|---|---|
| primary | 26 | 0.71 | 20.7 | 25 | 0.711 | 0.37 to 1.77 |
| serious_any | 30 | 0.31 | 43.1 | 29 | 0.045 | 0.21 to 0.41 |

District estimates for the primary outcome rest on few events each (many districts have under 20 silent-group events), so the range is mostly noise; the test is the informative part.

### 6. Placebo: the silent flag shuffled inside the matching cells

| outcome | real relative risk | placebo mean | placebo 95% range (200 shuffles) | real outside the placebo range |
|---|---|---|---|---|
| primary: vacate or DOB hazard (core) | 0.65 | 1.005 | 0.93 to 1.07 | yes |
| vacate or DOB hazard (wide) | 0.74 | 1.002 | 0.95 to 1.06 | yes |
| any serious event | 0.29 | 0.999 | 0.98 to 1.02 | yes |
| OMO charge | 0.25 | 1.000 | 0.98 to 1.02 | yes |
| vacate or AEP | 0.36 | 0.998 | 0.91 to 1.09 | yes |
| litigation | 0.26 | 0.997 | 0.97 to 1.02 | yes |

### 7. Who is in the silent group (geography-level summaries)

| borough | buildings | silent share (by construction 10%) | model-residual silent share | access-blocked share | no complaint in 12 months | mean units | co-op or condo | mean predicted risk |
|---|---|---|---|---|---|---|---|---|
| BK | 78,384 | 10.0% | 1.7% | 1.4% | 82% | 10.3 | 9.0% | 0.35% |
| BX | 23,058 | 10.0% | 5.1% | 2.0% | 62% | 21.2 | 3.4% | 0.97% |

Community districts, silent share of building-snapshots (the share is 10% by construction in each borough, so the spread across districts is the finding):

| district | buildings | silent share | no complaint in 12 months | mean units | co-op or condo | primary event rate |
|---|---|---|---|---|---|---|
| 201 | 1,393 | 9.2% | 55% | 30.5 | 4.1% | 1.41% |
| 202 | 1,066 | 10.1% | 52% | 18.5 | 6.4% | 1.04% |
| 203 | 1,438 | 8.6% | 53% | 24.3 | 4.9% | 1.09% |
| 204 | 1,773 | 6.7% | 40% | 30.7 | 3.5% | 2.38% |
| 205 | 1,496 | 7.7% | 35% | 35.8 | 2.7% | 2.60% |
| 206 | 1,790 | 7.1% | 53% | 18.6 | 4.5% | 1.48% |
| 207 | 1,642 | 7.5% | 31% | 32.5 | 3.9% | 1.85% |
| 208 | 924 | 15.9% | 56% | 41.7 | 18.5% | 1.74% |
| 209 | 3,455 | 16.8% | 78% | 16.1 | 1.3% | 0.73% |
| 210 | 2,060 | 9.8% | 85% | 15.6 | 2.6% | 0.29% |
| 211 | 2,078 | 11.0% | 76% | 18.5 | 1.8% | 0.68% |
| 212 | 3,942 | 7.8% | 74% | 8.6 | 1.0% | 0.58% |
| 301 | 8,118 | 12.0% | 86% | 11.0 | 14.3% | 0.24% |
| 302 | 3,810 | 13.3% | 86% | 18.7 | 19.3% | 0.39% |
| 303 | 7,571 | 7.9% | 80% | 8.0 | 7.1% | 0.40% |
| 304 | 5,690 | 10.5% | 75% | 6.7 | 3.6% | 0.38% |
| 305 | 4,653 | 11.3% | 78% | 10.8 | 1.2% | 0.49% |
| 306 | 6,326 | 7.5% | 91% | 7.7 | 18.7% | 0.19% |
| 307 | 4,550 | 9.0% | 86% | 6.5 | 7.3% | 0.18% |
| 308 | 3,819 | 9.9% | 70% | 11.3 | 9.8% | 0.48% |
| 309 | 1,814 | 12.6% | 62% | 19.2 | 7.2% | 0.87% |
| 310 | 3,315 | 11.6% | 85% | 9.9 | 7.3% | 0.34% |
| 311 | 6,631 | 7.9% | 91% | 6.4 | 4.5% | 0.17% |
| 312 | 5,783 | 9.8% | 90% | 7.2 | 14.0% | 0.20% |
| 313 | 1,840 | 12.6% | 82% | 23.4 | 11.3% | 0.71% |
| 314 | 2,059 | 8.6% | 52% | 25.0 | 10.8% | 1.16% |
| 315 | 2,694 | 9.5% | 85% | 14.2 | 13.1% | 0.35% |
| 316 | 2,725 | 11.4% | 72% | 11.9 | 2.1% | 0.58% |
| 317 | 4,474 | 14.2% | 74% | 9.3 | 1.0% | 0.66% |
| 318 | 2,506 | 2.5% | 90% | 7.5 | 3.0% | 0.22% |

| flag | flagged rows | units: flagged vs other | age: flagged vs other | co-op or condo: flagged vs other | no complaint: flagged vs other | predicted risk: flagged vs other |
|---|---|---|---|---|---|---|
| silent | 161,546 | 30 vs 11 | 91 vs 88 | 9.5% vs 7.5% | 99% vs 75% | 0.63% vs 0.48% |
| silent_resid | 39,839 | 102 vs 11 | 81 vs 88 | 25.7% vs 7.3% | 78% vs 77% | 2.71% vs 0.44% |
| access_blocked | 25,009 | 20 vs 13 | 88 vs 88 | 5.9% vs 7.7% | 4% vs 78% | 0.82% vs 0.49% |

<!-- END GENERATED -->

## 4. Figures (`reports/phase4/figures/`)

- `matched_forest.png`: relative risk of silent vs matched not-silent buildings, every outcome and definition.
- `calibration_groups.png`: observed vs predicted events in each group.
- `placebo.png`: the real ratios against the shuffled-flag distribution.
- `silent_by_district.png`: share of building-snapshots flagged silent in each community district.

## 5. Choices made after seeing results (disclosure)

1. **Primary outcome switched from the wide to the core DOB-hazard definition**, after seeing event rates and calibration (not any gap result). Both are reported.
2. **A finer-matching sensitivity analysis was added** after the balance table showed silent buildings still larger inside the pre-specified cells (SMD 0.21 on log units; 0.19 with finer cells; the outcome ratios were already visible when I added it). Both are reported, and the covariate-adjusted regression was added for the same reason. Their estimates bracket the matched one (0.79 adjusted to 0.65 matched).
3. **The rental-only and co-op/condo checks were added** after looking at the building-class composition of the flags (predictors only, no outcomes).
4. **The 0.5 access-blocked cutoff** was chosen after viewing the distribution of the no-access share, before outcomes.
5. The silent definition, the top-decile cutoff, the strata and the calibration rule were fixed before any outcome analysis. Nothing was tuned on the final test slice; folds and test are all out of time.

## 6. Alternative explanations that remain, and caveats

- **Good condition.** Buildings with no complaints may simply be in good shape, which is what the data lean toward: complaints add information beyond the non-complaint profile. The condition model reaches ROC-AUC 0.80 to 0.85 and PR-AUC 0.03 to 0.05 against a 0.55% base rate, so it is informative but far from precise.
- **Tenure and management.** Co-ops and condos (owner-occupants do not file HPD tenant complaints) make up 26% of the model-residual flag; large professionally managed rentals are over-represented in the rank-gap group (30 units on average against 11). Excluding co-ops and condos barely changes the rank-gap result (0.65) and the residual one (0.73).
- **The outcomes depend on the same reporting system.** Vacate orders and DOB hazard violations are less tenant-driven than OMO or litigation but not independent of it, so a ratio below 1 is expected even if silent buildings had the same physical problems. The ratio for the chain-driven outcomes (0.25 to 0.36) against the primary (0.65) shows how much the chain matters, not how much hidden condition there is.
- **p_hat is not completely complaint free.** `prior_*` events (earlier OMO charges, litigation) are themselves downstream of old complaints. This weakens the claim that p_hat measures condition independently of tenants; a condition model limited to `static_*` alone is untested.
- **Silence is the norm.** 77% of building-snapshots have no complaint problem in the prior 12 months, so "silent" is defined by the gap, not by having zero complaints (99% of the silent group has none, as do 75% of everyone else).
- **Residual imbalance.** After matching, silent buildings are still somewhat larger (SMD 0.19 to 0.21) and the within-decile predicted risk is slightly lower (SMD -0.08); because larger buildings have more events this should push the ratio toward 1, so the estimates are if anything conservative, but I cannot prove that.
- **No demographics.** ACS and Census data were not pulled (out of scope for this phase). Whether silent areas are lower income or have more non-English speakers is the obvious next extension; this analysis says nothing about it.
- **PyMC hierarchical model:** not run. The two-stage models are enough to answer the question asked; a hierarchical Bayesian model would change the uncertainty of the community-district effects, not the verdict.
- **Power:** the primary outcome has about 2,200 events per fold and 949 in the silent group over all 16 snapshots. Pooled intervals are usable (relative risk CI width about 0.15); single folds and individual community districts are noisy (district estimates range from 0.12 to 2.05 and should not be read one by one).

## 7. Fairness note: who the silent group is

The silent flag is 10% of every borough by construction, so the differences are across community districts and building types. The share of building-snapshots flagged silent ranges from 2.5% (one Brooklyn district) to 16.8% across the 30 community districts, and the model-residual flag is three times as common in the Bronx (5.1%) as in Brooklyn (1.7%).
Silent buildings are larger (30 units vs 11), almost all have no complaint (99%), and are 9.5% co-op or condo (7.5% for the rest). The Bronx has far fewer buildings with no complaint (62% vs 82% in Brooklyn), so its silent flag is a rarer, sharper signal there.
**Reading "silent" as "disadvantaged" or "neglected" is not supported by this analysis**: silent buildings do not have worse later outcomes, and no demographic data were used. These scores describe model estimates for research, not findings about any owner or tenant. They should not be used to prioritise or deprioritise inspections without a separate fairness review.
No owner names appear anywhere in this repository's reports, and per-building scores are kept only in gitignored files.

## 8. Reproduce

```bash
make features   # Phase 2 tables
make silent     # condition models (7 min), loudness and gaps (1 min), validation with bootstrap (8 min)
make report4    # figures and the generated tables above
make test       # includes the no-leakage and matching-balance tests
```
Runtime on this laptop: condition models 6.9 minutes, loudness/gap assembly 0.8 minutes, validation (200 bootstraps, 200 placebo shuffles) 7.8 minutes.
