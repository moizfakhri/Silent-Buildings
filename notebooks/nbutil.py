"""Helpers for the narrative notebooks. They read only committed outputs (reports/, docs/, app/web/data), never data/raw or data/processed."""
import re
from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
REPORTS = ROOT / "reports"
DOCS = ROOT / "docs"

plt.rcParams.update({"figure.dpi": 110, "axes.spines.top": False, "axes.spines.right": False, "axes.grid": True, "grid.alpha": 0.25, "font.size": 9})
BLUE, RED, GREY, GREEN = "#1f6f8b", "#b5472f", "#8a8f94", "#4c8a4c"


def md_table(path, after, nth=0):
    """The nth markdown table that follows the first line containing `after` (a heading or sentence) in a markdown file."""
    lines = Path(path).read_text().splitlines()
    start = next(i for i, ln in enumerate(lines) if after in ln)
    tables, i = [], start
    while i < len(lines):
        if lines[i].startswith("|") and i + 1 < len(lines) and re.match(r"^\|[\s\-:|]+\|$", lines[i + 1]):
            j = i
            while j < len(lines) and lines[j].startswith("|"):
                j += 1
            rows = [[c.strip() for c in ln.strip().strip("|").split("|")] for ln in lines[i:j] if not re.match(r"^\|[\s\-:|]+\|$", ln)]
            tables.append(pd.DataFrame(rows[1:], columns=rows[0]))
            i = j
        else:
            i += 1
    return tables[nth]


def num(s):
    """'12,345' -> 12345.0, '6.13%' -> 6.13, otherwise NaN."""
    try:
        return float(str(s).replace(",", "").replace("%", ""))
    except ValueError:
        return float("nan")


def forest(ax, labels, est, lo, hi, ref=1.0, color=BLUE, xlabel=""):
    y = list(range(len(labels)))[::-1]
    ax.errorbar(est, y, xerr=[[e - l for e, l in zip(est, lo)], [h - e for e, h in zip(est, hi)]], fmt="o", color=color, capsize=3, ms=4)
    ax.axvline(ref, color=GREY, lw=1, ls="--")
    ax.set_yticks(y)
    ax.set_yticklabels(labels)
    ax.set_xlabel(xlabel)
