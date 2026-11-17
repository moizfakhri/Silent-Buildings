"""Staggered-adoption difference-in-differences event study (Callaway and Sant'Anna 2021 style, no covariates), implemented here.

For each cohort G (the first treated period) and each event time e, ATT(G, G+e) = mean over cohort-G units of (Y[G+e] - Y[G-1]) minus the same
change for a comparison group: `never` = units never treated; `notyet` = never-treated plus units whose own treatment period is later than both
periods involved. The event-time effect is the cohort-size-weighted average over cohorts: theta(e). e = -1 is the reference period (exactly 0).
Because every quantity is a weighted column mean per group, a cluster bootstrap (resampling units) costs only a few matrix products per draw.
Identifying assumption: parallel trends between treated and comparison units absent treatment; the pre-period theta(e<-1) check it.
"""
import numpy as np
from scipy import sparse
from scipy.stats import chi2


def _group_sums(Y, labels, w, n_groups):
    """Weighted column sums and weights per group. labels in 0..n_groups-1 (never-treated = the last group)."""
    A = sparse.csr_matrix((w, (labels, np.arange(len(labels)))), shape=(n_groups, len(labels)))
    return A @ Y, np.asarray(A.sum(axis=1)).ravel()


def theta_from_weights(Y, g, w, pre, post, control="never"):
    """Event-study point estimate for one set of unit weights. Returns (events array, theta array, per-cohort ATT dict)."""
    cohorts = np.array(sorted(set(g[g >= 0].tolist())))
    ng = len(cohorts)
    lab = np.where(g >= 0, np.searchsorted(cohorts, g), ng)
    S, N = _group_sums(Y, lab, w, ng + 1)
    events = np.array([e for e in range(-pre, post + 1) if e != -1])
    T = Y.shape[1]
    num = np.zeros(len(events))
    den = np.zeros(len(events))
    att = {}
    for gi, G in enumerate(cohorts):
        if N[gi] <= 0:
            continue
        b = G - 1
        for k, e in enumerate(events):
            t = G + e
            if t < 0 or t >= T or b < 0:
                continue
            if control == "never":
                cs, cn = S[ng], N[ng]
                if cn <= 0:
                    continue
                c_diff = (cs[t] - cs[b]) / cn
            else:
                allowed = [ng] + [j for j in range(ng) if cohorts[j] > max(t, b) and j != gi]
                cn = sum(N[j] for j in allowed)
                if cn <= 0:
                    continue
                c_diff = sum(S[j][t] - S[j][b] for j in allowed) / cn
            a = (S[gi][t] - S[gi][b]) / N[gi] - c_diff
            att[(int(G), int(e))] = a
            num[k] += N[gi] * a
            den[k] += N[gi]
    theta = np.where(den > 0, num / np.where(den > 0, den, 1), np.nan)
    return events, theta, att


def stratum_weights(m, g, strata):
    """Bootstrap multiplicities `m` -> unit weights that make the never-treated controls match the treated units' stratum mix.

    Controls get m * (treated weight in stratum / control weight in stratum). Treated units in a stratum with no controls get weight 0
    (they have no comparable control and are dropped from that draw), and so do strata with no treated.
    """
    treated = g >= 0
    k = int(strata.max()) + 1
    t_sum = np.bincount(strata[treated], weights=m[treated], minlength=k)
    c_sum = np.bincount(strata[~treated], weights=m[~treated], minlength=k)
    ratio = np.divide(t_sum, c_sum, out=np.zeros(k), where=c_sum > 0)
    w = m.astype(float).copy()
    w[~treated] = m[~treated] * ratio[strata[~treated]]
    w[treated] = m[treated] * (c_sum[strata[treated]] > 0)
    return w


def trend_adjusted(events, theta):
    """Average post effect after subtracting the linear pre-trend extrapolated from e <= -1 (e = -1 is exactly 0 by construction)."""
    pre = [i for i, e in enumerate(events) if e <= -2]
    x = np.append(events[pre], -1.0)
    y = np.append(theta[pre], 0.0)
    ok = ~np.isnan(y)
    slope, icpt = np.polyfit(x[ok], y[ok], 1)
    post = [i for i, e in enumerate(events) if e >= 0]
    return float(np.nanmean(theta[post] - (icpt + slope * events[post])))


def event_study(Y, g, pre=8, post=8, control="never", n_boot=300, seed=0, strata=None):
    """Point estimate, cluster-bootstrap (by unit) intervals, a joint pre-trend test and a pre-trend-extrapolation adjustment.

    `strata` (int array, one per unit) reweights never-treated controls to the treated stratum mix inside every draw (control="never" only).
    Returns dict(events, theta, lo, hi, se, pre_trend_p, pre_trend_wald, avg_post (+_lo/_hi), adj_post (+_lo/_hi), draws).
    """
    n = len(g)

    def weights(m):
        return stratum_weights(m, g, strata) if (strata is not None and control == "never") else m.astype(float)

    ev, th, _ = theta_from_weights(Y, g, weights(np.ones(n)), pre, post, control)
    rng = np.random.default_rng(seed)
    draws = np.empty((n_boot, len(ev)))
    for b in range(n_boot):
        draws[b] = theta_from_weights(Y, g, weights(np.bincount(rng.integers(0, n, n), minlength=n)), pre, post, control)[1]
    lo, hi = np.nanpercentile(draws, [2.5, 97.5], axis=0)
    se = np.nanstd(draws, axis=0, ddof=1)
    pre_idx = [i for i, e in enumerate(ev) if e <= -2]
    cov = np.cov(draws[:, pre_idx].T) + 1e-12 * np.eye(len(pre_idx))
    wald = float(th[pre_idx] @ np.linalg.solve(cov, th[pre_idx]))
    post_idx = [i for i, e in enumerate(ev) if e >= 0]
    avg_draws = np.nanmean(draws[:, post_idx], axis=1)
    adj_draws = np.array([trend_adjusted(ev, d) for d in draws])
    return dict(events=ev, theta=th, lo=lo, hi=hi, se=se, pre_trend_p=float(chi2.sf(wald, len(pre_idx))), pre_trend_wald=wald,
                avg_post=float(np.nanmean(th[post_idx])), avg_post_lo=float(np.percentile(avg_draws, 2.5)), avg_post_hi=float(np.percentile(avg_draws, 97.5)),
                adj_post=trend_adjusted(ev, th), adj_post_lo=float(np.percentile(adj_draws, 2.5)), adj_post_hi=float(np.percentile(adj_draws, 97.5)), draws=draws)
