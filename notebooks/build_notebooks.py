"""Build and execute the narrative notebooks (they render from committed outputs only).

    python notebooks/build_notebooks.py          # writes notebooks/*.ipynb with outputs saved

The notebooks never read data/raw or data/processed, so they run on a fresh clone of the repository.
"""
import sys
from pathlib import Path

import nbformat
from nbconvert.preprocessors import ExecutePreprocessor

HERE = Path(__file__).resolve().parent
NB = {}


def notebook(name, cells):
    nb = nbformat.v4.new_notebook()
    nb.metadata["kernelspec"] = {"display_name": "Python 3", "language": "python", "name": "python3"}
    nb.cells = [nbformat.v4.new_markdown_cell(t) if k == "md" else nbformat.v4.new_code_cell(t) for k, t in cells]
    NB[name] = nb


# ------------------------------------------------------------------------------------------------------------------ 01
notebook("01_data_audit", [
    ("md", """# 01 Data audit: what was pulled and what is wrong with it

Twelve NYC Open Data tables, Bronx and Brooklyn, 2018 onward, pulled with a resumable keyset-paged Socrata client into raw Parquet (gitignored). This notebook renders the
audit that `pipelines/audit.py` wrote to [`docs/data_audit.md`](../docs/data_audit.md); it does not touch the raw data.

**The two findings that shape everything after this:**
1. About one in six closed HPD complaint problems ends with *the inspector could not gain access*. That is a censoring mechanism: no inspection, no violation.
2. HPD violation text is mostly free-form (half of the texts are unique after normalising), so text is a hard signal to use (Phase 7 tests that).
"""),
    ("code", r'''from nbutil import *
import re
audit = (DOCS / "data_audit.md").read_text()
section = lambda a, b: audit.split(a, 1)[1].split(b, 1)[0]

rows = re.findall(r"^- (\w+): ([\d,]+) rows, (\d+) columns", section("## Row counts and manifests", "## Key uniqueness"), flags=re.M)
counts = pd.DataFrame(rows, columns=["table", "rows", "ncols"]).assign(rows=lambda d: d.rows.map(num), ncols=lambda d: d.ncols.map(num))
fig, ax = plt.subplots(figsize=(7, 3.6))
d = counts.sort_values("rows")
ax.barh(d.table, d.rows / 1e6, color=BLUE)
ax.set_xlabel("rows (millions)")
ax.set_title(f"{counts.rows.sum() / 1e6:.1f}M rows in {len(counts)} tables")
plt.show()'''),
    ("md", """## Keys and joins

Every table that has a natural key was tested for duplicates. The BBL (borough-block-lot, the building's tax lot id) is the join key across tables; the audit measures how many distinct BBLs in each table exist in PLUTO (the lot table).
The three tables that match only 60 to 78% are the ones pulled **citywide** (no borough filter in `pipelines/ingest/datasets.py`: OMO charges, vacate orders, AEP), so their misses are lots outside the Bronx and Brooklyn, not join failures."""),
    ("code", r'''cov = []
for name, a, b, pct in re.findall(r"^- ([^:]+): .*?distinct bbl ([\d,]+), in PLUTO ([\d,]+) \(([\d.]+)%\)", section("## BBL quality", "## HPD complaints"), flags=re.M):
    cov.append((name, num(a), num(b), float(pct)))
cov = pd.DataFrame(cov, columns=["table", "distinct_bbl", "in_pluto", "pct_in_pluto"])
fig, ax = plt.subplots(figsize=(7, 3.8))
d = cov.sort_values("pct_in_pluto")
ax.barh(d.table, d.pct_in_pluto, color=[RED if p < 95 else BLUE for p in d.pct_in_pluto])
ax.set_xlim(50, 100); ax.set_xlabel("% of distinct BBLs found in PLUTO")
plt.show()
cov.round(1)'''),
    ("code", r'''dups = re.findall(r"^- (\w+) key \(([^)]*)\): ([\d,]+) rows, ([\d,]+) distinct, duplicates ([\d,]+)", section("## Key uniqueness", "## Date sanity"), flags=re.M)
pd.DataFrame(dups, columns=["table", "key", "rows", "distinct", "duplicates"]).assign(duplicates=lambda d: d.duplicates.map(num)).query("duplicates > 0")'''),
    ("md", """Only registrations, registration contacts and AEP have duplicate keys; they are deduplicated in staging with documented rules (newest registration, most complete contact row, the AEP row that has a discharge date).

## Censoring: complaints closed because the inspector could not get in

HPD closes a complaint problem with a status text. One of those texts says HPD "was not able to gain access". The share is large and differs by borough and year."""),
    ("code", r'''na = section("## HPD complaints: inspector no-access", "## Text diversity")
by_year = pd.DataFrame(re.findall(r"(\d{4}) ([\d.]+)%", re.search(r"strict rate by year: (.*)", na).group(1)), columns=["year", "pct"]).astype({"pct": float})
by_boro = pd.DataFrame(re.findall(r"([A-Z]+) ([\d.]+)%", re.search(r"strict rate by borough: (.*)", na).group(1)), columns=["borough", "pct"]).astype({"pct": float})
fig, (a, b) = plt.subplots(1, 2, figsize=(9, 3.2), gridspec_kw={"width_ratios": [3, 1.2]})
a.plot(by_year.year, by_year.pct, "-o", color=BLUE); a.set_ylim(0, 25); a.set_ylabel("% of closed problems"); a.set_title("No-access share by year (2026 is partial)")
b.bar(by_boro.borough, by_boro.pct, color=[RED, BLUE]); b.set_ylim(0, 25); b.set_title("By borough")
plt.tight_layout(); plt.show()
print(re.search(r"- strict 'not able to gain access' rows: (.*)", na).group(0))'''),
    ("md", """Reading: about 16% of closed problems (17% of distinct complaints) end with no access. Brooklyn is higher than the Bronx. Phase 4 asks whether buildings where this happens a lot are quietly worse off; the answer there is no (see notebook 04).

## How templated is the text?"""),
    ("code", r'''td = section("## Text diversity", "\x00") if "\x00" in audit else audit.split("## Text diversity", 1)[1]
out = []
for col, a, b, c in re.findall(r"- (\S+): .*?top 10 / 100 / 1000 normalized texts cover ([\d.]+)% / ([\d.]+)% / ([\d.]+)% of rows", td):
    out.append((col, float(a), float(b), float(c)))
pd.DataFrame(out, columns=["column", "top 10 cover %", "top 100 cover %", "top 1000 cover %"])'''),
    ("md", """HPD violation descriptions are mostly unique (top 1,000 texts cover about a quarter of rows), while DOB descriptions are heavily templated (top 100 cover 89%). That is why the Phase 7 text experiments were worth running and why they could have gone either way.

## Takeaways
- Pull is complete (every manifest says `complete=True`) and keys are clean; the only real join loss is the three citywide tables.
- The no-access mechanism is real and sizeable. It is a **property of the measurement**: the absence of a violation can mean nobody got in to look.
- Dates contain impossible values in a few columns (e.g. year 9202, 2040) that are filtered by the stated rule in Phase 2, not ignored.
"""),
])

# ------------------------------------------------------------------------------------------------------------------ 02
notebook("02_labels_and_leakage", [
    ("md", """# 02 Labels, features and the leakage tests

Grain: one row per building lot and quarterly snapshot (28 snapshots, 2019-01-01 to 2025-10-01; 2.81M rows, 82 features). Features see only what was known at the snapshot; labels look at the **next 12 months**.
This notebook shows (a) the convention that keeps the two windows from touching, (b) how the labels behave, (c) what is missing by design, and (d) the tests that make leakage fail loudly.
Numbers come from [`docs/labels_and_features.md`](../docs/labels_and_features.md), generated by the pipeline."""),
    ("md", """## The quarter-bucket convention, as a toy

Every event is assigned to the quarter *ending* at or after its date. An event dated exactly on a snapshot belongs to the bucket that ends there, so it is a **feature** at that snapshot and can never be its **label**."""),
    ("code", r'''from nbutil import *
SNAPS = pd.date_range("2022-01-01", "2024-01-01", freq="QS")
def bucket_end(d):
    d = pd.Timestamp(d)
    q = SNAPS[SNAPS >= d]
    return q[0] if len(q) else None
t = pd.Timestamp("2023-01-01")
events = ["2022-01-02", "2022-06-30", "2022-12-31", "2023-01-01", "2023-01-02", "2023-09-30", "2024-01-01"]
rows = []
for e in events:
    b = bucket_end(e)
    where = "feature (past 12 months)" if t - pd.DateOffset(months=12) < b <= t else ("LABEL (next 12 months)" if t < b <= t + pd.DateOffset(months=12) else "outside")
    rows.append((e, b.date() if b is not None else None, where))
pd.DataFrame(rows, columns=["event date", "bucket ends", f"role at snapshot {t.date()}"])'''),
    ("md", """## The leak that needed care: no-access closure

"The inspector could not gain access" is only known when a complaint problem **closes**. Keyed on the receipt date, a snapshot would "know" the outcome of a complaint that was still open. The features therefore use the closure date. Toy:"""),
    ("code", r'''toy = pd.DataFrame({"problem": ["A", "B", "C"], "received": pd.to_datetime(["2022-11-20", "2022-12-10", "2022-12-28"]),
                    "closed": pd.to_datetime(["2022-12-01", "2023-02-15", "2022-12-30"]), "no_access": [True, True, False]})
t = pd.Timestamp("2023-01-01")
toy["wrong (receipt date)"] = toy.received <= t
toy["right (closed by t)"] = toy.closed <= t
print("no-access problems counted at t by the WRONG rule:", int((toy["wrong (receipt date)"] & toy.no_access).sum()),
      "| by the RIGHT rule:", int((toy["right (closed by t)"] & toy.no_access).sum()))
toy'''),
    ("md", """Problem B was received before the snapshot but only closed (as no access) in February, so the wrong rule would leak a 2023 outcome into a 2023-01-01 feature.

## Label behaviour"""),
    ("code", r'''P = DOCS / "labels_and_features.md"
lab = md_table(P, "### Label prevalence, overall and by borough")
for c in lab.columns[1:]:
    lab[c] = lab[c].map(num)
lab'''),
    ("code", r'''d = lab[lab.slice != "all"].set_index("slice")[["omo", "litigation", "vacate", "aep", "serious_any"]]
d.T.plot.bar(figsize=(7, 3.2), color=[BLUE, RED], rot=0)
plt.ylabel("% of building-snapshots with the event in the next 12 months"); plt.title("The Bronx is far sicker on every label"); plt.show()'''),
    ("md", """78% of `any serious event` is emergency-repair (OMO) charges. HPD enforcement is rule driven off violation counts: AEP selects by open class B and C violations and repairs follow uncorrected hazardous violations. So **a violation count predicts these labels almost by construction**, which is why the Phase 3 baseline is hard to beat, and why Phase 4 needed a less circular target.

## Missing by design

A feature window that reaches back before a source's first covered date is NULL, not 0: "no events" and "not observed" must not look alike."""),
    ("code", r'''miss = md_table(P, "### Missing-by-design windows")
miss = miss.set_index("year").astype(float)
import matplotlib.pyplot as plt
fig, ax = plt.subplots(figsize=(7.5, 3))
im = ax.imshow(miss.iloc[:, :4].T.values, aspect="auto", cmap="Blues", vmin=0, vmax=1)
ax.set_xticks(range(len(miss))); ax.set_xticklabels(miss.index); ax.set_yticks(range(4)); ax.set_yticklabels(miss.columns[:4]); ax.grid(False)
ax.set_title("NULL share of the 36 month and 311 windows, by snapshot year (1 = never observed)")
plt.colorbar(im); plt.show()'''),
    ("md", """## The sanity baseline (not a model)

A single column used as a score: HPD violations in the prior 12 months, on the last two snapshots."""),
    ("code", r'''md_table(P, "### Smoke baseline", 0)'''),
    ("md", """## The tests that guard the pipeline

All run on a synthetic raw fixture with hand-placed edge dates, no real data needed (`make test`). The most important:"""),
    ("code", r'''import ast
src = (ROOT / "tests" / "test_features.py").read_text()
tests = [(n.name, (ast.get_docstring(n) or "").split("\n")[0]) for n in ast.parse(src).body if isinstance(n, ast.FunctionDef) and n.name.startswith("test_")]
pd.DataFrame(tests, columns=["test", "what it checks"]).set_index("test")'''),
    ("md", """Mutation check (done by hand and recorded in the docs): deliberately breaking the SQL (features reading one bucket ahead, a label window that overlaps t, no-access keyed on the receipt date) makes the matching test fail; restoring it makes it pass.
Real-data checks: the pandas brute-force oracle found 0 mismatches on 100 sampled (building, snapshot) rows across 76 columns, and 0 label-identity exceptions over 2.4M snapshot pairs.

## Known approximations (not errors)
Open-violation counts are approximate and undercounted before 2018; the spine uses today's PLUTO; static fields are current-state; the source tables are edited in place. All are listed in section 7 of the doc."""),
])

# ------------------------------------------------------------------------------------------------------------------ 03
notebook("03_model_results", [
    ("md", """# 03 Model results: does a fitted model beat the obvious rule?

Target: any serious event (vacate order, emergency-repair charge, AEP selection or new litigation) in the next 12 months.
Validation: strictly temporal walk-forward folds with a 12 month purge gap; the final test slice is the last four snapshots (2025-01-01 to 2025-10-01), scored once.
Intervals are cluster bootstraps by building. Source tables: `reports/phase3/*.csv`. Full write-up: [`docs/modeling_phase3.md`](../docs/modeling_phase3.md)."""),
    ("code", r'''from nbutil import *
m = pd.read_csv(REPORTS / "phase3" / "metrics_test_ci.csv")
def get(model, fset, metric, target="label_serious_any", slc="all"):
    r = m[(m.target == target) & (m.slice == slc) & (m.model == model) & (m.fset == fset) & (m.metric == metric)].iloc[0]
    return r.point, r.lo, r.hi
rows = [("violations last 12m (rule)", "rule_viol_12m", "-"), ("complaints last 12m (rule)", "rule_complaints_12m", "-"), ("most recent event (rule)", "rule_last_event", "-"),
        ("logistic regression", "logit", "all"), ("LightGBM", "lgb", "all")]
tab = pd.DataFrame([(n, *get(mo, fs, "pr_auc"), *get(mo, fs, "roc_auc")) for n, mo, fs in rows],
                   columns=["model", "PR-AUC", "pr_lo", "pr_hi", "ROC-AUC", "roc_lo", "roc_hi"])
fig, ax = plt.subplots(1, 2, figsize=(10, 3.2))
for a, (c, lo, hi) in zip(ax, [("PR-AUC", "pr_lo", "pr_hi"), ("ROC-AUC", "roc_lo", "roc_hi")]):
    a.barh(tab.model[::-1], tab[c][::-1], xerr=[(tab[c] - tab[lo])[::-1], (tab[hi] - tab[c])[::-1]], color=[BLUE, GREY, GREY, GREY, GREY][::-1], capsize=3)
    a.set_xlabel(c); a.set_xlim(tab[c].min() * 0.8 if c == "PR-AUC" else 0.6, 1 if c == "ROC-AUC" else 0.75)
plt.suptitle("Final test slice, any serious event (95% CI)"); plt.tight_layout(); plt.show()
tab.round(3)'''),
    ("md", """LightGBM beats each simple rule on both PR-AUC and ROC-AUC, but the rules are a **strong** baseline: enforcement is rule driven off violation counts, so the label is partly circular with it. Most of the gain is already available to a logistic regression.

## It wins everywhere, not just on average"""),
    ("code", r'''ps = pd.read_csv(REPORTS / "phase3" / "per_snapshot.csv", parse_dates=["snapshot_date"])
fig, ax = plt.subplots(figsize=(8, 3.2))
for name, mo, fs, col, ls in [("rule: violations 12m", "rule_viol_12m", "-", GREY, "--"), ("logistic", "logit", "all", GREEN, "-"), ("LightGBM", "lgb", "all", BLUE, "-")]:
    d = ps[(ps.model == mo) & (ps.fset == fs)].sort_values("snapshot_date")
    ax.plot(d.snapshot_date, d.pr_auc, ls, color=col, marker="o", ms=3, label=name)
ax.set_ylabel("PR-AUC"); ax.set_title("16 out-of-time snapshots"); ax.legend(frameon=False); plt.show()
a = ps[(ps.model == "lgb") & (ps.fset == "all")].set_index("snapshot_date").pr_auc
b = ps[(ps.model == "rule_viol_12m")].set_index("snapshot_date").pr_auc
print(f"LightGBM beats the rule at {(a > b).sum()} of {len(a)} snapshots; PR-AUC gap {((a - b).min()):.3f} to {((a - b).max()):.3f}")'''),
    ("md", """## What each feature group adds (ablation)

Removing complaint-derived features costs little; removing violation features costs more; removing both still beats the rule, narrowly. The groups substitute for each other."""),
    ("code", r'''ab = pd.DataFrame([(fs, *get("lgb", fs, "pr_auc")) for fs in ["all", "no_loud", "no_viol", "static_prior"]], columns=["feature set", "PR-AUC", "lo", "hi"])
rule = get("rule_viol_12m", "-", "pr_auc")[0]
fig, ax = plt.subplots(figsize=(6.5, 2.8))
ax.barh(ab["feature set"][::-1], ab["PR-AUC"][::-1], xerr=[(ab["PR-AUC"] - ab.lo)[::-1], (ab.hi - ab["PR-AUC"])[::-1]], color=BLUE, capsize=3)
ax.axvline(rule, color=RED, ls="--"); ax.text(rule, 3.45, " violations rule", color=RED, fontsize=8); ax.set_xlim(0.5, 0.7); ax.set_xlabel("PR-AUC (test slice)")
plt.show(); ab.round(3)'''),
    ("md", """## Where the model helps most: buildings the rule would not flag

`quiet` = no class C violation and at most 2 violations last year (82% of rows). `clean_record` is stricter. The rule is almost useless there; the model keeps some signal, mostly from static building attributes."""),
    ("code", r'''rows = []
for s in ["all", "quiet", "clean_record"]:
    rows.append((s, get("rule_viol_12m", "-", "roc_auc", slc=s)[0], get("lgb", "all", "roc_auc", slc=s)[0], get("lgb", "all", "pr_auc", slc=s)[0], get("lgb", "all", "base_rate", slc=s)[0]))
pd.DataFrame(rows, columns=["slice", "ROC-AUC rule", "ROC-AUC LightGBM", "PR-AUC LightGBM", "base rate"]).round(3)'''),
    ("md", """## Calibration"""),
    ("code", r'''c = pd.read_csv(REPORTS / "phase3" / "calibration_test.csv")
c = c[(c.target == "label_serious_any") & (c.model == "lgb") & (c.fset == "all")]
fig, ax = plt.subplots(figsize=(4.2, 4))
ax.plot([0, c.mean_pred.max()], [0, c.mean_pred.max()], color=GREY, ls="--"); ax.plot(c.mean_pred, c.observed, "o-", color=BLUE)
ax.set_xlabel("mean predicted"); ax.set_ylabel("observed rate"); ax.set_title("Deciles of the score, test slice"); plt.show()'''),
    ("md", """Probabilities are well calibrated (ECE about 0.006) and slightly high, because the test base rate (8.5%) is below the training average. No recalibration was applied.

## What the score is made of (SHAP shares)"""),
    ("code", r'''sg = pd.read_csv(REPORTS / "phase3" / "shap_groups.csv")
sg = sg[sg.fset == "all"].sort_values("share")
fig, ax = plt.subplots(figsize=(6, 2.8)); ax.barh(sg.group, 100 * sg.share, color=BLUE); ax.set_xlabel("% of mean |SHAP|"); plt.show()'''),
    ("md", """Complaints take 40% and violations 24%, but because those two are correlated SHAP overstates what each uniquely adds; the ablation above is the cleaner evidence.

## Figures from the pipeline"""),
    ("code", r'''from IPython.display import Image, display
for f in ["slices.png", "shap_beeswarm.png"]:
    display(Image(filename=str(REPORTS / "phase3" / "figures" / f), width=700))'''),
    ("md", """## What this does and does not show
- **Does:** a model out-ranks the naive violation rule, out of time, at all 16 snapshots, and generalises to community districts it has not seen (held-out districts leave ROC-AUC unchanged at 0.93).
- **Does not:** it predicts city *enforcement events*, not physical condition. A high score mostly means the city is already engaged with the building. Borough and building class are strong static features and need a fairness review before any use for targeting.
"""),
])

# ------------------------------------------------------------------------------------------------------------------ 04
notebook("04_silent_distress", [
    ("md", """# 04 Silent distress: do buildings that NYC does not hear from hide danger?

The hypothesis: buildings whose *non-complaint* profile looks bad but whose complaint record is empty ("silent") carry hidden risk. The test: fit a condition model **without complaint information**, flag the top decile of the within-borough gap between predicted condition and complaint volume, and ask whether silent buildings later have *more* serious outcomes than their predicted condition implies, or than matched louder buildings.

If silence hid danger, the observed/predicted ratio would be at or above 1. All source tables are `reports/phase4/*.csv`; the full write-up is [`docs/silent_distress_phase4.md`](../docs/silent_distress_phase4.md)."""),
    ("code", r'''from nbutil import *
R4 = REPORTS / "phase4"
cg = pd.read_csv(R4 / "calibration_groups.csv")
p = cg[cg.outcome == "primary"].set_index("group")
p[["n_rows", "n_events", "observed", "predicted", "ratio_level_corrected", "ratio_level_corrected_lo", "ratio_level_corrected_hi"]].round(4)'''),
    ("md", """## 1. Are silent buildings riskier than their predicted condition says?

Primary outcome: a vacate order or a DOB physical-hazard violation in the next 12 months (the least tenant-driven outcome available; chosen after seeing event-rate stability, before any gap result was computed, and disclosed). Ratios are observed / predicted, corrected for the model's overall level."""),
    ("code", r'''g = p.loc[[i for i in ["silent", "silent_resid", "not_silent"] if i in p.index]]
fig, ax = plt.subplots(figsize=(6.5, 2.6))
forest(ax, list(g.index), g.ratio_level_corrected.tolist(), g.ratio_level_corrected_lo.tolist(), g.ratio_level_corrected_hi.tolist(), xlabel="observed / predicted (1 = as predicted)")
ax.set_title("Primary outcome, 16 out-of-time snapshots"); plt.show()'''),
    ("md", """The silent group sits **below 1**: 16% fewer events than the model expects, not more.

## 2. Matched comparison: silent vs similar buildings with louder records

Coarsened exact matching on predicted condition, borough, size band and year built, ATT weights, cluster bootstrap by building."""),
    ("code", r'''mt = pd.read_csv(R4 / "matched.csv")
a = mt[(mt.analysis == "matched") & (mt.treatment == "silent") & (mt.subset == "all snapshots")].set_index("outcome")
fig, ax = plt.subplots(figsize=(6.5, 3.2))
forest(ax, list(a.index), a.rr.tolist(), a.rr_lo.tolist(), a.rr_hi.tolist(), xlabel="relative risk, silent vs matched not-silent")
ax.set_xscale("log"); ax.set_title("Silent buildings have fewer later events, most of all for tenant-driven outcomes"); plt.show()
a[["rate_treated", "rate_control", "rr", "rr_lo", "rr_hi", "events_treated"]].round(3)'''),
    ("md", """Chain-driven outcomes (OMO charges, litigation, AEP) show relative risks of 0.25 to 0.36. **That is largely mechanical**: those events begin with a complaint, so they are rare where nobody complains. The primary outcome (0.65) is the least chain-driven and still below 1, but is not independent of the reporting system either.

## 3. Robustness of the primary result"""),
    ("code", r'''b = mt[(mt.outcome == "primary") & (mt.treatment.isin(["silent", "silent_resid", "silent_311"]))].copy()
b["label"] = b.treatment + ": " + b.subset
fig, ax = plt.subplots(figsize=(7, 4.2))
forest(ax, b.label.tolist(), b.rr.tolist(), b.rr_lo.tolist(), b.rr_hi.tolist(), xlabel="relative risk (primary outcome)")
plt.show()
pl = pd.read_csv(R4 / "placebo.csv")
print("Shuffling the silent flag inside the matching cells gives a ratio near 1 (the real ratios are outside the shuffled range):")
pl.round(3)'''),
    ("code", r'''pd.read_csv(R4 / "adjusted.csv").query("flag == 'silent'").round(3)'''),
    ("md", """Same sign in all four out-of-time folds, in rental-only buildings, with finer cells, with 311 instead of HPD complaints, and with the model-residual definition of silence. The shuffle gives 1.00. Covariate adjustment moves it from 0.65 to 0.79: still below 1.

## 4. The milder version that survives: condition still predicts later complaints among the complaint-free"""),
    ("code", r'''lr = pd.read_csv(R4 / "later_loudness_regression.csv")
lr[["sample", "term", "irr", "irr_lo", "irr_hi"]].round(2)'''),
    ("md", """Among buildings with **no complaint at all** in the prior year, the non-complaint condition score still predicts complaints in the next year (incidence rate ratio 1.70 per standard deviation). But compared with matched buildings that had the same prior complaint level, silent buildings are *not* louder later (0.96), so the rise is what regression to the mean predicts. Suppression and noise cannot be told apart.

## 5. Access-blocked buildings

At least 3 closed problems and at least half closed for no access (9.8% of eligible buildings)."""),
    ("code", r'''ab = pd.read_csv(R4 / "access_blocked.csv")
ab = ab[ab.analysis == "access_blocked"]
x = ab[ab.subset.str.startswith("eligible")].set_index("outcome")
fig, ax = plt.subplots(figsize=(6.5, 2.8))
forest(ax, list(x.index), x.rr.tolist(), x.rr_lo.tolist(), x.rr_hi.tolist(), xlabel="relative risk vs matched buildings with better access")
plt.show()'''),
    ("md", """The no-access mechanism is real (about 16% of closed problems) but access-blocked buildings show **no hidden extra risk**: fewer later events (0.84) and fewer later violations (0.81), which is also what the chain predicts when a closure stops a violation from being written.

## 6. Who is in the silent group? (fairness)"""),
    ("code", r'''geo = pd.read_csv(R4 / "geography.csv")
cd = geo[geo.level == "community_district"].sort_values("silent_share")
fig, ax = plt.subplots(figsize=(7, 4.4))
ax.barh(cd.area.astype(str), 100 * cd.silent_share, color=BLUE); ax.set_xlabel("% of building-snapshots flagged silent"); ax.set_ylabel("community district"); ax.tick_params(axis="y", labelsize=6)
plt.show()
comp = pd.read_csv(R4 / "composition.csv")
comp[comp.flag == "silent"][["borough", "units_flagged", "units_other", "zero_complaints_flagged", "zero_complaints_other", "coop_condo_flagged", "coop_condo_other"]].round(2)'''),
    ("md", """The flag is 10% of every borough by construction. Silent buildings are mostly **large, complaint-free buildings** (about 30 units vs 11). Reading "silent" as "disadvantaged" or "neglected" is not supported: they do not have worse outcomes and no demographic data were used. The scores are research estimates, not findings about any owner or tenant.

## Verdict
- Silent-distress in its **strong form is not supported**: silent buildings have an ordinary event rate for their size.
- A **milder form is weakly supported**: condition predicts later complaints among the complaint-free, though regression to the mean explains the rise.
- **Mostly, silence reflects ordinary risk.** 77% of building-snapshots have no complaint in a year.

![matched forest](../reports/phase4/figures/matched_forest.png)
"""),
])

# ------------------------------------------------------------------------------------------------------------------ 05
notebook("05_sale_study", [
    ("md", """# 05 After the sale: does a building's record change when it is sold?

A staggered event study around whole-building arms-length sales, split by whether the building was silent before the sale. Honest framing up front: this is observational, the estimand is the change in *recorded* activity, and the interesting subgroup (silent buildings) is small.
Source tables: `reports/phase5/*.csv`. Full write-up and limits: [`docs/sales_phase5.md`](../docs/sales_phase5.md)."""),
    ("code", r'''from nbutil import *
R5 = REPORTS / "phase5"
cov = pd.read_csv(R5 / "acris_vs_dof_coverage.csv")
fig, ax = plt.subplots(figsize=(7, 3))
ax.plot(cov.year, cov.dof_priced_sales, "-o", color=BLUE, label="DOF priced sales")
ax.plot(cov.year, cov.acris_deed_documents, "-o", color=RED, label="ACRIS deed documents (open-data extract)")
ax.set_ylim(0); ax.legend(frameon=False); ax.set_title("Data-quality finding: the ACRIS extract holds about 8% of recent deeds")
plt.show()'''),
    ("md", """The plan was to use ACRIS deeds. A pre-declared coverage rule (usable only if the source's recent volume is at least 60% of an independent count) failed at 8%, so the study uses the Department of Finance sales files instead, which have no party names. **No owner or buyer names are used anywhere.**

## Who is treated, who is a control"""),
    ("code", r'''att = pd.read_csv(R5 / "study_attrition.csv"); att["n"] = att.n.map("{:,}".format); att'''),
    ("code", r'''co = pd.read_csv(R5 / "study_cohorts.csv")
fig, ax = plt.subplots(figsize=(7, 2.8)); ax.bar(co.cohort_quarter_index, co.n_buildings, color=BLUE)
ax.set_xlabel("quarter of sale (0 = 2018Q1)"); ax.set_ylabel("buildings"); ax.set_title("19 quarterly cohorts, none under 100"); plt.show()
pd.read_csv(R5 / "study_balance.csv").rename(columns={"Unnamed: 0": "", "False": "never sold", "True": "sold"}).round(2)'''),
    ("md", """Sold buildings are smaller (8 vs 16 units) and had more violations per unit in 2018-19, which is why controls are reweighted to the treated mix.

## Event study (primary specification)"""),
    ("code", r'''ev = pd.read_csv(R5 / "study_event_time.csv")
res = pd.read_csv(R5 / "study_results.csv")
titles = {"any_violation": "Any HPD violation", "any_class_c": "Any class C violation", "any_complaint": "Any complaint problem", "any_serious": "Any serious event"}
fig, axes = plt.subplots(1, 4, figsize=(14, 3.3), sharex=True)
for ax, o in zip(axes, titles):
    d = ev[(ev.group == "all") & (ev.spec == "primary") & (ev.outcome == o)]
    d = pd.concat([d, pd.DataFrame([dict(event=-1, theta=0, lo=0, hi=0)])]).sort_values("event")
    ax.fill_between(d.event, d.lo, d.hi, color=BLUE, alpha=0.2); ax.plot(d.event, d.theta, "-o", color=BLUE, ms=3); ax.axhline(0, color=GREY, lw=.8); ax.axvline(-.5, color=GREY, ls="--", lw=.8)
    r = res[(res.group == "all") & (res.spec == "primary") & (res.outcome == o)].iloc[0]
    ax.set_title(f"{titles[o]}\navg post {r.avg_post:+.3f} [{r.avg_post_lo:+.3f}, {r.avg_post_hi:+.3f}]", fontsize=8); ax.set_xlabel("quarters since sale")
plt.tight_layout(); plt.show()'''),
    ("code", r'''t = res[(res.spec == "primary") & (res.group == "all")][["outcome", "pre_mean_treated", "avg_post", "avg_post_lo", "avg_post_hi", "relative_pct", "adj_post", "adj_post_lo", "adj_post_hi", "pre_trend_p"]]
t.round(4)'''),
    ("md", """Reading the table: violations and complaints rise modestly after a sale (about +7% and +16% relative to the pre-sale rate), serious events do not move detectably. Complaints and class C violations were **already drifting upward before the sale**, so the "after removing the pre-trend" columns are the conservative reading; class C attenuates to roughly zero there.

## Silent vs not silent (sales from 2022Q2, flag at the 2022-01-01 snapshot)"""),
    ("code", r'''s = res[(res.spec == "primary") & res.group.isin(["silent", "not_silent"])]
fig, axes = plt.subplots(1, 4, figsize=(14, 3.1), sharex=True)
for ax, o in zip(axes, titles):
    for grp, col in [("silent", RED), ("not_silent", BLUE)]:
        d = ev[(ev.group == grp) & (ev.spec == "primary") & (ev.outcome == o)]
        d = pd.concat([d, pd.DataFrame([dict(event=-1, theta=0, lo=0, hi=0)])]).sort_values("event")
        ax.fill_between(d.event, d.lo, d.hi, color=col, alpha=0.15); ax.plot(d.event, d.theta, "-o", color=col, ms=3, label=grp)
    ax.axhline(0, color=GREY, lw=.8); ax.set_title(titles[o], fontsize=8)
axes[0].legend(frameon=False, fontsize=7); plt.tight_layout(); plt.show()
print(pd.read_csv(R5 / "study_silent_difference.csv").round(4).to_string(index=False))
s[["group", "outcome", "n_treated", "avg_post", "avg_post_lo", "avg_post_hi"]].round(4)'''),
    ("md", """Only 453 sold buildings were silent at baseline, so intervals are wide and **no difference between silent and not-silent buildings is detectable**.

## Robustness: different control groups"""),
    ("code", r'''res[(res.group == "all") & (res.outcome.isin(["any_violation", "any_complaint", "any_serious"]))][["spec", "outcome", "avg_post", "avg_post_lo", "avg_post_hi", "pre_trend_p"]].round(4)'''),
    ("md", """## What this does and does not show
- **Does:** a small, robust-to-control-choice rise in recorded violations and complaints after whole-building sales; no detectable change in serious events; no detectable difference for silent buildings.
- **Does not:** show that sales harm tenants (more records can mean active new management, turnover or more inspection attention); sale timing is not random; LLC-interest transfers are invisible; there is no buyer information by design.
"""),
])

# ------------------------------------------------------------------------------------------------------------------ 06
notebook("06_map_tour", [
    ("md", """# 06 Map tour: the 3D Civic Atlas and how it is built

A static web application (`app/web/`): 120,705 Bronx and Brooklyn residential building footprints extruded to their real roof heights across 8 layers (5 empirical investigation layers + 3 quarterly out-of-time model layers), paired with Building Report Cards, address search, an Investigations broadsheet, and a sortable 30-district Rankings table.
Run it with `make map && make serve` (see [`docs/map.md`](../docs/map.md)).

![NYC Housing Monitor 3D Atlas and Building Report Card](../docs/img/atlas_3d_report_card.png)

| | |
|---|---|
| ![Investigations broadsheet](../docs/img/atlas_investigations.png) | ![District Rankings](../docs/img/atlas_rankings.png) |
| Interactive empirical investigations | Sortable 30-neighborhood ledger |"""),
    ("code", r'''from nbutil import *
import json
WEB = ROOT / "app" / "web" / "data"
meta = json.loads((WEB / "meta.json").read_text())
print({k: v for k, v in meta.items() if k != "snapshots"}); print("snapshots:", meta["snapshots"][0], "to", meta["snapshots"][-1], f"({len(meta['snapshots'])})")'''),
    ("md", """## The default view is aggregate: district averages

The map opens zoomed out on 30 community-district averages (approximate shapes unioned from footprints) so the first impression is not building by building."""),
    ("code", r'''from matplotlib.patches import Polygon
from matplotlib.collections import PatchCollection
import numpy as np
dj = json.loads((WEB / "districts.json").read_text())
def draw(ax, key, title, cmap, scale=1.0):
    patches, vals = [], []
    for f in dj["features"]:
        geom = f["geometry"]; polys = geom["coordinates"] if geom["type"] == "MultiPolygon" else [geom["coordinates"]]
        for poly in polys:
            ring = np.array(poly[0])
            ring[:, 0] = ring[:, 0] * np.cos(np.radians(40.7))
            patches.append(Polygon(ring, closed=True)); vals.append(f["properties"]["v"][key][-1] * scale)
    pc = PatchCollection(patches, cmap=cmap, edgecolor="white", linewidth=0.4); pc.set_array(np.array(vals)); ax.add_collection(pc)
    ax.autoscale_view(); ax.set_aspect("equal"); ax.axis("off"); ax.set_title(title, fontsize=9); plt.colorbar(pc, ax=ax, shrink=0.6)
fig, axes = plt.subplots(1, 3, figsize=(12, 4))
draw(axes[0], "risk", "Mean predicted probability of an enforcement event\nin the next 12 months, 2025-10 snapshot (%)", "YlOrRd", 100)
draw(axes[1], "comp", "Complaint problems per unit, last 12 months", "Blues")
draw(axes[2], "silent", "Share flagged silent", "Purples", 100)
plt.tight_layout(); plt.show()'''),
    ("md", """## How the slider avoids reloading data

Each score series is a string of 16 three-digit numbers (one per out-of-time snapshot, 999 = no value). Moving the slider only slices a string inside a MapLibre expression, so nothing is refetched; 80 numbers per building as separate tile properties would have been too heavy. A demonstration on the committed sample:"""),
    ("code", r'''try:
    g = json.loads((WEB / "sample" / "buildings.geojson").read_text())
    f = g["features"][0]["properties"]
    s = f["r"]; k = len(meta["snapshots"])
    series = [int(s[3 * i:3 * i + 3]) for i in range(k)]
    print("raw string length:", len(s), "-> 16 values, one per snapshot")
    print(dict(zip(meta["snapshots"], [None if v == 999 else v for v in series])))
except FileNotFoundError:
    print("sample not present in this checkout")'''),
    ("md", """## One community district, drawn from the committed sample

The sample is one community district (Bronx CD 202) as plain GeoJSON so the page works without the 101 MB tile file. Footprints are coloured by the predicted-risk percentile at the latest snapshot (the tiles store percentiles within each snapshot; the district view above shows mean probabilities). No owner or tenant names exist anywhere in the sample."""),
    ("code", r'''try:
    patches, vals = [], []
    for f in g["features"]:
        pr = f["properties"]
        v = int(pr["r"][-3:])
        if v == 999: continue
        geom = f["geometry"]; polys = geom["coordinates"] if geom["type"] == "MultiPolygon" else [geom["coordinates"]]
        for poly in polys:
            ring = np.array(poly[0]); ring[:, 0] = ring[:, 0] * np.cos(np.radians(40.85))
            patches.append(Polygon(ring, closed=True)); vals.append(v / 10)
    fig, ax = plt.subplots(figsize=(6, 6))
    pc = PatchCollection(patches, cmap="YlOrRd", linewidth=0.1, edgecolor="#555"); pc.set_array(np.array(vals)); ax.add_collection(pc)
    ax.autoscale_view(); ax.set_aspect("equal"); ax.axis("off"); plt.colorbar(pc, shrink=0.6, label="risk percentile"); plt.show()
except NameError:
    pass'''),
    ("md", """## Privacy and limits
No owner names, tenant information or contacts anywhere in the tiles, shards or page; per-building shards and tiles are gitignored. Footprints inherit the scores of their lot; 471 scored lots have no footprint; district shapes are approximate; only the 16 out-of-time snapshots exist.
"""),
])

# ------------------------------------------------------------------------------------------------------------------ 07
notebook("07_llm_layer", [
    ("md", """# 07 The LLM layer: what ran, what did not, and the RAG gates

Everything here ran **offline against deterministic stubs**. No live model was used (no API key is configured), so there are no live accuracy numbers; they are marked pending.
The layer has three parts: sandboxed text-to-SQL over DuckDB marts (structured data, so not RAG), building biographies with citations and a code-based verifier, and two measured gates deciding whether retrieval (RAG) earns a place. Write-up: [`docs/llm_layer.md`](../docs/llm_layer.md)."""),
    ("code", r'''from nbutil import *
import json
h = json.loads((REPORTS / "phase7" / "llm_harness.json").read_text())
print(h["mode"])
pd.DataFrame(h["text_to_sql"]).T.round(3)'''),
    ("md", """The three stubs bracket the metric: the oracle stub (returns the reference SQL) must score 1.0, an always-`SELECT 1` stub 0.0, and a crude keyword stub 0.03. They show the harness can fail and say **nothing** about how well a language model writes SQL.

For biographies, the verifier is code, not a model: cited ids must exist, numbers must appear in a cited record, no uncited factual sentence, no blame language."""),
    ("code", r'''b = h["biography"]
print(f"template biographies passing the verifier: {b['template_fully_verified']}/{b['buildings']}")
print(f"numeric corruptions caught: {b['numeric_corruptions_caught']}/{b['numeric_corruptions_tried']}; invented ids caught: {b['invented_ids_caught']}/{b['numeric_corruptions_tried']}")'''),
    ("md", """## Gate E1: does retrieval beat plain SQL keywords at finding the records about a condition?

Within one building's violation records, retrieve those about a condition ("no heat or hot water", "rats mice and roaches", ...). Ground truth is structured (HPD order-number families), independent of the text. 400 buildings, 2,317 building-condition pairs.
Rule fixed in advance: adopt retrieval only if BM25 beats the SQL keyword baseline by at least 0.03 precision@10 with the paired interval above 0."""),
    ("code", r'''r = json.loads((REPORTS / "phase7" / "retrieval_eval.json").read_text())["summary"]
names = ["sql_keywords", "bm25", "tfidf", "random"]
fig, ax = plt.subplots(figsize=(6.5, 2.8))
ax.barh(names[::-1], [r[n]["precision_at_10"] for n in names][::-1], xerr=[[r[n]["precision_at_10"] - r[n]["p_lo"] for n in names][::-1], [r[n]["p_hi"] - r[n]["precision_at_10"] for n in names][::-1]], color=[GREY, GREY, GREY, BLUE], capsize=3)
ax.set_xlabel("precision@10"); plt.show()'''),
    ("md", """Plain SQL keywords win (0.67 vs BM25 0.53). Retrieval wins only on lead paint. **Not adopted.** Caveat: the keyword lists were written by someone who knew the corpus vocabulary, which is what a SQL user with domain knowledge does; an embedding model was not tried.

## Gate E2: do text-derived severity features improve the Phase 3 model?"""),
    ("code", r'''t = pd.DataFrame(json.loads((REPORTS / "phase7" / "text_features_eval.json").read_text())["rows"])
x = t[t.target == "label_serious_any"]
fig, ax = plt.subplots(figsize=(5.5, 2.6)); ax.bar(x.fold, x.gain, color=[BLUE if g > 0 else RED for g in x.gain]); ax.axhline(0.005, color=GREY, ls="--"); ax.text(0, 0.0052, "adoption threshold +0.005", fontsize=7)
ax.set_ylabel("PR-AUC gain"); ax.set_ylim(-0.002, 0.007); plt.show()
x[["fold", "pr_auc_base", "pr_auc_text", "gain"]].round(4)'''),
    ("md", """The gain is detectable but negligible (about +0.001 PR-AUC, positive in 2 of 4 folds), far below the +0.005 threshold. **Not adopted.**

## Conclusion
RAG is not used anywhere in the pipeline, by measurement: the two places where it might have helped were tested against a simple baseline and lost. The text-to-SQL and biography components stand on their own and are ready for a live evaluation (`make llm-live`, needs an API key).
"""),
])


def main():
    only = sys.argv[1:]
    for name, nb in NB.items():
        if only and name not in only:
            continue
        ep = ExecutePreprocessor(timeout=600, kernel_name="python3")
        ep.preprocess(nb, {"metadata": {"path": str(HERE)}})
        nbformat.write(nb, HERE / f"{name}.ipynb")
        print("executed", name, flush=True)


if __name__ == "__main__":
    sys.path.insert(0, str(HERE))
    main()
