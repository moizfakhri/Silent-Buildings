import pandas as pd
import pytest

from nycdistress.splits import (FOLD_ENDS, add_months, build_fold, check_purge, district_groups,
                                make_folds)

SNAPS = list(pd.date_range("2019-01-01", "2025-10-01", freq="QS"))  # the 28 real snapshots


def test_grid_is_the_real_one():
    assert len(SNAPS) == 28 and SNAPS[0] == pd.Timestamp("2019-01-01") and SNAPS[-1] == pd.Timestamp("2025-10-01")


@pytest.mark.parametrize("name", list(FOLD_ENDS))
def test_no_training_label_window_overlaps_validation(name):
    """The key leakage guarantee, checked with real date arithmetic and not with the index formula."""
    f = {x.name: x for x in make_folds(SNAPS)}[name]
    first_eval = min(f.eval)
    for t in f.train:                      # every training row: label window (t, t+12m] ended before validation
        assert add_months(t, 12) <= first_eval
    first_es = min(f.es)
    for t in f.inner_train:                # same rule between the inner training slice and the early-stopping slice
        assert add_months(t, 12) <= first_es
    assert max(f.train) < first_eval and max(f.inner_train) < first_es
    # nothing is in two slices that must be disjoint
    assert not set(f.train) & set(f.eval) and not set(f.inner_train) & set(f.es)
    assert set(f.es) <= set(f.train) and set(f.inner_train) <= set(f.train)


def test_fold_shapes_and_purge_gap():
    folds = {f.name: f for f in make_folds(SNAPS)}
    assert [f.name for f in make_folds(SNAPS)] == ["fold1", "fold2", "fold3", "test"]
    for f in folds.values():
        assert len(f.eval) == 4 and len(f.es) == 4
        gap = SNAPS.index(min(f.eval)) - SNAPS.index(max(f.train))
        assert gap == 4                      # exactly the 12 month purge: 3 snapshots dropped in between
    t = folds["test"]
    assert list(t.eval) == SNAPS[-4:]        # the final test is the last 4 usable snapshots
    assert max(t.train) == pd.Timestamp("2024-01-01") and min(t.eval) == pd.Timestamp("2025-01-01")
    # expanding window: each later fold trains on strictly more, and evaluations move forward without overlap
    ev = [set(f.eval) for f in folds.values()]
    assert all(not (a & b) for i, a in enumerate(ev) for b in ev[i + 1:])
    assert [len(f.train) for f in folds.values()] == sorted(len(f.train) for f in folds.values())


def test_validation_slices_never_precede_training():
    for f in make_folds(SNAPS):
        assert min(f.eval) > max(f.train) > max(f.inner_train)


def test_check_purge_detects_a_leaky_split():
    train = SNAPS[:9]                         # last training snapshot 2021-01-01, label window ends 2022-01-01
    check_purge(train, SNAPS[13:17])          # a quarter after the label window ended: fine
    check_purge(train, SNAPS[12:16])          # starting exactly when the last label window ends: allowed (t + 12m <= v)
    with pytest.raises(ValueError):
        check_purge(train, SNAPS[11:15])      # starts 2021-10-01, one quarter inside the last training label window
    with pytest.raises(ValueError):
        check_purge(train, SNAPS[9:13])       # no gap at all
    with pytest.raises(ValueError):
        check_purge([], SNAPS[13:17])


def test_build_fold_rejects_impossible_folds():
    with pytest.raises(ValueError):
        build_fold(SNAPS, a=22, name="too_late")     # eval would run past the last snapshot
    with pytest.raises(ValueError):
        build_fold(SNAPS, a=4, name="too_early")     # no room for an early-stopping slice after a purge


def test_district_groups_cover_everything_once_and_balance():
    d = pd.Series(["301"] * 50 + ["302"] * 30 + ["303"] * 30 + ["201"] * 20 + ["202"] * 20 + ["203"] * 10 + [None] * 5)
    g = district_groups(d, n_groups=3)
    assert set(g) == {"301", "302", "303", "201", "202", "203"}            # each district exactly once, NaN ignored
    assert set(g.values()) <= {0, 1, 2}
    loads = pd.Series(d.map(g)).value_counts()
    assert loads.max() - loads.min() <= 20                                 # roughly balanced
    assert g == district_groups(d, n_groups=3)                             # deterministic
