"""Regenerate the numeric tables in docs/labels_and_features.md from data/processed/*.parquet.

The doc keeps its hand-written text and replaces only what is between the GENERATED markers.

    python pipelines/report_features.py          # (or `make report`)
"""
import json
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parents[1]
PROC = ROOT / "data" / "processed"
DOC = ROOT / "docs" / "labels_and_features.md"
BEGIN, END = "<!-- BEGIN GENERATED -->", "<!-- END GENERATED -->"
LABELS = ["label_vacate", "label_aep", "label_omo", "label_litigation", "label_serious_any"]
GROUPS = [("meta_", "meta (flags)"), ("static_", "static PLUTO"), ("viol_", "viol_ HPD violations (mixed provenance)"),
          ("loud_", "loud_ complaint-driven"), ("evict_", "evict_ evictions"), ("dob_", "dob_ DOB violations"),
          ("prior_", "prior_ earlier city/court events")]


def table(headers, rows):
    out = ["| " + " | ".join(headers) + " |", "|" + "|".join("---" for _ in headers) + "|"]
    out += ["| " + " | ".join(str(c) for c in r) + " |" for r in rows]
    return "\n".join(out)


def pct(x, digits=2):
    return f"{100 * x:.{digits}f}%"


def main():
    con = duckdb.connect()
    F, L, S = (f"read_parquet('{PROC / n}.parquet')" for n in ("features", "labels", "spine"))
    q = lambda s: con.sql(s).fetchall()  # noqa: E731
    info = json.loads((PROC / "build_info.json").read_text())
    p = info["params"]
    out = []

    n_feat, n_lots, n_snap = q(f"SELECT count(*), count(DISTINCT bbl), count(DISTINCT snapshot_date) FROM {F}")[0]
    cols = [r[0] for r in q(f"DESCRIBE SELECT * FROM {F}")]
    out.append(f"Built {info['built_at']} with snapshots {p['first_snapshot']} to {p['last_snapshot']} (quarterly), "
               f"data cutoff {p['data_cutoff']}. Build time: {sum(info['timings_s'].values()):.0f} s "
               f"({', '.join(f'{k} {v}s' for k, v in info['timings_s'].items())}).\n")
    out.append("### Row counts\n")
    by_b = q(f"SELECT s.borough, count(DISTINCT f.bbl), count(*) FROM {F} f JOIN {S} s USING (bbl) GROUP BY 1 ORDER BY 1")
    rows = [("spine lots (Bronx+Brooklyn, 3+ residential units)", f"{q(f'SELECT count(*) FROM {S}')[0][0]:,}"),
            ("snapshots", n_snap), ("bbl x snapshot rows (features = labels)", f"{n_feat:,}"),
            ("distinct lots appearing in at least one snapshot", f"{n_lots:,}"), ("feature columns (excl. keys)", len(cols) - 2)]
    rows += [(f"  borough {b}: lots / rows", f"{lots:,} / {n:,}") for b, lots, n in by_b]
    out.append(table(["quantity", "value"], rows) + "\n")

    out.append("### Feature columns by group\n")
    rows = []
    for prefix, label in GROUPS:
        gc = [c for c in cols if c.startswith(prefix)]
        rows.append((label, len(gc), ", ".join(gc) if len(gc) <= 14 else ", ".join(gc[:14]) + ", ..."))
    out.append(table(["group", "columns", "names"], rows) + "\n")

    out.append("### Label prevalence, overall and by borough\n")
    ov = q(f"SELECT {', '.join(f'avg({lb})' for lb in LABELS)}, avg(label_loud_complaints_next12) FROM {L}")[0]
    rows = [("all", f"{n_feat:,}", *[pct(v) for v in ov[:-1]], f"{ov[-1]:.2f}")]
    for b in ("BK", "BX"):
        r = q(f"SELECT count(*), {', '.join(f'avg(l.{x})' for x in LABELS)}, avg(l.label_loud_complaints_next12) FROM {L} l JOIN {S} s USING (bbl) WHERE s.borough = '{b}'")[0]
        rows.append((b, f"{r[0]:,}", *[pct(v) for v in r[1:-1]], f"{r[-1]:.2f}"))
    out.append(table(["slice", "rows", "vacate", "aep", "omo", "litigation", "serious_any", "mean complaint problems next 12m"], rows) + "\n")

    out.append("### Label prevalence per snapshot\n")
    rows = []
    for r in q(f"SELECT snapshot_date, count(*), {', '.join(f'avg({lb})' for lb in LABELS)}, avg(label_loud_complaints_next12) FROM {L} GROUP BY 1 ORDER BY 1"):
        rows.append((r[0], f"{r[1]:,}", *[pct(v) for v in r[2:-1]], f"{r[-1]:.2f}"))
    out.append(table(["snapshot", "rows", "vacate", "aep", "omo", "litigation", "serious_any", "mean complaint problems next 12m"], rows) + "\n")

    out.append("### Missing-by-design windows (NULL share by snapshot year)\n")
    out.append("A window that reaches back before the source's first covered date is NULL, not 0.\n")
    rows = q(f"""SELECT year(snapshot_date), round(avg((viol_n_36m IS NULL)::INT), 2), round(avg((loud_prob_n_36m IS NULL)::INT), 2),
                 round(avg((loud_311_n_12m IS NULL)::INT), 2), round(avg((loud_311_n_36m IS NULL)::INT), 2),
                 round(avg((prior_litig_months_since IS NULL)::INT), 2), round(avg((prior_omo_months_since IS NULL)::INT), 2)
                 FROM {F} GROUP BY 1 ORDER BY 1""")
    out.append(table(["year", "viol_*_36m", "loud_*_36m", "loud_311_*_12m", "loud_311_*_36m", "prior_litig_months_since (no earlier event)",
                      "prior_omo_months_since (no earlier event)"], rows) + "\n")

    bp = PROC / "baseline_smoke.json"
    if bp.exists():
        b = json.loads(bp.read_text())
        out.append("### Smoke baseline (SANITY CHECK ONLY, NOT A MODEL RESULT)\n")
        out.append("Rule: score = HPD violations in the prior 12 months (`viol_n_12m`), nothing fitted. "
                   "Target `label_serious_any`, last two snapshots.\n")
        rows = [(r["snapshot"], r["score"], f"{r['base_rate']:.4f}", f"{r['roc_auc']:.4f}", f"{r['pr_auc']:.4f}",
                 f"{r['precision_at_top1pct']:.4f}") for r in b["results"]]
        out.append(table(["snapshot", "score", "base rate", "ROC-AUC", "PR-AUC", "precision at top 1%"], rows) + "\n")
        out.append("The same baseline score against each label separately:\n")
        rows = [(r["snapshot"], r["label"], f"{r['base_rate']:.4f}", f"{r['roc_auc']:.4f}", f"{r['pr_auc']:.4f}") for r in b["per_label"]]
        out.append(table(["snapshot", "label", "base rate", "ROC-AUC", "PR-AUC"], rows) + "\n")

    block = f"{BEGIN}\n\n" + "\n".join(out) + f"\n{END}"
    text = DOC.read_text()
    if BEGIN in text:
        text = text[:text.index(BEGIN)] + block + text[text.index(END) + len(END):]
    else:
        text += "\n" + block + "\n"
    DOC.write_text(text)
    print(f"updated {DOC.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
