"""Figures and generated tables for docs/silent_distress_phase4.md, from reports/phase4/*.csv.
Geography-level and aggregate numbers only: no building identifiers, no owner names.

    python pipelines/report_phase4.py        # or `make report4`
"""
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
R = ROOT / "reports" / "phase4"
FIG = R / "figures"
DOC = ROOT / "docs" / "silent_distress_phase4.md"
BEGIN, END = "<!-- BEGIN GENERATED -->", "<!-- END GENERATED -->"
ONAME = {"primary": "primary: vacate or DOB hazard (core)", "wide": "vacate or DOB hazard (wide)", "serious_any": "any serious event",
         "omo": "OMO charge", "vacate_or_aep": "vacate or AEP", "litigation": "litigation"}
CHAIN = {"serious_any", "omo", "vacate_or_aep", "litigation"}


def md(headers, rows):
    out = ["| " + " | ".join(headers) + " |", "|" + "|".join("---" for _ in headers) + "|"]
    return "\n".join(out + ["| " + " | ".join(str(c) for c in r) + " |" for r in rows])


def ci(r, k="rr", d=2, pct=False):
    f = (lambda v: f"{100 * v:.{d}f}%") if pct else (lambda v: f"{v:.{d}f}")
    return f"{f(r[k])} [{f(r[k + '_lo'])}, {f(r[k + '_hi'])}]"


def cal_ci(r, k):
    f = lambda v: f"{v:.2f}"  # noqa: E731
    return f"{f(r[k])} [{f(r[k + '_lo'])}, {f(r[k + '_hi'])}]"


def main():
    FIG.mkdir(parents=True, exist_ok=True)
    pw, cal, mt = pd.read_csv(R / "power.csv"), pd.read_csv(R / "calibration_groups.csv"), pd.read_csv(R / "matched.csv")
    ll, ldesc, lreg = pd.read_csv(R / "later_loudness.csv"), pd.read_csv(R / "later_loudness_descriptive.csv"), pd.read_csv(R / "later_loudness_regression.csv")
    ab, bal, pl = pd.read_csv(R / "access_blocked.csv"), pd.read_csv(R / "balance.csv"), pd.read_csv(R / "placebo.csv")
    hb, ht = pd.read_csv(R / "heterogeneity_borough.csv"), pd.read_csv(R / "heterogeneity_test.csv")
    geo, comp = pd.read_csv(R / "geography.csv"), pd.read_csv(R / "composition.csv")
    cm = pd.read_csv(R / "condition_model.csv")
    adj = pd.read_csv(R / "adjusted.csv") if (R / "adjusted.csv").exists() else None
    out = []

    # ------------------------------------------------------------------ power and condition model
    p = pw.set_index("fold")
    rows = [[f, f"{int(p.loc[f, 'rows']):,}", f"{int(p.loc[f, 'silent_rows']):,}", f"{int(p.loc[f, 'events_primary']):,}", f"{int(p.loc[f, 'events_primary_in_silent']):,}",
             f"{int(p.loc[f, 'events_wide']):,}", f"{int(p.loc[f, 'events_serious_any']):,}", f"{int(p.loc[f, 'events_vacate_or_aep']):,}"] for f in ("fold1", "fold2", "fold3", "test", "all")]
    out += ["### Power: events per evaluation fold\n", "The primary outcome has about 2,200 events per fold (949 inside the silent group over all folds), enough for the matched comparison to have usable intervals "
            "when snapshots are pooled; single folds have wider intervals (about 190 to 290 events in the silent group). The wide definition's event count varies by a factor of 2 between folds (administrative batches).\n",
            md(["fold", "building-snapshots", "silent rows", "primary events", "primary events in silent group", "wide events", "any serious events", "vacate or AEP events"], rows), ""]
    c = cm[cm.target == "label_vacate_or_dobhaz_core"]
    out += ["### The condition model (static + earlier city/court events only), primary outcome\n",
            md(["fold", "base rate", "mean predicted", "ROC-AUC", "PR-AUC", "lift top 5%", "ECE"],
               [[r.fold, f"{100 * r.base_rate:.2f}%", f"{100 * r.mean_pred:.2f}%", f"{r.roc_auc:.3f}", f"{r.pr_auc:.3f}", f"{r.lift_top5pct:.1f}x", f"{r.ece:.4f}"] for r in c.itertuples()]), ""]

    # ------------------------------------------------------------------ calibration within groups
    out.append("### 1. Calibration within groups: are silent buildings as risky as the condition model says?\n")
    out.append("Observed event rate divided by the condition model's mean prediction, pooled over 16 out-of-time snapshots. 'Level corrected' rescales each snapshot's predictions so the average building is exactly 1.00 "
               "(the event base rate drifts between snapshots). 1.00 means the complaint record adds no information beyond predicted condition; below 1.00 means silent buildings have fewer events than predicted. 95% CI: cluster bootstrap by building.\n")
    names = {"silent": "silent (rank gap, top decile)", "not_silent": "not silent", "silent_resid": "silent (model residual)", "silent_311": "silent (311 loudness)",
             "silent_rental_only": "silent, excluding co-ops and condos", "access_blocked": "access-blocked"}
    for o in ("primary", "wide", "serious_any", "omo"):
        d = cal[cal.outcome == o].set_index("group")
        rows = [[names[g], f"{int(d.loc[g, 'n_events']):,}", f"{100 * d.loc[g, 'observed']:.2f}%", f"{100 * d.loc[g, 'predicted']:.2f}%", cal_ci(d.loc[g], "ratio"), cal_ci(d.loc[g], "ratio_level_corrected")]
                for g in names if g in d.index]
        out += [f"**{ONAME[o]}**\n", md(["group", "events", "observed", "predicted", "observed / predicted", "level corrected"], rows), ""]

    # ------------------------------------------------------------------ matched
    out.append("### 2. Matched comparison: silent vs not silent buildings with the same predicted condition\n")
    out.append("Coarsened exact matching inside cells of snapshot x borough x size band x building class x age band x predicted-risk decile (controls reweighted to the silent group). Relative risk = event rate "
               "of silent buildings divided by that of matched not-silent buildings. Outcomes that start with a tenant complaint (OMO, litigation, AEP, hence 'any serious') are mechanically rarer where nobody complains, "
               "so they are shown in a separate column group.\n")
    rows = []
    for a, t, label in (("matched", "silent", "rank gap (pre-specified)"), ("matched_fine", "silent", "rank gap, finer cells"), ("matched_rental_only", "silent", "rank gap, rental buildings only"),
                        ("matched", "silent_311", "rank gap on 311 loudness"), ("matched", "silent_resid", "model residual"), ("matched_fine", "silent_resid", "model residual, finer cells"),
                        ("matched_rental_only", "silent_resid", "model residual, rental only")):
        d = mt[(mt.analysis == a) & (mt.treatment == t)].set_index("outcome")
        if d.empty:
            continue
        rows.append([label, f"{int(d.loc['primary', 'n_matched']):,}", ci(d.loc["primary"]), ci(d.loc["wide"]), ci(d.loc["serious_any"]), ci(d.loc["omo"]), ci(d.loc["litigation"]), ci(d.loc["vacate_or_aep"])])
    out += [md(["silent definition", "silent rows matched", "primary", "wide DOB hazard", "any serious (chain)", "OMO (chain)", "litigation (chain)", "vacate or AEP"], rows), ""]
    d = mt[(mt.analysis == "matched") & (mt.treatment == "silent") & (mt.outcome == "primary")].iloc[0]
    out += [f"Primary outcome, silent group: {100 * d.rate_treated:.2f}% vs {100 * d.rate_control:.2f}% in matched not-silent buildings ({int(d.events_treated):,} events in the silent group, {d.share_matched * 100:.1f}% of silent rows matched).\n"]
    rows = []
    for fold in ("fold1", "fold2", "fold3", "test"):
        d = mt[(mt.analysis == "matched_by_fold") & (mt.subset == fold)].set_index("outcome")
        rows.append([fold, f"{int(d.loc['primary', 'events_treated']):,}", ci(d.loc["primary"]), ci(d.loc["serious_any"]), ci(d.loc["omo"])])
    out += ["By fold (rank-gap silent, pre-specified matching):\n", md(["fold", "silent events (primary)", "primary", "any serious", "OMO"], rows), ""]
    rows = []
    for b in ("0", "1-3", "4-11"):
        d = mt[(mt.analysis == "matched_by_prior_complaints") & (mt.subset == f"prior complaint problems {b}")].set_index("outcome")
        if not d.empty:
            rows.append([b, f"{int(d.loc['primary', 'n_flagged']):,}", ci(d.loc["primary"]), ci(d.loc["serious_any"])])
    out += ["Stratified by the number of complaint problems in the prior 12 months (silent vs not silent inside the stratum; only a handful of silent buildings have complaints):\n",
            md(["prior complaint problems", "silent rows", "primary", "any serious"], rows), ""]
    if adj is not None:
        rows = [[r.flag, ONAME[r.outcome], f"{r.rr:.2f} [{r.rr_lo:.2f}, {r.rr_hi:.2f}]"] for r in adj.itertuples()]
        out += ["Covariate-adjusted risk ratio (Poisson regression, log link, standard errors clustered by building; controls: predicted condition, size, age, borough, class, snapshot):\n",
                md(["flag", "outcome", "risk ratio [95% CI]"], rows), ""]
    out += ["Covariate balance (standardised mean differences; below 0.10 is conventional):\n",
            md(["covariate", "before matching", "after (pre-specified)", "after (finer cells)", "residual flag: before", "residual flag: after"],
               [[r.covariate, f"{r.smd_before:.2f}", f"{r.smd_after:.2f}", f"{r.smd_after_fine:.2f}", f"{r.resid_smd_before:.2f}", f"{r.resid_smd_after:.2f}"] for r in bal.itertuples()]), ""]

    # ------------------------------------------------------------------ later loudness
    out.append("### 3. Does silence precede later loudness?\n")
    d = ll[(ll.treatment == "silent")]
    rows = [[r.subset, r.outcome, f"{r.rate_treated:.3f}", f"{r.rate_control:.3f}", ci(dict(rr=r.rr, rr_lo=r.rr_lo, rr_hi=r.rr_hi))] for r in d.itertuples()]
    out += [md(["matching cells", "outcome", "silent", "matched not silent", "ratio [95% CI]"], rows), ""]
    rows = [[r.group, f"{r.prior_rate:.3f}", f"{r.expected_rate_from_condition:.3f}", f"{r.next_rate:.3f}"] for r in ldesc.itertuples()]
    out += ["Complaint problems per unit per year, descriptive:\n", md(["group", "prior 12 months", "expected from predicted condition (cross-sectional model)", "next 12 months"], rows), ""]
    rows = [[r.sample, f"{r.rows:,}", r.term, f"{r.irr:.2f} [{r.irr_lo:.2f}, {r.irr_hi:.2f}]"] for r in lreg.itertuples()]
    out += ["Negative-binomial regression of next-12-month complaint problems, final test slice (incidence rate ratios; controls: community district, snapshot, size; cluster-robust by building):\n",
            md(["sample", "rows", "term", "IRR [95% CI]"], rows), ""]

    # ------------------------------------------------------------------ access blocked
    out.append("### 4. Access-blocked buildings\n")
    out.append("Buildings with at least 3 problems closed in the last 12 months and at least half of them closed for no access, against buildings with at least 3 closed problems and a lower no-access share, "
               "matched on snapshot, borough, size, number of closed problems, prior complaint bucket and predicted-risk tercile.\n")
    rows = [[r.outcome, f"{r.rate_treated:.4g}", f"{r.rate_control:.4g}", ci(dict(rr=r.rr, rr_lo=r.rr_lo, rr_hi=r.rr_hi))] for r in ab.itertuples()]
    out += [md(["outcome in the next 12 months", "access-blocked", "matched comparison", "ratio [95% CI]"], rows), ""]

    # ------------------------------------------------------------------ heterogeneity
    out.append("### 5. Heterogeneity\n")
    rows = [[r.subset, ONAME[r.outcome], ci(dict(rr=r.rr, rr_lo=r.rr_lo, rr_hi=r.rr_hi))] for r in hb[hb.outcome.isin(["primary", "serious_any", "omo"])].itertuples()]
    out += [md(["borough", "outcome", "relative risk [95% CI]"], rows), "",
            md(["outcome", "community districts", "pooled RR", "Q", "df", "p-value", "district RR range"],
               [[r.outcome, r.districts, f"{r.pooled_rr:.2f}", f"{r.Q:.1f}", r.df, f"{r.p_value:.3f}", f"{r.rr_min:.2f} to {r.rr_max:.2f}"] for r in ht.itertuples()]), "",
            "District estimates for the primary outcome rest on few events each (many districts have under 20 silent-group events), so the range is mostly noise; the test is the informative part.\n"]

    # ------------------------------------------------------------------ placebo
    out += ["### 6. Placebo: the silent flag shuffled inside the matching cells\n",
            md(["outcome", "real relative risk", "placebo mean", "placebo 95% range (200 shuffles)", "real outside the placebo range"],
               [[ONAME[r.outcome], f"{r.real_rr:.2f}", f"{r.placebo_mean:.3f}", f"{r.placebo_lo:.2f} to {r.placebo_hi:.2f}", "yes" if r.real_outside_placebo else "no"] for r in pl.itertuples()]), ""]

    # ------------------------------------------------------------------ geography / fairness
    out.append("### 7. Who is in the silent group (geography-level summaries)\n")
    b = geo[geo.level == "borough"]
    out += [md(["borough", "buildings", "silent share (by construction 10%)", "model-residual silent share", "access-blocked share", "no complaint in 12 months", "mean units", "co-op or condo", "mean predicted risk"],
               [[r.area, f"{r.buildings:,}", f"{100 * r.silent_share:.1f}%", f"{100 * r.silent_resid_share:.1f}%", f"{100 * r.access_blocked_share:.1f}%", f"{100 * r.zero_complaint_share:.0f}%", f"{r.mean_units:.1f}",
                 f"{100 * r.coop_condo_share:.1f}%", f"{100 * r.mean_p_hat:.2f}%"] for r in b.itertuples()]), ""]
    cd = geo[geo.level == "community_district"].sort_values("area")
    out += ["Community districts, silent share of building-snapshots (the share is 10% by construction in each borough, so the spread across districts is the finding):\n",
            md(["district", "buildings", "silent share", "no complaint in 12 months", "mean units", "co-op or condo", "primary event rate"],
               [[r.area, f"{r.buildings:,}", f"{100 * r.silent_share:.1f}%", f"{100 * r.zero_complaint_share:.0f}%", f"{r.mean_units:.1f}", f"{100 * r.coop_condo_share:.1f}%", f"{100 * r.primary_event_rate:.2f}%"] for r in cd.itertuples()]), ""]
    c = comp[comp.borough == "all"]
    out += [md(["flag", "flagged rows", "units: flagged vs other", "age: flagged vs other", "co-op or condo: flagged vs other", "no complaint: flagged vs other", "predicted risk: flagged vs other"],
               [[r.flag, f"{int(r.flagged_rows):,}", f"{r.units_flagged:.0f} vs {r.units_other:.0f}", f"{r.age_flagged:.0f} vs {r.age_other:.0f}", f"{100 * r.coop_condo_flagged:.1f}% vs {100 * r.coop_condo_other:.1f}%",
                 f"{100 * r.zero_complaints_flagged:.0f}% vs {100 * r.zero_complaints_other:.0f}%", f"{100 * r.p_hat_flagged:.2f}% vs {100 * r.p_hat_other:.2f}%"] for r in c.itertuples()]), ""]

    # ------------------------------------------------------------------ figures
    # 1 forest
    fig, ax = plt.subplots(figsize=(8.5, 4.6))
    defs = [("matched", "silent", "rank gap"), ("matched_fine", "silent", "rank gap, finer cells"), ("matched_rental_only", "silent", "rank gap, rental only"),
            ("matched", "silent_311", "311 rank gap"), ("matched", "silent_resid", "model residual")]
    ys, labels, k = [], [], 0
    for o in ("primary", "wide", "serious_any", "omo", "litigation"):
        for a, t, lab in defs:
            d = mt[(mt.analysis == a) & (mt.treatment == t) & (mt.outcome == o)]
            if d.empty:
                continue
            r = d.iloc[0]
            ax.errorbar(r.rr, k, xerr=[[r.rr - r.rr_lo], [r.rr_hi - r.rr]], fmt="o", color="#1f77b4" if o not in CHAIN else "#d62728", ms=4, capsize=2)
            labels.append(f"{ONAME[o].split(':')[0]} | {lab}")
            ys.append(k)
            k += 1
        k += 0.6
    ax.axvline(1, color="k", lw=1, ls="--")
    ax.set_yticks(ys)
    ax.set_yticklabels(labels, fontsize=6)
    ax.invert_yaxis()
    ax.set_xscale("log")
    ax.set_xlabel("relative risk, silent vs matched not-silent (log scale; below 1 = fewer events when silent)")
    ax.set_title("Silent buildings have FEWER later events than comparable buildings\n(blue: least tenant-driven outcomes; red: outcomes that start with a complaint)", fontsize=9)
    fig.tight_layout()
    fig.savefig(FIG / "matched_forest.png", dpi=150)
    plt.close(fig)
    # 2 calibration within groups
    fig, ax = plt.subplots(figsize=(8, 3.8))
    gs = ["silent", "silent_resid", "silent_rental_only", "access_blocked"]
    for i, o in enumerate(("primary", "wide", "serious_any", "omo")):
        d = cal[cal.outcome == o].set_index("group")
        for j, g in enumerate(gs):
            r = d.loc[g]
            ax.errorbar(i + 0.15 * j - 0.22, r.ratio_level_corrected, yerr=[[r.ratio_level_corrected - r.ratio_level_corrected_lo], [r.ratio_level_corrected_hi - r.ratio_level_corrected]],
                        fmt="o", color=["#1f77b4", "#ff7f0e", "#2ca02c", "#9467bd"][j], capsize=2, label=names[g] if i == 0 else None, ms=4)
    ax.axhline(1, color="k", lw=1, ls="--")
    ax.set_xticks(range(4))
    ax.set_xticklabels(["primary", "wide DOB hazard", "any serious", "OMO"])
    ax.set_ylabel("observed / predicted (level corrected)")
    ax.set_title("Observed events vs the condition model's prediction, by group (1.0 = complaints add nothing)", fontsize=9)
    ax.legend(fontsize=6)
    fig.tight_layout()
    fig.savefig(FIG / "calibration_groups.png", dpi=150)
    plt.close(fig)
    # 3 geography
    cdg = geo[geo.level == "community_district"].sort_values("area")
    fig, ax = plt.subplots(figsize=(9, 3.6))
    ax.bar(cdg.area.astype(str), 100 * cdg.silent_share, color=["#1f77b4" if str(a).startswith("3") else "#d95f02" for a in cdg.area])
    ax.axhline(10, color="k", lw=1, ls="--")
    ax.set_ylabel("silent share of building-snapshots (%)")
    ax.set_title("Silent share by community district (blue Brooklyn, orange Bronx; 10% by construction within each borough)", fontsize=9)
    ax.tick_params(axis="x", labelsize=6, rotation=90)
    fig.tight_layout()
    fig.savefig(FIG / "silent_by_district.png", dpi=150)
    plt.close(fig)
    # 4 placebo
    fig, ax = plt.subplots(figsize=(7, 3.2))
    for i, r in enumerate(pl.itertuples()):
        ax.plot([r.placebo_lo, r.placebo_hi], [i, i], color="#999999", lw=6, solid_capstyle="butt", label="placebo 95% range" if i == 0 else None)
        ax.plot(r.real_rr, i, "o", color="#d62728", label="real" if i == 0 else None)
    ax.axvline(1, color="k", lw=1, ls="--")
    ax.set_yticks(range(len(pl)))
    ax.set_yticklabels([ONAME[o].split(":")[0] for o in pl.outcome], fontsize=7)
    ax.invert_yaxis()
    ax.set_xlabel("relative risk")
    ax.legend(fontsize=6)
    ax.set_title("Placebo: shuffling the flag inside the matching cells removes the effect", fontsize=9)
    fig.tight_layout()
    fig.savefig(FIG / "placebo.png", dpi=150)
    plt.close(fig)

    block = f"{BEGIN}\n\n" + "\n".join(out) + f"\n{END}"
    text = DOC.read_text() if DOC.exists() else "# Phase 4\n"
    text = (text[:text.index(BEGIN)] + block + text[text.index(END) + len(END):]) if BEGIN in text else text + "\n" + block + "\n"
    DOC.write_text(text)
    print(f"updated {DOC.relative_to(ROOT)}; figures in {FIG.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
