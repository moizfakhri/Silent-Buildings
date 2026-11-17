"""Phase 3 evaluation: reads the predictions written by train_phase3.py and writes small CSV/JSON
tables and figures to reports/phase3/, plus data/processed/scores_phase3.parquet.

    python pipelines/evaluate_phase3.py            # all of it (bootstrap on the test slice takes a few minutes)
    python pipelines/evaluate_phase3.py --boot 50  # quicker, wider CIs
"""
import argparse
import json
import time
from pathlib import Path

import pandas as pd

from nycdistress.evaluation import RankEval, brier, calibration_table, cluster_bootstrap, ece
from nycdistress.modeling import FEATURE_SETS, PROC, SLICES, TARGETS, baseline_scores, load_frame, rows
from nycdistress.splits import FOLD_ENDS, make_folds

ROOT = Path(__file__).resolve().parents[1]
REPORTS = ROOT / "reports" / "phase3"
PREDS = PROC / "phase3" / "preds"
RULES = ["rule_viol_12m", "rule_complaints_12m", "rule_last_event"]
REF = "rule_viol_12m"
PROB = ("logit", "lgb")           # models that output probabilities (calibration is meaningful)


def model_scores(ev, target, fold):
    """{(model, fset): score array} for one fold's evaluation rows."""
    out = {(r, "-"): v for r, v in baseline_scores(ev).items()}
    for fset in FEATURE_SETS:
        path = PREDS / f"{target}__{fold}__{fset}.parquet"
        if not path.exists():
            continue
        p = pd.read_parquet(path)
        assert (p.bbl.to_numpy() == ev.bbl.to_numpy()).all() and (p.snapshot_date.to_numpy() == ev.snapshot_date.to_numpy()).all()
        for m in PROB:
            out[(m, fset)] = p[m].to_numpy()
    return out


def point_metrics(ev, scores, target, fold):
    rows_ = []
    y_all = ev[target].to_numpy()
    for sname, fn in SLICES.items():
        mask = fn(ev)
        if mask.sum() < 1000 or y_all[mask].sum() < 5:
            continue
        y, snap = y_all[mask], ev.snapshot_date.to_numpy()[mask]
        for (m, fset), s in scores.items():
            sm = s[mask]
            r = RankEval(y, sm, snap).metrics()
            r.update(n_rows=int(mask.sum()), n_pos=int(y.sum()))
            if m in PROB:
                r.update(brier=brier(y, sm), ece=ece(y, sm), mean_pred=float(sm.mean()))
            rows_.append(dict(target=target, fold=fold, slice=sname, model=m, fset=fset, **r))
    return rows_


def main(args):
    REPORTS.mkdir(parents=True, exist_ok=True)
    (REPORTS / "figures").mkdir(exist_ok=True)
    t0 = time.time()
    df = load_frame()
    snaps = sorted(df.snapshot_date.unique())
    folds = {f.name: f for f in make_folds(snaps)}

    # ---------------------------------------------------------------- point metrics, every fold
    allm, cache = [], {}
    for fname, f in folds.items():
        ev = df[rows(df, f.eval)].reset_index(drop=True)
        for target in TARGETS:
            sc = model_scores(ev, target, fname)
            if len(sc) <= 3:
                continue
            cache[(fname, target)] = (ev, sc)
            allm += point_metrics(ev, sc, target, fname)
    metrics = pd.DataFrame(allm)
    metrics.to_csv(REPORTS / "metrics_by_fold.csv", index=False)
    print(f"point metrics: {len(metrics):,} rows ({time.time() - t0:.0f}s)", flush=True)

    # ---------------------------------------------------------------- test slice: cluster bootstrap by building
    boot = []
    for target in TARGETS:
        if ("test", target) not in cache:
            continue
        ev, sc = cache[("test", target)]
        y_all = ev[target].to_numpy()
        for sname, fn in SLICES.items():
            mask = fn(ev)
            if mask.sum() < 1000 or y_all[mask].sum() < 20:
                continue
            codes = pd.factorize(ev.bbl[mask])[0]
            evals = {f"{m}|{fset}": RankEval(y_all[mask], s[mask], ev.snapshot_date.to_numpy()[mask]) for (m, fset), s in sc.items()}
            out = cluster_bootstrap(evals, codes, n_boot=args.boot, seed=0, ref=f"{REF}|-")
            out.insert(0, "slice", sname)
            out.insert(0, "target", target)
            boot.append(out)
            print(f"bootstrap {target} / {sname}: {mask.sum():,} rows, {len(evals)} models ({time.time() - t0:.0f}s)", flush=True)
    if boot:
        b = pd.concat(boot)
        b[["model", "fset"]] = b.model.str.split("|", expand=True)
        b.to_csv(REPORTS / "metrics_test_ci.csv", index=False)

    # ---------------------------------------------------------------- is LightGBM better than the logistic regression? (paired)
    if ("test", TARGETS[0]) in cache:
        ev, sc = cache[("test", TARGETS[0])]
        codes = pd.factorize(ev.bbl)[0]
        pair = {}
        for fset in FEATURE_SETS:
            for m in PROB:
                pair[f"{m}|{fset}"] = RankEval(ev[TARGETS[0]].to_numpy(), sc[(m, fset)], ev.snapshot_date.to_numpy())
        out = cluster_bootstrap({k: v for k, v in pair.items() if k.endswith("|all")}, codes, n_boot=args.boot, seed=1, ref="logit|all")
        out.to_csv(REPORTS / "lgb_vs_logit_test.csv", index=False)

    # ---------------------------------------------------------------- per snapshot (primary target, key models)
    ps = []
    key = [("rule_viol_12m", "-"), ("logit", "all"), ("lgb", "all"), ("lgb", "no_viol"), ("lgb", "no_loud"), ("lgb", "static_prior")]
    for fname in folds:
        if (fname, TARGETS[0]) not in cache:
            continue
        ev, sc = cache[(fname, TARGETS[0])]
        for snap in sorted(ev.snapshot_date.unique()):
            m = (ev.snapshot_date == snap).to_numpy()
            for k in key:
                if k in sc:
                    r = RankEval(ev[TARGETS[0]].to_numpy()[m], sc[k][m], ev.snapshot_date.to_numpy()[m]).metrics()
                    ps.append(dict(fold=fname, snapshot_date=snap, model=k[0], fset=k[1], **{x: r[x] for x in ("roc_auc", "pr_auc", "p_top1pct", "p_top5pct", "base_rate")}))
    pd.DataFrame(ps).to_csv(REPORTS / "per_snapshot.csv", index=False)

    # ---------------------------------------------------------------- calibration, test slice
    cal = []
    for target in TARGETS:
        if ("test", target) not in cache:
            continue
        ev, sc = cache[("test", target)]
        for (m, fset), s in sc.items():
            if m in PROB:
                t = calibration_table(ev[target], s, 10)
                t.insert(0, "fset", fset)
                t.insert(0, "model", m)
                t.insert(0, "target", target)
                cal.append(t)
    if cal:
        pd.concat(cal).to_csv(REPORTS / "calibration_test.csv", index=False)

    # ---------------------------------------------------------------- vacate / AEP: descriptive, using the serious_any scores
    if ("test", TARGETS[0]) in cache:
        ev, sc = cache[("test", TARGETS[0])]
        desc = []
        for lab in ("label_vacate", "label_aep", "label_vacate_or_aep", "label_omo", "label_litigation"):
            y = ev[lab].to_numpy()
            for k in (("rule_viol_12m", "-"), ("lgb", "all"), ("lgb", "no_loud"), ("lgb", "static_prior")):
                if k in sc:
                    r = RankEval(y, sc[k], ev.snapshot_date.to_numpy())
                    top = r.top_stats()
                    desc.append(dict(label=lab, events=int(y.sum()), model=k[0], fset=k[1], roc_auc=r.roc_auc(), pr_auc=r.pr_auc(),
                                     recall_top1pct=top["r_top1pct"], recall_top5pct=top["r_top5pct"], lift_top5pct=top["lift_top5pct"]))
        pd.DataFrame(desc).to_csv(REPORTS / "pooled_labels_from_serious_any.csv", index=False)

    # ---------------------------------------------------------------- spatial block check
    sp = PREDS / f"spatial__{TARGETS[0]}__fold3__all.parquet"
    if sp.exists() and ("fold3", TARGETS[0]) in cache:
        ev, sc = cache[("fold3", TARGETS[0])]
        s = pd.read_parquet(sp)
        m = ev.merge(s, on=["bbl", "snapshot_date"], how="inner")
        base = ev.merge(pd.DataFrame({"bbl": ev.bbl, "snapshot_date": ev.snapshot_date, "lgb_time_only": sc[("lgb", "all")]}), on=["bbl", "snapshot_date"])
        m = m.merge(base[["bbl", "snapshot_date", "lgb_time_only"]], on=["bbl", "snapshot_date"])
        y = m[TARGETS[0]].to_numpy()
        res = []
        for name, col in (("time_only (all districts seen in training)", "lgb_time_only"), ("time + place held out (district groups)", "lgb_spatial")):
            r = RankEval(y, m[col].to_numpy(), m.snapshot_date.to_numpy()).metrics()
            res.append(dict(setup=name, n_rows=len(m), **{k: r[k] for k in ("roc_auc", "pr_auc", "p_top1pct", "p_top5pct", "lift_top5pct", "base_rate")}))
        pd.DataFrame(res).to_csv(REPORTS / "spatial_check.csv", index=False)

    # ---------------------------------------------------------------- scores for the later 3D map (out-of-fold)
    parts = []
    for fname in folds:
        pieces = {}
        for fset, col in (("all", "score"), ("no_loud", "score_no_loud"), ("no_viol", "score_no_viol"), ("static_prior", "score_static_prior")):
            p = PREDS / f"{TARGETS[0]}__{fname}__{fset}.parquet"
            if p.exists():
                pieces[col] = pd.read_parquet(p).set_index(["bbl", "snapshot_date"])["lgb"]
        if pieces:
            d = pd.DataFrame(pieces).reset_index()
            d.insert(2, "fold", fname)
            parts.append(d)
    if parts:
        sc_all = pd.concat(parts)
        sc_all["snapshot_date"] = pd.to_datetime(sc_all.snapshot_date).dt.date
        sc_all.to_parquet(PROC / "scores_phase3.parquet", index=False)
        print(f"scores_phase3.parquet: {len(sc_all):,} rows, folds {sorted(sc_all.fold.unique())}", flush=True)

    (REPORTS / "run_info.json").write_text(json.dumps(dict(
        boot=args.boot, fold_ends=FOLD_ENDS, eval_snapshots={k: [str(d.date()) for d in f.eval] for k, f in folds.items()},
        train_end={k: str(f.train[-1].date()) for k, f in folds.items()}, built=time.strftime("%Y-%m-%dT%H:%M:%S")), indent=2))
    print(f"evaluation done in {(time.time() - t0) / 60:.1f} min", flush=True)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--boot", type=int, default=200)
    main(ap.parse_args())
