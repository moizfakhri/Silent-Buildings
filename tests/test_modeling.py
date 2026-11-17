import numpy as np
import pandas as pd

from nycdistress.modeling import (CATEGORICAL, FEATURE_SETS, LogitPrep, SLICES, baseline_scores, feature_columns,
                                  negative_subsample)


def frame(n=400, seed=0):
    r = np.random.default_rng(seed)
    df = pd.DataFrame({
        "bbl": [f"{i:010d}" for i in range(n)],
        "snapshot_date": pd.Timestamp("2021-01-01"),
        "static_borough": pd.Categorical(r.choice(["BK", "BX"], n), categories=["BK", "BX"]),
        "static_bldgclass": pd.Categorical(r.choice(["C1", "D3"], n), categories=["C1", "D3", "S5"]),
        "static_bldgclass_letter": pd.Categorical(r.choice(["C", "D"], n), categories=["C", "D", "S"]),
        "static_landuse": pd.Categorical(r.choice(["2", "3"], n), categories=["2", "3", "4"]),
        "static_age_at_t": r.integers(1, 120, n).astype("float32"),
        "viol_n_12m": r.poisson(3, n).astype("float32"),
        "viol_c_n_12m": r.poisson(0.5, n).astype("float32"),
        "viol_n_36m": np.where(r.random(n) < 0.3, np.nan, r.poisson(9, n)).astype("float32"),
        "loud_prob_n_12m": r.poisson(5, n).astype("float32"),
        "loud_nacc_share_12m": np.where(r.random(n) < 0.4, np.nan, r.random(n)).astype("float32"),
        "prior_omo_n": r.poisson(1, n).astype("float32"),
        "prior_omo_months_since": np.where(r.random(n) < 0.5, np.nan, r.integers(0, 60, n)).astype("float32"),
        "prior_litig_months_since": np.where(r.random(n) < 0.7, np.nan, r.integers(0, 60, n)).astype("float32"),
        "prior_vacate_months_since": np.nan, "prior_aep_months_since": np.nan,
        "label_serious_any": (r.random(n) < 0.1).astype("int32"),
    })
    df["viol_n_36m"] = df["viol_n_36m"].astype("float32")
    return df


def test_feature_sets_partition_the_groups_and_never_contain_labels_or_keys():
    df = frame()
    allc = feature_columns(df, "all")
    assert not any(c.startswith("label_") or c in ("bbl", "snapshot_date") for c in allc)
    assert not any(c.startswith("viol_") for c in feature_columns(df, "no_viol"))
    assert any(c.startswith("loud_") for c in feature_columns(df, "no_viol"))
    assert not any(c.startswith("loud_") for c in feature_columns(df, "no_loud"))
    assert any(c.startswith("viol_") for c in feature_columns(df, "no_loud"))
    sp = feature_columns(df, "static_prior")
    assert not any(c.startswith(("viol_", "loud_")) for c in sp) and any(c.startswith("prior_") for c in sp)
    assert set(FEATURE_SETS) == {"all", "no_viol", "no_loud", "static_prior"}


def test_negative_subsample_is_unbiased_and_keeps_every_positive():
    y = (np.random.default_rng(1).random(200_000) < 0.1).astype(int)
    keep, w = negative_subsample(y, np.random.default_rng(2), neg_keep=0.25)
    assert keep[y == 1].all()
    assert w[y[keep] == 1].max() == 1.0 and np.isclose(w[y[keep] == 0].min(), 4.0)
    assert abs(w.sum() - len(y)) / len(y) < 0.01                  # weighted size matches the full data
    assert abs((w * y[keep]).sum() / w.sum() - y.mean()) < 0.002   # and so does the base rate
    keep, w = negative_subsample(y, np.random.default_rng(2), neg_keep=1.0)
    assert keep.all() and (w == 1).all()


def test_logit_prep_handles_nulls_explicitly_and_uses_only_training_statistics():
    df = frame(600)
    cols = feature_columns(df, "all")
    train, test = df.iloc[:400], df.iloc[400:].copy()
    prep = LogitPrep(cols).fit(train)
    x = prep.transform(test)
    assert x.dtype == np.float32 and not np.isnan(x).any()
    assert len(prep.names) == x.shape[1]
    # an explicit 0/1 flag for every column that has NULLs in training, and no flag for complete columns
    assert {"viol_n_36m", "loud_nacc_share_12m", "prior_omo_months_since"} <= set(prep.null_cols)
    assert "viol_n_12m" not in prep.null_cols
    ind = x[:, [prep.names.index("isnull_viol_n_36m")]].ravel()
    assert set(np.unique(ind)) <= {0.0, 1.0} and np.array_equal(ind.astype(bool), test["viol_n_36m"].isna().to_numpy())
    # statistics come from the training rows only: changing the test rows cannot change them
    test2 = test.assign(viol_n_12m=test["viol_n_12m"] + 1000)
    prep2 = LogitPrep(cols).fit(train)
    assert np.allclose(prep2.mean, prep.mean) and np.allclose(prep2.std, prep.std)
    assert not np.allclose(prep2.transform(test2), x)
    # an all-NULL training column is constant after imputation: no division by zero, no NaN
    allnull = train.assign(viol_n_36m=np.float32(np.nan))
    p3 = LogitPrep(cols).fit(allnull)
    assert not np.isnan(p3.transform(test)).any() and p3.median["viol_n_36m"] == 0.0
    # one-hot columns follow the fixed global levels, even for a level absent from the data (S5)
    assert "static_bldgclass=S5" in prep.names


def test_baseline_rules_use_only_snapshot_time_columns_and_rank_sensibly():
    df = frame(50)
    b = baseline_scores(df)
    assert set(b) == {"rule_viol_12m", "rule_complaints_12m", "rule_last_event"}
    assert np.array_equal(b["rule_viol_12m"], df.viol_n_12m.to_numpy())
    assert (b["rule_last_event"] >= 0).all() and (b["rule_last_event"] <= 1).all()
    d = df.iloc[:2].copy()
    d["prior_omo_months_since"] = [2.0, 30.0]
    d["prior_litig_months_since"] = [np.nan, np.nan]
    assert baseline_scores(d)["rule_last_event"][0] > baseline_scores(d)["rule_last_event"][1]   # more recent event ranks higher
    d["prior_omo_months_since"] = np.nan
    assert (baseline_scores(d)["rule_last_event"] == 0).all()                                    # no earlier event: lowest


def test_quiet_slices():
    df = frame(100)
    q, z = SLICES["quiet"](df), SLICES["zero_viol"](df)
    assert (df.loc[q, "viol_c_n_12m"] == 0).all() and (df.loc[q, "viol_n_12m"] <= 2).all()
    assert (df.loc[z, "viol_n_12m"] == 0).all()
    d2 = df.copy()
    for c in ("viol_open_n", "prior_litig_n", "prior_vacate_n", "prior_aep_n"):
        d2[c] = np.float32(0)
    d2["viol_n_12m"] = np.float32(0)
    d2["loud_prob_n_12m"] = np.float32(0)
    d2["prior_omo_n"] = np.float32(0)
    assert SLICES["clean_record"](d2).all()                                    # nothing on record
    d2.loc[d2.index[0], "prior_omo_n"] = np.float32(1)                          # one earlier emergency repair
    d2.loc[d2.index[1], "viol_open_n"] = np.float32(3)                          # one old violation still open
    assert not SLICES["clean_record"](d2)[:2].any() and SLICES["clean_record"](d2)[2:].all()
    assert SLICES["bronx"](df).sum() + SLICES["brooklyn"](df).sum() == len(df)
    assert CATEGORICAL[0] == "static_borough"


def test_condition_model_can_never_see_complaint_provenance_features():
    from nycdistress.modeling import CONDITION_SETS
    df = frame()
    extra = {c: np.float32(1) for c in ("dob_n_12m", "evict_n_12m", "meta_hist36_complete", "loud_nacc_share_12m", "viol_open_n",
                                          "prior_omo_n", "static_age_at_t", "label_omo", "loud_311_n_12m", "viol_c_n_12m")}
    df = df.assign(**extra)
    for name in CONDITION_SETS:
        cols = feature_columns(df, name)
        assert cols, name
        assert not any(c.startswith(("viol_", "loud_", "meta_", "label_")) for c in cols), (name, cols)
        assert not any(c in ("bbl", "snapshot_date", "community_district") for c in cols)
    core = set(feature_columns(df, "cond_core"))
    plus = set(feature_columns(df, "cond_plus"))
    assert core < plus and {c for c in plus - core} == {"dob_n_12m", "evict_n_12m"}          # plus = core + dob_* + evict_*
    assert all(c.startswith(("static_", "prior_")) for c in core)
