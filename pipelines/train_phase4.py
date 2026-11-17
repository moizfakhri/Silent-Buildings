"""Phase 4, step 1: the CONDITION model p_hat, out of time, from features with no complaint provenance.

    python pipelines/train_phase4.py                       # every fold x outcome x feature set (resumable)
    python pipelines/train_phase4.py --targets label_vacate_or_dobhaz --folds test

Features: `cond_core` = static_* + prior_* (earlier OMO, litigation, vacate, AEP events), and `cond_plus` = core plus
dob_* and evict_*. Never viol_* or loud_*. Same walk-forward folds and 12 month purge gap as Phase 3, so the
score of every evaluation snapshot comes from a model trained only on snapshots whose label windows had ended.

Calibration is cross-fitted so no calibrator ever sees data its model trained on: an inner model (trained up to a-7)
scores the early-stopping slice (a-3..a); isotonic regression fitted on those scores maps the refit model's raw
probabilities. Both p_raw and p_cal are saved.
"""
import argparse
import json
import time

import numpy as np
from sklearn.isotonic import IsotonicRegression

from nycdistress.modeling import (CONDITION_SETS, P4_PRIMARY, P4_TARGETS, PROC, feature_columns, fit_lgb, load_frame,
                                  predict_lgb, rows)
from nycdistress.splits import FOLD_ENDS, make_folds

OUT = PROC / "phase4" / "cond"


def main(args):
    OUT.mkdir(parents=True, exist_ok=True)
    df = load_frame()
    folds = {f.name: f for f in make_folds(sorted(df.snapshot_date.unique()))}
    t_all = time.time()
    for fname in args.folds:
        f = folds[fname]
        itr, es, tr, ev = (df[rows(df, d)] for d in (f.inner_train, f.es, f.train, f.eval))
        print(f"== {fname}: train {len(tr):,} rows to {tr.snapshot_date.max().date()}, eval {len(ev):,} rows "
              f"{ev.snapshot_date.min().date()}..{ev.snapshot_date.max().date()}", flush=True)
        for target in args.targets:
            for fset in args.sets:
                path = OUT / f"{target}__{fname}__{fset}.parquet"
                if path.exists() and not args.force:
                    continue
                cols = feature_columns(df, fset)
                assert not any(c.startswith(("viol_", "loud_", "meta_", "label_")) for c in cols), "complaint-provenance feature in the condition model"
                t0 = time.time()
                final, best, n_fit, inner = fit_lgb(itr, es, cols, target, final_train=tr, return_inner=True)
                iso = IsotonicRegression(y_min=0.0, y_max=1.0, out_of_bounds="clip").fit(predict_lgb(inner, es, cols), es[target].to_numpy())
                p_raw = predict_lgb(final, ev, cols)
                out = ev[["bbl", "snapshot_date"]].copy()
                out["p_raw"] = p_raw
                out["p_cal"] = iso.predict(p_raw).astype(np.float32)
                out.to_parquet(path, index=False)
                path.with_suffix(".json").write_text(json.dumps(dict(
                    target=target, fold=fname, feature_set=fset, n_features=len(cols), best_iteration=best,
                    n_train_rows=len(tr), seconds=round(time.time() - t0, 1), train_end=str(tr.snapshot_date.max().date()))))
                print(f"{fname} {target:<28} {fset:<10} best_iter {best:>4}  {time.time() - t0:4.0f}s", flush=True)
    print(f"done in {(time.time() - t_all) / 60:.1f} min", flush=True)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--targets", nargs="*", default=P4_TARGETS)
    ap.add_argument("--folds", nargs="*", default=list(FOLD_ENDS))
    ap.add_argument("--sets", nargs="*", default=list(CONDITION_SETS))
    ap.add_argument("--force", action="store_true")
    assert P4_PRIMARY in P4_TARGETS
    main(ap.parse_args())
