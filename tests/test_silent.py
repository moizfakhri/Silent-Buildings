import numpy as np
import pandas as pd
import pytest

from nycdistress.silent import (access_blocked, boot_weights, cluster_codes, eb_rate, fit_expected_complaints,
                                fit_gamma_prior, matched_att, pct_within, rank_gap, resid_gap, shuffle_within,
                                size_bucket, top_decile)


def sim_counts(n=20000, a=3.0, mean_rate=0.12, seed=0):
    r = np.random.default_rng(seed)
    units = r.integers(3, 120, n).astype(float)
    b = a / mean_rate
    lam = r.gamma(a, 1 / b, n)
    return r.poisson(units * lam), units, lam, (a, b)


# ---------------------------------------------------------------------------------- shrinkage
def test_gamma_prior_is_recovered():
    y, u, _, (a, b) = sim_counts()
    a_hat, b_hat = fit_gamma_prior(y, u)
    assert abs(a_hat - a) / a < 0.15 and abs(a_hat / b_hat - a / b) / (a / b) < 0.05


def test_shrinkage_beats_raw_rates_and_lies_between_raw_and_prior():
    y, u, lam, _ = sim_counts()
    post, raw, prior = eb_rate(y, u, np.zeros(len(y)))
    assert np.mean((post - lam) ** 2) < np.mean((raw - lam) ** 2)            # closer to the truth than raw rates
    lo, hi = np.minimum(raw, prior), np.maximum(raw, prior)
    assert ((post >= lo - 1e-12) & (post <= hi + 1e-12)).all()               # a compromise between data and prior
    assert (post > 0).all()                                                  # a zero count still gets a positive rate
    small, large = u < 6, u > 80                                             # small buildings are pulled harder to the prior
    pull = np.abs(post - prior) / np.maximum(np.abs(raw - prior), 1e-9)
    assert np.median(pull[small]) < np.median(pull[large])


def test_eb_rate_is_fitted_per_group():
    y1, u1, _, _ = sim_counts(5000, mean_rate=0.05, seed=1)
    y2, u2, _, _ = sim_counts(5000, mean_rate=0.40, seed=2)
    post, _, prior = eb_rate(np.r_[y1, y2], np.r_[u1, u2], np.r_[np.zeros(5000), np.ones(5000)])
    assert prior[:5000].mean() < 0.08 and prior[5000:].mean() > 0.3


def test_size_bucket_edges():
    b = size_bucket([3, 5, 6, 11, 12, 24, 25, 49, 50, 900])
    assert list(b) == ["3-5", "3-5", "6-11", "6-11", "12-24", "12-24", "25-49", "25-49", "50+", "50+"]


# ---------------------------------------------------------------------------------- percentiles and gaps
def test_pct_within_midranks_ties_and_groups():
    assert np.allclose(pct_within([1, 2, 3, 4], ["a"] * 4), [0.125, 0.375, 0.625, 0.875])
    assert np.allclose(pct_within([5, 5, 5, 5], ["a"] * 4), [0.5] * 4)                         # all tied: all in the middle
    p = pct_within([1, 2, 10, 20, 30], ["a", "a", "b", "b", "b"])
    assert np.allclose(p, [0.25, 0.75, 1 / 6, 0.5, 5 / 6])                                     # groups ranked independently


def test_rank_gap_zero_when_aligned_and_silent_share_is_a_decile_within_each_group():
    r = np.random.default_rng(0)
    n = 6000
    g = np.repeat(["a", "b", "c"], n // 3)
    p = r.random(n)
    assert np.allclose(rank_gap(p, p * 2 + 1, g), 0)                                           # same ordering: no gap
    loud = np.clip(p + r.normal(scale=0.3, size=n), 0, None)
    gap = rank_gap(p, loud, g)
    flag = top_decile(gap, g)
    for grp in "abc":
        assert abs(flag[g == grp].mean() - 0.10) < 0.01
    assert gap.min() >= -1 and gap.max() <= 1
    # the flagged rows are the ones with a high condition score and a low complaint score
    assert p[flag].mean() > p.mean() and loud[flag].mean() < loud.mean() + 0.2


def test_access_blocked_needs_enough_closed_problems_and_a_high_share():
    closed = [10, 3, 2, 10, 0, 5]
    share = [0.9, 0.5, 1.0, 0.4, np.nan, np.nan]
    assert list(access_blocked(closed, share)) == [True, True, False, False, False, False]


# ---------------------------------------------------------------------------------- expected complaints (negative binomial)
def sim_nb(n=15000, alpha=0.6, suppress=0.0, seed=3):
    r = np.random.default_rng(seed)
    p = np.clip(r.beta(2.0, 10, n), 1e-3, 0.9)
    units = r.integers(3, 80, n).astype(float)
    district = r.choice(["301", "302", "303", "201", "202"], n)
    cd_eff = {"301": 0.0, "302": 0.4, "303": -0.3, "201": 0.6, "202": 0.2}
    logmu = np.log(units) + -0.8 + 0.9 * np.log(p / (1 - p)) + np.array([cd_eff[d] for d in district])   # mean about 4 problems a year, like the real data
    mu = np.exp(logmu)
    y = r.negative_binomial(1 / alpha, 1 / (1 + alpha * mu))
    hidden = r.random(n) < suppress
    y = np.where(hidden, r.binomial(y, 0.1), y)
    return y, p, units, district, hidden, mu


def test_nb_model_recovers_dispersion_and_slope_and_flags_suppressed_buildings():
    y, p, u, d, hidden, mu_true = sim_nb(suppress=0.08)
    res = fit_expected_complaints(y, p, u, d)
    assert 0.35 < res["alpha"] < 1.2                                      # suppression inflates dispersion a little
    assert abs(res["coef"]["logit_p"] - 0.9) < 0.15
    assert (res["mu_lo"] <= res["mu"] + 1e-9).all() and (res["mu"] <= res["mu_hi"] + 1e-9).all()
    silent = res["p_low"] < 0.05
    assert silent[hidden].mean() > 3 * silent[~hidden].mean()             # the hidden buildings are the ones flagged
    assert silent[~hidden].mean() < 0.08                                  # and the false-flag rate is near the nominal 5%
    gap, lo, hi = resid_gap(y, res["mu"], res["mu_lo"], res["mu_hi"])
    assert gap[hidden].mean() > gap[~hidden].mean() + 0.3 and (lo <= gap + 1e-9).all() and (gap <= hi + 1e-9).all()


# ---------------------------------------------------------------------------------- matching, bootstrap, placebo
def sim_matched(n=60000, true_rr=2.0, seed=4):
    r = np.random.default_rng(seed)
    strata = r.integers(0, 40, n)
    base = 0.01 + 0.004 * strata                                          # the outcome rate rises with the stratum
    treated = r.random(n) < (0.02 + 0.02 * (strata / 40))                 # and so does the chance of being treated: confounding
    y = (r.random(n) < base * np.where(treated, true_rr, 1.0)).astype(float)
    return y, treated, strata


def test_matched_comparison_removes_confounding_that_a_naive_one_does_not():
    y, t, s = sim_matched()
    naive = y[t].mean() / y[~t].mean()
    m = matched_att(y, t, s)
    assert naive > 2.3                                                    # confounded upwards
    assert abs(m["rr"] - 2.0) < 0.25 and m["n_strata"] == 40


def test_matched_att_drops_strata_without_controls_and_weights_equal_repeated_rows():
    y = np.array([1, 0, 1, 0, 0, 1.0])
    t = np.array([True, False, True, False, True, False])
    strata = np.array([0, 0, 1, 1, 2, 2])
    m = matched_att(y, t, strata)
    assert m["n_matched"] == 3 and m["n_treated"] == 3 and m["n_strata"] == 3
    r = np.random.default_rng(1)
    y, t, s = sim_matched(4000, seed=7)
    w = r.integers(0, 3, len(y)).astype(float)
    rep = np.repeat(np.arange(len(y)), w.astype(int))
    a, b = matched_att(y, t, s, w), matched_att(y[rep], t[rep], s[rep])
    assert np.isclose(a["rr"], b["rr"]) and np.isclose(a["diff"], b["diff"])
    only_treated = matched_att(np.array([1.0, 0.0]), np.array([True, True]), np.array([0, 0]))
    assert only_treated["n_matched"] == 0 and np.isnan(only_treated["rr"])


def test_placebo_shuffle_keeps_stratum_shares_and_kills_the_effect():
    y, t, s = sim_matched()
    rng = np.random.default_rng(0)
    sh = shuffle_within(t, s, rng)
    assert sh.sum() == t.sum()
    for k in (0, 17, 39):
        assert sh[s == k].sum() == t[s == k].sum()                         # each stratum keeps its number of flagged rows
    rrs = [matched_att(y, shuffle_within(t, s, rng), s)["rr"] for _ in range(30)]
    assert abs(np.mean(rrs) - 1.0) < 0.1 and np.max(rrs) < 1.5             # no effect once the flag is random
    assert matched_att(y, t, s)["rr"] > 1.6                                # while the real flag shows one


def test_bootstrap_weights_are_constant_within_a_building_and_sum_to_the_number_of_buildings():
    bbl = np.repeat(np.arange(100), 5)
    codes = cluster_codes(bbl)
    for w in boot_weights(codes, 5, seed=1):
        assert len(w) == 500
        assert np.allclose(w.reshape(100, 5), w.reshape(100, 5)[:, :1])      # a building's rows share one weight
        assert w.sum() == 500                                                # as many draws as buildings x rows each
    ws = list(boot_weights(codes, 2, seed=1))
    assert not np.array_equal(ws[0], ws[1])
    pd.testing.assert_series_equal(pd.Series(codes[:5]), pd.Series([0] * 5), check_dtype=False)


# ---------------------------------------------------------------------------------- strata, multi-outcome matching, balance
def test_bucket_helpers_and_deciles():
    from nycdistress.silent import age_bucket, complaint_bucket, decile_within, strata_codes
    assert list(age_bucket([5, 40, 69, 70, 89, 90, 109, 110, 300, np.nan])) == ["<40", "40-69", "40-69", "70-89", "70-89", "90-109", "90-109", "110+", "110+", "unknown"]
    assert list(complaint_bucket([0, 1, 3, 4, 11, 12, 500])) == ["0", "1-3", "1-3", "4-11", "4-11", "12+", "12+"]
    v = np.r_[np.zeros(50), np.arange(50)]                                  # half the rows tied at zero
    d = decile_within(v, np.zeros(100))
    assert np.bincount(d).tolist() == [10] * 10                              # still ten equal groups
    d2 = decile_within(np.r_[np.arange(10), np.arange(10)], np.r_[np.zeros(10), np.ones(10)], n=5)
    assert np.bincount(d2[:10]).tolist() == [2] * 5 and np.bincount(d2[10:]).tolist() == [2] * 5   # deciles are per group
    c = strata_codes(["a", "a", "b", "b"], [1, 2, 1, 1])
    assert c[2] == c[3] and len(set(c)) == 3


def test_matched_multi_agrees_with_single_outcome_version_and_weights():
    y, t, s = sim_matched(8000, seed=11)
    from nycdistress.silent import matched_multi
    Y = np.c_[y, 1 - y, y * 3]
    m = matched_multi(Y, t, s)
    one = matched_att(y, t, s)
    assert np.isclose(m["rate_t"][0], one["rate_treated"]) and np.isclose(m["rate_c"][0], one["rate_control_att"])
    assert np.isclose(m["rate_t"][2], 3 * m["rate_t"][0]) and np.isclose(m["rate_t"][0] + m["rate_t"][1], 1.0)
    r = np.random.default_rng(2)
    w = r.integers(0, 3, len(y)).astype(float)
    rep = np.repeat(np.arange(len(y)), w.astype(int))
    a, b = matched_multi(Y, t, s, w), matched_multi(Y[rep], t[rep], s[rep])
    assert np.allclose(a["rate_t"], b["rate_t"]) and np.allclose(a["rate_c"], b["rate_c"])


def test_matching_balances_the_matching_variables_but_naive_comparison_does_not():
    from nycdistress.silent import att_balance
    r = np.random.default_rng(5)
    n = 80000
    borough = r.integers(0, 2, n)
    units = r.integers(0, 5, n)
    p_dec = r.integers(0, 10, n)
    logit_t = -2.5 + 1.2 * (p_dec / 9) + 0.8 * borough - 0.4 * units / 4          # treatment depends on the matching variables
    treated = r.random(n) < 1 / (1 + np.exp(-logit_t))
    X = np.c_[borough, units, p_dec]
    codes = (borough * 5 + units) * 10 + p_dec
    before, after = att_balance(X, treated, codes)
    assert np.abs(before).max() > 0.15                                           # real imbalance before
    assert np.abs(after).max() < 0.02                                            # coarsened exact matching removes it
    # a variable NOT in the matching cells (and unrelated to treatment) stays balanced; one related to treatment but omitted does not
    extra_bad = (r.random(n) < 0.3 + 0.3 * treated).astype(float)
    b2, a2 = att_balance(np.c_[X, extra_bad], treated, codes)
    assert abs(a2[-1]) > 0.1 and abs(a2[-1]) > 5 * np.abs(after).max()


# ---------------------------------------------------------------------------------- no leakage in the score builder and the saved models
def _load_silent_pipeline():
    import importlib.util
    from pathlib import Path
    path = Path(__file__).resolve().parents[1] / "pipelines" / "silent_phase4.py"
    spec = importlib.util.spec_from_file_location("silent_phase4", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_build_scores_uses_only_values_known_at_the_snapshot_and_never_outcomes():
    mod = _load_silent_pipeline()
    r = np.random.default_rng(8)
    n = 4000
    base = pd.DataFrame({
        "static_unitsres": r.integers(3, 60, n).astype(float),
        "static_borough": pd.Categorical(r.choice(["BK", "BX"], n)),
        "community_district": r.choice(["301", "302", "201"], n),
        "loud_prob_n_12m": r.poisson(3, n).astype(float),
        "loud_311_n_12m": r.poisson(2, n).astype(float),
        "loud_closed_n_12m": r.poisson(3, n).astype(float),
        "loud_nacc_share_12m": np.where(r.random(n) < 0.3, np.nan, r.random(n) * 0.7),
    })
    p = r.beta(1.5, 100, n)
    a = mod.build_scores(base, p)
    # outcome columns (the future) can be anything, even adversarial: the scores must not move
    noisy = base.assign(label_serious_any=r.integers(0, 2, n), label_loud_complaints_next12=r.integers(0, 50, n),
                        label_vacate_or_dobhaz_core=r.integers(0, 2, n), viol_next12=r.integers(0, 30, n))
    b = mod.build_scores(noisy, p)
    pd.testing.assert_frame_equal(a, b)
    # and a frame holding ONLY the documented inputs is enough to build them (nothing else is touched)
    assert set(a.columns) >= {"p_hat", "loudness", "gap_rank", "silent", "gap_resid", "gap_resid_lo", "gap_resid_hi", "silent_resid", "access_blocked"}
    assert a.silent.mean() == pytest.approx(0.10, abs=0.01) and (a.gap_resid_lo <= a.gap_resid + 1e-9).all()


def test_saved_condition_models_were_trained_only_on_snapshots_whose_label_windows_had_ended():
    import json
    from pathlib import Path
    cond = Path(__file__).resolve().parents[1] / "data" / "processed" / "phase4" / "cond"
    metas = sorted(cond.glob("*.json")) if cond.exists() else []
    if not metas:
        pytest.skip("condition models not trained in this checkout")
    from nycdistress.splits import FOLD_ENDS, add_months
    first_eval = {"fold1": "2022-01-01", "fold2": "2023-01-01", "fold3": "2024-01-01", "test": "2025-01-01"}
    seen = set()
    for p in metas:
        m = json.loads(p.read_text())
        assert add_months(m["train_end"], 12) <= pd.Timestamp(first_eval[m["fold"]]), p.name     # purge: label window ended before scoring starts
        assert not any(k in m["feature_set"] for k in ("viol", "loud"))
        seen.add(m["fold"])
    assert seen == set(FOLD_ENDS)
