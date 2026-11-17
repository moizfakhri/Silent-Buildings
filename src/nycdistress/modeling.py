"""Phase 3 modelling: data loading, feature sets, explicit NULL handling, baselines, logistic
regression and LightGBM trained strictly forward in time (see splits.py for the fold layout).

NULL handling (never zero-filled silently):
  * Window features are NULL when the window reaches back before the source's first covered date
    (36-month windows in 2019-2020, 311 windows in 2020-2022). LightGBM receives them as NaN and
    learns a missing direction. Logistic regression gets a 0/1 `isnull_<col>` indicator for every
    column that has NULLs in the training rows, then the median of the non-null training values.
  * A column that is entirely NULL in the training rows (all 36m windows in fold1) has no median;
    it is constant, so the logistic model gives it a zero weight. LightGBM never splits on it.
  * `prior_*_months_since` and `loud_nacc_share_*` are NULL because there is no event: the indicator
    carries that meaning ("no earlier event"), the imputed value is the training median.
"""
import warnings
from dataclasses import dataclass
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
PROC = ROOT / "data" / "processed"
KEYS = ["bbl", "snapshot_date"]
TARGETS = ["label_serious_any", "label_omo", "label_litigation", "label_vacate_or_aep"]
CATEGORICAL = ["static_borough", "static_bldgclass", "static_bldgclass_letter", "static_landuse"]
FEATURE_SETS = {
    "all": lambda c: True,
    "no_viol": lambda c: not c.startswith("viol_"),
    "no_loud": lambda c: not c.startswith("loud_"),
    # no HPD violations and no complaints: static, evictions, DOB and earlier city/court events only.
    # This is the feature set the Phase 4 condition model is allowed to see.
    "static_prior": lambda c: not c.startswith(("viol_", "loud_")),
}
# Phase 4 condition-model feature sets: nothing with complaint provenance (no viol_*, no loud_*), and no
# meta_* time flag. `cond_core` = static fields + earlier city/court events; `cond_plus` adds DOB violations and evictions.
CONDITION_SETS = {
    "cond_core": lambda c: c.startswith(("static_", "prior_")),
    "cond_plus": lambda c: c.startswith(("static_", "prior_", "dob_", "evict_")),
}
# outcomes for the condition model. Primary = vacate orders or DOB physical-hazard violations of the CORE definition
# (IMEGNCY, UB, FISPHAZ, EGNCY): the least tenant-driven outcome we have. The wide definition also counts AEUHAZ1
# (certification failures) and is kept as a sensitivity analysis: its rate swings 0.24% to 2.1% between snapshots
# (batch issuance) and its calibration level drifts, whereas the core rate is stable (0.2% to 0.33%).
# This choice was made after looking at event rates and calibration, before any gap or silent-group outcome existed.
P4_PRIMARY = "label_vacate_or_dobhaz_core"
P4_TARGETS = [P4_PRIMARY, "label_vacate_or_dobhaz", "label_serious_any", "label_omo", "label_vacate_or_aep", "label_litigation"]
# "quiet" evaluation slices: buildings the violation-count rule would not flag
SLICES = {
    "all": lambda d: np.ones(len(d), dtype=bool),
    "quiet": lambda d: ((d["viol_c_n_12m"] == 0) & (d["viol_n_12m"] <= 2)).to_numpy(),   # no class C, at most 2 violations in 12m
    "zero_viol": lambda d: (d["viol_n_12m"] == 0).to_numpy(),
    # nothing on record at all: no violation in 12 months, none still open, no complaint in 12 months, and no
    # earlier OMO charge, litigation, vacate order or AEP selection. Only static fields can speak here.
    "clean_record": lambda d: ((d["viol_n_12m"] == 0) & (d["viol_open_n"] == 0) & (d["loud_prob_n_12m"] == 0)
                               & (d["prior_omo_n"] == 0) & (d["prior_litig_n"] == 0) & (d["prior_vacate_n"] == 0)
                               & (d["prior_aep_n"] == 0)).to_numpy(),
    "bronx": lambda d: (d["static_borough"] == "BX").to_numpy(),
    "brooklyn": lambda d: (d["static_borough"] == "BK").to_numpy(),
}
NEG_KEEP = 1.0    # train on every row. (A value < 1 keeps negatives with that probability and reweights them.)


def load_frame(proc=None):
    """features + labels + community district, one row per (bbl, snapshot), sorted by snapshot then bbl."""
    proc = Path(proc or PROC)
    con = duckdb.connect()
    df = con.sql(f"""
        SELECT f.*, l.* EXCLUDE (bbl, snapshot_date), s.community_district
        FROM read_parquet('{proc / "features.parquet"}') f
        JOIN read_parquet('{proc / "labels.parquet"}') l USING (bbl, snapshot_date)
        JOIN read_parquet('{proc / "spine.parquet"}') s USING (bbl)
        ORDER BY snapshot_date, bbl""").df()
    df["snapshot_date"] = pd.to_datetime(df["snapshot_date"])
    for c in CATEGORICAL:
        df[c] = df[c].astype(str).astype("category")
    df["meta_hist36_complete"] = df["meta_hist36_complete"].astype("int8")
    for c in df.columns:
        if c in KEYS or c in CATEGORICAL or c == "community_district" or c.startswith("label_"):
            continue
        df[c] = df[c].astype("float32")
    for c in [c for c in df.columns if c.startswith("label_")]:
        df[c] = df[c].astype("int32")
    return df


def feature_columns(df, fset):
    keep = FEATURE_SETS[fset] if fset in FEATURE_SETS else CONDITION_SETS[fset]
    return [c for c in df.columns if c not in KEYS and not c.startswith("label_") and c != "community_district" and keep(c)]


def rows(df, dates):
    return df["snapshot_date"].isin(list(dates)).to_numpy()


def negative_subsample(y, rng, neg_keep=NEG_KEEP):
    """Keep every positive and each negative with probability neg_keep; weights restore the original mix."""
    y = np.asarray(y)
    keep = (y == 1) | (rng.random(len(y)) < neg_keep)
    w = np.where(y[keep] == 1, 1.0, 1.0 / neg_keep)
    return keep, w


# ------------------------------------------------------------------------------------ baselines
def baseline_scores(df):
    """Rules with nothing to fit. All use only features known at the snapshot."""
    months = df[["prior_litig_months_since", "prior_omo_months_since", "prior_vacate_months_since", "prior_aep_months_since"]]
    last = months.min(axis=1, skipna=True)           # months since the most recent earlier city/court event of any kind
    return {
        "rule_viol_12m": df["viol_n_12m"].fillna(0).to_numpy(),
        "rule_complaints_12m": df["loud_prob_n_12m"].fillna(0).to_numpy(),
        # most recent earlier event first; lots with no earlier event score lowest
        "rule_last_event": (1.0 / (1.0 + last)).fillna(0).to_numpy(),
    }


# ------------------------------------------------------------------------------------ logistic preprocessing
LOG_PREFIXES = ("static_unit", "static_lot", "static_bldgarea", "static_numfloors")


def _is_log_col(c):
    return (c.endswith(("_3m", "_12m", "_36m")) and "share" not in c and "months_since" not in c) or \
        c in ("viol_open_n", "viol_open_a_n", "viol_open_b_n", "viol_open_c_n", "loud_open_prob_n", "prior_litig_n", "prior_omo_n",
              "prior_vacate_n", "prior_vacate_active_n", "prior_aep_n", "prior_aep_active_n") or \
        c.startswith(LOG_PREFIXES) or "months_since" in c


@dataclass
class LogitPrep:
    """Impute, flag, log-transform and standardise; every statistic comes from the training rows only."""
    cols: list
    num_cols: list = None
    cat_cols: list = None
    cat_levels: dict = None
    null_cols: list = None
    median: dict = None
    mean: np.ndarray = None
    std: np.ndarray = None

    def _num(self, df):
        x = df[self.num_cols].to_numpy(dtype=np.float64, copy=True)
        for j, c in enumerate(self.num_cols):
            if _is_log_col(c):
                x[:, j] = np.log1p(np.clip(x[:, j], 0, None))
        return x

    def fit(self, df):
        self.cat_cols = [c for c in self.cols if c in CATEGORICAL]
        self.num_cols = [c for c in self.cols if c not in CATEGORICAL]
        self.cat_levels = {c: list(df[c].cat.categories) for c in self.cat_cols}
        x = self._num(df)
        nan = np.isnan(x)
        self.null_cols = [c for j, c in enumerate(self.num_cols) if nan[:, j].any()]
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)       # an all-NULL column has no median: handled just below
            med = np.nanmedian(x, axis=0)
        med = np.where(np.isnan(med), 0.0, med)      # a column that is NULL in every training row
        self.median = dict(zip(self.num_cols, med))
        x = np.where(nan, med, x)
        self.mean = x.mean(axis=0)
        std = x.std(axis=0)
        self.std = np.where(std < 1e-9, 1.0, std)    # constant column: weight will be 0, do not divide by 0
        return self

    def transform(self, df):
        x = self._num(df)
        nan = np.isnan(x)
        ind = np.stack([nan[:, self.num_cols.index(c)] for c in self.null_cols], axis=1).astype(np.float32) if self.null_cols else np.zeros((len(df), 0), np.float32)
        med = np.array([self.median[c] for c in self.num_cols])
        x = (np.where(nan, med, x) - self.mean) / self.std
        parts = [x.astype(np.float32), ind]
        for c in self.cat_cols:
            codes = pd.Categorical(df[c].astype(str), categories=self.cat_levels[c]).codes
            oh = np.zeros((len(df), len(self.cat_levels[c])), np.float32)
            ok = codes >= 0
            oh[np.flatnonzero(ok), codes[ok]] = 1.0
            parts.append(oh)
        return np.hstack(parts)

    @property
    def names(self):
        out = list(self.num_cols) + [f"isnull_{c}" for c in self.null_cols]
        for c in self.cat_cols:
            out += [f"{c}={lv}" for lv in self.cat_levels[c]]
        return out


# ------------------------------------------------------------------------------------ models
LGB_PARAMS = dict(objective="binary", learning_rate=0.05, num_leaves=63, min_data_in_leaf=200, feature_fraction=0.8,
                  bagging_fraction=0.8, bagging_freq=1, lambda_l2=5.0, max_bin=127, num_threads=10, verbose=-1, seed=0,
                  deterministic=True, force_row_wise=True)


def _lgb_data(df, cols, y, w=None, reference=None):
    import lightgbm as lgb
    cats = [c for c in cols if c in CATEGORICAL]
    return lgb.Dataset(df[cols], label=y, weight=w, categorical_feature=cats, reference=reference, free_raw_data=False)


def fit_lgb(train, es, cols, target, seed=0, max_rounds=2000, early_stop=100, refit_scale=1.1, final_train=None,
            return_inner=False):
    """Early-stop on `es` (a later, purged time slice, scored unweighted), then refit on `final_train`
    with round(best_iteration * refit_scale) trees. Returns (booster, best_iteration, n_rows_fit), plus the
    early-stopped inner booster when return_inner=True (used to fit a calibrator on `es`)."""
    import lightgbm as lgb
    rng = np.random.default_rng(seed)
    p = {**LGB_PARAMS, "seed": seed}
    keep, w = negative_subsample(train[target].to_numpy(), rng)
    tr = _lgb_data(train.loc[keep], cols, train[target].to_numpy()[keep], w)
    va = _lgb_data(es, cols, es[target].to_numpy(), None, reference=tr)
    b = lgb.train({**p, "metric": "binary_logloss"}, tr, num_boost_round=max_rounds, valid_sets=[va],
                  callbacks=[lgb.early_stopping(early_stop, verbose=False)])
    best = int(b.best_iteration)
    ft = final_train if final_train is not None else train
    keep, w = negative_subsample(ft[target].to_numpy(), np.random.default_rng(seed + 1))
    full = _lgb_data(ft.loc[keep], cols, ft[target].to_numpy()[keep], w)
    final = lgb.train(p, full, num_boost_round=max(10, int(round(best * refit_scale))))
    if return_inner:
        return final, best, int(keep.sum()), b
    return final, best, int(keep.sum())


def predict_lgb(booster, df, cols):
    return booster.predict(df[cols], num_threads=LGB_PARAMS["num_threads"]).astype(np.float32)


def fit_logit(train, cols, target, seed=0, C=1.0):
    from sklearn.linear_model import LogisticRegression
    keep, w = negative_subsample(train[target].to_numpy(), np.random.default_rng(seed))
    sub = train.loc[keep]
    prep = LogitPrep(cols).fit(sub)
    clf = LogisticRegression(C=C, max_iter=300, tol=1e-4)
    clf.fit(prep.transform(sub), sub[target].to_numpy(), sample_weight=w)
    return prep, clf


def predict_logit(model, df):
    prep, clf = model
    return clf.predict_proba(prep.transform(df))[:, 1].astype(np.float32)
