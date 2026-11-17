"""Phase 4, step 2: loudness, silent-distress gaps and flags for every out-of-time snapshot.

    python pipelines/silent_phase4.py        # needs train_phase4.py first (about 4 minutes)

Inputs: Phase 2 features/labels, the out-of-time condition scores from train_phase4.py.
Writes (gitignored, building level): data/processed/scores_phase4.parquet and data/processed/phase4/analysis_frame.parquet.
Writes (small, geography-free): reports/phase4/condition_model.csv, calibration_choice.json, gap_definitions.csv.

Calibration rule (fixed before looking at any gap): use the isotonic-calibrated probability for a (target, feature set) only if
it lowers the expected calibration error averaged over folds 1-3; otherwise the raw probability. The test fold is not used.
"""
import json
import time
from pathlib import Path

import numpy as np
import pandas as pd

from nycdistress.evaluation import RankEval, brier, ece
from nycdistress.modeling import P4_PRIMARY, P4_TARGETS, PROC, load_frame, rows
from nycdistress.silent import (access_blocked, eb_rate, fit_expected_complaints, rank_gap, resid_gap, size_bucket, top_decile)
from nycdistress.splits import make_folds

ROOT = Path(__file__).resolve().parents[1]
REPORTS = ROOT / "reports" / "phase4"
COND = PROC / "phase4" / "cond"
FSET = "cond_core"


def build_scores(ev, p_hat):
    """Loudness, gaps and flags for ONE snapshot (rows of `ev`), from values known at that snapshot."""
    units = ev["static_unitsres"].to_numpy(dtype=float)
    borough = ev["static_borough"].astype(str).to_numpy()
    size = size_bucket(units).astype(str).to_numpy()
    grp = np.char.add(np.char.add(borough.astype(str), "|"), size.astype(str))
    y = ev["loud_prob_n_12m"].to_numpy(dtype=float)
    post, raw, _ = eb_rate(y, units, grp)
    y311 = ev["loud_311_n_12m"].to_numpy(dtype=float)
    ok311 = ~np.isnan(y311)
    post311 = np.full(len(ev), np.nan)
    if ok311.all():
        post311, _, _ = eb_rate(y311, units, grp)
    gap_a = rank_gap(p_hat, post, borough)
    out = pd.DataFrame({"p_hat": p_hat, "loudness": post, "loudness_raw": raw, "loudness_311": post311,
                        "gap_rank": gap_a, "silent": top_decile(gap_a, borough)}, index=ev.index)
    if ok311.all():
        g311 = rank_gap(p_hat, post311, borough)
        out["gap_rank_311"], out["silent_311"] = g311, top_decile(g311, borough)
    res = fit_expected_complaints(y, p_hat, units, ev["community_district"].astype(str).to_numpy())
    gr, lo, hi = resid_gap(y, res["mu"], res["mu_lo"], res["mu_hi"])
    out["expected_complaints"], out["gap_resid"], out["gap_resid_lo"], out["gap_resid_hi"] = res["mu"], gr, lo, hi
    out["p_low"], out["silent_resid"] = res["p_low"], res["p_low"] < 0.05
    out["access_blocked"] = access_blocked(ev["loud_closed_n_12m"].to_numpy(dtype=float), ev["loud_nacc_share_12m"].to_numpy(dtype=float))
    out["nb_alpha"] = res["alpha"]
    return out


def main():
    REPORTS.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    df = load_frame()
    folds = {f.name: f for f in make_folds(sorted(df.snapshot_date.unique()))}
    parts = []
    for fname, f in folds.items():
        ev = df[rows(df, f.eval)].copy()
        ev.insert(0, "fold", fname)
        parts.append(ev)
    ev = pd.concat(parts).reset_index(drop=True)

    # ---------------------------------------------------------------- condition scores and the calibration rule
    quality, choice = [], {}
    cond = {}
    for t in P4_TARGETS:
        frames = []
        for fname in folds:
            p = pd.read_parquet(COND / f"{t}__{fname}__{FSET}.parquet")
            frames.append(p)
        p = pd.concat(frames).reset_index(drop=True)
        assert (p.bbl.to_numpy() == ev.bbl.to_numpy()).all() and (p.snapshot_date.to_numpy() == ev.snapshot_date.to_numpy()).all()
        y = ev[t].to_numpy()
        cv = (ev.fold != "test").to_numpy()
        e_raw, e_cal = ece(y[cv], p.p_raw.to_numpy()[cv]), ece(y[cv], p.p_cal.to_numpy()[cv])
        use = "cal" if e_cal < e_raw else "raw"
        choice[t] = dict(use=use, ece_raw_folds123=e_raw, ece_cal_folds123=e_cal)
        cond[t] = p.p_cal.to_numpy() if use == "cal" else p.p_raw.to_numpy()
        for fname in folds:
            m = (ev.fold == fname).to_numpy()
            r = RankEval(y[m], cond[t][m], ev.snapshot_date.to_numpy()[m]).metrics()
            quality.append(dict(target=t, fold=fname, used=use, rows=int(m.sum()), events=int(y[m].sum()), base_rate=y[m].mean(),
                                mean_pred=float(cond[t][m].mean()), roc_auc=r["roc_auc"], pr_auc=r["pr_auc"], lift_top5pct=r["lift_top5pct"],
                                ece=ece(y[m], cond[t][m]), brier=brier(y[m], cond[t][m])))
    pd.DataFrame(quality).to_csv(REPORTS / "condition_model.csv", index=False)
    (REPORTS / "calibration_choice.json").write_text(json.dumps(choice, indent=2))
    print("calibration choice:", {k: v["use"] for k, v in choice.items()}, f"({time.time() - t0:.0f}s)", flush=True)
    for t in P4_TARGETS:
        ev["p_" + t.replace("label_", "")] = cond[t]

    # ---------------------------------------------------------------- loudness, gaps, flags (cross-sectional, per snapshot)
    scored = []
    for snap, g in ev.groupby("snapshot_date"):
        s = build_scores(g, g["p_" + P4_PRIMARY.replace("label_", "")].to_numpy())
        scored.append(s)
        print(f"  {snap.date()}: {len(g):,} rows, silent {s.silent.mean():.3f}, silent_resid {s.silent_resid.mean():.3f}, access_blocked {s.access_blocked.mean():.3f}, alpha {s.nb_alpha.iloc[0]:.2f} ({time.time() - t0:.0f}s)", flush=True)
    sc = pd.concat(scored).loc[ev.index]
    ev = pd.concat([ev, sc], axis=1)

    # ---------------------------------------------------------------- next-12-month information that exists as features at t + 12 months
    nxt = df[["bbl", "snapshot_date", "viol_n_12m", "viol_c_n_12m", "loud_311_n_12m"]].rename(
        columns={"viol_n_12m": "viol_next12", "viol_c_n_12m": "viol_c_next12", "loud_311_n_12m": "c311_next12"})
    nxt["snapshot_date"] = nxt["snapshot_date"] - pd.DateOffset(years=1)
    ev = ev.merge(nxt, on=["bbl", "snapshot_date"], how="left")
    ev.to_parquet(PROC / "phase4" / "analysis_frame.parquet", index=False)

    # ---------------------------------------------------------------- the file for the later map (building level, gitignored)
    out = ev[["bbl", "snapshot_date", "fold", "p_hat", "loudness", "gap_rank", "gap_resid", "gap_resid_lo", "gap_resid_hi",
              "silent", "silent_resid", "access_blocked"]].copy()
    out["borough"] = ev["static_borough"].astype(str)
    out["community_district"] = ev["community_district"].astype(str)
    out["snapshot_date"] = out.snapshot_date.dt.date
    out.to_parquet(PROC / "scores_phase4.parquet", index=False)
    print(f"scores_phase4.parquet: {len(out):,} rows, {out.snapshot_date.nunique()} snapshots ({time.time() - t0:.0f}s)", flush=True)

    # ---------------------------------------------------------------- how the two gap definitions relate (geography-free summary)
    rows_ = []
    for snap, g in ev.groupby("snapshot_date"):
        a, b = g.silent.to_numpy(), g.silent_resid.to_numpy()
        rows_.append(dict(snapshot_date=str(snap.date()), silent_rank=a.mean(), silent_resid=b.mean(), both=(a & b).mean(),
                          jaccard=(a & b).sum() / max((a | b).sum(), 1), spearman=g.gap_rank.corr(g.gap_resid, method="spearman"),
                          silent_311_overlap=(a & g.silent_311.to_numpy()).sum() / max(a.sum(), 1)))
    pd.DataFrame(rows_).to_csv(REPORTS / "gap_definitions.csv", index=False)
    print(f"done in {(time.time() - t0) / 60:.1f} min", flush=True)


if __name__ == "__main__":
    main()
