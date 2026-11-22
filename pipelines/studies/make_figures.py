"""Generate publication-grade summary figures for Studies 1 through 5 -> reports/studies/figures/."""
from __future__ import annotations

from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
REP = ROOT / "reports" / "studies"
FIG = REP / "figures"

# Editorial civic-data palette (NYC subway/architectural blueprint inspired: deep slate, terracotta vermilion, warm amber, teal)
INK = "#16191f"
MUTED = "#5b6472"
GRID = "#e4e7ec"
VERMILION = "#c83e2b"
AMBER = "#d97706"
SLATE = "#2b4162"
TEAL = "#1b7f79"
CREAM = "#faf8f4"


def style_ax(ax):
    ax.set_facecolor(CREAM)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.spines["left"].set_color("#c5cbd4")
    ax.spines["bottom"].set_color("#c5cbd4")
    ax.grid(axis="y", color=GRID, linewidth=0.8, zorder=0)
    ax.set_axisbelow(True)
    ax.tick_params(colors=INK, labelsize=10.2)
    ax.xaxis.label.set_size(10.5)
    ax.yaxis.label.set_size(10.5)


def save_fig(fig, path: Path):
    """Save crisp 240-DPI Retina PNG with a subtle archival frame that looks clean on both GitHub Light and Dark modes."""
    fig.patch.set_edgecolor("#cfc8b8")
    fig.patch.set_linewidth(1.5)
    plt.tight_layout(pad=1.8)
    fig.savefig(path, dpi=240, facecolor=CREAM, edgecolor="#cfc8b8")
    plt.close(fig)


def fig_study1():
    tiers_p = REP / "study1_quiet_building_tiers.csv"
    reg_p = REP / "study1_contagion_regressions.csv"
    if not tiers_p.exists() or not reg_p.exists():
        return
    tiers = pd.read_csv(tiers_p)
    regs = pd.read_csv(reg_p)

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(12.2, 4.7), facecolor=CREAM)
    # Left: Quiet buildings (0 complaints & 0 violations) next-year Class C rate by sister-building tier
    labels = ["Clean\n(0)", "Low\n(<0.05)", "Medium\n(0.05–0.15)", "High\n(0.15–0.35)", "Severe\n(0.35+)"]
    x = np.arange(len(tiers))
    colors = [SLATE, "#53749e", AMBER, "#d95b38", VERMILION]
    bars = ax1.bar(x, tiers["pct_class_c_next12m"], color=colors, width=0.62, zorder=3)
    for bar, val in zip(bars, tiers["pct_class_c_next12m"]):
        ax1.text(bar.get_x() + bar.get_width() / 2, val + 0.35, f"{val:.1f}%", ha="center", va="bottom", fontsize=9.5, fontweight="bold", color=INK)
    ax1.set_xticks(x)
    ax1.set_xticklabels(labels)
    ax1.set_ylabel("% getting Class C hazard in next 12m", color=INK)
    ax1.set_xlabel("Sister buildings' Class C rate per unit (prior 12m)", color=INK)
    ax1.set_title("Completely Quiet Buildings (0 complaints, 0 violations)\nNext-Year Class C Rate by Landlord's Sister Buildings", fontsize=10.5, fontweight="bold", color=INK, pad=10)
    ax1.set_ylim(0, max(tiers["pct_class_c_next12m"]) * 1.22)
    style_ax(ax1)

    # Right: Forest plot of controlled contagion ORs (per SD of log sister Class C)
    sel = regs[regs["outcome"] == "label_class_c_any"].copy()
    name_map = {
        "quiet_0v_0c": "Quiet buildings (0 comp, 0 viol)",
        "quiet_never_sold": "Quiet & never sold (2018–25)",
        "quiet_small_port_le50": "Quiet (portfolio ≤ 50 bldgs)",
        "quiet_headofficer_only": "Quiet (Head Officer link only)",
        "phase4_silent": "Phase 4 'Silent' buildings",
        "all_multi_port": "All multi-building lots",
        "quiet_0v_0c_placebo": "Shuffled-portfolio placebo",
    }
    sel = sel[sel["slice"].isin(name_map)].copy()
    sel["order"] = sel["slice"].map({k: i for i, k in enumerate(name_map)})
    sel = sel.sort_values("order", ascending=False)
    y = np.arange(len(sel))
    ax2.axvline(1.0, color=MUTED, linestyle="--", linewidth=1.1, zorder=1)
    for yi, (_, r) in enumerate(sel.iterrows()):
        col = MUTED if "placebo" in r["slice"] else VERMILION
        ax2.plot([r["ci_lo"], r["ci_hi"]], [yi, yi], color=col, linewidth=2.4, zorder=3)
        ax2.scatter([r["or"]], [yi], color=col, s=55, zorder=4)
        ax2.text(r["ci_hi"] + 0.02, yi, f"{r['or']:.2f} [{r['ci_lo']:.2f}, {r['ci_hi']:.2f}]", va="center", fontsize=8.5, color=INK)
    ax2.set_yticks(y)
    ax2.set_yticklabels([name_map[s] for s in sel["slice"]])
    ax2.set_xlabel("Odds Ratio per +1 SD sister-building Class C rate\n(CD + Snapshot FE, portfolio-clustered 95% CI)", color=INK)
    ax2.set_title("Controlled Portfolio Contagion Estimates\n(Outcome: Any Class C Hazard in Next 12 Months)", fontsize=10.5, fontweight="bold", color=INK, pad=10)
    ax2.set_xlim(0.85, max(sel["ci_hi"]) + 0.35)
    style_ax(ax2)
    ax2.grid(axis="x", color=GRID, linewidth=0.8)
    ax2.grid(axis="y", visible=False)

    save_fig(fig, FIG / "study1_portfolio_contagion.png")


def fig_study2():
    hw = pd.read_csv(REP / "study2_heat_markov_persistence.csv")
    conc = pd.read_csv(REP / "study2_concentration.csv")
    c1 = conc[conc["top_pct"] == 1.0].copy()

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(12.2, 4.7), facecolor=CREAM)
    # Left: Concentration top 1% buildings vs top 1% units (rate-ranked)
    short = {
        "omo_usd": "Taxpayer OMO ($)",
        "hw_probs_7w": "Winter Heat\nComplaints",
        "evict_n": "Marshal\nEvictions",
        "viol_c": "Class C\nViolations",
        "open_c": "Open Class C\nViolations",
        "litig_n": "HPD\nLitigations",
    }
    c1 = c1.sort_values("share_by_top_bldgs_pct", ascending=True)
    y = np.arange(len(c1))
    h = 0.36
    ax1.barh(y + h / 2, c1["share_by_top_bldgs_pct"], height=h, color=VERMILION, label="Top 1% of buildings", zorder=3)
    ax1.barh(y - h / 2, c1["share_by_top_units_rate_pct"], height=h, color=SLATE, label="Top 1% of units (size-adjusted)", zorder=3)
    for yi, (_, r) in enumerate(c1.iterrows()):
        ax1.text(r["share_by_top_bldgs_pct"] + 0.8, yi + h / 2, f"{r['share_by_top_bldgs_pct']:.1f}%", va="center", fontsize=8.5, fontweight="bold", color=VERMILION)
        ax1.text(r["share_by_top_units_rate_pct"] + 0.8, yi - h / 2, f"{r['share_by_top_units_rate_pct']:.1f}%", va="center", fontsize=8.5, color=SLATE)
    ax1.set_yticks(y)
    ax1.set_yticklabels([short[m] for m in c1["metric"]])
    ax1.set_xlabel("% of All Bronx & Brooklyn Events / Dollars")
    ax1.set_title("Extreme Concentration Across 101,749 Buildings\n(Raw Top 1% vs. Size-Adjusted Top 1% of Units)", fontsize=10.5, fontweight="bold", color=INK, pad=10)
    ax1.set_xlim(0, 64)
    ax1.legend(frameon=True, facecolor=CREAM, edgecolor="none", fontsize=8.5, loc="upper center", bbox_to_anchor=(0.5, -0.17), ncol=2)
    style_ax(ax1)
    ax1.grid(axis="x", color=GRID)
    ax1.grid(axis="y", visible=False)

    # Right: Heat Markov persistence staircase into Winter 2024-25
    x = hw["prior_failed_winters_of_6"].to_numpy()
    vals = hw["pct_fail_winter_2024_25"].to_numpy()
    bars = ax2.bar(x, vals, color=[SLATE if k < 3 else (AMBER if k < 5 else VERMILION) for k in x], width=0.65, zorder=3)
    for bar, v in zip(bars, vals):
        ax2.text(bar.get_x() + bar.get_width() / 2, v + 1.8, f"{v:.1f}%", ha="center", va="bottom", fontsize=9, fontweight="bold", color=INK)
    ax2.set_xticks(x)
    ax2.set_xticklabels([f"{k}/6" for k in x])
    ax2.set_xlabel("Prior Failed Winters (2018–2024, ≥3 Heat Complaints)")
    ax2.set_ylabel("% Failing Heat Again in Winter 2024–25")
    ax2.set_title("Winter Heat Recidivism: Near-Deterministic Persistence\n(1,920 6/6 Repeaters: 92% Fail Again = 42.5% of Complaints)", fontsize=10.2, fontweight="bold", color=INK, pad=10)
    ax2.set_ylim(0, 108)
    style_ax(ax2)

    save_fig(fig, FIG / "study2_concentration_heat.png")


def fig_study3():
    km = pd.read_csv(REP / "study3_km_survival.csv")
    mo = pd.read_csv(REP / "study3_complaint_seasonality.csv")

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(12.2, 4.7), facecolor=CREAM)
    # Left: KM median days to close Class C violations by hazard category
    hc = km[km["group_type"] == "classC_hazard_category"].copy()
    hc = hc[hc["group"] != "other"].sort_values("km_median_days", ascending=True)
    nice = {
        "heat_hot_water": "Heat & Hot Water",
        "water_plumbing": "Water Leak / Plumbing",
        "fire_safety": "Fire / Smoke / CO",
        "doors_windows_locks": "Doors / Locks / Windows",
        "walls_ceilings_floors": "Plaster / Walls / Floors",
        "lead_paint": "Lead Paint (21-day law)",
        "pests_vermin": "Pests / Rats / Roaches",
        "mold": "Mold / Mildew",
    }
    y = np.arange(len(hc))
    cols = [VERMILION if d >= 250 else (AMBER if d >= 105 else SLATE) for d in hc["km_median_days"]]
    ax1.barh(y, hc["km_median_days"], color=cols, height=0.62, zorder=3)
    for yi, (_, r) in enumerate(hc.iterrows()):
        ax1.text(r["km_median_days"] + 10, yi, f"{int(r['km_median_days'])}d ({r['km_still_open_1yr_pct']:.0f}% open at 1yr)", va="center", fontsize=8.5, color=INK)
    ax1.axvline(1, color=TEAL, linestyle=":", linewidth=1.2)
    ax1.set_yticks(y)
    ax1.set_yticklabels([nice.get(g, g) for g in hc["group"]])
    ax1.set_xlabel("Kaplan-Meier Median Days to Close (Right-Censoring Adjusted)")
    ax1.set_title("Class C ('24-Hour Immediately Hazardous') Survival Time\n(1.06M Violations, 2018–2025)", fontsize=10.5, fontweight="bold", color=INK, pad=10)
    ax1.set_xlim(0, 820)
    style_ax(ax1)
    ax1.grid(axis="x", color=GRID)
    ax1.grid(axis="y", visible=False)

    # Right: Winter complaint surge vs violation-yield collapse
    months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
    x = np.arange(12)
    ax2.bar(x, mo["closed_problems"] / 1000.0, color="#d0d7e2", width=0.65, label="Closed complaints (k)", zorder=2)
    ax2.set_xticks(x)
    ax2.set_xticklabels(months, fontsize=8.5)
    ax2.set_ylabel("Closed HPD Problems (Thousands)", color=MUTED)
    ax2.set_ylim(0, 460)
    style_ax(ax2)

    ax2b = ax2.twinx()
    ax2b.plot(x, mo["pct_violation_issued"], color=VERMILION, marker="o", linewidth=2.4, label="% Violation Issued", zorder=4)
    ax2b.plot(x, mo["pct_no_access"], color=SLATE, marker="s", linewidth=1.8, linestyle="--", label="% No Access", zorder=4)
    ax2b.set_ylabel("% of Closed Complaints", color=VERMILION)
    ax2b.set_ylim(0, 96)
    ax2b.spines["top"].set_visible(False)
    ax2.set_title("Winter Enforcement Bottleneck: Volume Doubles,\nViolation-Issuance Rate Drops in Half (68% → 33%)", fontsize=10.5, fontweight="bold", color=INK, pad=10)
    lines1, labels1 = ax2.get_legend_handles_labels()
    lines2, labels2 = ax2b.get_legend_handles_labels()
    ax2b.legend(lines1 + lines2, labels1 + labels2, frameon=False, fontsize=8.2, loc="upper center", ncol=3, columnspacing=1.0, handlelength=1.6)

    save_fig(fig, FIG / "study3_zombie_classC_seasonality.png")


def fig_study4():
    cem = pd.read_csv(REP / "study4_cem_comparison.csv")
    es = pd.read_csv(REP / "study4_event_study.csv")

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(12.2, 4.7), facecolor=CREAM)
    # Left: CEM ratios (evicting vs matched same-size same-CD non-evicting)
    sub = cem[cem["metric"] != "units_residential"].copy()
    labels = {
        "vc_pu": "Class C Violations\n(per unit)",
        "open_c_pu": "Open Class C\n(per unit)",
        "omo_pu": "Taxpayer OMO Spend\n($ per unit)",
        "lit_n": "HPD Litigations\n(count)",
        "harass_lit": "Harassment\nLitigations",
    }
    y = np.arange(len(sub))
    ax1.axvline(1.0, color=MUTED, linestyle="--", linewidth=1.1)
    for yi, (_, r) in enumerate(sub.iterrows()):
        ax1.plot([r["ratio_ci_lo"], r["ratio_ci_hi"]], [yi, yi], color=VERMILION, linewidth=2.6, zorder=3)
        ax1.scatter([r["ratio"]], [yi], color=VERMILION, s=60, zorder=4)
        ax1.text(r["ratio_ci_hi"] + 0.05, yi, f"{r['ratio']:.2f}x [{r['ratio_ci_lo']:.2f}, {r['ratio_ci_hi']:.2f}]", va="center", fontsize=8.8, fontweight="bold", color=INK)
    ax1.set_yticks(y)
    ax1.set_yticklabels([labels[m] for m in sub["metric"]])
    ax1.set_xlabel("Matched Ratio: Evicting ÷ Identical-Size Same-CD Non-Evicting (95% CI)")
    ax1.set_title("The Eviction–Hazard Paradox (11,429 Evicting Buildings)\nMatched on District, Fine Unit-Size, Era & Building Class", fontsize=10.5, fontweight="bold", color=INK, pad=10)
    ax1.set_xlim(0.8, 3.05)
    style_ax(ax1)
    ax1.grid(axis="x", color=GRID)
    ax1.grid(axis="y", visible=False)

    # Right: Event study around first post-moratorium eviction (complaints & Class C count)
    cp = es[es["outcome"] == "any_complaint_q"].copy()
    ref = pd.DataFrame([{"outcome": "any_complaint_q", "event_q": -1, "theta": 0.0, "lo": 0.0, "hi": 0.0}])
    cp = pd.concat([cp, ref]).sort_values("event_q")
    ax2.axhline(0, color=MUTED, linestyle="--", linewidth=1)
    ax2.axvline(-0.5, color=VERMILION, linestyle=":", linewidth=1.4, label="First post-moratorium eviction")
    ax2.fill_between(cp["event_q"], cp["lo"] * 100, cp["hi"] * 100, color=SLATE, alpha=0.18, zorder=2)
    ax2.plot(cp["event_q"], cp["theta"] * 100, color=SLATE, marker="o", linewidth=2.2, label="Any HPD complaint (pp vs matched controls)", zorder=3)
    ax2.set_xlabel("Quarters Relative to First Post-Moratorium Eviction (e = -1 ref)")
    ax2.set_ylabel("Change in Quarterly Complaint Probability (pp)")
    ax2.set_title("After Eviction: Complaints Drop Cleanly (-2.0 pp)\n(Flat Pre-Trend p = 0.60; 6,844 Treated vs 89,685 Controls)", fontsize=10.5, fontweight="bold", color=INK, pad=10)
    ax2.legend(frameon=False, fontsize=8.5, loc="lower left")
    style_ax(ax2)

    save_fig(fig, FIG / "study4_eviction_hazard.png")


def fig_study5():
    aep_ev = pd.read_csv(REP / "study5_aep_event_study.csv")
    rel = pd.read_csv(REP / "study5_aep_relapse.csv").iloc[0]
    sh = pd.read_csv(REP / "study5_sales_heterogeneous.csv")

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(12.2, 4.7), facecolor=CREAM)
    # Left: AEP OMO event study + post-discharge relapse callout
    om = aep_ev[aep_ev["outcome"] == "any_omo_q"].copy()
    ref = pd.DataFrame([{"outcome": "any_omo_q", "event_q": -1, "theta": 0.0, "lo": 0.0, "hi": 0.0}])
    om = pd.concat([om, ref]).sort_values("event_q")
    ax1.axhline(0, color=MUTED, linestyle="--", linewidth=1)
    ax1.axvline(-0.5, color=TEAL, linestyle=":", linewidth=1.4, label="AEP selection")
    ax1.fill_between(om["event_q"], om["lo"] * 100, om["hi"] * 100, color=TEAL, alpha=0.18)
    ax1.plot(om["event_q"], om["theta"] * 100, color=TEAL, marker="o", linewidth=2.2, label="Quarterly OMO probability (pp)")
    ax1.set_xlabel("Quarters Relative to AEP Selection")
    ax1.set_ylabel("Change in Quarterly OMO Emergency Repair Prob. (pp)")
    ax1.set_title(f"AEP Cuts Acute Emergency Repairs (~20 pp),\nYet {rel['pct_5plus_classC_within_2y']:.0f}% of Discharged Buildings Relapse Within 2 Years", fontsize=10.2, fontweight="bold", color=INK, pad=10)
    ax1.text(0.03, 0.10, f"Post-discharge (n={int(rel['discharged_bldgs']):,}):\n• {rel['pct_5plus_classC_within_2y']:.1f}% get 5+ new Class C in 2y\n• {rel['pct_new_omo_within_2y']:.1f}% need new OMO in 2y\n• {rel['pct_reentered_aep']:.1f}% re-enter AEP",
             transform=ax1.transAxes, fontsize=8.2, bbox=dict(boxstyle="round,pad=0.4", facecolor="#fff", edgecolor="#c5cbd4"))
    ax1.legend(frameon=False, fontsize=8.2, loc="upper right")
    style_ax(ax1)

    # Right: Heterogeneous post-sale DiD (Clean vs Mild vs Distressed)
    tiers = ["clean_base_0C", "mild_base_1to4C", "distressed_base_5plusC"]
    tlabels = ["Clean pre-sale\n(0 Class C, n=7,254)", "Mild pre-sale\n(1–4 Class C, n=651)", "Distressed pre-sale\n(5+ Class C, n=674)"]
    x = np.arange(len(tiers))
    w = 0.26
    for j, (out, lbl, col) in enumerate([("any_classC", "Any Class C", VERMILION), ("any_complaint", "Any Complaint", AMBER), ("any_eviction", "Any Eviction", SLATE)]):
        s = sh[(sh["tier"].isin(tiers)) & (sh["outcome"] == out)].set_index("tier").loc[tiers]
        vals = s["avg_post"].to_numpy() * 100
        err_lo = (s["avg_post"] - s["avg_post_lo"]).to_numpy() * 100
        err_hi = (s["avg_post_hi"] - s["avg_post"]).to_numpy() * 100
        ax2.bar(x + (j - 1) * w, vals, width=w, color=col, label=lbl, zorder=3)
        ax2.errorbar(x + (j - 1) * w, vals, yerr=[err_lo, err_hi], fmt="none", ecolor=INK, capsize=3, linewidth=1.1, zorder=4)
    ax2.axhline(0, color=MUTED, linewidth=1)
    ax2.set_xticks(x)
    ax2.set_xticklabels(tlabels, fontsize=8.8)
    ax2.set_ylabel("Avg Post-Sale DiD Change (percentage points)")
    ax2.set_title("Post-Sale Event Study Split by Pre-Sale Condition\n(Distressed Buildings Don't Get Fixed; Evictions Dip Slightly)", fontsize=10.2, fontweight="bold", color=INK, pad=10)
    ax2.legend(frameon=False, fontsize=8.5, loc="upper left")
    style_ax(ax2)

    save_fig(fig, FIG / "study5_aep_and_sales.png")


def main():
    FIG.mkdir(parents=True, exist_ok=True)
    fig_study1()
    fig_study2()
    fig_study3()
    fig_study4()
    fig_study5()
    print("Generated figures in", FIG)


if __name__ == "__main__":
    main()
