"""Evaluation for ranked risk scores: ROC-AUC, PR-AUC, precision/recall/lift at the top of each
snapshot's ranking, calibration, and a cluster bootstrap by building.

All metrics accept row weights. A bootstrap resample of buildings is expressed as integer weights
(how many times each building is drawn), so no data is copied: `RankEval` sorts the scores once and
re-evaluates every metric for each weight vector in O(n).
"""
import numpy as np
import pandas as pd

FRACS = (0.01, 0.05)          # top 1% and top 5% of buildings in every snapshot
KS = (500, 1000, 2500)        # top-k buildings per snapshot


class RankEval:
    def __init__(self, y, score, snap, fracs=FRACS, ks=KS):
        self.y = np.asarray(y, dtype=np.float64)
        self.score = np.asarray(score, dtype=np.float64)
        n = len(self.y)
        self.order = np.argsort(self.score, kind="stable")           # ascending, for AUC
        s = self.score[self.order]
        self.starts = np.concatenate(([0], np.flatnonzero(np.diff(s)) + 1))  # tie-group boundaries
        # per-snapshot top selections (descending score, ties by input order)
        snap = np.asarray(snap)
        self.sel = {}
        codes, uniq = pd.factorize(snap, sort=True)
        by_snap = [np.flatnonzero(codes == i) for i in range(len(uniq))]
        ranked = [idx[np.argsort(-self.score[idx], kind="stable")] for idx in by_snap]
        for f in fracs:
            self.sel[f"top{int(round(f * 100))}pct"] = np.concatenate([r[: max(1, int(np.ceil(f * len(r))))] for r in ranked])
        for k in ks:
            self.sel[f"top{k}"] = np.concatenate([r[:k] for r in ranked])
        self.n = n

    def _w(self, w):
        return np.ones(self.n) if w is None else np.asarray(w, dtype=np.float64)

    def _groups(self, w):
        wy = (w * self.y)[self.order]
        wn = (w * (1.0 - self.y))[self.order]
        return np.add.reduceat(wy, self.starts), np.add.reduceat(wn, self.starts)

    def roc_auc(self, w=None):
        pos, neg = self._groups(self._w(w))
        P, N = pos.sum(), neg.sum()
        if P == 0 or N == 0:
            return float("nan")
        neg_before = np.cumsum(neg) - neg
        return float((pos * (neg_before + 0.5 * neg)).sum() / (P * N))

    def pr_auc(self, w=None):
        pos, neg = self._groups(self._w(w))
        P = pos.sum()
        if P == 0:
            return float("nan")
        pos, neg = pos[::-1], neg[::-1]                               # descending score
        tp, fp = np.cumsum(pos), np.cumsum(neg)
        seen = tp + fp
        # leading tie groups can have zero total weight (e.g. every building in them was not drawn
        # by a bootstrap resample); they contribute nothing, so precision is only taken where defined
        prec = np.divide(tp, seen, out=np.zeros_like(tp), where=seen > 0)
        return float((pos / P * prec).sum())                          # average precision, ties as one threshold

    def top_stats(self, w=None):
        w = self._w(w)
        total_pos = float((w * self.y).sum())
        base = total_pos / float(w.sum())
        out = {}
        for name, idx in self.sel.items():
            wi = w[idx]
            hit = float((wi * self.y[idx]).sum())
            prec = hit / float(wi.sum()) if wi.sum() > 0 else float("nan")
            out[f"p_{name}"] = prec
            out[f"r_{name}"] = hit / total_pos if total_pos > 0 else float("nan")
            out[f"lift_{name}"] = prec / base if base > 0 else float("nan")
        return out

    def metrics(self, w=None):
        w_ = self._w(w)
        return {"roc_auc": self.roc_auc(w_), "pr_auc": self.pr_auc(w_),
                "base_rate": float((w_ * self.y).sum() / w_.sum()), **self.top_stats(w_)}


def calibration_table(y, p, n_bins=10):
    """Equal-mass bins by predicted probability: mean predicted vs observed rate."""
    df = pd.DataFrame({"y": np.asarray(y, dtype=float), "p": np.asarray(p, dtype=float)})
    df["bin"] = pd.qcut(df.p.rank(method="first"), n_bins, labels=False)
    g = df.groupby("bin").agg(n=("y", "size"), mean_pred=("p", "mean"), observed=("y", "mean")).reset_index()
    return g


def brier(y, p):
    y, p = np.asarray(y, dtype=float), np.asarray(p, dtype=float)
    return float(np.mean((p - y) ** 2))


def ece(y, p, n_bins=10):
    """Expected calibration error with equal-mass bins."""
    t = calibration_table(y, p, n_bins)
    return float((t.n / t.n.sum() * (t.mean_pred - t.observed).abs()).sum())


def cluster_bootstrap(evals, cluster_codes, n_boot=300, seed=0, ref=None):
    """Bootstrap by building. `evals`: {model: RankEval} on the same rows; `cluster_codes`: integer
    building code per row. Every model sees the same resamples, so differences to `ref` are paired.

    Returns a long DataFrame: model, metric, point, lo, hi (95% percentile interval), and for
    model != ref also rows with metric 'diff_<m>' = model - ref.
    """
    rng = np.random.default_rng(seed)
    codes = np.asarray(cluster_codes)
    n_clusters = int(codes.max()) + 1
    point = {m: ev.metrics() for m, ev in evals.items()}
    keys = list(next(iter(point.values())).keys())
    draws = {m: {k: np.empty(n_boot) for k in keys} for m in evals}
    for b in range(n_boot):
        mult = np.bincount(rng.integers(0, n_clusters, n_clusters), minlength=n_clusters).astype(np.float64)
        w = mult[codes]
        for m, ev in evals.items():
            r = ev.metrics(w)
            for k in keys:
                draws[m][k][b] = r[k]
    rows = []
    for m in evals:
        for k in keys:
            lo, hi = np.nanpercentile(draws[m][k], [2.5, 97.5])
            rows.append((m, k, point[m][k], lo, hi))
            if ref is not None and m != ref:
                d = draws[m][k] - draws[ref][k]
                lo, hi = np.nanpercentile(d, [2.5, 97.5])
                rows.append((m, f"diff_{k}", point[m][k] - point[ref][k], lo, hi))
    return pd.DataFrame(rows, columns=["model", "metric", "point", "lo", "hi"])
