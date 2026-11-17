import numpy as np

from nycdistress.did import event_study, stratum_weights, trend_adjusted


def simulate(n_treat=1500, n_ctrl=3000, T=30, effect=0.0, pre_slope=0.0, het=False, seed=0):
    """Panel with unit effects, a common time trend, staggered cohorts at quarters 10..18, and an optional true effect."""
    rng = np.random.default_rng(seed)
    n = n_treat + n_ctrl
    g = np.full(n, -1)
    g[:n_treat] = rng.integers(10, 19, n_treat)
    unit = rng.normal(0, 1, n)[:, None]
    time = (0.05 * np.arange(T))[None, :] + 0.3 * np.sin(np.arange(T) / 3.0)[None, :]
    Y = unit + time + rng.normal(0, 1, (n, T))
    for i in range(n_treat):
        t = np.arange(T) - g[i]
        Y[i] += pre_slope * t                          # a differential linear trend that continues after treatment (violates parallel trends)
        eff = effect * (1 + (g[i] - 14) / 4.0) if het else effect  # effect differs by cohort
        Y[i, t >= 0] += eff
    return Y, g


def test_recovers_effect_with_heterogeneous_cohorts():
    Y, g = simulate(effect=0.5, het=True)
    r = event_study(Y, g, n_boot=100)
    # cohort-size-weighted average of the heterogeneous effect: here about 0.5 (cohorts are symmetric around 14)
    assert abs(r["avg_post"] - 0.5) < 0.12
    assert r["avg_post_lo"] < 0.5 < r["avg_post_hi"] + 0.15
    assert r["pre_trend_p"] > 0.01


def test_null_effect_and_clean_pretrends():
    Y, g = simulate(effect=0.0, seed=3)
    r = event_study(Y, g, n_boot=100)
    assert r["avg_post_lo"] <= 0 <= r["avg_post_hi"]
    assert r["pre_trend_p"] > 0.01
    assert np.all(np.abs(r["theta"][r["events"] <= -2]) < 0.2)


def test_detects_pre_trend_violation_and_adjusts():
    Y, g = simulate(effect=0.0, pre_slope=0.08, seed=5)
    r = event_study(Y, g, n_boot=100)
    assert r["pre_trend_p"] < 0.01            # the pre-trend test fires
    # the naive post effect is biased by the diverging trend; the extrapolation adjustment pulls it back toward the truth (0)
    assert abs(r["adj_post"]) < abs(r["avg_post"])


def test_event_minus_one_is_excluded_and_events_cover_window():
    Y, g = simulate(seed=2)
    r = event_study(Y, g, pre=6, post=5, n_boot=20)
    assert list(r["events"]) == [-6, -5, -4, -3, -2, 0, 1, 2, 3, 4, 5]


def test_not_yet_treated_controls_recover_effect():
    Y, g = simulate(n_ctrl=300, effect=0.5, seed=7)
    r = event_study(Y, g, control="notyet", n_boot=60)
    assert abs(r["avg_post"] - 0.5) < 0.2


def test_stratified_weights_remove_composition_bias():
    # two strata; controls over-represent stratum 1 and stratum 1 has a steeper trend: unweighted DiD is biased, reweighted is not
    rng = np.random.default_rng(1)
    T = 24
    nt, nc = 2000, 4000
    strata = np.concatenate([rng.integers(0, 2, nt) * 0, np.where(rng.random(nc) < 0.8, 1, 0)])  # treated all stratum 0
    g = np.concatenate([rng.integers(8, 14, nt), -np.ones(nc, int)])
    slope = np.where(strata == 1, 0.15, 0.0)[:, None]
    Y = slope * np.arange(T)[None, :] + rng.normal(0, 1, (nt + nc, T))
    plain = event_study(Y, g, n_boot=40)["avg_post"]
    strat = event_study(Y, g, n_boot=40, strata=strata)["avg_post"]
    assert abs(plain) > 0.3 and abs(strat) < 0.15


def test_stratum_weights_drop_treated_without_controls():
    g = np.array([5, 5, -1, -1])
    strata = np.array([0, 1, 0, 0])
    w = stratum_weights(np.ones(4), g, strata)
    assert list(w) == [1.0, 0.0, 0.5, 0.5]


def test_trend_adjusted_removes_linear_trend():
    events = np.array([-4, -3, -2, 0, 1, 2])
    theta = 0.1 * (events + 1.0)       # a pure line through (-1, 0): the pre-trend extrapolation explains everything
    assert abs(trend_adjusted(events, theta)) < 1e-9
