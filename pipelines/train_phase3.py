"""Phase 3 training: logistic regression and LightGBM, walk-forward with a 12 month purge gap.

    python pipelines/train_phase3.py                      # all folds x targets x feature sets (resumable)
    python pipelines/train_phase3.py --targets label_serious_any --folds test
    python pipelines/train_phase3.py --spatial            # community-district hold-out check on fold3

For each (fold, target, feature set) it early-stops LightGBM on a later, purged time slice, refits on
the whole training window, and writes predictions for the fold's 4 evaluation snapshots to
data/processed/phase3/preds/. Existing prediction files are skipped, so an interrupted run resumes.
The test fold is trained on snapshots <= 2024-01-01 and scored on the last four snapshots once.
Models, predictions and logs are gitignored.
"""
import argparse
import json
import time

import numpy as np
import pandas as pd

from nycdistress.modeling import (FEATURE_SETS, PROC, TARGETS, feature_columns, fit_lgb, fit_logit, load_frame,
                                  predict_lgb, predict_logit, rows)
from nycdistress.splits import FOLD_ENDS, build_fold, district_groups, make_folds

OUT = PROC / "phase3"


def save_preds(path, ev, **scores):
    out = ev[["bbl", "snapshot_date"]].copy()
    for k, v in scores.items():
        out[k] = np.asarray(v, dtype=np.float32)
    out.to_parquet(path, index=False)


def run(args):
    (OUT / "preds").mkdir(parents=True, exist_ok=True)
    (OUT / "models").mkdir(parents=True, exist_ok=True)
    df = load_frame()
    snaps = sorted(df.snapshot_date.unique())
    folds = {f.name: f for f in make_folds(snaps)}
    t_all = time.time()
    for fname in args.folds:
        f = folds[fname]
        itr, es, tr, ev = (df[rows(df, d)] for d in (f.inner_train, f.es, f.train, f.eval))
        print(f"== {fname}: train {len(tr):,} rows ({tr.snapshot_date.min().date()}..{tr.snapshot_date.max().date()}), "
              f"eval {len(ev):,} rows ({ev.snapshot_date.min().date()}..{ev.snapshot_date.max().date()})", flush=True)
        for target in args.targets:
            for fset in args.sets:
                path = OUT / "preds" / f"{target}__{fname}__{fset}.parquet"
                if path.exists() and not args.force:
                    continue
                cols = feature_columns(df, fset)
                t0 = time.time()
                booster, best, n_fit = fit_lgb(itr, es, cols, target, final_train=tr)
                p_lgb = predict_lgb(booster, ev, cols)
                t_lgb = time.time() - t0
                t0 = time.time()
                p_logit = predict_logit(fit_logit(tr, cols, target), ev)
                t_logit = time.time() - t0
                save_preds(path, ev, lgb=p_lgb, logit=p_logit)
                path.with_suffix(".json").write_text(json.dumps(dict(
                    target=target, fold=fname, feature_set=fset, n_features=len(cols), best_iteration=best,
                    n_train_rows=len(tr), n_fit_rows=n_fit, seconds_lgb=round(t_lgb, 1), seconds_logit=round(t_logit, 1))))
                if fname == "test":
                    booster.save_model(str(OUT / "models" / f"{target}__{fset}.txt"))
                print(f"{fname} {target:<22} {fset:<13} best_iter {best:>4}  lgb {t_lgb:5.0f}s  logit {t_logit:4.0f}s", flush=True)
    print(f"done in {(time.time() - t_all) / 60:.1f} min", flush=True)


def run_spatial(args):
    """Hold out whole community districts: train and early-stop without any row from the held-out
    districts, score only the held-out districts' rows in the evaluation slice. Both time AND place
    are unseen. Five district groups, one fold, the primary target, all features."""
    (OUT / "preds").mkdir(parents=True, exist_ok=True)
    df = load_frame()
    snaps = sorted(df.snapshot_date.unique())
    f = build_fold(snaps, FOLD_ENDS["fold3"], "fold3")
    df = df[df.community_district.notna()]
    groups = district_groups(df.drop_duplicates("bbl").community_district, n_groups=5)
    df = df.assign(_g=df.community_district.map(groups))
    cols = feature_columns(df, "all")
    target = "label_serious_any"
    parts = []
    for g in range(5):
        itr, es, tr = (df[rows(df, d) & (df._g != g).to_numpy()] for d in (f.inner_train, f.es, f.train))
        ev = df[rows(df, f.eval) & (df._g == g).to_numpy()]
        booster, best, _ = fit_lgb(itr, es, cols, target, final_train=tr)
        out = ev[["bbl", "snapshot_date"]].copy()
        out["lgb_spatial"] = predict_lgb(booster, ev, cols)
        out["group"] = g
        parts.append(out)
        print(f"spatial group {g}: held-out districts {sorted(d for d, k in groups.items() if k == g)}, best_iter {best}, "
              f"eval rows {len(ev):,}", flush=True)
    pd.concat(parts).to_parquet(OUT / "preds" / f"spatial__{target}__fold3__all.parquet", index=False)
    (OUT / "preds" / "spatial_groups.json").write_text(json.dumps({str(k): v for k, v in groups.items()}))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--targets", nargs="*", default=TARGETS)
    ap.add_argument("--folds", nargs="*", default=list(FOLD_ENDS))
    ap.add_argument("--sets", nargs="*", default=list(FEATURE_SETS))
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--spatial", action="store_true")
    a = ap.parse_args()
    run_spatial(a) if a.spatial else run(a)
