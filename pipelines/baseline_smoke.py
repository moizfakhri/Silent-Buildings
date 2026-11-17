"""SANITY CHECK ONLY, NOT A MODEL RESULT.

Scores the naive rule "number of HPD violations in the prior 12 months" against label_serious_any on
the last two snapshots, to confirm that features and labels line up and carry signal. Nothing is
fitted or tuned. A real model must beat this baseline out of time (Phase 3).

    python pipelines/baseline_smoke.py        # reads data/processed/features|labels.parquet
"""
import json
from pathlib import Path

import duckdb

from nycdistress.metrics import average_precision, precision_at_k, roc_auc

PROC = Path(__file__).resolve().parents[1] / "data" / "processed"
SCORES = {  # name -> SQL expression over the features table
    "viol_n_12m (the baseline)": "f.viol_n_12m",
    "loud_prob_n_12m (complaints, for context)": "f.loud_prob_n_12m",
    "prior_omo_n_12m (prior repairs, for context)": "f.prior_omo_n_12m",
    "constant (no information)": "0",
}


def main():
    con = duckdb.connect()
    f = f"read_parquet('{PROC / 'features.parquet'}')"
    lab = f"read_parquet('{PROC / 'labels.parquet'}')"
    snaps = [r[0] for r in con.sql(f"SELECT DISTINCT snapshot_date FROM {lab} ORDER BY 1 DESC LIMIT 2").fetchall()]
    out = {"note": "sanity check only, not a model result", "snapshots": [str(s) for s in snaps], "results": []}
    for s in sorted(snaps):
        for name, expr in SCORES.items():
            df = con.sql(f"""SELECT {expr} AS score, l.label_serious_any AS y FROM {f} f
                             JOIN {lab} l USING (bbl, snapshot_date) WHERE f.snapshot_date = DATE '{s}'""").df()
            df["score"] = df["score"].fillna(0)
            k = max(1, len(df) // 100)
            out["results"].append(dict(
                snapshot=str(s), score=name, rows=len(df), base_rate=round(float(df.y.mean()), 4),
                roc_auc=round(roc_auc(df.y, df.score), 4), pr_auc=round(average_precision(df.y, df.score), 4),
                precision_at_top1pct=round(precision_at_k(df.y, df.score, k), 4)))
    # the same baseline score against each label separately (serious_any is mostly OMO charges)
    out["per_label"] = []
    for s in sorted(snaps):
        for label in ("label_vacate", "label_aep", "label_omo", "label_litigation", "label_serious_any"):
            df = con.sql(f"""SELECT f.viol_n_12m AS score, l.{label} AS y FROM {f} f
                             JOIN {lab} l USING (bbl, snapshot_date) WHERE f.snapshot_date = DATE '{s}'""").df()
            df["score"] = df["score"].fillna(0)
            out["per_label"].append(dict(snapshot=str(s), label=label, base_rate=round(float(df.y.mean()), 4),
                                         roc_auc=round(roc_auc(df.y, df.score), 4),
                                         pr_auc=round(average_precision(df.y, df.score), 4)))
    (PROC / "baseline_smoke.json").write_text(json.dumps(out, indent=2))
    print("SANITY CHECK ONLY, NOT A MODEL RESULT")
    for r in out["results"]:
        print(f"{r['snapshot']}  {r['score']:<46} base {r['base_rate']:.4f}  AUC {r['roc_auc']:.4f}  "
              f"PR-AUC {r['pr_auc']:.4f}  P@top1% {r['precision_at_top1pct']:.4f}")
    print("\nviol_n_12m against each label separately:")
    for r in out["per_label"]:
        print(f"{r['snapshot']}  {r['label']:<20} base {r['base_rate']:.4f}  AUC {r['roc_auc']:.4f}  PR-AUC {r['pr_auc']:.4f}")


if __name__ == "__main__":
    main()
