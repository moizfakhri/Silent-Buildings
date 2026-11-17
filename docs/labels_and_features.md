# Phase 2: spine, as-of features and forward labels

Run it with `make features` (about 11 s, 4.3 GB peak memory on the full data), then `make baseline` and `make report`.
Output (gitignored): `data/processed/spine.parquet`, `features.parquet`, `labels.parquet`, `build_info.json`.
Code: SQL in `pipelines/sql/10..60_*.sql`, runner in `src/nycdistress/build.py`, CLI `pipelines/build_features.py`.

## 1. Grain and keys

One row per **building lot x quarterly snapshot**: `(bbl, snapshot_date)`. `bbl` is the 10-digit string
(borough 1 digit, block 5, lot 4). The features table and the labels table have exactly the same keys, so they
join one to one. Nothing in `labels` is used as a feature and nothing in `features` uses a date after `snapshot_date`.

## 2. Spine (which lots)

PLUTO lots in the Bronx or Brooklyn with `unitsres >= 3` and `landuse` in (2 walk-up multifamily, 3 elevator
multifamily, 4 mixed residential and commercial). This is 101,749 of PLUTO's 365,468 lots (102,110 have 3+ units; the 361
dropped have other land uses such as public facilities, commercial or unknown). PLUTO's `bbl` is stored as text like `'3085280034.00000000'`, so it is
cast through DOUBLE to a 10-digit integer first.

A lot enters a snapshot only if it already existed: `yearbuilt < year(snapshot_date)`. Unknown year built (0 in PLUTO, 189 of the
3+ unit lots) is kept at every snapshot.

`spine.parquet` also carries `community_district` (`cd`, 30 districts: 18 in Brooklyn, 12 in the Bronx; 7 lots have none) and `census_tract_2010`, added in Phase 3 for the spatial hold-out check. They are lot attributes, not features.

**Risk:** the spine is chosen with the *current* PLUTO release (version 26v2), so a lot that had 3+ units in 2019 but was converted,
merged or demolished since is missing, and a lot converted into 3+ units after t is judged by today's use. See section 6.

## 3. Snapshots and the quarter convention

Quarterly snapshots from `2019-01-01` to `2025-10-01` (28). The last one is the latest whose 12-month label window
ends inside the data: the label sources all run to Oct to Nov 2026 (monthly counts checked, no reporting lag in Sep 2026), so
`2025-10-01 + 12 months = 2026-10-01` is covered. The next snapshot (2026-01-01) would look 12 months into 2027.

**Convention.** Every event date is assigned to a quarter bucket `qi(d)`, with buckets anchored at 2018-01-01 and ending on the
snapshot dates. An event dated *exactly on* a snapshot belongs to the bucket that ends there. So for snapshot `t`:

- feature windows are `(t - w months, t]` for w = 3, 12, 36 (the last 1, 4 or 12 buckets) and "ever" means `<= t`;
- label windows are `(t, t + 12 months]` (the next 4 buckets);
- the two never share a bucket or a day, and an event on `t` is a feature and never a label.

**Missing by design.** A feature window that reaches back before its source's first covered date is NULL, not 0, because
"no events" and "not observed" must not look alike. Coverage starts: HPD violations, complaints, evictions, DOB violations,
litigations 2018-01-01 (the extract filter); 311 requests 2020-01-01 (all the 311 extract holds). So 36 month features are NULL for
all 2019 and 2020 snapshots, 311 12-month features until 2021-01-01 and 311 36-month features until 2023-01-01. `meta_hist36_complete`
is true once 36 months of history exist (snapshots from 2021-01-01).

## 4. Features (prefix = group)

Complaint-derived features are all in `loud_*` so that Phase 4 can fit a condition model **without** them.

| group | what | windows |
|---|---|---|
| `static_*` | PLUTO: borough, units, building class (and letter), land use, year built, **age at t** (`year(t) - yearbuilt`), floors, lot area, building area | none |
| `viol_*` | HPD violations by inspection date: all and class A / B / C counts; **open at t** (all and by class A/B/C) | 3, 12, 36 months |
| `loud_*` | HPD complaint problems received: total, distinct complaints, emergency (EMERGENCY + IMMEDIATE EMERGENCY), non-emergency, heat/hot water broken out, and 7 other major categories (12m only); **open problems at t**; problems closed in the window, **inspector no-access** count and share; 311 HPD requests (total, heat/hot water) | 3, 12, 36 months (categories and 311 heat 12m, shares 12 and 36m) |
| `evict_*` | executed residential marshal evictions | 12, 36 months |
| `dob_*` | DOB violations by issue date (all; elevator, boiler, construction at 12m) | 12, 36 months |
| `prior_*` | HPD litigations (`caseopendate`), OMO / emergency repair charges (`omocreatedate`), vacate orders (`vacate_effective_date`), AEP selections (`aep_start_date`): count to date, count in last 12m (litigation, OMO), **months since the last one** (calendar-month difference), orders/programs still **active** at t | cumulative |

Excluded on purpose: PLUTO assessed value, exemptions, owner name and owner type, and `yearalter1/2`. PLUTO is a current-state release only,
so these time-varying fields would show the 2026 value at a 2019 snapshot. Registrations and registration contacts are deduplicated
in staging but are **not** features for the same reason (a registration today says nothing about t). They are kept for the Phase 5 portfolio work.

### The no-access features (the part that leaks if keyed on the wrong date)

The outcome text ("inspector was not able to gain access") is only known when a complaint problem closes. So these features use the **closure date**, never the receipt date:

- A problem counts as closed at t only if both the problem and its complaint are `CLOSE`, and then the **later** of the two status dates (never earlier than the receipt date; 15,413 rows have a status date before the receipt date).
- `loud_closed_n_*` and `loud_nacc_n_*` count problems whose known closure date is in the window; `loud_nacc_share_*` is their ratio, NULL when nothing closed.
- `loud_open_prob_n` = received `<= t` minus known closed `<= t`.
- Why both dates: the text is problem-level (it differs between problems of the same complaint in 297,182 of 2.4M complaints, and 7,053 problems are closed while their complaint is open), but we only have the *current* status and no history, so we use the conservative reading. It costs almost nothing: complaints close a median of 1 day (p90 1 day, p99 29 days) after their problem.

## 5. Labels over (t, t + 12 months]

| label | event | date column | notes |
|---|---|---|---|
| `label_vacate` | HPD vacate order | `vacate_effective_date` | the dataset has only the *effective* date, not the issue date. Dates after the data cutoff (15 rows up to 2040) are dropped |
| `label_aep` | selected into the Alternative Enforcement Program | `aep_start_date` | one round a year (about 250 buildings citywide each Jan/Feb); exact duplicate rows collapsed |
| `label_omo` | emergency repair / OMO charge created | `omocreatedate` | includes demolition and AEP-linked charges (6.7% of OMO rows have `isaep = AEP`); about 78% of `label_serious_any` |
| `label_litigation` | new HPD litigation case | `caseopendate` | the 2 rows dated 2030 are dropped; the extract starts in 2018 |
| `label_serious_any` | any of the four | | union |
| `label_vacate_or_aep` | vacate order or AEP selection | as above | added in Phase 3 as the rare, harder pair (12,671 positive rows, 0.45%); not part of `label_serious_any`'s definition, which is unchanged |
| `label_loud_complaints_next12` | count of HPD complaint problems received | `received_date` | a count, for the later silent-distress gap; equals `loud_prob_n_12m` measured 12 months later |

## 6. Cleaning and dedupe rules (all stated in `10_staging.sql`)

- **BBL:** the source's stored `bbl` first (it handles condo billing lots), else built from borough, block, lot. Applies to violations (3,786 rows built), complaints (10,747 rows built, borough name mapped BRONX 2, BROOKLYN 3), OMO. DOB and registrations are built from boro/block/lot only. Rows with no usable BBL are dropped (311 10,067; evictions 5,094; litigations 45; vacate 11; AEP 4).
- **Source duplicates:** AEP `(building_id, aep_start_date)`: keep one row, preferring one with a discharge date (the duplicate was an exact repeat). Registrations `(registrationid, buildingid)`: newest `lastregistrationdate`. Contacts `registrationcontactid`: the row with the most non-null fields, ties by a hash of the row. Violations, complaints, 311, OMO, litigations, vacate and PLUTO have no duplicate keys.
- **Dates after the data cutoff (2026-11-14) are dropped** in every source (affects litigations 2, vacate 15 rows). One DOB date (`33218262`) does not parse and is dropped.
- **Evictions:** residential only (63,200 of 67,769).
- **Violation closure:** closed means `violationstatus = 'Close'`, closed on `max(currentstatusdate, inspectiondate)`. 23 closed violations carry garbage status dates (2108, 9202): they stay "open" at every snapshot.
- **Complaint duplicates:** `problem_duplicate_flag = Y` rows (15.4%) are kept. They record repeated complaints about the same building-wide condition, which is complaint behaviour.

## 7. Approximations and leakage risks (read before modelling)

1. **Open violations at t is an approximation.** Closed-ness comes from the *current* status and its date; there is no status history. A violation counts as open at t if inspected `<= t` and not (closed with a close date `<= t`). Intermediate states (reinspected, certified, not complied) are not used. It is also **left-censored**: violations inspected before 2018 that were still open are not in the extract, so open counts are undercounts, worst in 2019.
2. **Complaint outcome only from the closure date** (section 4). Reopened or revised complaints cannot be seen.
3. **Spine selection uses today's PLUTO** (section 2): lots converted, merged, split or demolished since t are mis-sampled, and a lot's BBL changing (merges and splits) loses its history.
4. **Static fields are current-state.** Floors, units and building area change with alterations; at old snapshots they show the latest value. The effect should be small but is not zero.
5. **The source tables are live and edited in place.** A violation issued before t and later deleted or reassigned is invisible; features at t see what survived to 2026-11-14.
6. **Left-censored history.** Litigations before 2018 are not in the extract, so `prior_litig_months_since` is NULL for lots whose last case predates 2018. OMO (from 1998), vacate (from 2012) and AEP (from 2007) have longer history. Evictions are missing a BBL in 7.5% of rows, so eviction counts are undercounts.
7. **Label definitions.** Vacate uses the effective date, not the issue date. AEP is selected once a year, so a 12-month window at some quarters contains one AEP round and at others a boundary of it. Everything in the label window has to exist by 2026-10-01; litigation counts for Oct 2026 look low (283 vs about 420) so the last quarter of the data is not complete, which is why the last snapshot is 2025-10-01.
8. **Label circularity.** HPD enforcement is rule driven off violation counts: AEP selects buildings by their number of open B/C violations and emergency repairs follow uncorrected hazardous violations. So the violation history predicts these labels almost by construction (see the smoke baseline). `viol_*` is also **mixed provenance**: many violations follow a tenant complaint, but the data does not say which. Phase 4 must decide whether `viol_*` counts as "loud".
9. **HPD complaints and 311 overlap** (HPD complaints originate from 311 calls), so using both double counts the same households.
10. **Time effects in the labels.** The litigation rate falls to about 1.8% in 2020 (court closures) and recovers to about 4%; the model has to be validated out of time, not randomly.

## 8. Tests (`make test`, no real data needed)

All run on a synthetic raw fixture (`tests/fixture_data.py`) built with the same columns and string types as `data/raw`, with hand-placed edge dates (exactly on t, a day later, exactly t - 12 months) and source quirks (PLUTO `.00000000` BBLs, duplicate AEP rows, vacate dates in 2040, a litigation in 2030, violations with no stored BBL, complaints closed before they were received).

- **(a) As-of invariance** (`test_features_at_t_ignore_everything_after_t`): for three snapshots, features from the full data equal features from data where every event after t is deleted *and* every status or outcome known only after t is scrambled (closure dates pushed to 2099, outcomes rewritten to "no access", rescind and discharge dates cleared).
- **(b) Label windows do not overlap feature windows** (`test_label_window_is_the_next_feature_window`): `label_x(t)` is true exactly when the cumulative count of x grows between t and t + 12 months; `label_loud_complaints_next12(t)` equals `loud_prob_n_12m` measured at t + 12 months. Plus hand-computed edge cases (`test_hand_checked_edge_cases`).
- **(c) No duplicate keys** and identical keys in features and labels; spine rules; static columns.
- **(d) Brute-force oracle** (`tests/oracle.py`, plain pandas, exact dates, no buckets): every column of the SQL output for all 482 fixture rows must equal it. The same oracle was run on 350 real buildings (200 random plus 150 of the busiest) at 3 snapshots each against the full build (see section 9).
- **Mutation check:** deliberately breaking the SQL (features reading one bucket ahead, label window overlapping t, no-access keyed on the receipt date) makes these tests fail, and restoring it makes them pass again. Each of the invariance and window tests catches its leak on its own, not only the oracle.

## 9. Real-data verification and findings

Checked on the full real build (`data/processed/`, 2,809,580 rows):

- **Brute-force oracle on real buildings:** 100 (bbl, snapshot) rows from 50 buildings (the 25 with the most complaint rows, one of which has 22,649 complaint problems, plus 25 random), 76 feature and label columns each: **0 mismatches** against the pandas oracle. This is a sample, not a census: the oracle takes about 15 s per call on the busiest buildings, so the planned 350-building run was stopped. The SQL itself is checked on all 482 synthetic rows in the test suite.
- **Structural identities on all rows:** no duplicate `(bbl, snapshot_date)` keys; features and labels have identical keys; every `bbl` is 10 digits and in the spine. Over all 2,403,812 pairs of snapshots 12 months apart, `label_omo`, `label_litigation`, `label_vacate` and `label_aep` at t equal "the cumulative count grew between t and t + 12 months" with **0 exceptions**, `label_loud_complaints_next12` equals `loud_prob_n_12m` at t + 12 months with **0 exceptions**, and `label_serious_any` is exactly the union of the four.

What looked odd in the data (none of it is a pipeline error):

- **The Bronx is much sicker on every label:** OMO 11.6% vs 4.5% in Brooklyn, litigation 7.7% vs 2.1%, any serious event 15.4% vs 5.6%, and about 10 complaint problems per lot-year vs 2.4. Borough must be handled explicitly in validation (spatial block CV) and in any fairness claim.
- **Complaints with a status date before the receipt date:** 15,413 rows (0.38%); clamped to the receipt date. 223 closed rows have no problem status date; the later of the remaining dates is used.
- **Litigation rate dips in 2020** (about 1.8% at the 2020-04-01 snapshot against 4% before and after), and the last month of litigation data is thin; see section 7.
- **The violation-count baseline is strong, on every label** (section 10). AEP selection is by violation count by design (AUC 0.97), and 78% of `label_serious_any` is OMO charges, which follow uncorrected violations. A model has to beat this baseline out of time, and "silent distress" needs a target that is not a mechanical function of violation history.
- **Stored vs built violation BBL:** the two differ in 0.42% of rows (condo billing lots); the stored one is used.


## 10. Numbers (generated; do not edit between the markers)

<!-- BEGIN GENERATED -->

Built 2026-11-13T21:00:30 with snapshots 2019-01-01 to 2025-10-01 (quarterly), data cutoff 2026-11-14. Build time: 8 s (10_staging 0.7s, 20_spine 0.6s, 30_features 4.6s, 50_labels 0.1s, 60_assemble 1.6s).

### Row counts

| quantity | value |
|---|---|
| spine lots (Bronx+Brooklyn, 3+ residential units) | 101,749 |
| snapshots | 28 |
| bbl x snapshot rows (features = labels) | 2,809,580 |
| distinct lots appearing in at least one snapshot | 101,442 |
| feature columns (excl. keys) | 82 |
|   borough BK: lots / rows | 78,384 / 2,173,988 |
|   borough BX: lots / rows | 23,058 / 635,592 |

### Feature columns by group

| group | columns | names |
|---|---|---|
| meta (flags) | 1 | meta_hist36_complete |
| static PLUTO | 11 | static_borough, static_unitsres, static_unitstotal, static_bldgclass, static_bldgclass_letter, static_landuse, static_year_built, static_age_at_t, static_numfloors, static_lotarea, static_bldgarea |
| viol_ HPD violations (mixed provenance) | 16 | viol_n_3m, viol_n_12m, viol_n_36m, viol_a_n_3m, viol_a_n_12m, viol_a_n_36m, viol_b_n_3m, viol_b_n_12m, viol_b_n_36m, viol_c_n_3m, viol_c_n_12m, viol_c_n_36m, viol_open_n, viol_open_a_n, ... |
| loud_ complaint-driven | 35 | loud_prob_n_3m, loud_prob_n_12m, loud_prob_n_36m, loud_cmpl_n_3m, loud_cmpl_n_12m, loud_cmpl_n_36m, loud_emerg_n_3m, loud_emerg_n_12m, loud_emerg_n_36m, loud_nonemerg_n_3m, loud_nonemerg_n_12m, loud_nonemerg_n_36m, loud_heat_n_3m, loud_heat_n_12m, ... |
| evict_ evictions | 2 | evict_n_12m, evict_n_36m |
| dob_ DOB violations | 5 | dob_n_12m, dob_n_36m, dob_elevator_n_12m, dob_boiler_n_12m, dob_construction_n_12m |
| prior_ earlier city/court events | 12 | prior_litig_n, prior_litig_n_12m, prior_litig_months_since, prior_omo_n, prior_omo_n_12m, prior_omo_months_since, prior_vacate_n, prior_vacate_active_n, prior_vacate_months_since, prior_aep_n, prior_aep_active_n, prior_aep_months_since |

### Label prevalence, overall and by borough

| slice | rows | vacate | aep | omo | litigation | serious_any | mean complaint problems next 12m |
|---|---|---|---|---|---|---|---|
| all | 2,809,580 | 0.28% | 0.18% | 6.13% | 3.33% | 7.83% | 4.21 |
| BK | 2,173,988 | 0.18% | 0.13% | 4.53% | 2.05% | 5.62% | 2.43 |
| BX | 635,592 | 0.61% | 0.34% | 11.62% | 7.71% | 15.38% | 10.30 |

### Label prevalence per snapshot

| snapshot | rows | vacate | aep | omo | litigation | serious_any | mean complaint problems next 12m |
|---|---|---|---|---|---|---|---|
| 2019-01-01 | 99,168 | 0.23% | 0.19% | 5.37% | 3.98% | 7.41% | 3.72 |
| 2019-04-01 | 99,168 | 0.24% | 0.18% | 5.96% | 3.74% | 7.65% | 3.33 |
| 2019-07-01 | 99,168 | 0.23% | 0.18% | 5.98% | 3.21% | 7.39% | 3.00 |
| 2019-10-01 | 99,168 | 0.20% | 0.18% | 5.62% | 2.75% | 6.93% | 2.97 |
| 2020-01-01 | 99,668 | 0.20% | 0.18% | 5.36% | 2.21% | 6.51% | 2.87 |
| 2020-04-01 | 99,668 | 0.20% | 0.18% | 5.36% | 1.76% | 6.23% | 3.04 |
| 2020-07-01 | 99,668 | 0.21% | 0.18% | 5.74% | 2.19% | 6.81% | 3.29 |
| 2020-10-01 | 99,668 | 0.23% | 0.18% | 5.92% | 2.37% | 7.06% | 3.49 |
| 2021-01-01 | 99,969 | 0.25% | 0.18% | 6.00% | 2.53% | 7.27% | 3.68 |
| 2021-04-01 | 99,969 | 0.25% | 0.19% | 6.05% | 2.75% | 7.43% | 4.00 |
| 2021-07-01 | 99,969 | 0.27% | 0.19% | 6.12% | 2.97% | 7.64% | 4.09 |
| 2021-10-01 | 99,969 | 0.27% | 0.19% | 6.20% | 3.13% | 7.82% | 4.04 |
| 2022-01-01 | 100,272 | 0.27% | 0.19% | 6.41% | 3.31% | 8.11% | 4.31 |
| 2022-04-01 | 100,272 | 0.29% | 0.19% | 6.38% | 3.55% | 8.16% | 4.16 |
| 2022-07-01 | 100,272 | 0.30% | 0.19% | 6.28% | 3.61% | 8.05% | 4.18 |
| 2022-10-01 | 100,272 | 0.30% | 0.19% | 6.38% | 3.72% | 8.20% | 4.34 |
| 2023-01-01 | 100,742 | 0.28% | 0.19% | 6.35% | 3.78% | 8.23% | 4.34 |
| 2023-04-01 | 100,742 | 0.27% | 0.18% | 6.39% | 3.91% | 8.31% | 4.61 |
| 2023-07-01 | 100,742 | 0.24% | 0.18% | 6.80% | 4.08% | 8.73% | 4.76 |
| 2023-10-01 | 100,742 | 0.25% | 0.18% | 6.64% | 4.08% | 8.62% | 4.78 |
| 2024-01-01 | 101,134 | 0.27% | 0.18% | 6.35% | 3.93% | 8.40% | 4.81 |
| 2024-04-01 | 101,134 | 0.31% | 0.18% | 6.08% | 3.78% | 8.15% | 4.90 |
| 2024-07-01 | 101,134 | 0.33% | 0.18% | 5.79% | 3.81% | 7.96% | 4.86 |
| 2024-10-01 | 101,134 | 0.34% | 0.18% | 6.20% | 3.77% | 8.26% | 4.78 |
| 2025-01-01 | 101,442 | 0.34% | 0.18% | 6.34% | 3.73% | 8.43% | 4.93 |
| 2025-04-01 | 101,442 | 0.36% | 0.17% | 6.53% | 3.61% | 8.55% | 5.25 |
| 2025-07-01 | 101,442 | 0.40% | 0.17% | 6.71% | 3.46% | 8.60% | 5.45 |
| 2025-10-01 | 101,442 | 0.39% | 0.17% | 6.34% | 3.45% | 8.25% | 5.69 |

### Missing-by-design windows (NULL share by snapshot year)

A window that reaches back before the source's first covered date is NULL, not 0.

| year | viol_*_36m | loud_*_36m | loud_311_*_12m | loud_311_*_36m | prior_litig_months_since (no earlier event) | prior_omo_months_since (no earlier event) |
|---|---|---|---|---|---|---|
| 2019 | 1.0 | 1.0 | 1.0 | 1.0 | 0.94 | 0.77 |
| 2020 | 1.0 | 1.0 | 1.0 | 1.0 | 0.93 | 0.75 |
| 2021 | 0.0 | 0.0 | 0.0 | 1.0 | 0.92 | 0.74 |
| 2022 | 0.0 | 0.0 | 0.0 | 1.0 | 0.9 | 0.73 |
| 2023 | 0.0 | 0.0 | 0.0 | 0.0 | 0.89 | 0.72 |
| 2024 | 0.0 | 0.0 | 0.0 | 0.0 | 0.88 | 0.72 |
| 2025 | 0.0 | 0.0 | 0.0 | 0.0 | 0.86 | 0.71 |

### Smoke baseline (SANITY CHECK ONLY, NOT A MODEL RESULT)

Rule: score = HPD violations in the prior 12 months (`viol_n_12m`), nothing fitted. Target `label_serious_any`, last two snapshots.

| snapshot | score | base rate | ROC-AUC | PR-AUC | precision at top 1% |
|---|---|---|---|---|---|
| 2025-07-01 | viol_n_12m (the baseline) | 0.0860 | 0.8605 | 0.5527 | 0.8679 |
| 2025-07-01 | loud_prob_n_12m (complaints, for context) | 0.0860 | 0.8793 | 0.5463 | 0.8294 |
| 2025-07-01 | prior_omo_n_12m (prior repairs, for context) | 0.0860 | 0.6731 | 0.3067 | 0.7978 |
| 2025-07-01 | constant (no information) | 0.0860 | 0.5000 | 0.0860 | 0.0868 |
| 2025-10-01 | viol_n_12m (the baseline) | 0.0825 | 0.8570 | 0.5458 | 0.8767 |
| 2025-10-01 | loud_prob_n_12m (complaints, for context) | 0.0825 | 0.8778 | 0.5385 | 0.8304 |
| 2025-10-01 | prior_omo_n_12m (prior repairs, for context) | 0.0825 | 0.6869 | 0.3165 | 0.7880 |
| 2025-10-01 | constant (no information) | 0.0825 | 0.5000 | 0.0825 | 0.0888 |

The same baseline score against each label separately:

| snapshot | label | base rate | ROC-AUC | PR-AUC |
|---|---|---|---|---|
| 2025-07-01 | label_vacate | 0.0040 | 0.7689 | 0.0284 |
| 2025-07-01 | label_aep | 0.0017 | 0.9753 | 0.1072 |
| 2025-07-01 | label_omo | 0.0671 | 0.8708 | 0.4777 |
| 2025-07-01 | label_litigation | 0.0346 | 0.8600 | 0.3429 |
| 2025-07-01 | label_serious_any | 0.0860 | 0.8605 | 0.5527 |
| 2025-10-01 | label_vacate | 0.0039 | 0.7692 | 0.0286 |
| 2025-10-01 | label_aep | 0.0017 | 0.9718 | 0.1043 |
| 2025-10-01 | label_omo | 0.0634 | 0.8660 | 0.4653 |
| 2025-10-01 | label_litigation | 0.0345 | 0.8631 | 0.3464 |
| 2025-10-01 | label_serious_any | 0.0825 | 0.8570 | 0.5458 |

<!-- END GENERATED -->
