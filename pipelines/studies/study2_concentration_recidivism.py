"""Study 2: Extreme Concentration, Taxpayer OMO Dollars, & 7-Winter Heat Recidivism.

Quantifies:
  2a. Building-level Lorenz / Gini / top-0.5%, 1%, 5%, 10% concentration curves BOTH unweighted
      (share of buildings) AND unit-weighted (excess concentration beyond building size!) across
      Class C hazards, open Class C, OMO taxpayer dollars, evictions, litigations, and winter heat complaints.
  2b. 7-Winter Heat & Hot Water Recidivism (Winters 2018-19 through 2024-25):
      distribution of failed winters (0..7), Markov year-to-year persistence P(fail t+1 | k prior failed winters),
      borough & community-district hotspots, and the Enforcement Gap (% of 6-7 winter chronic offenders never
      in AEP or HPD Heat & Hot Water litigation).
  2c. Taxpayer Emergency Repair (OMO) Anatomy & Recidivism:
      work-type breakdown, yearly spend 2018-2025, repeat-recipient concentration (share of dollars going to
      buildings with 5+, 10+, 25+ OMO orders), and overlap with expired registrations.

Outputs:
  reports/studies/study2_*.csv, reports/studies/study2_summary.json
  data/processed/studies/building_distress_profile.parquet (gitignored, per-BBL summary for map)
"""
from __future__ import annotations

import json
import time
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
RAW = ROOT / "data" / "raw"
PROC = ROOT / "data" / "processed"
OUT_REP = ROOT / "reports" / "studies"
OUT_PROC = PROC / "studies"


def gini(x: np.ndarray, weights: np.ndarray | None = None) -> float:
    x = np.asarray(x, dtype=float)
    if x.sum() <= 0:
        return 0.0
    if weights is None:
        s = np.sort(x)
        n = len(s)
        cum = np.cumsum(s)
        return float((n + 1 - 2 * np.sum(cum) / cum[-1]) / n)
    w = np.asarray(weights, dtype=float)
    rate = x / np.maximum(w, 1e-9)
    order = np.argsort(rate)
    w_s = w[order]
    x_s = x[order]
    cw = np.cumsum(w_s) / np.sum(w_s)
    cx = np.cumsum(x_s) / np.sum(x_s)
    cw0 = np.concatenate(([0.0], cw))
    cx0 = np.concatenate(([0.0], cx))
    area = np.sum((cw0[1:] - cw0[:-1]) * (cx0[1:] + cx0[:-1]) / 2.0)
    return float(1.0 - 2.0 * area)


def main():
    t0 = time.time()
    OUT_REP.mkdir(parents=True, exist_ok=True)
    OUT_PROC.mkdir(parents=True, exist_ok=True)

    con = duckdb.connect(str(PROC / "marts.duckdb"), read_only=True)
    con.execute("SET threads=6")

    # ------------------------------------------------------------------ 2a. Building-level totals & concentration
    print("[Study 2a] Computing building distress profiles & concentration...", flush=True)
    b = con.sql("""
        WITH v AS (
            SELECT bbl,
                   count(*) AS viol_all,
                   count(*) FILTER (WHERE violation_class = 'C') AS viol_c,
                   count(*) FILTER (WHERE status = 'Open' AND violation_class = 'C') AS open_c,
                   count(*) FILTER (WHERE status = 'Open') AS open_all
            FROM hpd_violations
            WHERE inspection_date >= DATE '2018-01-01'
            GROUP BY 1
        ),
        o AS (
            SELECT bbl,
                   count(*) AS omo_n,
                   sum(award_amount) AS omo_usd,
                   sum(award_amount) FILTER (WHERE work_type = 'HEAT') AS omo_heat_usd,
                   sum(award_amount) FILTER (WHERE work_type = 'DELEAD') AS omo_lead_usd
            FROM omo_charges
            WHERE created_date >= DATE '2018-01-01' AND award_amount > 0
            GROUP BY 1
        ),
        e AS (SELECT bbl, count(*) AS evict_n FROM evictions WHERE executed_date >= DATE '2018-01-01' GROUP BY 1),
        l AS (
            SELECT bbl,
                   count(*) AS litig_n,
                   count(*) FILTER (WHERE case_type = 'Heat and Hot Water') AS litig_heat_n
            FROM litigations WHERE opened_date >= DATE '2018-01-01' GROUP BY 1
        ),
        a AS (SELECT bbl, count(*) AS aep_n FROM aep_programs GROUP BY 1),
        hw AS (
            SELECT bbl,
                   CASE WHEN month(received_date) >= 10 THEN year(received_date) ELSE year(received_date) - 1 END AS winter_yr,
                   count(*) AS probs
            FROM hpd_complaints
            WHERE major_category = 'HEAT/HOT WATER'
              AND (month(received_date) >= 10 OR month(received_date) <= 5)
              AND received_date BETWEEN DATE '2018-10-01' AND DATE '2025-05-31'
            GROUP BY 1, 2
        ),
        hw_b AS (
            SELECT bbl,
                   count(*) FILTER (WHERE probs >= 3) AS bad_winters_3plus,
                   count(*) FILTER (WHERE probs >= 1) AS any_winters,
                   sum(probs) AS hw_probs_7w
            FROM hw GROUP BY 1
        )
        SELECT b.bbl, b.borough, b.community_district, b.units_residential, b.year_built, b.building_class,
               coalesce(v.viol_all, 0) AS viol_all,
               coalesce(v.viol_c, 0) AS viol_c,
               coalesce(v.open_c, 0) AS open_c,
               coalesce(v.open_all, 0) AS open_all,
               coalesce(o.omo_n, 0) AS omo_n,
               coalesce(o.omo_usd, 0.0) AS omo_usd,
               coalesce(o.omo_heat_usd, 0.0) AS omo_heat_usd,
               coalesce(o.omo_lead_usd, 0.0) AS omo_lead_usd,
               coalesce(e.evict_n, 0) AS evict_n,
               coalesce(l.litig_n, 0) AS litig_n,
               coalesce(l.litig_heat_n, 0) AS litig_heat_n,
               coalesce(a.aep_n, 0) AS aep_n,
               coalesce(hw_b.bad_winters_3plus, 0) AS bad_winters_3plus,
               coalesce(hw_b.any_winters, 0) AS any_winters,
               coalesce(hw_b.hw_probs_7w, 0) AS hw_probs_7w
        FROM buildings b
        LEFT JOIN v USING (bbl) LEFT JOIN o USING (bbl) LEFT JOIN e USING (bbl)
        LEFT JOIN l USING (bbl) LEFT JOIN a USING (bbl) LEFT JOIN hw_b USING (bbl)
    """).df()

    # Concentration metrics (both building-share and unit-weighted excess concentration)
    metrics = [
        ("viol_c", "Class C violations (2018+)"),
        ("open_c", "Open Class C violations"),
        ("omo_usd", "Taxpayer OMO spend ($)"),
        ("evict_n", "Executed evictions (2018+)"),
        ("litig_n", "HPD litigations (2018+)"),
        ("hw_probs_7w", "Winter heat/hot-water complaints (7 winters)"),
    ]
    conc_rows = []
    tot_u = b["units_residential"].sum()
    n_b = len(b)
    for col, label in metrics:
        tot = b[col].sum()
        g_bldg = gini(b[col].to_numpy())
        g_unit = gini(b[col].to_numpy(), b["units_residential"].to_numpy())
        # Rank by count (building-share) and by per-unit rate (unit-weighted share)
        by_cnt = b.sort_values(col, ascending=False)
        by_rate = b.assign(_rate=b[col] / b["units_residential"].clip(lower=1)).sort_values("_rate", ascending=False)
        cum_u = by_rate["units_residential"].cumsum().to_numpy()

        for pct in [0.005, 0.01, 0.02, 0.05, 0.10]:
            k = max(1, int(round(n_b * pct)))
            top_b = by_cnt.iloc[:k]
            # Top pct of UNITS ranked by per-unit rate (pure excess concentration controlling for building size!)
            u_cut = np.searchsorted(cum_u, tot_u * pct) + 1
            top_u = by_rate.iloc[:u_cut]
            conc_rows.append({
                "metric": col,
                "label": label,
                "total": round(float(tot), 1),
                "top_pct": pct * 100,
                "n_buildings_top": k,
                "share_by_top_bldgs_pct": round(100.0 * top_b[col].sum() / tot, 2),
                "units_in_top_bldgs_pct": round(100.0 * top_b["units_residential"].sum() / tot_u, 2),
                "share_by_top_units_rate_pct": round(100.0 * top_u[col].sum() / tot, 2),
                "gini_building": round(g_bldg, 4),
                "gini_unit_weighted": round(g_unit, 4),
            })
    conc_df = pd.DataFrame(conc_rows)
    conc_df.to_csv(OUT_REP / "study2_concentration.csv", index=False)

    # ------------------------------------------------------------------ 2b. 7-Winter Heat Recidivism & Markov Persistence
    print("[Study 2b] Computing 7-winter heat recidivism & enforcement gap...", flush=True)
    hw_panel = con.sql("""
        WITH hw AS (
            SELECT bbl,
                   CASE WHEN month(received_date) >= 10 THEN year(received_date) ELSE year(received_date) - 1 END AS winter_yr,
                   count(*) AS probs
            FROM hpd_complaints
            JOIN buildings USING (bbl)
            WHERE major_category = 'HEAT/HOT WATER'
              AND (month(received_date) >= 10 OR month(received_date) <= 5)
              AND received_date BETWEEN DATE '2018-10-01' AND DATE '2025-05-31'
            GROUP BY 1, 2
        )
        SELECT bbl, winter_yr, probs FROM hw
    """).df()

    # Distribution by bad_winters (0..7)
    hw_dist = b.groupby("bad_winters_3plus").agg(
        buildings=("bbl", "count"),
        units=("units_residential", "sum"),
        total_hw_probs=("hw_probs_7w", "sum"),
        omo_heat_usd=("omo_heat_usd", "sum"),
        pct_ever_aep=("aep_n", lambda x: round(100.0 * (x > 0).mean(), 2)),
        pct_ever_heat_litig=("litig_heat_n", lambda x: round(100.0 * (x > 0).mean(), 2)),
        pct_ever_any_litig=("litig_n", lambda x: round(100.0 * (x > 0).mean(), 2)),
    ).reset_index()
    hw_dist["pct_of_buildings"] = (100.0 * hw_dist["buildings"] / len(b)).round(2)
    hw_dist["pct_of_units"] = (100.0 * hw_dist["units"] / tot_u).round(2)
    hw_dist["pct_of_all_hw_probs"] = (100.0 * hw_dist["total_hw_probs"] / hw_dist["total_hw_probs"].sum()).round(2)
    hw_dist.to_csv(OUT_REP / "study2_heat_recidivism.csv", index=False)

    # Markov persistence: across winters 2019..2024 (predicting winter t from prior failed winters 2018..t-1)
    piv = hw_panel.pivot(index="bbl", columns="winter_yr", values="probs").reindex(b["bbl"]).fillna(0)
    winters = sorted(piv.columns)  # 2018..2024 (7 winters)
    fail = (piv >= 3).astype(int)
    markov_rows = []
    # Predict final winter (2024-25) from count of prior 6 failed winters (2018-23)
    prior6 = fail[winters[:6]].sum(axis=1)
    y_24 = fail[winters[6]]
    for k in range(7):
        m = prior6 == k
        markov_rows.append({
            "prior_failed_winters_of_6": k,
            "buildings": int(m.sum()),
            "pct_fail_winter_2024_25": round(100.0 * y_24[m].mean(), 2),
            "avg_probs_2024_25": round(float(piv.loc[m, winters[6]].mean()), 2),
            "share_of_2024_25_probs_pct": round(100.0 * piv.loc[m, winters[6]].sum() / piv[winters[6]].sum(), 2),
        })
    markov_df = pd.DataFrame(markov_rows)
    markov_df.to_csv(OUT_REP / "study2_heat_markov_persistence.csv", index=False)

    # ------------------------------------------------------------------ 2c. OMO Emergency Repair Spend & Recidivism
    print("[Study 2c] Analyzing taxpayer OMO emergency repair spending & recidivism...", flush=True)
    omo_work = con.sql("""
        SELECT work_type,
               count(*) AS orders,
               count(DISTINCT bbl) AS buildings,
               round(sum(award_amount) / 1e6, 2) AS total_M,
               round(avg(award_amount), 0) AS avg_order_usd,
               round(median(award_amount), 0) AS median_order_usd
        FROM omo_charges
        JOIN buildings USING (bbl)
        WHERE created_date >= DATE '2018-01-01' AND award_amount > 0
        GROUP BY 1 ORDER BY 4 DESC
    """).df()
    omo_work.to_csv(OUT_REP / "study2_omo_by_worktype.csv", index=False)

    omo_yr = con.sql("""
        SELECT year(created_date) AS yr,
               count(*) AS orders,
               count(DISTINCT bbl) AS buildings,
               round(sum(award_amount) / 1e6, 2) AS total_M
        FROM omo_charges
        JOIN buildings USING (bbl)
        WHERE created_date >= DATE '2018-01-01' AND award_amount > 0
        GROUP BY 1 ORDER BY 1
    """).df()
    omo_yr.to_csv(OUT_REP / "study2_omo_by_year.csv", index=False)

    # Repeat OMO recipients
    omo_rec = b[b["omo_n"] > 0].copy()
    omo_rec["omo_tier"] = pd.cut(
        omo_rec["omo_n"], bins=[0, 1, 4, 9, 24, 99, 100000],
        labels=["1_order", "2-4_orders", "5-9_orders", "10-24_orders", "25-99_orders", "100plus_orders"]
    )
    omo_tier_tbl = omo_rec.groupby("omo_tier", observed=True).agg(
        buildings=("bbl", "count"),
        orders=("omo_n", "sum"),
        total_M=("omo_usd", lambda x: round(x.sum() / 1e6, 2)),
        pct_of_omo_dollars=("omo_usd", lambda x: round(100.0 * x.sum() / omo_rec["omo_usd"].sum(), 2)),
        avg_units=("units_residential", lambda x: round(x.mean(), 1)),
    ).reset_index()
    omo_tier_tbl.to_csv(OUT_REP / "study2_omo_recidivism.csv", index=False)

    # Save building-level distress profile (for map + Building Report Card!)
    b.to_parquet(OUT_PROC / "building_distress_profile.parquet", index=False)

    print("\n=== Study 2 Headline: Concentration (Top 1% Buildings vs Top 1% Unit-Rate) ===")
    print(conc_df[conc_df["top_pct"] == 1.0][["metric", "share_by_top_bldgs_pct", "units_in_top_bldgs_pct", "share_by_top_units_rate_pct", "gini_unit_weighted"]].to_string(index=False))
    print("\n=== Study 2 Headline: 7-Winter Heat Recidivism ===")
    print(hw_dist[["bad_winters_3plus", "buildings", "pct_of_buildings", "pct_of_all_hw_probs", "pct_ever_aep", "pct_ever_heat_litig"]].to_string(index=False))
    print("\n=== Study 2 Headline: Heat Markov Persistence into Winter 2024-25 ===")
    print(markov_df.to_string(index=False))
    print("\n=== Study 2 Headline: OMO Recidivism ===")
    print(omo_tier_tbl.to_string(index=False))

    summary = {
        "study": "Study 2: Extreme Concentration, OMO Spending & 7-Winter Heat Recidivism",
        "elapsed_sec": round(time.time() - t0, 1),
        "spine_omo_2018plus_M": round(float(b["omo_usd"].sum() / 1e6), 2),
        "chronic_7winter_heat_bldgs": int((b["bad_winters_3plus"] == 7).sum()),
        "chronic_7winter_heat_share_pct": float(hw_dist.loc[hw_dist["bad_winters_3plus"] == 7, "pct_of_all_hw_probs"].iloc[0]),
    }
    (OUT_REP / "study2_summary.json").write_text(json.dumps(summary, indent=2))
    con.close()
    print(f"[Study 2] Done in {time.time()-t0:.1f}s", flush=True)


if __name__ == "__main__":
    main()
