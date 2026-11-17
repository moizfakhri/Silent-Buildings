"""Make the Phase 3 figures and refresh the generated tables in docs/modeling_phase3.md from
reports/phase3/*.csv (written by evaluate_phase3.py and shap_phase3.py).

    python pipelines/report_phase3.py          # or `make report`
"""
import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
REPORTS = ROOT / "reports" / "phase3"
FIG = REPORTS / "figures"
DOC = ROOT / "docs" / "modeling_phase3.md"
BEGIN, END = "<!-- BEGIN GENERATED -->", "<!-- END GENERATED -->"
LABEL = {"rule_viol_12m": "rule: violations in last 12m", "rule_complaints_12m": "rule: complaints in last 12m",
         "rule_last_event": "rule: most recent earlier event", "logit": "logistic", "lgb": "LightGBM"}
FSET = {"-": "", "all": "all features", "no_viol": "without viol_*", "no_loud": "without loud_*", "static_prior": "static + prior only"}
TARGET_NAME = {"label_serious_any": "any serious event", "label_omo": "OMO / emergency repair charge",
               "label_litigation": "HPD litigation", "label_vacate_or_aep": "vacate order or AEP selection"}
HEAD_ORDER = [("rule_viol_12m", "-"), ("rule_complaints_12m", "-"), ("rule_last_event", "-"), ("logit", "all"), ("logit", "no_viol"),
              ("logit", "no_loud"), ("logit", "static_prior"), ("lgb", "all"), ("lgb", "no_viol"), ("lgb", "no_loud"), ("lgb", "static_prior")]
COMPACT = [("rule_viol_12m", "-"), ("logit", "all"), ("lgb", "all"), ("lgb", "no_viol"), ("lgb", "no_loud"), ("lgb", "static_prior")]


def name(m, f):
    return LABEL[m] + (f" ({FSET[f]})" if FSET[f] else "")


def md(headers, rows):
    out = ["| " + " | ".join(headers) + " |", "|" + "|".join("---" for _ in headers) + "|"]
    return "\n".join(out + ["| " + " | ".join(str(c) for c in r) + " |" for r in rows])


def ci(d, metric, pct=False, digits=3):
    r = d[d.metric == metric]
    if r.empty:
        return "-"
    r = r.iloc[0]
    f = (lambda v: f"{100 * v:.1f}%") if pct else (lambda v: f"{v:.{digits}f}")
    return f"{f(r.point)} [{f(r.lo)}, {f(r.hi)}]"


def point(d, metric, pct=False, digits=3):
    r = d[d.metric == metric]
    if r.empty:
        return "-"
    v = r.iloc[0].point
    return f"{100 * v:.1f}%" if pct else f"{v:.{digits}f}"


def main():
    FIG.mkdir(parents=True, exist_ok=True)
    ci_df = pd.read_csv(REPORTS / "metrics_test_ci.csv")
    mf = pd.read_csv(REPORTS / "metrics_by_fold.csv")
    out = []

    def sel(target, slc):
        return ci_df[(ci_df.target == target) & (ci_df.slice == slc)]

    def row_of(d, m, f):
        return d[(d.model == m) & (d.fset == f)]

    # ---------------------------------------------------------------- headline
    t0 = "label_serious_any"
    d = sel(t0, "all")
    rows = []
    for m, f in HEAD_ORDER:
        r = row_of(d, m, f)
        if r.empty:
            continue
        cal = mf[(mf.target == t0) & (mf.fold == "test") & (mf.slice == "all") & (mf.model == m) & (mf.fset == f)]
        brier_ece = f"{cal.iloc[0].brier:.4f} / {cal.iloc[0].ece:.4f}" if not cal.empty and pd.notna(cal.iloc[0].get("brier")) else "-"
        dp = "(reference)" if (m, f) == ("rule_viol_12m", "-") else ci(r, "diff_pr_auc")
        out.append(("headline", [name(m, f), ci(r, "roc_auc"), ci(r, "pr_auc"), ci(r, "p_top1pct", True), ci(r, "p_top5pct", True),
                                 point(r, "lift_top5pct", digits=2) + "x", dp, brier_ece]))
    out_md = ["### Headline: final test slice, any serious event\n",
              f"Train on snapshots up to 2024-01-01, score the last four snapshots (2025-01-01 to 2025-10-01), touched once. "
              f"Base rate {point(d[d.model == 'rule_viol_12m'], 'base_rate', True)}. 95% intervals are cluster bootstraps by building "
              f"({int(json.loads((REPORTS / 'run_info.json').read_text())['boot'])} resamples, the same resamples for every model, so the difference column is paired). "
              "Precision at top 1% / 5% is measured inside each snapshot and pooled.\n",
              md(["model", "ROC-AUC", "PR-AUC", "precision top 1%", "precision top 5%", "lift top 5%", "PR-AUC minus violation rule", "Brier / ECE"],
                 [r for k, r in out if k == "headline"]), ""]

    # ---------------------------------------------------------------- other targets
    out_md.append("### Other targets (final test slice)\n")
    for target in ("label_omo", "label_litigation", "label_vacate_or_aep"):
        d = sel(target, "all")
        if d.empty:
            continue
        base = point(d[d.model == "rule_viol_12m"], "base_rate", True)
        rows = []
        for m, f in COMPACT:
            r = row_of(d, m, f)
            if not r.empty:
                rows.append([name(m, f), ci(r, "roc_auc"), ci(r, "pr_auc"), ci(r, "p_top5pct", True), point(r, "lift_top5pct", digits=2) + "x",
                             "(reference)" if (m, f) == ("rule_viol_12m", "-") else ci(r, "diff_pr_auc")])
        out_md += [f"**{TARGET_NAME[target]}** (base rate {base})\n",
                   md(["model", "ROC-AUC", "PR-AUC", "precision top 5%", "lift top 5%", "PR-AUC minus violation rule"], rows), ""]

    # ---------------------------------------------------------------- ablation summary
    rows = []
    for target in TARGET_NAME:
        d = sel(target, "all")
        for f in ("all", "no_viol", "no_loud", "static_prior"):
            r = row_of(d, "lgb", f)
            if not r.empty:
                rows.append([TARGET_NAME[target], FSET[f], ci(r, "pr_auc"), ci(r, "diff_pr_auc")])
    out_md += ["### What each feature group contributes (LightGBM, final test slice)\n",
               "`PR-AUC minus violation rule` is paired against the violations-in-the-last-12-months rule.\n",
               md(["target", "LightGBM features", "PR-AUC", "minus violation rule"], rows), ""]

    # ---------------------------------------------------------------- borough and quiet slices
    for title, slices in (("### By borough (any serious event, final test slice)\n", ("bronx", "brooklyn")),
                          ("### Buildings the violation rule would not flag (any serious event, final test slice)\n", ("quiet", "zero_viol", "clean_record"))):
        out_md.append(title)
        if slices[0] == "quiet":
            out_md.append("`quiet` = no class C violation and at most 2 violations in the prior 12 months; `zero_viol` = no violation at all in the prior 12 months; `clean_record` = nothing on record: no violation in 12 months, none still open, no complaint in 12 months, "
                          "and no earlier OMO charge, litigation, vacate order or AEP selection (so only static fields can speak). "
                          "`quiet` still includes buildings with a large backlog of OLD open violations, so it is not a clean test of silence; `clean_record` is.\n")
        rows = []
        for slc in slices:
            d = sel(t0, slc)
            if d.empty:
                continue
            for m, f in COMPACT:
                r = row_of(d, m, f)
                if not r.empty:
                    n = mf[(mf.target == t0) & (mf.fold == "test") & (mf.slice == slc) & (mf.model == m) & (mf.fset == f)].iloc[0]
                    rows.append([slc, f"{int(n.n_rows):,} / {int(n.n_pos):,}", name(m, f), point(r, "base_rate", True), ci(r, "roc_auc"), ci(r, "pr_auc"),
                                 ci(r, "p_top5pct", True), point(r, "lift_top5pct", digits=2) + "x"])
        out_md += [md(["slice", "rows / events", "model", "base rate", "ROC-AUC", "PR-AUC", "precision top 5%", "lift top 5%"], rows), ""]

    lv = REPORTS / "lgb_vs_logit_test.csv"
    if lv.exists():
        x = pd.read_csv(lv)
        x = x[x.model == "lgb|all"]
        out_md += ["### Is LightGBM better than the logistic regression? (any serious event, all features, final test slice, paired)\n",
                   md(["metric", "LightGBM minus logistic [95% CI]"],
                      [[m, f"{r.point:.4f} [{r.lo:.4f}, {r.hi:.4f}]"] for m in ("roc_auc", "pr_auc", "p_top5pct", "p_top1pct")
                       for r in x[x.metric == f"diff_{m}"].itertuples()]), ""]

    # ---------------------------------------------------------------- walk-forward stability
    rows = []
    for fold in ("fold1", "fold2", "fold3", "test"):
        for m, f in (("rule_viol_12m", "-"), ("logit", "all"), ("lgb", "all"), ("lgb", "no_loud"), ("lgb", "static_prior")):
            r = mf[(mf.target == t0) & (mf.fold == fold) & (mf.slice == "all") & (mf.model == m) & (mf.fset == f)]
            if not r.empty:
                r = r.iloc[0]
                rows.append([fold, name(m, f), f"{r.roc_auc:.3f}", f"{r.pr_auc:.3f}", f"{100 * r.p_top5pct:.1f}%", f"{100 * r.base_rate:.1f}%"])
    ev_info = json.loads((REPORTS / "run_info.json").read_text())
    out_md += ["### Walk-forward folds (any serious event)\n",
               "Evaluation snapshots: " + "; ".join(f"{k}: {v[0]} to {v[-1]} (trained up to {ev_info['train_end'][k]})" for k, v in ev_info["eval_snapshots"].items()) + ".\n",
               md(["fold", "model", "ROC-AUC", "PR-AUC", "precision top 5%", "base rate"], rows), ""]

    # ---------------------------------------------------------------- pooled labels, spatial, shap
    pl = REPORTS / "pooled_labels_from_serious_any.csv"
    if pl.exists():
        p = pd.read_csv(pl)
        rows = [[r.label, f"{int(r.events):,}", name(r.model, r.fset), f"{r.roc_auc:.3f}", f"{r.pr_auc:.3f}", f"{100 * r.recall_top1pct:.1f}%", f"{100 * r.recall_top5pct:.1f}%", f"{r.lift_top5pct:.2f}x"]
                for r in p.itertuples()]
        out_md += ["### Rare events scored with the any-serious-event model (descriptive, final test slice)\n",
                   md(["event", "events", "score used", "ROC-AUC", "PR-AUC", "recall in top 1%", "recall in top 5%", "lift top 5%"], rows), ""]
    sp = REPORTS / "spatial_check.csv"
    if sp.exists():
        s = pd.read_csv(sp)
        rows = [[r.setup, f"{r.n_rows:,}", f"{r.roc_auc:.3f}", f"{r.pr_auc:.3f}", f"{100 * r.p_top5pct:.1f}%", f"{r.lift_top5pct:.2f}x"] for r in s.itertuples()]
        out_md += ["### Spatial hold-out (fold3, any serious event, LightGBM, all features)\n",
                   md(["setup", "rows", "ROC-AUC", "PR-AUC", "precision top 5%", "lift top 5%"], rows), ""]
    sg = REPORTS / "shap_groups.csv"
    if sg.exists():
        g = pd.read_csv(sg)
        rows = []
        for fset in ("all", "no_viol", "no_loud", "static_prior"):
            d = g[g.fset == fset]
            if not d.empty:
                rows.append([FSET[fset]] + [f"{100 * d[d.group == x].share.iloc[0]:.0f}%" if (d.group == x).any() else "-" for x in ("static", "viol", "loud", "evict", "dob", "prior")])
        out_md += ["### SHAP: share of the score's attribution by feature group (any serious event, final test slice)\n",
                   "Mean absolute group SHAP (features summed within the group first), as a share of the total. Log-odds scale.\n",
                   md(["LightGBM features", "static", "viol_*", "loud_*", "evict_*", "dob_*", "prior_*"], rows), ""]
        tf = pd.read_csv(REPORTS / "shap_top_features.csv")
        for fset in ("all", "no_loud"):
            d = tf[tf.fset == fset].head(12)
            if not d.empty:
                out_md += [f"Top 12 features ({FSET[fset]}): " + ", ".join(f"`{r.feature}` ({r.mean_abs_shap:.2f})" for r in d.itertuples()) + "\n"]
        ex = REPORTS / "shap_examples.csv"
        if ex.exists():
            e = pd.read_csv(ex)
            rows = [[r.example, r.bbl, f"{r.score:.2f}", r.rank_in_snapshot, r.outcome, r.feature, r.value, r.shap] for r in e.itertuples()]
            out_md += ["Example buildings (latest test snapshot, top 6 contributions each):\n",
                       md(["example", "bbl", "score", "rank", "event", "feature", "value", "SHAP"], rows), ""]

    # ---------------------------------------------------------------- training meta
    metas = [json.loads(p.read_text()) for p in sorted((ROOT / "data" / "processed" / "phase3" / "preds").glob("*.json")) if "spatial" not in p.name and "groups" not in p.name]
    if metas:
        m = pd.DataFrame(metas)
        out_md += ["### Training runtime and early stopping\n",
                   f"{len(m)} (fold, target, feature set) fits. LightGBM seconds per fit: median {m.seconds_lgb.median():.0f}, max {m.seconds_lgb.max():.0f}; "
                   f"logistic regression: median {m.seconds_logit.median():.0f}, max {m.seconds_logit.max():.0f}. Best iteration (early stopping on a later purged slice): "
                   f"median {int(m.best_iteration.median())}, range {int(m.best_iteration.min())} to {int(m.best_iteration.max())}.\n"]

    # ---------------------------------------------------------------- figures
    ps = pd.read_csv(REPORTS / "per_snapshot.csv", parse_dates=["snapshot_date"])
    cal = pd.read_csv(REPORTS / "calibration_test.csv")
    colors = {("rule_viol_12m", "-"): "#7f7f7f", ("logit", "all"): "#ff7f0e", ("lgb", "all"): "#1f77b4", ("lgb", "no_viol"): "#2ca02c",
              ("lgb", "no_loud"): "#9467bd", ("lgb", "static_prior"): "#8c564b"}
    # 1 headline bars
    d = sel(t0, "all")
    fig, axes = plt.subplots(1, 2, figsize=(11, 4.2))
    for ax, metric, title in ((axes[0], "pr_auc", "PR-AUC"), (axes[1], "roc_auc", "ROC-AUC")):
        labels, pts, los, his, cs = [], [], [], [], []
        for m, f in HEAD_ORDER:
            r = row_of(d, m, f)
            r = r[r.metric == metric]
            if not r.empty:
                labels.append(name(m, f))
                pts.append(r.iloc[0].point)
                los.append(r.iloc[0].point - r.iloc[0].lo)
                his.append(r.iloc[0].hi - r.iloc[0].point)
                cs.append(colors.get((m, f), "#bbbbbb" if m.startswith("rule") else ("#fdbf6f" if m == "logit" else "#1f77b4")))
        ax.barh(labels[::-1], pts[::-1], xerr=[los[::-1], his[::-1]], color=cs[::-1], capsize=2)
        ax.set_title(f"{title} (95% CI, bootstrap by building)", fontsize=10)
        ax.tick_params(axis="y", labelsize=7)
        ax.set_xlim(min(pts) * 0.9, max(his[i] + pts[i] for i in range(len(pts))) * 1.02)
    fig.suptitle("Any serious event, final test slice: models and ablations", fontsize=11)
    fig.tight_layout()
    fig.savefig(FIG / "headline_ablation.png", dpi=150)
    plt.close(fig)
    # 2 calibration
    fig, ax = plt.subplots(figsize=(4.8, 4.6))
    ax.plot([0, 0.5], [0, 0.5], "k--", lw=1, label="perfect")
    c = cal[cal.target == t0]
    for (m, f), col in ((("lgb", "all"), "#1f77b4"), (("logit", "all"), "#ff7f0e"), (("lgb", "no_loud"), "#9467bd")):
        x = c[(c.model == m) & (c.fset == f)]
        ax.plot(x.mean_pred, x.observed, "o-", color=col, label=name(m, f), ms=4)
    ax.set_xlabel("mean predicted probability (decile)")
    ax.set_ylabel("observed event rate")
    ax.set_title("Calibration, final test slice", fontsize=10)
    ax.legend(fontsize=7)
    fig.tight_layout()
    fig.savefig(FIG / "calibration.png", dpi=150)
    plt.close(fig)
    # 3 per snapshot
    fig, axes = plt.subplots(1, 2, figsize=(11, 3.8), sharex=True)
    for ax, metric, title in ((axes[0], "pr_auc", "PR-AUC"), (axes[1], "p_top5pct", "precision at top 5%")):
        for (m, f), col in colors.items():
            x = ps[(ps.model == m) & (ps.fset == f)].sort_values("snapshot_date")
            ax.plot(x.snapshot_date, x[metric], "o-", ms=3, color=col, label=name(m, f))
        ax.set_title(f"{title} by evaluation snapshot (out of time)", fontsize=10)
        ax.tick_params(axis="x", labelsize=7, rotation=30)
    axes[0].legend(fontsize=6)
    fig.tight_layout()
    fig.savefig(FIG / "per_snapshot.png", dpi=150)
    plt.close(fig)
    # 4 slices
    fig, ax = plt.subplots(figsize=(8, 3.8))
    slices = ("all", "bronx", "brooklyn", "quiet", "zero_viol", "clean_record")
    width = 0.13
    for i, (m, f) in enumerate(COMPACT):
        vals = []
        for slc in slices:
            r = row_of(sel(t0, slc), m, f)
            r = r[r.metric == "pr_auc"]
            vals.append(r.iloc[0].point if not r.empty else float("nan"))
        ax.bar([j + i * width for j in range(len(slices))], vals, width, label=name(m, f), color=colors.get((m, f)))
    ax.set_xticks([j + 2.5 * width for j in range(len(slices))])
    ax.set_xticklabels(slices)
    ax.set_ylabel("PR-AUC")
    ax.set_title("PR-AUC by slice (any serious event, final test slice)", fontsize=10)
    ax.legend(fontsize=6)
    fig.tight_layout()
    fig.savefig(FIG / "slices.png", dpi=150)
    plt.close(fig)

    block = f"{BEGIN}\n\n" + "\n".join(out_md) + f"\n{END}"
    text = DOC.read_text() if DOC.exists() else "# Phase 3\n"
    text = (text[:text.index(BEGIN)] + block + text[text.index(END) + len(END):]) if BEGIN in text else text + "\n" + block + "\n"
    DOC.write_text(text)
    print(f"updated {DOC.relative_to(ROOT)}; figures in {FIG.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
