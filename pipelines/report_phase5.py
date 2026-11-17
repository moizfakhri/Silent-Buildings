"""Phase 5 figures from reports/phase5/study_*.csv (run after sales_study.py)."""
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "reports" / "phase5"
FIG = OUT / "figures"
TITLES = {"any_violation": "Any HPD violation", "any_class_c": "Any class C violation", "any_complaint": "Any complaint problem", "any_serious": "Any serious event"}


def panel(ax, ev, group, spec, outcome, color, label=None):
    d = ev[(ev.group == group) & (ev.spec == spec) & (ev.outcome == outcome)].sort_values("event")
    d = pd.concat([d, pd.DataFrame([dict(event=-1, theta=0.0, lo=0.0, hi=0.0)])]).sort_values("event")
    ax.fill_between(d.event, d.lo, d.hi, color=color, alpha=0.18, lw=0)
    ax.plot(d.event, d.theta, "-o", color=color, ms=3.5, lw=1.5, label=label)


def main():
    ev = pd.read_csv(OUT / "study_event_time.csv")
    res = pd.read_csv(OUT / "study_results.csv")
    FIG.mkdir(parents=True, exist_ok=True)
    fig, axes = plt.subplots(1, 4, figsize=(15, 3.8), sharex=True)
    for ax, o in zip(axes, TITLES):
        panel(ax, ev, "all", "primary", o, "#1f6f8b")
        r = res[(res.group == "all") & (res.spec == "primary") & (res.outcome == o)].iloc[0]
        ax.axhline(0, color="#777", lw=0.8)
        ax.axvline(-0.5, color="#aaa", lw=0.8, ls="--")
        ax.set_title(f"{TITLES[o]}\navg post {r.avg_post:+.3f} [{r.avg_post_lo:+.3f}, {r.avg_post_hi:+.3f}]\npre-trend p={r.pre_trend_p:.2f}", fontsize=9)
        ax.set_xlabel("quarters since the sale")
    axes[0].set_ylabel("effect on probability in a quarter\n(vs quarter -1, vs matched never-sold buildings)")
    fig.tight_layout()
    fig.savefig(FIG / "event_study_all.png", dpi=160)
    plt.close(fig)

    fig, axes = plt.subplots(1, 4, figsize=(15, 3.4), sharex=True)
    for ax, o in zip(axes, TITLES):
        panel(ax, ev, "silent", "primary", o, "#b5472f", "silent at baseline")
        panel(ax, ev, "not_silent", "primary", o, "#1f6f8b", "not silent")
        ax.axhline(0, color="#777", lw=0.8)
        ax.axvline(-0.5, color="#aaa", lw=0.8, ls="--")
        ax.set_title(TITLES[o], fontsize=9)
        ax.set_xlabel("quarters since the sale")
    axes[0].legend(fontsize=8, frameon=False)
    axes[0].set_ylabel("effect on probability in a quarter")
    fig.tight_layout()
    fig.savefig(FIG / "event_study_silent_vs_not.png", dpi=160)
    plt.close(fig)
    lines = ["| Group | Outcome | Treated / controls | Pre-sale mean | Avg post-sale effect [95% CI] | Relative | After removing the pre-trend [95% CI] | Pre-trend p |",
             "|---|---|---|---|---|---|---|---|"]
    names = {"all": "all sales", "late_all": "sales 2022Q2+", "silent": "silent at baseline", "not_silent": "not silent"}
    for _, r in res[res.spec == "primary"].iterrows():
        lines.append(f"| {names[r.group]} | {r.outcome} | {int(r.n_treated):,} / {int(r.n_control):,} | {r.pre_mean_treated:.3f} | {r.avg_post:+.4f} [{r.avg_post_lo:+.4f}, {r.avg_post_hi:+.4f}] "
                     f"| {r.relative_pct:+.0f}% | {r.adj_post:+.4f} [{r.adj_post_lo:+.4f}, {r.adj_post_hi:+.4f}] | {r.pre_trend_p:.3f} |")
    (OUT / "study_table.md").write_text("\n".join(lines) + "\n")
    rob = res[(res.group == "all") & (res.spec != "primary")]
    lines = ["| Control group | Outcome | Avg post-sale effect [95% CI] | Pre-trend p |", "|---|---|---|---|"]
    sp = {"uncond": "never-sold, no reweighting", "notyet": "not-yet-sold (staggered)"}
    for _, r in rob.iterrows():
        lines.append(f"| {sp[r.spec]} | {r.outcome} | {r.avg_post:+.4f} [{r.avg_post_lo:+.4f}, {r.avg_post_hi:+.4f}] | {r.pre_trend_p:.3f} |")
    (OUT / "study_robustness_table.md").write_text("\n".join(lines) + "\n")
    print("figures and tables written")


if __name__ == "__main__":
    main()
