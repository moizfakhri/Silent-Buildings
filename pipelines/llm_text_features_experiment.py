"""Phase 7, gate E2: do text-derived severity features improve out-of-time prediction?

    python pipelines/llm_text_features_experiment.py        # about 8 minutes

Features (as of each snapshot t, violations inspected in (t - 12 months, t], same bucket convention as Phase 2): counts of HPD violations whose
text matches ten keyword categories (heat/hot water, mold or leak, pests, lead, fire safety, gas or electric, structural, sanitation, plumbing,
doors/locks/windows) and the share of hazard-type categories among the violations. The text is only read, never generated.

Test: LightGBM with the Phase 3 `all` features versus `all` plus these 11 columns, same walk-forward folds with the 12 month purge, same
hyperparameters, target `label_serious_any` on all four folds and the Phase 4 primary outcome on the two latest folds.
Adoption rule, fixed before running: adopt only if the final-test PR-AUC gain is at least +0.005 with a paired cluster-bootstrap 95% interval
above 0, and the gain is positive in at least 3 of the 4 folds.
"""
import json
import time
from pathlib import Path

import duckdb
import pandas as pd

from nycdistress.evaluation import RankEval, cluster_bootstrap
from nycdistress.modeling import PROC, feature_columns, fit_lgb, load_frame, predict_lgb, rows
from nycdistress.splits import make_folds

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "reports" / "phase7"
CATS = {
    "heat_hot_water": r"HEAT|HOT WATER", "mold_leak": r"MOLD|LEAK", "pests": r"ROACH|MICE|MOUSE|\bRATS?\b|RODENT|VERMIN|BEDBUG|INFEST",
    "lead": r"\bLEAD\b", "fire_safety": r"\bFIRE\b|SMOKE DETECT|CARBON MONOXIDE", "gas_electric": r"\bGAS\b|ELECTRIC|WIRING",
    "structural": r"UNSAFE|COLLAPS|STRUCTURAL|BULGING|CRACKED", "sanitation": r"REFUSE|RUBBISH|GARBAGE|FILTH|ACCUMULAT",
    "plumbing": r"FAUCET|SINK|WASH ?BASIN|WATER CLOSET|TOILET|FLUSH|PLUMB", "doors_locks_windows": r"\bLOCK|DOOR|WINDOW|INTERCOM|BUZZER",
}
HAZARD = ["heat_hot_water", "mold_leak", "pests", "lead", "fire_safety", "gas_electric", "structural"]
TXT = [f"txt_{c}_n_12m" for c in CATS] + ["txt_hazard_share_12m"]


def build_text_features():
    out = PROC / "text_features.parquet"
    con = duckdb.connect()
    con.execute("SET memory_limit='8GB'")
    raw = f"read_parquet('{ROOT / 'data' / 'raw' / 'hpd_violations'}/part-*.parquet', union_by_name=true)"
    base = "DATE '2018-01-01'"
    qi = lambda x: f"CAST(floor((datediff('month', {base}, CAST(date_trunc('month', {x}) AS DATE)) + CASE WHEN day({x}) > 1 THEN 1 ELSE 0 END + 2) / 3.0) AS INTEGER)"  # noqa: E731
    flags = ", ".join(f"regexp_matches(upper(novdescription), '{rx}') AS c_{k}" for k, rx in CATS.items())
    con.execute(f"""CREATE TABLE v AS
        SELECT lpad(CAST(COALESCE(CAST(TRY_CAST(bbl AS DOUBLE) AS BIGINT),
                   TRY_CAST(boroid AS BIGINT) * 1000000000 + TRY_CAST(block AS BIGINT) * 10000 + TRY_CAST(lot AS BIGINT)) AS VARCHAR), 10, '0') AS bbl,
               CAST(TRY_CAST(inspectiondate AS TIMESTAMP) AS DATE) AS d, {flags}
        FROM {raw} WHERE TRY_CAST(inspectiondate AS TIMESTAMP) IS NOT NULL""")
    sel = ", ".join(f"CAST(sum(CASE WHEN c_{k} THEN 1 ELSE 0 END) AS INTEGER) AS n_{k}" for k in CATS)
    con.execute(f"CREATE TABLE ev AS SELECT bbl, {qi('d')} AS qb, count(*) AS n_all, {sel} FROM v WHERE d <= DATE '2026-11-14' GROUP BY 1, 2")
    con.execute(f"""CREATE TABLE snaps AS SELECT CAST(DATE '2019-01-01' + to_months(3 * i) AS DATE) AS snapshot_date, {qi("CAST(DATE '2019-01-01' + to_months(3 * i) AS DATE)")} AS q FROM range(0, 28) t(i)""")
    wsum = ", ".join(f"CAST(COALESCE(sum(e.n_{k}), 0) AS INTEGER) AS txt_{k}_n_12m" for k in CATS)
    con.execute(f"""CREATE TABLE f AS
        SELECT sp.bbl, n.snapshot_date, {wsum}, CAST(COALESCE(sum(e.n_all), 0) AS INTEGER) AS n_all
        FROM read_parquet('{PROC / 'spine.parquet'}') sp CROSS JOIN snaps n
        LEFT JOIN ev e ON e.bbl = sp.bbl AND e.qb > n.q - 4 AND e.qb <= n.q
        WHERE sp.yearbuilt IS NULL OR sp.yearbuilt < year(n.snapshot_date)
        GROUP BY sp.bbl, n.snapshot_date""")
    hz = " + ".join(f"txt_{k}_n_12m" for k in HAZARD)
    con.execute(f"COPY (SELECT bbl, snapshot_date, {', '.join(f'txt_{k}_n_12m' for k in CATS)}, CASE WHEN n_all > 0 THEN ({hz}) * 1.0 / n_all END AS txt_hazard_share_12m FROM f) TO '{out}' (FORMAT PARQUET)")
    return out


def main():
    t0 = time.time()
    OUT.mkdir(parents=True, exist_ok=True)
    tf = PROC / "text_features.parquet"
    if not tf.exists():
        build_text_features()
    print(f"text features ready ({time.time() - t0:.0f}s)", flush=True)
    df = load_frame()
    base_cols = feature_columns(df, "all")          # taken BEFORE the text columns are merged in
    t = pd.read_parquet(tf)
    t["snapshot_date"] = pd.to_datetime(t["snapshot_date"])
    df = df.merge(t, on=["bbl", "snapshot_date"], how="left")
    for c in TXT:
        df[c] = df[c].astype("float32")
    folds = {f.name: f for f in make_folds(sorted(df.snapshot_date.unique()))}
    cols_text = base_cols + TXT
    res, boot_out = [], {}
    plan = [("label_serious_any", ["fold1", "fold2", "fold3", "test"]), ("label_vacate_or_dobhaz_core", ["fold3", "test"])]
    for target, fnames in plan:
        for fname in fnames:
            f = folds[fname]
            itr, es, tr, ev = (df[rows(df, d)] for d in (f.inner_train, f.es, f.train, f.eval))
            scores = {}
            for name, cols in (("base", base_cols), ("text", cols_text)):
                booster, _, _ = fit_lgb(itr, es, cols, target, final_train=tr)
                scores[name] = predict_lgb(booster, ev, cols)
            y = ev[target].to_numpy()
            evals = {k: RankEval(y, s, ev.snapshot_date.to_numpy()) for k, s in scores.items()}
            m = {k: e.metrics() for k, e in evals.items()}
            res.append(dict(target=target, fold=fname, pr_auc_base=m["base"]["pr_auc"], pr_auc_text=m["text"]["pr_auc"], gain=m["text"]["pr_auc"] - m["base"]["pr_auc"],
                            roc_base=m["base"]["roc_auc"], roc_text=m["text"]["roc_auc"], p5_base=m["base"]["p_top5pct"], p5_text=m["text"]["p_top5pct"]))
            if fname == "test":
                b = cluster_bootstrap(evals, pd.factorize(ev.bbl)[0], n_boot=200, seed=0, ref="base")
                row = b[(b.model == "text") & (b.metric == "diff_pr_auc")].iloc[0]
                boot_out[target] = dict(gain=float(row.point), lo=float(row.lo), hi=float(row.hi))
            print(f"{target} {fname}: PR-AUC {m['base']['pr_auc']:.4f} -> {m['text']['pr_auc']:.4f} ({res[-1]['gain']:+.4f}) ({time.time() - t0:.0f}s)", flush=True)
    r = pd.DataFrame(res)
    prim = r[r.target == "label_serious_any"]
    t = boot_out["label_serious_any"]
    adopt = bool(t["gain"] >= 0.005 and t["lo"] > 0 and (prim.gain > 0).sum() >= 3)
    out = dict(rows=r.to_dict("records"), test_gain_serious_any=t, test_gain_primary=boot_out.get("label_vacate_or_dobhaz_core"),
               folds_positive=int((prim.gain > 0).sum()), adoption_rule="test PR-AUC gain >= 0.005 with the paired 95% interval above 0 and a positive gain in >= 3 of 4 folds",
               adopt_text_features=adopt, features=TXT, seconds=round(time.time() - t0))
    (OUT / "text_features_eval.json").write_text(json.dumps(out, indent=2, default=float))
    r.to_csv(OUT / "text_features_eval.csv", index=False)
    print("test gain (any serious):", {k: round(v, 4) for k, v in t.items()}, "| folds positive:", out["folds_positive"], "| ADOPT:", adopt)


if __name__ == "__main__":
    main()
