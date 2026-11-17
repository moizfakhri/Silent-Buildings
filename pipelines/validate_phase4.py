"""Phase 4, step 3: does the silent-distress flag mean anything? Validation against what happens next.

    python pipelines/validate_phase4.py            # about 10 minutes; --boot 100 for a quick run

Reads data/processed/phase4/analysis_frame.parquet (building level, gitignored) and writes only small,
geography-level result tables to reports/phase4/*.csv. Outcomes are the events in (t, t + 12 months] and the complaints
and violations observed at t + 12 months; none of them is used to build a score.

What is mechanical and what is not
  * p_hat is trained to predict the outcome, so high p_hat raises risk by construction. Every comparison below holds p_hat fixed
    (matching on its within-snapshot decile, or comparing to the model's own prediction), so that part is controlled.
  * Events that need a complaint to start the enforcement chain (OMO charges, litigation, AEP) are mechanically rarer where
    nobody complains. The primary outcome (vacate orders and DOB physical-hazard violations) is the least tenant-driven we have;
    the other outcomes are reported next to it so the difference between chain-driven and not chain-driven outcomes is visible.
"""
import argparse
import time
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import chi2

from nycdistress.modeling import PROC
from nycdistress.silent import (age_bucket, att_balance, boot_weights, complaint_bucket, decile_within, matched_multi,
                                shuffle_within, size_bucket, strata_codes)

ROOT = Path(__file__).resolve().parents[1]
REPORTS = ROOT / "reports" / "phase4"
OUTCOMES = {  # short name -> (label column, matching condition-model probability column)
    "primary": ("label_vacate_or_dobhaz_core", "p_vacate_or_dobhaz_core"),
    "wide": ("label_vacate_or_dobhaz", "p_vacate_or_dobhaz"),
    "serious_any": ("label_serious_any", "p_serious_any"),
    "omo": ("label_omo", "p_omo"),
    "vacate_or_aep": ("label_vacate_or_aep", "p_vacate_or_aep"),
    "litigation": ("label_litigation", "p_litigation"),
}
COOP_CLASSES = {"C6", "C8", "D0", "D4"}
LOAD = ["bbl", "snapshot_date", "fold", "static_borough", "static_unitsres", "static_age_at_t", "static_bldgclass", "static_bldgclass_letter",
        "community_district", "loud_prob_n_12m", "loud_closed_n_12m", "loud_nacc_share_12m", "loud_311_n_12m", "label_loud_complaints_next12",
        "p_hat", "loudness", "silent", "silent_resid", "silent_311", "access_blocked", "expected_complaints", "viol_next12", "viol_c_next12",
        "c311_next12"] + [v[0] for v in OUTCOMES.values()] + [v[1] for v in OUTCOMES.values()]


def prepare():
    df = pd.read_parquet(PROC / "phase4" / "analysis_frame.parquet", columns=LOAD)
    df["borough"] = df.static_borough.astype(str)
    df["units"] = df.static_unitsres.astype(float)
    df["snap"] = df.snapshot_date.dt.strftime("%Y-%m-%d")
    df["bcode"] = pd.factorize(df.bbl)[0]
    bc = df.static_bldgclass.astype(str)
    df["coop_condo"] = bc.isin(COOP_CLASSES) | bc.str.startswith("R")
    df["size"] = size_bucket(df.units).astype(str).to_numpy()
    df["age_b"] = age_bucket(df.static_age_at_t)
    df["phat_dec"] = decile_within(df.p_hat, df.snap)
    df["cbucket"] = complaint_bucket(df.loud_prob_n_12m)
    df["prior_rate"] = df.loud_prob_n_12m / df.units
    df["next_rate"] = df.label_loud_complaints_next12 / df.units
    df["delta_rate"] = df.next_rate - df.prior_rate
    df["expected_rate"] = df.expected_complaints / df.units
    # finer matching, added after the balance table of the pre-specified matching showed silent buildings still larger inside the cells:
    # 8 size bands instead of 5 and 20 predicted-risk groups instead of 10 (chosen from covariate balance, after the outcome ratios had been seen)
    df["size_fine"] = pd.cut(df.units, [3, 6, 9, 12, 18, 25, 50, 100, np.inf], right=False, labels=False).astype(str).to_numpy()
    df["phat_vig"] = decile_within(df.p_hat, df.snap, n=20)
    df["strata_fine"] = strata_codes(df.snap, df.borough, df.size_fine, df.static_bldgclass_letter.astype(str), df.age_b, df.phat_vig)
    df["strata_A"] = strata_codes(df.snap, df.borough, df["size"], df.static_bldgclass_letter.astype(str), df.age_b, df.phat_dec)
    return df


def ci_row(draws, point, kind):
    lo, hi = np.nanpercentile(draws, [2.5, 97.5])
    return {f"{kind}": point, f"{kind}_lo": lo, f"{kind}_hi": hi}


def matched_boot(Y, treated, codes, bbl_codes, n_boot, seed=0):
    """Matched comparison for k outcomes with a cluster bootstrap by building. Returns a dict of arrays."""
    t = np.asarray(treated, dtype=bool)
    Y = np.asarray(Y, dtype=float)
    k = int(codes.max()) + 1
    both = (np.bincount(codes, t.astype(float), k) > 0) & (np.bincount(codes, (~t).astype(float), k) > 0)
    keep = both[codes]
    n_treated_all = int(t.sum())
    if not keep.any() or not (t & keep).any():
        nan = np.full(Y.shape[1], np.nan)
        return dict(n_treated_all=n_treated_all, n_matched=0, n_strata=0, rt=nan, rc=nan, rr=(nan, nan, nan), diff=(nan, nan, nan))
    Yk, tk = Y[keep], t[keep]
    ck = np.unique(codes[keep], return_inverse=True)[1]
    bk = np.unique(bbl_codes[keep], return_inverse=True)[1]
    pt = matched_multi(Yk, tk, ck)
    rr_d, df_d = [], []
    for w in boot_weights(bk, n_boot, seed):
        m = matched_multi(Yk, tk, ck, w)
        with np.errstate(divide="ignore", invalid="ignore"):
            rr_d.append(m["rate_t"] / m["rate_c"])
        df_d.append(m["rate_t"] - m["rate_c"])
    rr_d, df_d = np.array(rr_d), np.array(df_d)
    with np.errstate(divide="ignore", invalid="ignore"):
        rr_point = pt["rate_t"] / pt["rate_c"]
    return dict(n_treated_all=n_treated_all, n_matched=int(pt["n_treated_matched"]), n_strata=pt["n_strata"], rt=pt["rate_t"], rc=pt["rate_c"],
                rr=(rr_point, *np.nanpercentile(rr_d, [2.5, 97.5], axis=0)), diff=(pt["rate_t"] - pt["rate_c"], *np.nanpercentile(df_d, [2.5, 97.5], axis=0)))


def tidy(res, analysis, subset, treatment, names, scale=1.0):
    out = []
    for j, n in enumerate(names):
        out.append(dict(analysis=analysis, subset=subset, treatment=treatment, outcome=n, n_flagged=res["n_treated_all"], n_matched=res["n_matched"],
                        share_matched=res["n_matched"] / max(res["n_treated_all"], 1), n_strata=res["n_strata"],
                        rate_treated=res["rt"][j] * scale, rate_control=res["rc"][j] * scale, rr=res["rr"][0][j], rr_lo=res["rr"][1][j], rr_hi=res["rr"][2][j],
                        diff=res["diff"][0][j] * scale, diff_lo=res["diff"][1][j] * scale, diff_hi=res["diff"][2][j] * scale,
                        events_treated=res["rt"][j] * res["n_matched"]))
    return out


def main(args):
    REPORTS.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    B = args.boot
    df = prepare()
    print(f"{len(df):,} rows, {df.bbl.nunique():,} buildings ({time.time() - t0:.0f}s)", flush=True)
    names = list(OUTCOMES)
    Yb = df[[v[0] for v in OUTCOMES.values()]].to_numpy(dtype=float)

    # ------------------------------------------------------------------ power
    pw = []
    for fold, g in list(df.groupby("fold")) + [("all", df)]:
        row = dict(fold=fold, rows=len(g), silent_rows=int(g.silent.sum()), silent_resid_rows=int(g.silent_resid.sum()), access_blocked_rows=int(g.access_blocked.sum()))
        for n, (c, _) in OUTCOMES.items():
            row[f"events_{n}"] = int(g[c].sum())
            row[f"events_{n}_in_silent"] = int(g.loc[g.silent, c].sum())
        pw.append(row)
    pd.DataFrame(pw).to_csv(REPORTS / "power.csv", index=False)

    # ------------------------------------------------------------------ 1. calibration within groups
    groups = {"all": np.ones(len(df), bool), "silent": df.silent.to_numpy(), "not_silent": ~df.silent.to_numpy(), "silent_resid": df.silent_resid.to_numpy(),
              "access_blocked": df.access_blocked.to_numpy(), "silent_311": df.silent_311.to_numpy(),
              "silent_rental_only": (df.silent & ~df.coop_condo).to_numpy(), "p_hat_top_decile": (df.phat_dec == 9).to_numpy()}
    snap_codes = pd.factorize(df.snap)[0]
    ns = snap_codes.max() + 1
    rows_ = []
    for oname, (ycol, pcol) in OUTCOMES.items():
        y, p = df[ycol].to_numpy(float), df[pcol].to_numpy(float)

        def stats(w):
            scale = np.bincount(snap_codes, w * y, ns) / np.maximum(np.bincount(snap_codes, w * p, ns), 1e-12)   # per-snapshot level correction
            ps = p * scale[snap_codes]
            r = {}
            for g, m in groups.items():
                ws = w[m].sum()
                obs, pred, prs = (w[m] * y[m]).sum() / ws, (w[m] * p[m]).sum() / ws, (w[m] * ps[m]).sum() / ws
                r[g] = (obs, pred, obs / pred, obs / prs)
            return r
        point = stats(np.ones(len(df)))
        draws = [stats(w) for w in boot_weights(df.bcode.to_numpy(), B, 1)]
        for g in groups:
            row = dict(outcome=oname, group=g, n_rows=int(groups[g].sum()), n_events=int(y[groups[g]].sum()))
            for i, nm in enumerate(("observed", "predicted", "ratio", "ratio_level_corrected")):
                row.update(ci_row([d[g][i] for d in draws], point[g][i], nm))
            rows_.append(row)
        print(f"calibration {oname} ({time.time() - t0:.0f}s)", flush=True)
    pd.DataFrame(rows_).to_csv(REPORTS / "calibration_groups.csv", index=False)

    # ------------------------------------------------------------------ 2. matched comparison (CEM on strata A)
    bb = df.bcode.to_numpy()
    mrows = []
    for treat in ("silent", "silent_resid", "silent_311"):
        res = matched_boot(Yb, df[treat].to_numpy(), df.strata_A.to_numpy(), bb, B, 2)
        mrows += tidy(res, "matched", "all snapshots", treat, names)
    for treat in ("silent", "silent_resid"):
        res = matched_boot(Yb, df[treat].to_numpy(), df.strata_fine.to_numpy(), bb, B, 13)
        mrows += tidy(res, "matched_fine", "all snapshots, finer cells", treat, names)
    for fold in ("fold1", "fold2", "fold3", "test"):
        m = (df.fold == fold).to_numpy()
        res = matched_boot(Yb[m], df.silent.to_numpy()[m], df.strata_A.to_numpy()[m], bb[m], B, 3)
        mrows += tidy(res, "matched_by_fold", fold, "silent", names)
    m = ~df.coop_condo.to_numpy()
    res = matched_boot(Yb[m], df.silent.to_numpy()[m], df.strata_A.to_numpy()[m], bb[m], B, 4)
    mrows += tidy(res, "matched_rental_only", "excluding co-ops and condos", "silent", names)
    res = matched_boot(Yb[m], df.silent_resid.to_numpy()[m], df.strata_A.to_numpy()[m], bb[m], B, 14)
    mrows += tidy(res, "matched_rental_only", "excluding co-ops and condos", "silent_resid", names)
    for b in ("0", "1-3", "4-11", "12+"):
        m = (df.cbucket == b).to_numpy()
        if df.silent.to_numpy()[m].sum() > 200:
            res = matched_boot(Yb[m], df.silent.to_numpy()[m], df.strata_A.to_numpy()[m], bb[m], B, 5)
            mrows += tidy(res, "matched_by_prior_complaints", f"prior complaint problems {b}", "silent", names)
    pd.DataFrame(mrows).to_csv(REPORTS / "matched.csv", index=False)
    print(f"matched comparison ({time.time() - t0:.0f}s)", flush=True)

    # ------------------------------------------------------------------ balance before and after matching
    X = np.c_[df.p_hat, df.phat_dec, np.log(df.units), df.static_age_at_t.fillna(df.static_age_at_t.median()), (df.borough == "BX").astype(float),
              df.coop_condo.astype(float), df.prior_rate, df.loud_prob_n_12m == 0]
    bal_names = ["p_hat", "p_hat decile", "log units", "age", "Bronx", "co-op or condo", "prior complaint rate per unit (NOT matched on)", "zero prior complaints (NOT matched on)"]
    bf, af = att_balance(X.astype(float), df.silent.to_numpy(), df.strata_A.to_numpy())
    _, af_fine = att_balance(X.astype(float), df.silent.to_numpy(), df.strata_fine.to_numpy())
    bf2, af2 = att_balance(X.astype(float), df.silent_resid.to_numpy(), df.strata_A.to_numpy())
    pd.DataFrame(dict(covariate=bal_names, smd_before=bf, smd_after=af, smd_after_fine=af_fine, resid_smd_before=bf2, resid_smd_after=af2)).to_csv(REPORTS / "balance.csv", index=False)

    # ------------------------------------------------------------------ 3. does silence precede later loudness?
    rate_cols = ["next_rate", "delta_rate"]
    Yr = df[rate_cols].to_numpy(dtype=float)
    lrows = []
    strata_B = strata_codes(df.strata_A, df.cbucket)                                    # strata A + prior complaint bucket (guards against regression to the mean)
    for treat in ("silent", "silent_resid"):
        for label, codes in (("strata A (as the main comparison)", df.strata_A.to_numpy()), ("strata A + prior complaint bucket", strata_B)):
            res = matched_boot(Yr, df[treat].to_numpy(), codes, bb, B, 6)
            lrows += tidy(res, "later_loudness", label, treat, ["next-12m complaint problems per unit", "change from prior-12m rate"])
    m = df.c311_next12.notna().to_numpy()
    c311 = (df.c311_next12 / df.units).to_numpy()
    res = matched_boot(c311[m, None], df.silent.to_numpy()[m], df.strata_A.to_numpy()[m], bb[m], B, 7)
    lrows += tidy(res, "later_loudness", "strata A", "silent", ["next-12m 311 requests per unit"])
    pd.DataFrame(lrows).to_csv(REPORTS / "later_loudness.csv", index=False)
    # the silent group against the model's own expectation, and the descriptive catch-up
    desc = []
    for g, m in (("silent", df.silent), ("not_silent", ~df.silent), ("silent_resid", df.silent_resid)):
        s = df[m]
        desc.append(dict(group=g, rows=len(s), prior_rate=s.prior_rate.mean(), expected_rate_from_condition=s.expected_rate.mean(), next_rate=s.next_rate.mean()))
    pd.DataFrame(desc).to_csv(REPORTS / "later_loudness_descriptive.csv", index=False)
    print(f"later loudness ({time.time() - t0:.0f}s)", flush=True)
    regression(df, B)
    print(f"regression ({time.time() - t0:.0f}s)", flush=True)
    adjusted(df)
    print(f"adjusted ({time.time() - t0:.0f}s)", flush=True)

    # ------------------------------------------------------------------ 4. access-blocked check
    elig = (df.loud_closed_n_12m >= 3).to_numpy()
    ab = df[elig]
    cl_b = pd.cut(ab.loud_closed_n_12m, [3, 6, 12, 30, np.inf], right=False, labels=False).astype(str).to_numpy()
    codes = strata_codes(ab.snap, ab.borough, ab["size"], cl_b, ab.cbucket, np.minimum(ab.phat_dec // 3, 2))
    Ya = np.c_[ab[[v[0] for v in OUTCOMES.values()]].to_numpy(dtype=float), ab.next_rate.to_numpy(dtype=float)]
    names_a = names + ["next-12m complaint problems per unit"]
    arows = tidy(matched_boot(Ya, ab.access_blocked.to_numpy(), codes, ab.bcode.to_numpy(), B, 8), "access_blocked", "eligible buildings (>=3 problems closed in 12m)", "access_blocked", names_a)
    hv = ab.viol_next12.notna().to_numpy()
    Yv = np.c_[ab.viol_next12.to_numpy(dtype=float), ab.viol_c_next12.to_numpy(dtype=float)][hv]
    arows += tidy(matched_boot(Yv, ab.access_blocked.to_numpy()[hv], codes[hv], ab.bcode.to_numpy()[hv], B, 9), "access_blocked",
                  "eligible buildings, snapshots with a 12-month-later violation count", "access_blocked", ["violations issued in next 12m (count)", "class C violations in next 12m (count)"])
    pd.DataFrame(arows).to_csv(REPORTS / "access_blocked.csv", index=False)
    print(f"access-blocked ({time.time() - t0:.0f}s)", flush=True)

    # ------------------------------------------------------------------ 5. heterogeneity: borough and community district
    h = []
    for b in ("BK", "BX"):
        m = (df.borough == b).to_numpy()
        h += tidy(matched_boot(Yb[m], df.silent.to_numpy()[m], df.strata_A.to_numpy()[m], bb[m], B, 10), "heterogeneity_borough", b, "silent", names)
    pd.DataFrame(h).to_csv(REPORTS / "heterogeneity_borough.csv", index=False)
    cdrows = []
    for cd, g in df.groupby("community_district"):
        m = (df.community_district == cd).to_numpy()
        res = matched_boot(Yb[m][:, [0, 2]], df.silent.to_numpy()[m], df.strata_A.to_numpy()[m], bb[m], min(B, 100), 11)
        cdrows += tidy(res, "heterogeneity_cd", cd, "silent", ["primary", "serious_any"])
    cd_df = pd.DataFrame(cdrows)
    cd_df.to_csv(REPORTS / "heterogeneity_cd.csv", index=False)
    het = []
    for o in ("primary", "serious_any"):
        d = cd_df[(cd_df.outcome == o) & (cd_df.events_treated >= 10) & (cd_df.rr > 0) & cd_df.rr_lo.notna()]
        lr = np.log(d.rr.to_numpy())
        se = (np.log(d.rr_hi.to_numpy()) - np.log(d.rr_lo.to_numpy())) / (2 * 1.96)
        wts = 1 / se ** 2
        pooled = (wts * lr).sum() / wts.sum()
        q = float((wts * (lr - pooled) ** 2).sum())
        het.append(dict(outcome=o, districts=len(d), pooled_rr=float(np.exp(pooled)), Q=q, df=len(d) - 1, p_value=float(chi2.sf(q, len(d) - 1)),
                        rr_min=float(d.rr.min()), rr_max=float(d.rr.max())))
    pd.DataFrame(het).to_csv(REPORTS / "heterogeneity_test.csv", index=False)
    print(f"heterogeneity ({time.time() - t0:.0f}s)", flush=True)

    # ------------------------------------------------------------------ 6. placebo: shuffle the silent flag inside the matching cells
    codes = df.strata_A.to_numpy()
    flag = df.silent.to_numpy()
    k = int(codes.max()) + 1
    keep = ((np.bincount(codes, flag.astype(float), k) > 0) & (np.bincount(codes, (~flag).astype(float), k) > 0))[codes]
    ck = np.unique(codes[keep], return_inverse=True)[1]
    rng = np.random.default_rng(12)
    pl = []
    for _ in range(args.placebo):
        sh = shuffle_within(flag[keep], ck, rng)
        m = matched_multi(Yb[keep], sh, ck)
        pl.append(m["rate_t"] / m["rate_c"])
    pl = np.array(pl)
    real = matched_multi(Yb[keep], flag[keep], ck)
    prow = []
    for j, n in enumerate(names):
        prow.append(dict(outcome=n, real_rr=real["rate_t"][j] / real["rate_c"][j], placebo_mean=pl[:, j].mean(), placebo_lo=np.percentile(pl[:, j], 2.5),
                         placebo_hi=np.percentile(pl[:, j], 97.5), shuffles=len(pl),
                         real_outside_placebo=bool(not (np.percentile(pl[:, j], 2.5) <= real["rate_t"][j] / real["rate_c"][j] <= np.percentile(pl[:, j], 97.5)))))
    pd.DataFrame(prow).to_csv(REPORTS / "placebo.csv", index=False)
    print(f"placebo ({time.time() - t0:.0f}s)", flush=True)

    # ------------------------------------------------------------------ 7. who is silent: geography-level summaries only
    geo = []
    for level, key in (("borough", "borough"), ("community_district", "community_district")):
        for name_, g in df.groupby(key):
            row = dict(level=level, area=name_, building_snapshots=len(g), buildings=g.bbl.nunique(), silent_share=g.silent.mean(), silent_resid_share=g.silent_resid.mean(),
                       access_blocked_share=g.access_blocked.mean(), zero_complaint_share=(g.loud_prob_n_12m == 0).mean(), mean_units=g.units.mean(),
                       coop_condo_share=g.coop_condo.mean(), mean_p_hat=g.p_hat.mean(), primary_event_rate=g[OUTCOMES["primary"][0]].mean())
            geo.append(row)
    pd.DataFrame(geo).to_csv(REPORTS / "geography.csv", index=False)
    comp = []
    for b, g in list(df.groupby("borough")) + [("all", df)]:
        for flagname in ("silent", "silent_resid", "access_blocked"):
            f, nf = g[g[flagname]], g[~g[flagname]]
            comp.append(dict(borough=b, flag=flagname, flagged_rows=len(f), units_flagged=f.units.mean(), units_other=nf.units.mean(),
                             age_flagged=f.static_age_at_t.mean(), age_other=nf.static_age_at_t.mean(), coop_condo_flagged=f.coop_condo.mean(),
                             coop_condo_other=nf.coop_condo.mean(), zero_complaints_flagged=(f.loud_prob_n_12m == 0).mean(),
                             zero_complaints_other=(nf.loud_prob_n_12m == 0).mean(), p_hat_flagged=f.p_hat.mean(), p_hat_other=nf.p_hat.mean()))
    pd.DataFrame(comp).to_csv(REPORTS / "composition.csv", index=False)
    print(f"validation done in {(time.time() - t0) / 60:.1f} min", flush=True)


def adjusted(df):
    """Covariate-adjusted risk ratio for the silent flag: Poisson regression with a log link and robust standard errors clustered by
    building (a risk ratio, not an odds ratio). Controls: logit(p_hat), log units, age, borough, building class letter, snapshot. A check
    that the matched result is not an artefact of residual imbalance inside the matching cells."""
    import statsmodels.api as sm
    z = np.log(np.clip(df.p_hat, 1e-4, 1 - 1e-4) / (1 - np.clip(df.p_hat, 1e-4, 1 - 1e-4)))
    base = pd.DataFrame({"const": 1.0, "logit_p": z, "log_units": np.log(df.units), "age": df.static_age_at_t.fillna(df.static_age_at_t.median()) / 50.0,
                         "bronx": (df.borough == "BX").astype(float), "coop_condo": df.coop_condo.astype(float)})
    X0 = pd.concat([base, pd.get_dummies(df.static_bldgclass_letter.astype(str), prefix="cl", drop_first=True, dtype=float),
                    pd.get_dummies(df.snap, prefix="t", drop_first=True, dtype=float)], axis=1)
    rows = []
    for flag in ("silent", "silent_resid"):
        X = X0.assign(**{flag: df[flag].astype(float)})
        for name in ("primary", "wide", "serious_any", "omo"):
            y = df[OUTCOMES[name][0]].to_numpy(float)
            res = sm.GLM(y, X, family=sm.families.Poisson()).fit(cov_type="cluster", cov_kwds={"groups": df.bcode.to_numpy()})
            b, se = res.params[flag], res.bse[flag]
            rows.append(dict(flag=flag, outcome=name, rr=float(np.exp(b)), rr_lo=float(np.exp(b - 1.96 * se)), rr_hi=float(np.exp(b + 1.96 * se)), rows=len(df)))
    pd.DataFrame(rows).to_csv(REPORTS / "adjusted.csv", index=False)


def regression(df, B):
    """Negative-binomial regression on the final test slice: do the non-complaint features (through p_hat) predict
    complaints in the NEXT 12 months over and above last year's complaints? Also restricted to buildings with no complaint
    last year, the buildings that look silent. Cluster-robust standard errors by building."""
    import statsmodels.api as sm
    rows = []
    t = df[df.fold == "test"]
    for label, s in (("all buildings in the test slice", t), ("buildings with zero complaint problems in the prior 12 months", t[t.loud_prob_n_12m == 0])):
        z = np.log(np.clip(s.p_hat, 1e-4, 1 - 1e-4) / (1 - np.clip(s.p_hat, 1e-4, 1 - 1e-4)))
        sd = float(z.std())
        X = pd.DataFrame({"const": 1.0, "logit_p": z.to_numpy(), "log1p_prior": np.log1p(s.loud_prob_n_12m).to_numpy(), "log_units": np.log(s.units).to_numpy()})
        X = pd.concat([X, pd.get_dummies(s.community_district.astype(str), prefix="cd", drop_first=True, dtype=float).reset_index(drop=True),
                       pd.get_dummies(s.snap, prefix="t", drop_first=True, dtype=float).reset_index(drop=True)], axis=1)
        if label.startswith("buildings with zero"):
            X = X.drop(columns="log1p_prior")
        y = s.label_loud_complaints_next12.to_numpy(float)
        mu = sm.GLM(y, X, family=sm.families.Poisson()).fit().mu
        alpha = 0.5
        for _ in range(3):
            alpha = max(float(((y - mu) ** 2 - mu).sum() / (mu ** 2).sum()), 1e-3)
            res = sm.GLM(y, X, family=sm.families.NegativeBinomial(alpha=alpha)).fit(cov_type="cluster", cov_kwds={"groups": s.bcode.to_numpy()})
            mu = res.mu
        for term, scale, tname in (("logit_p", sd, "predicted condition (p_hat), per +1 SD of logit"), ("log1p_prior", 1.0, "log(1 + prior-12m complaint problems)")):
            if term in res.params.index:
                b, se = res.params[term] * scale, res.bse[term] * scale
                rows.append(dict(sample=label, rows=len(s), term=tname, irr=float(np.exp(b)), irr_lo=float(np.exp(b - 1.96 * se)), irr_hi=float(np.exp(b + 1.96 * se)),
                                 nb_alpha=alpha))
    pd.DataFrame(rows).to_csv(REPORTS / "later_loudness_regression.csv", index=False)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--boot", type=int, default=200)
    ap.add_argument("--placebo", type=int, default=200)
    main(ap.parse_args())
