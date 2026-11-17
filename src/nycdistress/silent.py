"""Phase 4 building blocks: complaint "loudness", the silent-distress gap (two definitions), the
access-blocked flag, and the validation machinery (coarsened exact matching, cluster bootstrap, placebo).

Everything here is cross-sectional at a snapshot t: it uses only values known at t (prior-12-month
complaint counts, the out-of-time condition score p_hat, static attributes). Outcomes in (t, t + 12 months]
are used only in the validation functions, never to build a score.

Definitions (fixed before any outcome was looked at):
  loudness   = empirical-Bayes posterior mean of the complaint problem rate per residential unit per year
               (Poisson-gamma, prior fitted by marginal likelihood within snapshot x borough x size bucket).
  gap_rank   = within (snapshot, borough) percentile of p_hat minus within (snapshot, borough) percentile of
               loudness. In [-1, 1]; large = predicted condition is bad, complaints are few.
  silent     = top decile of gap_rank within (snapshot, borough).
  gap_resid  = log((expected + 0.5) / (observed + 0.5)) from a negative-binomial GLM of the observed complaint
               problem count on logit(p_hat), log units and community district. silent_resid = observed count in
               the lower 5% tail of the model's predictive distribution.
  access_blocked = at least 3 problems closed in the last 12 months and a no-access share of at least 0.5.
"""
import numpy as np
import pandas as pd
from scipy.optimize import minimize
from scipy.special import expit, gammaln, logit
from scipy.stats import nbinom

SIZE_EDGES = [3, 6, 12, 25, 50, np.inf]          # residential units: 3-5, 6-11, 12-24, 25-49, 50+
SIZE_LABELS = ["3-5", "6-11", "12-24", "25-49", "50+"]
ACCESS_MIN_CLOSED = 3
ACCESS_MIN_SHARE = 0.5
SILENT_Q = 0.90


def size_bucket(units):
    return pd.cut(pd.Series(np.asarray(units, dtype=float)), SIZE_EDGES, labels=SIZE_LABELS, right=False)


# ------------------------------------------------------------------------------ loudness
def _nb_negloglik(params, y, u):
    a, b = np.exp(params)
    ll = (gammaln(y + a) - gammaln(a) - gammaln(y + 1) + a * np.log(b / (b + u)) + y * np.log(u / (b + u)))
    return -ll.sum()


def fit_gamma_prior(y, u):
    """Marginal-likelihood fit of lambda ~ Gamma(shape a, rate b) for counts y ~ Poisson(u * lambda).
    Returns (a, b). Starts from the method-of-moments estimate."""
    y, u = np.asarray(y, dtype=float), np.asarray(u, dtype=float)
    m = y.sum() / u.sum()                                          # pooled rate per unit
    v = np.average((y / u - m) ** 2, weights=u) - m / u.mean()     # excess variance of the rate
    a0 = m * m / v if v > 1e-9 else 50.0
    a0 = float(np.clip(a0, 0.05, 500.0))
    b0 = a0 / max(m, 1e-6)
    r = minimize(_nb_negloglik, np.log([a0, b0]), args=(y, u), method="L-BFGS-B", bounds=[(-6, 8), (-6, 12)])
    a, b = np.exp(r.x)
    return float(a), float(b)


def eb_rate(y, units, groups):
    """Poisson-gamma shrinkage of complaint counts to a rate per unit per year, by group.

    Returns (posterior_mean_rate, raw_rate, prior_mean_by_row). The posterior mean (a + y) / (b + u) lies
    between the raw rate and the group prior mean, and small buildings are pulled harder.
    """
    y = np.asarray(y, dtype=float)
    u = np.asarray(units, dtype=float)
    groups = np.asarray(groups)
    post = np.empty(len(y))
    prior = np.empty(len(y))
    for g in pd.unique(groups):
        m = groups == g
        a, b = fit_gamma_prior(y[m], u[m])
        post[m] = (a + y[m]) / (b + u[m])
        prior[m] = a / b
    return post, y / u, prior


# ------------------------------------------------------------------------------ gaps
def pct_within(values, groups):
    """Mid-rank percentile in (0, 1) within each group; ties share the average rank."""
    s = pd.Series(np.asarray(values, dtype=float))
    g = pd.Series(np.asarray(groups))
    rank = s.groupby(g).rank(method="average")
    n = s.groupby(g).transform("size")
    return ((rank - 0.5) / n).to_numpy()


def rank_gap(p_hat, loudness, groups):
    """pct(p_hat) - pct(loudness) within groups (group = snapshot x borough)."""
    return pct_within(p_hat, groups) - pct_within(loudness, groups)


def top_decile(gap, groups, q=SILENT_Q):
    s = pd.Series(np.asarray(gap, dtype=float))
    cut = s.groupby(np.asarray(groups)).transform(lambda x: x.quantile(q))
    return (s >= cut).to_numpy()


def access_blocked(closed_n, nacc_share, min_closed=ACCESS_MIN_CLOSED, min_share=ACCESS_MIN_SHARE):
    closed_n, share = np.asarray(closed_n, dtype=float), np.asarray(nacc_share, dtype=float)
    return (closed_n >= min_closed) & (share >= min_share) & ~np.isnan(share)


# ------------------------------------------------------------------------------ expected complaints (negative binomial)
def _design(p_hat, units, district, districts_levels):
    z = logit(np.clip(np.asarray(p_hat, dtype=float), 1e-4, 1 - 1e-4))
    X = pd.DataFrame({"const": 1.0, "logit_p": z, "log_units": np.log(np.asarray(units, dtype=float))})
    cd = pd.Categorical(district, categories=districts_levels)
    dummies = pd.get_dummies(cd, prefix="cd", drop_first=True, dtype=float)
    return pd.concat([X.reset_index(drop=True), dummies.reset_index(drop=True)], axis=1)


def fit_expected_complaints(y, p_hat, units, district, n_alpha_iter=3):
    """NB GLM of the observed complaint problem count with offset log(units). Returns a result dict with
    expected counts, a 95% interval on the expected count (parameter uncertainty), the dispersion alpha and
    the lower-tail probability P(Y <= observed) of every row."""
    import statsmodels.api as sm
    y = np.asarray(y, dtype=float)
    u = np.asarray(units, dtype=float)
    levels = sorted(pd.unique(pd.Series(district).dropna()))
    X = _design(p_hat, u, district, levels)
    off = np.log(u)
    pois = sm.GLM(y, X, family=sm.families.Poisson(), offset=off).fit()
    mu = pois.mu
    alpha = 0.5
    for _ in range(n_alpha_iter):                                  # moment estimate of alpha, then refit
        alpha = max(float(((y - mu) ** 2 - mu).sum() / (mu ** 2).sum()), 1e-3)
        res = sm.GLM(y, X, family=sm.families.NegativeBinomial(alpha=alpha), offset=off).fit()
        mu = res.mu
    pred = res.get_prediction(X, offset=off).summary_frame(alpha=0.05)
    n = 1.0 / alpha
    p = n / (n + mu)
    lower_tail = nbinom.cdf(y, n, p)                                # P(Y <= y)
    mid_p = lower_tail - 0.5 * nbinom.pmf(y, n, p)
    return dict(mu=mu, mu_lo=pred["mean_ci_lower"].to_numpy(), mu_hi=pred["mean_ci_upper"].to_numpy(),
                alpha=alpha, p_low=mid_p, coef=res.params, n=len(y))


def resid_gap(y, mu, mu_lo, mu_hi):
    """log((expected + .5) / (observed + .5)) with an interval from the uncertainty of the expectation."""
    y = np.asarray(y, dtype=float)
    return (np.log((mu + 0.5) / (y + 0.5)), np.log((mu_lo + 0.5) / (y + 0.5)), np.log((mu_hi + 0.5) / (y + 0.5)))


# ------------------------------------------------------------------------------ validation helpers
def cluster_codes(bbl):
    return pd.factorize(pd.Series(np.asarray(bbl)))[0]


def boot_weights(codes, n_boot, seed=0):
    """Yield integer row-weight vectors for a cluster bootstrap by building."""
    rng = np.random.default_rng(seed)
    n = int(codes.max()) + 1
    for _ in range(n_boot):
        yield np.bincount(rng.integers(0, n, n), minlength=n).astype(np.float64)[codes]


def wmean(x, w):
    return float((x * w).sum() / w.sum()) if w.sum() > 0 else float("nan")


def matched_att(y, treated, strata, w=None):
    """Treated-vs-control comparison within coarsened exact-matching strata (ATT weighting).

    Each stratum with both treated and control rows contributes; unmatched treated rows are dropped.
    Returns dict: rate_treated (matched treated rows), rate_control_att (the controls' stratum rates, weighted by the
    treated counts), diff, rr, n_treated, n_matched, n_strata.
    """
    y = np.asarray(y, dtype=float)
    t = np.asarray(treated, dtype=bool)
    w = np.ones(len(y)) if w is None else np.asarray(w, dtype=float)
    codes = pd.factorize(pd.Series(strata).astype(str))[0] if not isinstance(strata, np.ndarray) or strata.dtype.kind not in "iu" else strata
    k = int(codes.max()) + 1
    wt, wc = np.where(t, w, 0.0), np.where(~t, w, 0.0)
    nt, nc = np.bincount(codes, wt, k), np.bincount(codes, wc, k)
    yt, yc = np.bincount(codes, wt * y, k), np.bincount(codes, wc * y, k)
    ok = (nt > 0) & (nc > 0)
    if not ok.any() or nt[ok].sum() == 0:
        return dict(rate_treated=np.nan, rate_control_att=np.nan, diff=np.nan, rr=np.nan, n_treated=float(nt.sum()), n_matched=0.0, n_strata=0)
    rate_t = yt[ok].sum() / nt[ok].sum()
    rate_c = (nt[ok] * (yc[ok] / nc[ok])).sum() / nt[ok].sum()
    return dict(rate_treated=float(rate_t), rate_control_att=float(rate_c), diff=float(rate_t - rate_c),
                rr=float(rate_t / rate_c) if rate_c > 0 else float("nan"), n_treated=float(nt.sum()),
                n_matched=float(nt[ok].sum()), n_strata=int(ok.sum()))


def shuffle_within(flag, strata, rng):
    """Permute a 0/1 flag among the rows of each stratum (placebo): every stratum keeps its number of flagged rows.
    Vectorised: sort rows by (stratum, random key) and flag the first n_flagged rows of each stratum."""
    flag = np.asarray(flag, dtype=bool)
    codes = strata if (isinstance(strata, np.ndarray) and strata.dtype.kind in "iu") else pd.factorize(pd.Series(strata).astype(str))[0]
    k = int(codes.max()) + 1
    n_flag = np.bincount(codes, flag.astype(float), k).astype(int)
    order = np.lexsort((rng.random(len(flag)), codes))
    sorted_codes = codes[order]
    starts = np.r_[0, np.flatnonzero(np.diff(sorted_codes)) + 1]
    first = np.repeat(starts, np.diff(np.r_[starts, len(flag)]))
    within = np.arange(len(flag)) - first
    out = np.zeros(len(flag), dtype=bool)
    out[order] = within < n_flag[sorted_codes]
    return out


def calibrated_prob_check(p):
    p = np.asarray(p)
    assert np.all((p >= 0) & (p <= 1)), "probabilities out of range"
    return expit(logit(np.clip(p, 1e-6, 1 - 1e-6)))


# ------------------------------------------------------------------------------ multi-outcome matching, balance, strata
AGE_EDGES = [0, 40, 70, 90, 110, np.inf]
AGE_LABELS = ["<40", "40-69", "70-89", "90-109", "110+"]
COMPLAINT_EDGES = [0, 1, 4, 12, np.inf]            # prior-12-month complaint problems: 0, 1-3, 4-11, 12+
COMPLAINT_LABELS = ["0", "1-3", "4-11", "12+"]


def age_bucket(age):
    b = pd.cut(pd.Series(np.asarray(age, dtype=float)), AGE_EDGES, labels=AGE_LABELS, right=False).astype(object)
    return b.where(b.notna(), "unknown").to_numpy()


def complaint_bucket(n):
    return pd.cut(pd.Series(np.asarray(n, dtype=float)), COMPLAINT_EDGES, labels=COMPLAINT_LABELS, right=False).astype(str).to_numpy()


def decile_within(values, groups, n=10):
    """Decile 0..n-1 of `values` within each group (rank-based so ties and heavy zeros still give balanced groups)."""
    s = pd.Series(np.asarray(values, dtype=float))
    r = s.groupby(np.asarray(groups)).rank(method="first")
    m = s.groupby(np.asarray(groups)).transform("size")
    return np.minimum(((r - 1) * n / m).astype(int), n - 1).to_numpy()


def strata_codes(*cols):
    """Integer code of the combination of the given columns (the coarsened exact matching cell)."""
    key = pd.DataFrame({i: pd.Series(np.asarray(c)).astype(str) for i, c in enumerate(cols)})
    return key.groupby(list(key.columns), sort=False).ngroup().to_numpy()


def matched_multi(Y, treated, codes, w=None):
    """Treated-vs-control comparison inside strata for several outcomes at once (ATT weighting).

    Y: (n, k) array. Returns dict with rate_t, rate_c (arrays of length k), n_treated_matched, n_strata.
    Controls are reweighted so each stratum counts as often as its treated rows.
    """
    Y = np.asarray(Y, dtype=float)
    if Y.ndim == 1:
        Y = Y[:, None]
    t = np.asarray(treated, dtype=bool)
    w = np.ones(len(t)) if w is None else np.asarray(w, dtype=float)
    k = int(codes.max()) + 1
    wt, wc = np.where(t, w, 0.0), np.where(~t, w, 0.0)
    nt, nc = np.bincount(codes, wt, k), np.bincount(codes, wc, k)
    ok = (nt > 0) & (nc > 0)
    tot = nt[ok].sum()
    if tot == 0:
        nan = np.full(Y.shape[1], np.nan)
        return dict(rate_t=nan, rate_c=nan, n_treated_matched=0.0, n_strata=0)
    rt, rc = np.empty(Y.shape[1]), np.empty(Y.shape[1])
    ratio = np.where(ok, nt / np.where(nc > 0, nc, 1), 0.0)
    for j in range(Y.shape[1]):
        yt = np.bincount(codes, wt * Y[:, j], k)
        yc = np.bincount(codes, wc * Y[:, j], k)
        rt[j] = yt[ok].sum() / tot
        rc[j] = (ratio[ok] * yc[ok]).sum() / tot
    return dict(rate_t=rt, rate_c=rc, n_treated_matched=float(tot), n_strata=int(ok.sum()))


def att_balance(X, treated, codes):
    """Standardised mean differences of covariates X (n, p): treated vs ALL controls (before matching) and
    treated vs the ATT-reweighted controls (after). Reweighted controls count each stratum as often as its treated rows."""
    X = np.asarray(X, dtype=float)
    t = np.asarray(treated, dtype=bool)
    k = int(codes.max()) + 1
    nt = np.bincount(codes, t.astype(float), k)
    nc = np.bincount(codes, (~t).astype(float), k)
    ok = (nt > 0) & (nc > 0)
    wc = np.where(~t & ok[codes], nt[codes] / np.where(nc[codes] > 0, nc[codes], 1), 0.0)
    wt = np.where(t & ok[codes], 1.0, 0.0)
    sd = np.sqrt((X[t].var(axis=0) + X[~t].var(axis=0)) / 2)
    sd = np.where(sd < 1e-12, 1.0, sd)
    before = (X[t].mean(axis=0) - X[~t].mean(axis=0)) / sd
    mt = (X * wt[:, None]).sum(axis=0) / wt.sum()
    mc = (X * wc[:, None]).sum(axis=0) / wc.sum()
    return before, (mt - mc) / sd


def boot_ci(draws, point):
    lo, hi = np.nanpercentile(draws, [2.5, 97.5])
    return dict(point=float(point), lo=float(lo), hi=float(hi))
