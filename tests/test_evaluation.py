import math

import numpy as np
import pandas as pd
import pytest

from nycdistress.evaluation import RankEval, brier, calibration_table, cluster_bootstrap, ece
from nycdistress.metrics import average_precision, roc_auc

rng = np.random.default_rng(3)


def sample(n=3000, ties=True):
    y = (rng.random(n) < 0.15).astype(int)
    score = np.round(rng.normal(size=n) + 1.2 * y, 1 if ties else 8)
    snap = rng.integers(0, 4, n)
    return y, score, snap


def test_matches_unweighted_reference_functions():
    y, s, snap = sample()
    ev = RankEval(y, s, snap)
    assert math.isclose(ev.roc_auc(), roc_auc(y, s), rel_tol=1e-12)
    assert math.isclose(ev.pr_auc(), average_precision(y, s), rel_tol=1e-12)


@pytest.mark.parametrize("seed", range(60))
def test_weights_equal_repeating_rows(seed):
    """Includes weight vectors with zeros: a zero-weight top tie group once made PR-AUC NaN (bootstrap draws)."""
    r = np.random.default_rng(seed)
    n = 500
    y = (r.random(n) < 0.15).astype(int)
    s = np.round(r.normal(size=n) + 1.2 * y, 1)
    snap = r.integers(0, 4, n)
    w = r.integers(0, 4, n)
    rep = np.repeat(np.arange(n), w)
    a = RankEval(y, s, snap).metrics(w)
    b = RankEval(y[rep], s[rep], snap[rep]).metrics()
    for k in ("roc_auc", "pr_auc", "base_rate"):
        assert math.isclose(a[k], b[k], rel_tol=1e-9), k


def test_against_scikit_learn():
    sk = pytest.importorskip("sklearn.metrics")
    y, s, snap = sample(4000)
    w = rng.random(len(y)) + 0.1
    ev = RankEval(y, s, snap)
    assert math.isclose(ev.roc_auc(w), sk.roc_auc_score(y, s, sample_weight=w), rel_tol=1e-9)
    assert math.isclose(ev.pr_auc(w), sk.average_precision_score(y, s, sample_weight=w), rel_tol=1e-9)


def test_top_stats_per_snapshot_hand_example():
    # two snapshots of 10 rows; top 10% = 1 row each; top 20% = 2 rows each
    y = np.array([1, 0, 0, 0, 0, 0, 0, 0, 0, 0] + [0, 0, 0, 0, 0, 0, 0, 0, 0, 1])
    s = np.array([9, 8, 7, 6, 5, 4, 3, 2, 1, 0] + [0, 1, 2, 3, 4, 5, 6, 7, 8, 9])
    snap = np.array([0] * 10 + [1] * 10)
    ev = RankEval(y, s, snap, fracs=(0.1, 0.2), ks=(1, 2))
    m = ev.top_stats()
    assert m["p_top10pct"] == 1.0 and m["r_top10pct"] == 1.0                 # the single positive in each snapshot is its top row
    assert m["p_top20pct"] == 0.5 and m["lift_top20pct"] == pytest.approx(0.5 / 0.1)
    assert m["p_top1"] == 1.0 and m["p_top2"] == 0.5


def test_top_selection_is_per_snapshot_not_pooled():
    # snapshot 1 has all the high scores; pooled top-1 would take only snapshot 1 rows
    y = np.array([0, 0, 0, 1, 1, 0, 0, 0])
    s = np.array([1, 2, 3, 4, 100, 200, 300, 400.0])
    snap = np.array([0, 0, 0, 0, 1, 1, 1, 1])
    ev = RankEval(y, s, snap, fracs=(0.25,), ks=())
    assert sorted(ev.sel["top25pct"].tolist()) == [3, 7]                      # best row of each snapshot


def test_calibration_measures():
    n = 200_000
    p = rng.random(n) * 0.3
    y = (rng.random(n) < p).astype(int)
    assert ece(y, p) < 0.005                                                  # calibrated by construction
    assert ece(y, np.minimum(p * 2, 1)) > 0.05                                # over-confident
    assert math.isclose(brier([1, 0], [1.0, 0.0]), 0.0) and math.isclose(brier([1, 0], [0.5, 0.5]), 0.25)
    t = calibration_table(y, p, 10)
    assert t.n.sum() == n and len(t) == 10 and t.mean_pred.is_monotonic_increasing


def test_cluster_bootstrap_by_building_is_wider_than_row_bootstrap_and_paired():
    # 400 buildings x 5 snapshots with a building effect: rows within a building are strongly correlated
    nb, ns = 400, 5
    eff = rng.normal(size=nb)
    bbl = np.repeat(np.arange(nb), ns)
    y_b = (rng.random(nb) < 1 / (1 + np.exp(-(eff - 0.5)))).astype(int)   # a building's outcome persists across its snapshots
    y = y_b[bbl]
    s1 = eff[bbl] + rng.normal(scale=0.3, size=nb * ns)
    s2 = rng.normal(size=nb * ns)                                            # noise model
    snap = np.tile(np.arange(ns), nb)
    evals = {"good": RankEval(y, s1, snap), "noise": RankEval(y, s2, snap)}
    out = cluster_bootstrap(evals, bbl, n_boot=150, seed=1, ref="noise")
    auc = out[(out.model == "good") & (out.metric == "roc_auc")].iloc[0]
    assert auc.lo < auc.point < auc.hi
    diff = out[(out.model == "good") & (out.metric == "diff_roc_auc")].iloc[0]
    assert diff.lo > 0                                                       # paired difference excludes 0
    # a row-level bootstrap would pretend there are 5x more independent observations
    row_w = [RankEval(y, s1, snap).roc_auc(np.bincount(rng.integers(0, len(y), len(y)), minlength=len(y))) for _ in range(150)]
    assert (auc.hi - auc.lo) > 1.5 * (np.percentile(row_w, 97.5) - np.percentile(row_w, 2.5))


def test_dataframe_inputs_do_not_break():
    y, s, snap = sample(200)
    ev = RankEval(pd.Series(y), pd.Series(s), pd.Series(snap))
    assert 0 <= ev.roc_auc() <= 1
