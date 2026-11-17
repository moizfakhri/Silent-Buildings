"""Strictly temporal walk-forward folds with a purge gap, plus a spatial (community district) grouping.

A row at snapshot t has a label over (t, t + 12 months]. A training row is only usable for a
validation snapshot v if its label window has ended by v:  t + 12 months <= v.  So between the last
training snapshot and the first validation snapshot there is a 12 month (4 quarter) gap, and the
snapshots in between are dropped ("purged"). The same rule separates the inner training slice from
the early-stopping slice used inside each fold.

Fold layout (indices into the sorted list of quarterly snapshots, `a` = last training snapshot):

    inner_train   <= a - 7     fits trees while early stopping watches `es`
    (purged)      a-6 .. a-4
    es            a-3 .. a     early-stopping slice, the 4 most recent training quarters
    train         <= a         refit with the iteration count found on `es`
    (purged)      a+1 .. a+3
    eval          a+4 .. a+7   the 4 quarters the fold is scored on
"""
from dataclasses import dataclass

import pandas as pd

HORIZON_MONTHS = 12
HORIZON_Q = 4
# last training snapshot index per fold. "test" is the last 4 usable snapshots and is touched once.
FOLD_ENDS = {"fold1": 8, "fold2": 12, "fold3": 16, "test": 20}


def add_months(ts, months):
    return pd.Timestamp(ts) + pd.DateOffset(months=months)


@dataclass(frozen=True)
class Fold:
    name: str
    inner_train: tuple
    es: tuple
    train: tuple
    eval: tuple


def check_purge(earlier, later, months=HORIZON_MONTHS):
    """Raise if any `earlier` row's label window (t, t + months] reaches into `later` snapshots."""
    if not len(earlier) or not len(later):
        raise ValueError("empty snapshot list")
    first_later = min(pd.Timestamp(d) for d in later)
    for t in earlier:
        if add_months(t, months) > first_later:
            raise ValueError(f"label window of snapshot {pd.Timestamp(t).date()} ends "
                             f"{add_months(t, months).date()}, after validation starts {first_later.date()}")


def build_fold(snapshots, a, name, eval_q=4, es_q=4, horizon_q=HORIZON_Q):
    snaps = sorted(pd.Timestamp(s) for s in snapshots)
    if a + horizon_q + eval_q > len(snaps):
        raise ValueError(f"fold {name}: needs snapshots up to index {a + horizon_q + eval_q - 1}, have {len(snaps) - 1}")
    first_es = a - es_q + 1
    if first_es - horizon_q + 1 < 1:
        raise ValueError(f"fold {name}: not enough history before index {a} for an early-stopping slice")
    fold = Fold(name=name,
                inner_train=tuple(snaps[: first_es - horizon_q + 1]),
                es=tuple(snaps[first_es: a + 1]),
                train=tuple(snaps[: a + 1]),
                eval=tuple(snaps[a + horizon_q: a + horizon_q + eval_q]))
    check_purge(fold.train, fold.eval)
    check_purge(fold.inner_train, fold.es)
    return fold


def make_folds(snapshots, fold_ends=None):
    fold_ends = fold_ends or FOLD_ENDS
    return [build_fold(snapshots, a, name) for name, a in fold_ends.items()]


def district_groups(districts, n_groups=5, seed=0):
    """Assign each community district to one of n_groups, balancing the number of rows per group.

    `districts` is a Series of district codes (one entry per row). Returns {district: group}.
    Greedy largest-first assignment, deterministic for a given seed (only used to break ties).
    """
    counts = districts.dropna().value_counts()
    order = sorted(counts.index, key=lambda d: (-counts[d], str(d)))
    loads = [0] * n_groups
    out = {}
    for d in order:
        g = min(range(n_groups), key=lambda i: (loads[i], (i + seed) % n_groups))
        out[d] = g
        loads[g] += int(counts[d])
    return out
