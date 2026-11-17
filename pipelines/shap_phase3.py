"""SHAP for the final-test LightGBM models: global importance with feature-group rollups, a beeswarm
of the top features, and a few example buildings. Exact TreeSHAP via LightGBM's pred_contrib
(log-odds scale), on a random sample of the final test slice (the last four snapshots).

    python pipelines/shap_phase3.py
"""
import json
from pathlib import Path

import lightgbm as lgb
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
import shap  # noqa: E402

from nycdistress.modeling import PROC, SLICES, TARGETS, feature_columns, load_frame, rows  # noqa: E402
from nycdistress.splits import make_folds  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
REPORTS = ROOT / "reports" / "phase3"
MODELS = PROC / "phase3" / "models"
GROUPS = ["static", "meta", "viol", "loud", "evict", "dob", "prior"]
N_SAMPLE = 100_000
TARGET = TARGETS[0]


def group_of(col):
    return col.split("_")[0]


def contributions(booster, X):
    c = booster.predict(X, pred_contrib=True, num_threads=10)
    return c[:, :-1], c[:, -1]                      # per-feature SHAP (log-odds), base value


def main():
    (REPORTS / "figures").mkdir(parents=True, exist_ok=True)
    df = load_frame()
    f = {x.name: x for x in make_folds(sorted(df.snapshot_date.unique()))}["test"]
    ev = df[rows(df, f.eval)].reset_index(drop=True)
    rng = np.random.default_rng(0)
    idx = np.sort(rng.choice(len(ev), size=min(N_SAMPLE, len(ev)), replace=False))
    sample = ev.iloc[idx].reset_index(drop=True)

    group_rows, feat_rows, last = [], [], {}
    for fset in ("all", "no_viol", "no_loud", "static_prior"):
        path = MODELS / f"{TARGET}__{fset}.txt"
        if not path.exists():
            continue
        booster = lgb.Booster(model_file=str(path))
        cols = feature_columns(df, fset)
        sv, base = contributions(booster, sample[cols])
        sv_df = pd.DataFrame(sv, columns=cols)
        tot = np.abs(sv).sum(axis=1).mean()
        for g in GROUPS:
            gc = [c for c in cols if group_of(c) == g]
            if gc:
                val = float(np.abs(sv_df[gc].sum(axis=1)).mean())      # roll up first, then take |.|: groups can cancel
                group_rows.append(dict(fset=fset, group=g, n_features=len(gc), mean_abs_shap=val))
        imp = pd.Series(np.abs(sv).mean(axis=0), index=cols).sort_values(ascending=False)
        for c, v in imp.head(25).items():
            feat_rows.append(dict(fset=fset, feature=c, group=group_of(c), mean_abs_shap=float(v)))
        last[fset] = (sv, base, cols, booster)
        print(f"{fset}: mean |sum of SHAP| per row {tot:.3f}, top feature {imp.index[0]}", flush=True)
    g = pd.DataFrame(group_rows)
    g["share"] = g.mean_abs_shap / g.groupby("fset").mean_abs_shap.transform("sum")
    g.to_csv(REPORTS / "shap_groups.csv", index=False)
    pd.DataFrame(feat_rows).to_csv(REPORTS / "shap_top_features.csv", index=False)

    # ---- group rollup figure
    fig, axes = plt.subplots(1, len(last), figsize=(3.6 * len(last), 3.6), sharey=True)
    axes = np.atleast_1d(axes)
    colors = {"static": "#8c8c8c", "meta": "#bbbbbb", "viol": "#d62728", "loud": "#1f77b4", "evict": "#9467bd", "dob": "#8c564b", "prior": "#2ca02c"}
    for ax, fset in zip(axes, last):
        d = g[g.fset == fset].set_index("group").reindex(GROUPS).dropna()
        ax.barh(d.index[::-1], d.mean_abs_shap[::-1], color=[colors[x] for x in d.index[::-1]])
        ax.set_title(f"features: {fset}", fontsize=10)
        ax.set_xlabel("mean |group SHAP| (log-odds)")
    fig.suptitle(f"Which feature groups drive the {TARGET} score (final test slice)", fontsize=11)
    fig.tight_layout()
    fig.savefig(REPORTS / "figures" / "shap_groups.png", dpi=150)
    plt.close(fig)

    # ---- beeswarm, all-features model
    if "all" in last:
        sv, base, cols, booster = last["all"]
        top = pd.Series(np.abs(sv).mean(axis=0), index=cols).sort_values(ascending=False).head(15).index
        order = [cols.index(c) for c in top]
        X = sample[cols].copy()
        for c in X.select_dtypes("category"):
            X[c] = X[c].cat.codes.astype("float32")
        plt.figure(figsize=(8, 6))
        shap.summary_plot(sv[:20000][:, order], X.iloc[:20000, order].to_numpy(), feature_names=list(top), show=False, max_display=15)
        plt.title("SHAP, all features, top 15 (red = high feature value)", fontsize=10)
        plt.tight_layout()
        plt.savefig(REPORTS / "figures" / "shap_beeswarm.png", dpi=150)
        plt.close()

        # ---- example buildings: latest test snapshot, scored by the all-features model
        snap = ev.snapshot_date.max()
        lat = ev[ev.snapshot_date == snap].reset_index(drop=True)
        score = booster.predict(lat[cols], num_threads=10)
        lat["score"] = score
        y = lat[TARGET].to_numpy()
        rank = pd.Series(score).rank(ascending=False, method="first").to_numpy()
        quiet = SLICES["quiet"](lat)
        picks = {
            "highest-scoring true positive": np.flatnonzero(y == 1)[np.argmax(score[y == 1])],
            "silent: event in a 'quiet' building the violation rule misses, still in the model's top 5%": (lambda m: np.flatnonzero(m)[np.argmax(score[m])] if m.any() else None)((y == 1) & quiet & (rank <= 0.05 * len(lat))),
            "high-scoring false positive": np.flatnonzero(y == 0)[np.argmax(score[y == 0])],
            "missed event (positive with a low score)": np.flatnonzero(y == 1)[np.argmin(score[y == 1])],
        }
        ex_rows = []
        for title, i in picks.items():
            if i is None:
                continue
            sv_i, base_i = contributions(booster, lat.loc[[i], cols])
            order_i = np.argsort(-np.abs(sv_i[0]))[:6]
            for j in order_i:
                v = lat.loc[i, cols[j]]
                ex_rows.append(dict(example=title, bbl=lat.loc[i, "bbl"], snapshot_date=str(snap.date()), score=float(score[i]),
                                    rank_in_snapshot=int(rank[i]), outcome=int(y[i]), feature=cols[j],
                                    value=str(v) if not isinstance(v, (float, np.floating)) else (None if np.isnan(v) else round(float(v), 3)),
                                    shap=round(float(sv_i[0][j]), 3)))
            if title.startswith("highest"):
                names = [cols[j] for j in order_i[::-1]]
                data = [str(lat.loc[i, cols[j]]) for j in order_i[::-1]]
                exp = shap.Explanation(values=sv_i[0][order_i[::-1]], base_values=float(base_i[0]), data=np.array(data, dtype=object), feature_names=names)
                plt.figure(figsize=(7, 3.2))
                shap.plots.waterfall(exp, show=False, max_display=7)
                plt.savefig(REPORTS / "figures" / "shap_example_waterfall.png", dpi=150, bbox_inches="tight")
                plt.close()
        ex_df = pd.DataFrame(ex_rows)
        # building ids stay out of anything meant for git: the committed CSV uses opaque labels, the key stays in the gitignored data folder
        keys = {b: f"example building {k}" for k, b in enumerate(ex_df.bbl.drop_duplicates(), start=1)}
        pd.Series(keys, name="label").rename_axis("bbl").to_csv(ROOT / "data" / "processed" / "phase3" / "shap_example_keys.csv")
        ex_df.assign(bbl=ex_df.bbl.map(keys)).to_csv(REPORTS / "shap_examples.csv", index=False)
    (REPORTS / "shap_info.json").write_text(json.dumps(dict(sample_rows=len(sample), test_rows=len(ev), target=TARGET, scale="log-odds")))
    print("shap done", flush=True)


if __name__ == "__main__":
    main()
