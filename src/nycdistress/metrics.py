"""Ranking metrics (numpy/pandas only): ROC-AUC, average precision (PR-AUC), precision@k."""
import numpy as np


def roc_auc(y, score):
    """Area under the ROC curve via average ranks (ties count half). NaN if one class is missing."""
    y = np.asarray(y).astype(bool)
    s = np.asarray(score, dtype=float)
    n_pos, n_neg = int(y.sum()), int((~y).sum())
    if n_pos == 0 or n_neg == 0:
        return float("nan")
    order = np.argsort(s, kind="mergesort")
    ranks = np.empty(len(s), dtype=float)
    sorted_s = s[order]
    # average rank within tied groups
    boundaries = np.flatnonzero(np.diff(sorted_s)) + 1
    starts = np.concatenate(([0], boundaries))
    ends = np.concatenate((boundaries, [len(s)]))
    for a, b in zip(starts, ends):
        ranks[order[a:b]] = (a + 1 + b) / 2.0
    return float((ranks[y].sum() - n_pos * (n_pos + 1) / 2.0) / (n_pos * n_neg))


def average_precision(y, score):
    """Average precision = sum_n (R_n - R_{n-1}) P_n over distinct score thresholds (the usual PR-AUC)."""
    y = np.asarray(y).astype(bool)
    s = np.asarray(score, dtype=float)
    n_pos = int(y.sum())
    if n_pos == 0:
        return float("nan")
    order = np.argsort(-s, kind="mergesort")
    y_sorted, s_sorted = y[order], s[order]
    ends = np.concatenate((np.flatnonzero(np.diff(s_sorted)), [len(s) - 1]))  # last index of each tie group
    tp = np.cumsum(y_sorted)[ends]
    fp = (ends + 1) - tp
    precision = tp / (tp + fp)
    recall = tp / n_pos
    return float(np.sum(np.diff(np.concatenate(([0.0], recall))) * precision))


def precision_at_k(y, score, k):
    """Share of positives among the k highest scores (ties broken by input order)."""
    y = np.asarray(y).astype(bool)
    order = np.argsort(-np.asarray(score, dtype=float), kind="mergesort")[:k]
    return float(y[order].mean())
