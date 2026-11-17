# Project plan: the buildings NYC can't hear

*The original plan, written 2026-11-13 before anything was built. Kept as a record: the project's results and the places where it departed from this plan are in `REPORT.md` and `METHODOLOGY_LOG.md`.*
*Dataset facts below were checked live against data.cityofnewyork.us on 2026-11-13 (see `DATASETS.md`). Statements about prior work come from search-result skim only and are flagged as such.*

---

## 1. The question

> **NYC's housing agencies learn about bad buildings mostly from tenant complaints. Which buildings are probably in serious trouble but are not generating complaints, and what happens to them (and to the buildings around them) over the next 12 months?**

Every existing "building distress" tool ranks buildings by *recorded* problems (violations, complaints, litigation). Recorded problems are a mix of *real conditions* and *who complains / who gets inspected*. This project models the two separately. The headline artifact is a **"silent distress" map**: buildings whose predicted condition is much worse than their complaint record suggests, shown on a 3D city.

Why that is worth a research lab's attention: it is a **censored / selectively-observed outcome problem** on real public-sector data, with a clean story (equity of enforcement), a validatable result, and a decision use (where should proactive inspection go).

## 2. Is it unique? (prior work check)

Honest answer: the plain version ("predict bad buildings from 311 + violations") is **not** unique. Known, from search-result skim (titles and abstracts, not read in full, so verify before citing):

| Prior work | What it does | Gap it leaves |
|---|---|---|
| JustFix **Who Owns What** (open source) | Links buildings into landlord portfolios from HPD registration data, timeline of violations | Descriptive lookup, no prediction, no sale events |
| ANHD **Displacement Alert Project** | Map and watchlists of at-risk buildings, rent-stabilized loss, sales | Indicator dashboard, not a validated predictive model |
| HPD **Speculation Watch List** and **Building Indicator Project** (UNHP) | Agency/nonprofit rule-based flags (dataset `adax-9mit` is the watch list) | Rules, not learned; not tested against outcomes |
| Academic ML for tenant harassment/violations (Ye, Johnson et al. 2019, Data Science for Social Good; Neill/NYU talks) | Predicts harassment risk to target outreach | Treats complaints as ground truth |
| NYU Marron/CUSP **"Estimating reporting bias in 311 complaint data"** and **"Bias in smart city governance"** (Kontokosta et al.) | Shows 311 reporting varies by neighborhood; estimates under-reporting of heat/hot water | Tract level, one complaint type, no building-level silent-distress ranking, no downstream outcome validation |

**So the novelty has to come from what we add, not the topic.** The defensible gaps:

1. **Building-level, multi-signal under-reporting model** validated against outcomes that do *not* depend on tenant complaints (see 3.2). The NYU work is the closest relative; we cite it and extend it, we do not pretend it doesn't exist.
2. **Inspection-access censoring.** I sampled HPD complaint records: closed complaints carry text like "HPD Inspector was not able to gain access to inspect this complaint." Those complaints never become violations even if the problem is real. Treating "complaint filed but no access" as a censored observation is a modeling angle I did not see in the skimmed work (unverified, search more before claiming).
3. **After-the-sale causal layer** (spin 2 below), which no tool above does as a proper event study.

### Assessing the two spins

| | Spin 1: "Silent distress" | Spin 2: "After the sale" |
|---|---|---|
| Idea | Latent-condition model: observed complaints = real condition x propensity to report x chance of being inspected | Staggered event study: how violations, complaints, evictions, AEP/OMO change after a building is sold; does distress spread across the buyer's portfolio |
| Data feasibility | High. HPD complaints (14.1M), 311, violations, litigation, OMO charges all share BBL/BIN/BuildingID | Medium. ACRIS Master (17.1M) + Legals + Parties are huge and messy; owner entity resolution is hard (LLC names). HPD registration contacts (745k) give a partial portfolio link |
| Validation | Strong: hold out complaint-independent outcomes | Strong: proper DiD with modern estimators (Callaway-Sant'Anna) |
| Novelty | Medium-high (extends known bias work to building level and censoring) | Medium (Speculation Watch List and WoW are adjacent, but causal estimates are rarer) |
| Risk | Latent-variable identification is arguable, must be honest about assumptions | Entity resolution and sale-selection bias (buyers pick buildings) |
| Resume value | Statistical modeling, fairness, causal thinking | Causal inference, big data engineering |

**Recommendation.** Make **Spin 1 the headline** ("The buildings NYC can't hear") and **Spin 2 a second act that uses Spin 1's output**: *do silent-distress buildings get worse after a sale faster than loud ones?* That gives one coherent story, two methodologies, and the interview line "I found where the city's complaint-driven system is blind, then tested what happens there". Spin 2 is gated on a feasibility spike (Phase 4) so the project is still strong if entity resolution proves too painful.

## 3. Prediction target and validation

### 3.1 Unit and time
- Unit: **building** (BIN where possible, else BBL tax lot). Residential multi-family 3+ units to start (the set HPD actually regulates). PLUTO `bldgclass`/`unitsres` filters this.
- Time: monthly or quarterly **as-of snapshots**. Features use only records dated <= snapshot date; label looks at the next 12 months.

### 3.2 Defining "distress" (the part to get right)
Two kinds of signals, kept strictly apart:

- **Complaint-driven (loud):** HPD complaints/problems, 311 housing complaints, HPD violations from complaints. Reflect condition *and* propensity to complain.
- **Complaint-independent outcomes ("ground truth"):** events triggered by the city or courts rather than a tenant calling: HPD **emergency repair / OMO charges** (`mdbu-nrqn`), **vacate orders** (`tb8q-a3ar`), **AEP selection** (`hcir-3275`), HPD **litigation** by the city (`59kj-x8nc`), **DOB hazardous/ECB** violations, demolition, tax-lien/foreclosure (to be checked).

**Primary target (v1):** *serious distress event in the next 12 months* = any of {vacate order, AEP selection, new HPD litigation, OMO emergency repair charges above a threshold}. Rare event, so report PR-AUC and precision@k, not accuracy.

**Silent-distress score:** fit the condition model on complaint-independent outcomes using non-complaint features (age, construction year, building class, ownership type, DOB activity, energy data, boiler/elevator violations, rent stabilization signals, neighborhood context). Compare predicted condition to *observed complaint rate*; large positive gap = silent. Then validate: do high-gap buildings experience more serious events in the following year than low-gap buildings with the same complaint count? That is the testable claim.

### 3.3 Leakage control (non-negotiable, interviewers probe this)
- Temporal split only (train years <= T, validate T+1, test T+2). Never random split. Spatial block CV as a second check.
- Features computed *as of* each snapshot. Snapshot-less sources (**PLUTO, HPD registrations, ownership are "current state" only**) are a known leakage risk: either archive monthly pulls going forward, use the dated PLUTO releases from DCP, or restrict to static fields (year built, lot area) and say so.
- Label events must postdate the feature window; the label definition must not include any feature source.
- Report calibration, not just ranking. Baselines: prior-12-month violation count, then HPD-style rules, then the model. Beating a naive "last year's violations" baseline is the real bar.

## 4. Datasets (verified; details in DATASETS.md)

| Role | Dataset | ID | Live status |
|---|---|---|---|
| Violations | HPD Housing Maintenance Code Violations | `wvxf-dwi5` | updated 2026-11-12, about 11.4M rows live |
| Complaints | HPD Complaints and Problems | `ygpa-z7cr` | updated 2026-10-21, about 14.1M rows |
| Complaints | 311 Service Requests 2020-present | `erm2-nwe9` | updated 2026-11-11 |
| Evictions | Evictions (marshal executed) | `6z8x-wfk4` | updated 2026-11-01, 136,544 rows, 2017-2026 |
| Litigation | HPD Housing Litigations | `59kj-x8nc` | updated 2026-11-01, 242k rows |
| Outcomes | OMO / emergency repair charges | `mdbu-nrqn` | updated 2026-10-28 |
| Outcomes | Vacate orders | `tb8q-a3ar` | updated 2026-11-11 |
| Outcomes | AEP selected buildings | `hcir-3275` | updated 2026-10-01 |
| Construction | DOB Violations | `3h2n-5cm9` | updated 2026-11-08, 2.48M rows |
| Construction | DOB NOW job filings | `w9ak-ipjd` | updated 2026-11-10, 982k rows |
| Ownership | HPD Multiple Dwelling Registrations | `tesw-yqqr` | updated 2026-11-04, 187k rows |
| Ownership | HPD Registration Contacts | `feu5-w2e2` | updated 2026-11-04, 745k rows |
| Sales | ACRIS Master / Legals / Parties | `bnx9-e6tj` / `8h5j-fqxa` / `636b-3b5g` | updated 2026-11-10, Master 17.1M rows |
| Sales | Citywide Rolling Calendar Sales | `usep-8jbt` | updated 2026-10-15 |
| Watchlist | Speculation Watch List | `adax-9mit` | updated 2026-05-07 |
| Context | PLUTO | `64uk-42ks` | updated 2026-08-24, 858k lots |
| 3D | Building footprints (heights, BIN) | `5zhs-2jue` | updated 2026-11-08, 1.08M buildings |

**Data-quality findings from real samples (these go in the README, interviewers love this):**
- HPD violations **does have a `bbl` column** (an earlier version of this plan said it did not, which was wrong): 0.08% null in the Phase 1 pull. It disagrees with the BBL built from `boroid` + `block` (5 digits) + `lot` (4 digits) in 0.42% of rows, mostly condo billing lots (lot 29 stored as 7501). **Use the stored `bbl`, fall back to the built one.** Also carries `BIN` and `BuildingID`.
- HPD violations `inspectiondate` minimum is **year 0217**: bad dates exist and must be cleaned. On the server, Bronx+Brooklyn has 352,703 violations dated before 2000 (134 before 1970, which are garbage; 185,793 in 1970-1989 look like legacy records). The Phase 1 pull starts at 2018, so none of these are in the raw data. Rows that survived still have 23 future `currentstatusdate` values (2108, 9202); litigation `caseopendate` has 2 values in 2030; vacate `vacate_effective_date` has 15 up to 2040; OMO `omoawarddate` has year-0910 values; one DOB `issue_date` is unparseable.
- PLUTO `bbl` is stored as text like `'3085280034.00000000'`: cast through double before joining. A naive string join reported 0% coverage until fixed.
- **Source duplicates** exist: `hpd_reg_contacts` has 1,451 duplicate `registrationcontactid` values (388 exact repeats plus conflicting versions), `hpd_registrations` 5, `hpd_aep` 1. Every other keyed table is unique. Staging needs a dedupe rule.
- **BBL join coverage to PLUTO** (Bronx/Brooklyn) is about 99% of distinct BBLs for violations, complaints, 311, litigations and registrations; 93.9% for DOB; evictions 99.0% of distinct BBLs but 91.4% of rows because 7.5% of eviction rows have no bbl. The citywide pulls (OMO charges, vacate orders, AEP) match only 59-78% because PLUTO here is two boroughs.
- **Inspector no-access (the censoring basis), measured:** 15.68% of 4,099,685 HPD complaint problem rows and 16.66% of 2,408,241 distinct complaints say the inspector "was not able to gain access" (19.62% of rows if "unable to complete the inspection" is included). Brooklyn 17.72% vs Bronx 13.88%; by year 18.0% (2018), 20.2% (2019), 17.5% (2020), 13.8% (2021), 14.6% (2022), 13.7% (2023), 15.9% (2024), 15.2% (2025), 13.7% (2026).
- Pulled sizes, Bronx+Brooklyn from 2018 (see `DATASETS.md`): violations 4.72M, complaints 4.10M, 311 HPD 2.93M, OMO 517k (citywide), contacts 745k (citywide), PLUTO 365k, DOB violations 257k, registrations 107k, evictions 68k, litigations 52k, vacate orders 9k, AEP 4k.
- Metadata said 8.35M violation rows but a live count returned 11.38M; trust live counts, record the pull date.
- Evictions: 123,928 of 136,544 rows (90.8%) have a BBL; the rest need geocoding by BIN or address.
- Litigation `respondent` is a free-text list of people and LLCs, useful for the ownership graph.
- HPD complaint rows include inspector-access outcome text, which is the basis of the censoring idea.
- The Socrata API was flaky during checks (503s, slow aggregates). Plan for **bulk CSV/Parquet downloads** with retries, not live API queries.
- To check in Phase 1: ECB/OATH violations, DOF tax liens, rent stabilization lists, heat/hot-water sensor data, FDNY incidents, DOHMH rat inspections, Local Law 84 energy data, 311 internal 'HPD' categories, PLUTO historical releases.

## 5. Architecture

```
Socrata bulk export  ->  raw/ (immutable Parquet, pull date in filename)
        |
   DuckDB + dbt-duckdb (or plain SQL files)
        |-- staging: typed, cleaned, BBL/BIN keys built, bad dates flagged
        |-- entity: building spine (BIN<->BBL<->BuildingID crosswalk)
        |-- features: monthly as-of snapshots per building
        |-- labels: 12-month forward outcomes
        v
  marts/ (Parquet)  ->  models (LightGBM, hierarchical Bayes for reporting propensity)
        |                       |
        |                       +-> scores.parquet
        +-> DuckDB file  ->  LLM layer (text-to-SQL + RAG)
                          ->  3D app (vector tiles + deck.gl)
```
Rules: raw data never committed to git; every step reproducible from `make` targets; data tests (row counts, key uniqueness, date ranges) run in CI.

## 6. Modeling approach

1. **Baselines:** last-12-month violations; HPD-style rule score.
2. **Gradient boosting (LightGBM)** on as-of features for the primary target, with SHAP.
3. **Reporting-propensity model:** hierarchical Bayesian (PyMC or numpyro) or a two-stage model where observed complaint counts = Poisson(latent condition x propensity), propensity varies by neighborhood and demographics proxies (ACS tract data, language, tenure). Include the access-denied censoring as an explicit mechanism.
4. **Silent-distress gap** = predicted condition rank minus observed complaint rank, with uncertainty intervals.
5. **Fairness/ablation:** show that a naive complaint-trained model concentrates predictions where people already complain, and quantify the shift.
6. **Spin 2:** staggered DiD / event study around sale date (`document_date` of DEED docs from ACRIS Master joined through Legals by `document_id`), matched controls, dynamic effects +/- 24 months, split by silent vs loud.

## 7. LLM layer (and where RAG earns its place)

Rule: RAG goes in only where it beats a plain SQL baseline in an eval. Text-to-SQL over structured tables is **not** RAG and is labelled as such.

**What the text data actually looks like (measured on the full Phase 1 pull, 2026-11-13; this replaces the earlier skim-based assumption, which had HPD as thin and DOB as rich):**
- **HPD violation descriptions** (`novdescription`, 4.72M rows, median 184 characters, max 1,301): **50.7% of rows are distinct** after lowercasing and mapping digits to `#` (2,390,022 distinct texts); the top 10 / 100 / 1000 texts cover only 16.5% / 19.8% / 25.3% of rows. Two boilerplate texts (bedbug report, owner registration) account for about 684k rows, but most of the rest is a **code citation plus condition and location detail** ("mold ... north wall ... apt 1R, 1st story", "four free standing radiators at public hall"). So there is real condition and location text to work with, more than the skim suggested.
- **DOB violation descriptions** (256,821 rows): **only 9.7% distinct**; the top 10 / 100 / 1000 texts cover 80.9% / 88.8% / 90.6% of rows, and the top five are boiler, elevator and energy-report compliance filings (low-pressure boiler inspection, failure to certify ECB correction, annual boiler report, energy benchmarking). **14.6% of rows have no description.** DOB text is mostly templated compliance paperwork, not the free-form structural-risk text assumed earlier. Structured fields (violation type code, category) carry most of it.
- **HPD complaint** `status_description` is boilerplate (including the inspector no-access text), useful as a categorical flag, not for embeddings. The 311 and HPD complaint categories (`major_category`, `minor_category`, `problem_code`) are already structured.
- Verdict: the **main text test cases are HPD `novdescription` features and evidence retrieval over HPD text**; **DOB text is a minor case**. RAG is still scoped narrowly and must pass the eval gate below.

**Components:**
1. **Text-to-SQL (not RAG)** over the DuckDB marts, read-only, schema docs and few-shot examples, with a gold set of 50+ questions and execution-accuracy reporting. This is the primary way to answer factual questions about a building.
2. **Evidence retrieval for building biographies (RAG, gated).** Embed HPD violation text first (the richest source, see above), with DOB/ECB and litigation text as a minor addition, so the biography can pull the most relevant records out of a building's thousands and cite each claim by record id; also supports semantic search across buildings ("recurring ceiling collapse and no heat"). Eval: compare against a SQL-only baseline (latest and highest-class records) on (a) citation faithfulness, (b) human-rated relevance on about 30 buildings. **If retrieval does not beat the SQL baseline, drop it** and keep the SQL-only biography.
3. **Code retrieval (RAG, small).** Retrieve passages of the Housing Maintenance Code and HPD violation-class definitions so the model explains what a Class A/B/C violation means and cites the section. Corpus is small and public; need to confirm a clean source and licence in Phase 7.
4. **Text-derived severity features (experiment).** Embeddings or keyword flags (no heat, collapse, mold, vermin) as extra model features, built mainly from HPD `novdescription` (DOB only as a minor addition); keep only if they improve out-of-time PR-AUC over class and code features.

Every generated sentence must cite a record id, checked by a verifier pass. Model: Claude API; keys in `.env`, never in the repo.

## 8. 3D visualization

- Extruded footprints from `5zhs-2jue` (`height_roof`, BIN) at citywide scale: about 1.08M polygons, so convert to **PMTiles/vector tiles with tippecanoe** and render with **MapLibre GL + deck.gl** (or MapLibre fill-extrusion).
- Height = actual building height (honest geometry); **color = silent-distress score**; optional second mode with height encoding risk for contrast. Click a building to open the LLM biography panel.
- Time slider through monthly scores, and a "sale event" overlay (buildings that changed hands).
- Static notebook companion: PyDeck/Kepler export plus 2D matplotlib for the paper-style figures.
- Possible stretch: cinematic fly-through render for the README GIF.

## 9. Recommended stack

Python 3.12, uv; DuckDB + Parquet; dbt-duckdb (optional, good resume signal); polars/pandas; scikit-learn, LightGBM, SHAP; PyMC or numpyro; `differences`/`csdid` style DiD packages or hand-rolled estimators; Jupyter + Quarto for narrative notebooks; FastAPI for the LLM backend; Claude API; sentence-transformers + LanceDB or DuckDB `vss` for retrieval; MapLibre + deck.gl + tippecanoe + PMTiles; pytest, ruff, pre-commit, GitHub Actions; Dockerfile for reproducibility.

## 10. Proposed repo layout

```
NYC_OpenData/
  README.md                 # story, 3 figures, GIF of the 3D map, how to run
  docs/  PROJECT_PLAN.md  DATASETS.md  methodology.md  decisions/ (ADRs)
  data/  raw/ (gitignored)  interim/ (gitignored)  sample/ (tiny committed fixtures)
  pipelines/  ingest/  sql/staging  sql/marts  tests/
  notebooks/  01_data_audit  02_eda  03_labels_and_leakage  04_models  05_silent_distress  06_after_the_sale
  src/nycdistress/  io  features  models  eval  llm  geo
  app/  web/ (3D map)  api/ (FastAPI)
  evals/  text2sql_gold.jsonl  rag_faithfulness/
  Makefile  pyproject.toml  .env.example  .gitignore
```
Large data stays out of git; ship a `make sample` that pulls a one-borough slice so a stranger can run it in minutes.

## 11. Roadmap (each phase stands alone)

| Phase | Deliverable | Done when |
|---|---|---|
| 0. Scaffold | Repo layout, Makefile, uv env, gitignore, CI skeleton | `make setup` works on a clean machine |
| 1. Ingest and audit | Bulk pulls to Parquet, key crosswalk, data-quality notebook | Audit notebook reports row counts, date ranges, join coverage, known defects; PLUTO-history decision made |
| 2. Building spine and features | Building x month as-of feature table plus labels | Leakage tests pass; label prevalence documented |
| 3. Baseline predictive model | Temporal-split LightGBM, calibration, SHAP | Beats last-year baseline on PR-AUC and precision@k |
| 4. Silent distress | Reporting-propensity model, gap score, outcome validation | High-gap buildings show statistically more later events than matched low-gap ones |
| 5. After the sale (gated) | ACRIS sale panel, entity resolution spike, event study | Feasibility spike passes, then DiD results by silent/loud |
| 6. 3D map | PMTiles build, deck.gl app, building panel | Citywide map loads under a few seconds, deployable static site |
| 7. LLM layer | Text-to-SQL with eval set, RAG biographies | Reported execution accuracy and faithfulness |
| 8. Polish | README, figures, short write-up/preprint-style report, demo video | A stranger understands the finding in 2 minutes |

Phases 3 to 7 can reorder after Phase 2; Phase 6 can start in parallel with Phase 3 using placeholder scores.

## 12. Risks

- **Silent-distress identification is assumption-heavy.** Mitigate with complaint-independent validation and explicit sensitivity analysis.
- **Current-state-only datasets** (PLUTO, registrations) can leak the future. Mitigate as in 3.3.
- **Entity resolution** of LLC owners could eat weeks. Mitigate with the Phase 5 feasibility gate.
- **API instability / size.** Bulk download plus caching.
- **Ethics and framing.** Neighborhood propensity can proxy for race/income. Aggregate for publication, avoid naming individual landlords or tenants, frame as inspection targeting, not blame.
- **Compute.** Everything should run on a laptop through DuckDB; avoid cluster tooling.
- **Scope creep.** The LLM layer and 3D map are showcase pieces; the finding is the core.

## 13. Decisions (all eight accepted on 2026-11-13)

1. **Headline question:** silent distress (recommended) vs plain prediction vs sale-first. *Recommend silent distress with sale as act two.*
2. **Geography for v1:** citywide vs one or two boroughs. *Recommend Brooklyn plus Bronx first (dense, high HPD activity), then scale citywide once the pipeline is solid.*
3. **Time window:** 2017 onward (matches evictions) vs 2020 onward (311 data). *Recommend 2018 to present with 311 supplementing HPD complaints, since HPD complaints go back further.*
4. **Orchestration:** Makefile + dbt-duckdb (simple) vs Dagster/Airflow. *Recommend the simple version; mention orchestration in the README as a next step.*
5. **3D delivery:** hosted static site (GitHub Pages + PMTiles) vs notebook only. *Recommend static site, it is the best interview demo.*
6. **LLM provider and spend:** Claude API for text-to-SQL and RAG. *Recommend yes, small budget, keys out of the repo.*
7. **Publication ambition:** portfolio only vs also an arXiv-style write-up for lab appeal. *Recommend writing it as a short paper regardless; the structure forces rigor.*
8. **Data hosting:** raw data never in git; share a derived sample only. *Recommend this.*
