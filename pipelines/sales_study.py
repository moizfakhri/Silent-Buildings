"""Phase 5: what happens to a building's complaint, violation and serious-event record after a whole-building sale?

    python pipelines/sales_study.py            # about 15 minutes; writes reports/phase5/*.csv and figures

Design (declared before the results were seen; see docs/sales_phase5.md):
  treated   = first arms-length whole-building DOF sale 2020Q1-2024Q3 with 8 quarters before and 8 after and no other sale inside the window
  controls  = analysis buildings with no whole-building DOF row at all (never-treated)
  estimator = staggered-adoption event study (Callaway and Sant'Anna style, no covariates), base period = the quarter before the sale,
              controls reweighted to the treated stratum mix (primary), cluster bootstrap by building
  split     = Phase 4 silent flag (top decile of the within-borough complaint-gap rank) at the 2022-01-01 snapshot, for sales from 2022Q2 on
No owner or buyer names are read or written anywhere; outputs are aggregates only.
"""
import json
import sys
import time
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from nycdistress.did import event_study  # noqa: E402
from nycdistress.sales import build_cohorts  # noqa: E402

OUT = ROOT / "reports" / "phase5"
FIG = OUT / "figures"
T = 35  # quarters 0 (2018Q1) .. 34 (2026Q3); 2026Q4 is incomplete and left out
PRE, POST = 8, 8
N_BOOT = 400
SEED = 20261114
OUTCOMES = {
    "any_violation": "Any HPD violation in the quarter",
    "any_class_c": "Any class C (immediately hazardous) violation",
    "any_complaint": "Any HPD complaint problem",
    "any_serious": "Any serious event (emergency repair charge, litigation, vacate order, AEP)",
    "violations_n": "HPD violations (count, winsorized at the 99.5th percentile)",
    "complaints_n": "HPD complaint problems (count, winsorized at the 99.5th percentile)",
}


def quarter_counts(con, sql, bbl_index):
    """Rows (bbl, q, n) -> dense array [n_buildings, T]."""
    df = con.execute(sql).df()
    df = df[(df.q >= 0) & (df.q < T) & df.bbl.isin(bbl_index.index)]
    a = np.zeros((len(bbl_index), T))
    np.add.at(a, (bbl_index.loc[df.bbl].to_numpy(), df.q.to_numpy().astype(int)), df.n.to_numpy())
    return a


def build_panel(bbls):
    con = duckdb.connect(str(ROOT / "data" / "processed" / "marts.duckdb"), read_only=True)
    idx = pd.Series(np.arange(len(bbls)), index=pd.Index(bbls))

    def q(col):
        return f"(year({col}) - 2018) * 4 + (month({col}) - 1) // 3"

    viol = quarter_counts(con, f"SELECT bbl, {q('inspection_date')} AS q, count(*) AS n FROM hpd_violations GROUP BY 1, 2", idx)
    viol_c = quarter_counts(con, f"SELECT bbl, {q('inspection_date')} AS q, count(*) AS n FROM hpd_violations WHERE violation_class = 'C' GROUP BY 1, 2", idx)
    comp = quarter_counts(con, f"SELECT bbl, {q('received_date')} AS q, count(*) AS n FROM hpd_complaints GROUP BY 1, 2", idx)
    ser = quarter_counts(con, f"""SELECT bbl, q, count(*) AS n FROM (
        SELECT bbl, {q('created_date')} AS q FROM omo_charges UNION ALL SELECT bbl, {q('opened_date')} FROM litigations
        UNION ALL SELECT bbl, {q('effective_date')} FROM vacate_orders UNION ALL SELECT bbl, {q('start_date')} FROM aep_programs) GROUP BY 1, 2""", idx)
    base = con.execute("""SELECT b.bbl, b.borough, b.units_residential AS units, b.year_built, s.complaint_gap, s.gap_top_decile
        FROM buildings b LEFT JOIN building_snapshots s ON s.bbl = b.bbl AND s.snapshot_date = DATE '2022-01-01'""").df().set_index("bbl").loc[bbls]
    con.close()

    def win(a):
        return np.minimum(a, np.percentile(a[a > 0], 99.5))

    Y = {"any_violation": (viol > 0) * 1.0, "any_class_c": (viol_c > 0) * 1.0, "any_complaint": (comp > 0) * 1.0, "any_serious": (ser > 0) * 1.0,
         "violations_n": win(viol), "complaints_n": win(comp)}
    return Y, base, viol


def make_strata(base, viol):
    """borough x unit-size band x construction era x pre-period violation level (2018-2019, before every sale in the sample)."""
    rate = viol[:, :8].sum(axis=1) / base.units.to_numpy()
    vbin = pd.qcut(pd.Series(rate).rank(method="first"), 3, labels=False).to_numpy()
    ubin = pd.cut(base.units, [0, 5, 10, 20, 10_000], labels=False).to_numpy()
    era = pd.cut(base.year_built.fillna(1930), [0, 1930, 1960, 3000], labels=False).to_numpy()
    boro = (base.borough == "Brooklyn").astype(int).to_numpy()
    key = pd.Series(list(zip(boro, ubin, era, vbin)))
    return pd.factorize(key)[0]


def run(Y, g, strata, outcomes, control, use_strata, label, rows, events_rows, seed):
    sel = g != -2
    gg = g[sel]
    for name in outcomes:
        t0 = time.time()
        y = Y[name][sel]
        r = event_study(y, gg, PRE, POST, control=control, n_boot=N_BOOT, seed=seed, strata=strata[sel] if use_strata else None)
        treated = gg >= 0
        pre_mean = float(np.mean([y[treated][np.arange(treated.sum()), (gg[treated] - k)].mean() for k in range(1, PRE + 1)]))
        rows.append(dict(group=label[0], spec=label[1], outcome=name, n_treated=int(treated.sum()), n_control=int((gg == -1).sum()),
                         pre_mean_treated=pre_mean, avg_post=r["avg_post"], avg_post_lo=r["avg_post_lo"], avg_post_hi=r["avg_post_hi"],
                         relative_pct=100 * r["avg_post"] / pre_mean if pre_mean else np.nan,
                         adj_post=r["adj_post"], adj_post_lo=r["adj_post_lo"], adj_post_hi=r["adj_post_hi"],
                         pre_trend_wald=r["pre_trend_wald"], pre_trend_p=r["pre_trend_p"]))
        for e, th, lo, hi in zip(r["events"], r["theta"], r["lo"], r["hi"]):
            events_rows.append(dict(group=label[0], spec=label[1], outcome=name, event=int(e), theta=th, lo=lo, hi=hi))
        print(f"  {label[0]:>13} {label[1]:>9} {name:<14} post {r['avg_post']:+.4f} [{r['avg_post_lo']:+.4f},{r['avg_post_hi']:+.4f}] "
              f"pretrend p={r['pre_trend_p']:.3f}  ({time.time() - t0:.0f}s)", flush=True)
        if name in ("any_violation", "any_serious") and label[1] == "primary":
            np.save(OUT / f"draws_{label[0]}_{name}.npy", r["draws"].astype(np.float32))


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    FIG.mkdir(exist_ok=True)
    t0 = time.time()
    cohort, never, steps = build_cohorts(str(ROOT / "data/raw/dof_sales/part-*.parquet"), str(ROOT / "data/processed/spine.parquet"), PRE, POST, T - 1)
    con = duckdb.connect(str(ROOT / "data" / "processed" / "marts.duckdb"), read_only=True)
    bbls_all = [r[0] for r in con.execute("SELECT bbl FROM buildings ORDER BY bbl").fetchall()]
    con.close()
    q0 = dict(cohort)
    treated_set = set(q0)
    never_set = set(never)
    keep = [b for b in bbls_all if b in treated_set or b in never_set]
    Y, base, viol = build_panel(keep)
    g = np.array([q0.get(b, -1) for b in keep])
    strata = make_strata(base, viol)
    steps.append(("in the marts (analysis universe) - treated", int((g >= 0).sum())))
    steps.append(("in the marts (analysis universe) - never-treated controls", int((g == -1).sum())))
    pd.DataFrame(steps, columns=["step", "n"]).to_csv(OUT / "study_attrition.csv", index=False)
    coh = pd.Series(g[g >= 0]).value_counts().sort_index()
    coh.rename_axis("cohort_quarter_index").rename("n_buildings").to_csv(OUT / "study_cohorts.csv")
    # balance table (treated vs controls), aggregates only
    bal = pd.DataFrame({"treated": g >= 0, "units": base.units.to_numpy(), "brooklyn": (base.borough == "Brooklyn").to_numpy(),
                        "built_pre1930": (base.year_built.to_numpy() < 1930), "viol_per_unit_2018_19": viol[:, :8].sum(axis=1) / base.units.to_numpy(),
                        "any_complaint_2018_19": Y["any_complaint"][:, :8].max(axis=1)})
    bal.groupby("treated").mean().T.to_csv(OUT / "study_balance.csv")
    print(f"panel: {len(keep):,} buildings, {int((g >= 0).sum()):,} treated; built in {time.time() - t0:.0f}s", flush=True)

    rows, ev = [], []
    run(Y, g, strata, OUTCOMES, "never", True, ("all", "primary"), rows, ev, SEED)
    run(Y, g, strata, OUTCOMES, "never", False, ("all", "uncond"), rows, ev, SEED + 1)
    run(Y, g, strata, OUTCOMES, "notyet", False, ("all", "notyet"), rows, ev, SEED + 2)

    # silent vs loud: cohorts with a pre-sale snapshot (sales from 2022Q2), flag at the 2022-01-01 snapshot, controls split by the same flag
    flag = pd.to_numeric(base.gap_top_decile.astype("Float64"), errors="coerce").to_numpy(dtype=float, na_value=np.nan)
    late = (g == -1) | (g >= 17)
    flagged = ~np.isnan(flag)
    for lab, mask in (("late_all", late & flagged), ("silent", late & flagged & (flag == 1)), ("not_silent", late & flagged & (flag == 0))):
        gg = np.where(mask, g, -2)
        print(f"  group {lab}: treated {int((gg >= 0).sum()):,}, controls {int((gg == -1).sum()):,}", flush=True)
        run(Y, gg, strata, ["any_violation", "any_class_c", "any_complaint", "any_serious", "violations_n"], "never", True, (lab, "primary"), rows, ev, SEED + 10)
    pd.DataFrame(rows).to_csv(OUT / "study_results.csv", index=False)
    pd.DataFrame(ev).to_csv(OUT / "study_event_time.csv", index=False)

    # silent minus not-silent difference (disjoint units, independent bootstrap draws)
    diffs = []
    for name in ("any_violation", "any_serious"):
        a = np.load(OUT / f"draws_silent_{name}.npy").astype(float)
        b = np.load(OUT / f"draws_not_silent_{name}.npy").astype(float)
        post_cols = [i for i, e in enumerate([e for e in range(-PRE, POST + 1) if e != -1]) if e >= 0]
        n = min(len(a), len(b))
        d = np.nanmean(a[:n, post_cols], axis=1) - np.nanmean(b[:n, post_cols], axis=1)
        # point estimate = difference of the two full-sample estimates (not the mean of the bootstrap draws)
        point = {r["group"]: r["avg_post"] for r in rows if r["spec"] == "primary" and r["outcome"] == name and r["group"] in ("silent", "not_silent")}
        diffs.append(dict(outcome=name, diff_silent_minus_not=float(point["silent"] - point["not_silent"]),
                          lo=float(np.percentile(d, 2.5)), hi=float(np.percentile(d, 97.5))))
    pd.DataFrame(diffs).to_csv(OUT / "study_silent_difference.csv", index=False)
    for f in OUT.glob("draws_*.npy"):
        f.unlink()
    json.dump(dict(n_boot=N_BOOT, seed=SEED, quarters=T, pre=PRE, post=POST, runtime_min=round((time.time() - t0) / 60, 1)), open(OUT / "study_meta.json", "w"), indent=1)
    print(f"done in {(time.time() - t0) / 60:.1f} min", flush=True)


if __name__ == "__main__":
    main()
