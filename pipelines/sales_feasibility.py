"""Phase 5 feasibility spike: is there a usable sale panel for an after-the-sale event study?

    python pipelines/sales_feasibility.py        # needs data/raw/dof_sales and data/raw/acris_master (pull_acris.py)

Decision rule, declared before running: the study is feasible only if (a) the source's recent volume is at least 60% of an independent count, and
(b) there are at least 800 plausibly arms-length sales matched to analysis buildings with a full window of 8 quarters before and 8 after.
Findings are written to reports/phase5/. No party names are read or written: the sale panel is building-level.
"""
import json
from pathlib import Path

import duckdb
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
PROC = ROOT / "data" / "processed"
OUT = ROOT / "reports" / "phase5"
# whole-building sales only: condo units, parking spaces and co-op apartments are apartment-level transactions recorded on the building lot
WHOLE_BUILDING = ("03 THREE FAMILY DWELLINGS", "07 RENTALS - WALKUP APARTMENTS", "08 RENTALS - ELEVATOR APARTMENTS", "14 RENTALS - 4-10 UNIT")
MIN_PRICE = 100_000
MIN_PRICE_PER_UNIT = 25_000
PRE, POST = 8, 8
# quarter index 0 = 2018Q1; outcome data (violations, complaints, events) run through 2026Q3 = index 34
LAST_Q = 34


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect()
    q = lambda s: con.execute(s).fetchall()  # noqa: E731
    dof = f"read_parquet('{RAW / 'dof_sales'}/part-*.parquet', union_by_name=true)"
    acr = f"read_parquet('{RAW / 'acris_master'}/part-*.parquet', union_by_name=true)"
    sp = f"read_parquet('{PROC / 'spine.parquet'}')"
    con.execute(f"""CREATE TABLE sales AS
        SELECT lpad(CAST(TRY_CAST(bbl AS BIGINT) AS VARCHAR), 10, '0') AS bbl, CAST(TRY_CAST(sale_date AS TIMESTAMP) AS DATE) AS sale_date,
               TRY_CAST(sale_price AS DOUBLE) AS price, TRY_CAST(residential_units AS INTEGER) AS res_units_sale, building_class_category AS category, nullif(trim(apartment_number), '') AS apt
        FROM {dof} WHERE TRY_CAST(bbl AS BIGINT) IS NOT NULL""")

    # ---------------------------------------------------------------- (a) coverage: ACRIS Master open-data extract vs DOF sales
    cov = q(f"""SELECT y, a.n AS acris_deeds, d.n AS dof_priced_sales, round(100.0 * a.n / d.n, 1) AS acris_pct_of_dof FROM
        (SELECT year(CAST(TRY_CAST(recorded_datetime AS TIMESTAMP) AS DATE)) AS y, count(*) n FROM {acr} GROUP BY 1) a
        JOIN (SELECT year(sale_date) AS y, count(*) n FROM sales WHERE price > 0 GROUP BY 1) d USING (y) WHERE y BETWEEN 2018 AND 2025 ORDER BY y""")
    cov_df = pd.DataFrame(cov, columns=["year", "acris_deed_documents", "dof_priced_sales", "acris_pct_of_dof"])
    cov_df.to_csv(OUT / "acris_vs_dof_coverage.csv", index=False)
    recent = cov_df[cov_df.year >= 2021]
    ratio = float(recent.acris_deed_documents.sum() / recent.dof_priced_sales.sum())

    # ---------------------------------------------------------------- (b) attrition from raw rows to analysis-ready sales
    steps = []
    n0 = q("SELECT count(*) FROM sales")[0][0]
    steps.append(("DOF sale rows, Bronx and Brooklyn, 2016-2025", n0))
    steps.append(("with a positive price", q("SELECT count(*) FROM sales WHERE price > 0")[0][0]))
    steps.append((f"price at least ${MIN_PRICE:,}", q(f"SELECT count(*) FROM sales WHERE price >= {MIN_PRICE}")[0][0]))
    cats = ", ".join(f"'{c}'" for c in WHOLE_BUILDING)
    con.execute(f"""CREATE TABLE matched_all AS SELECT s.*, b.units_residential FROM sales s JOIN (SELECT bbl, unitsres AS units_residential FROM {sp}) b USING (bbl) WHERE s.sale_date >= DATE '2018-01-01'""")
    steps.append(("matched to an analysis building (3+ residential units), sold 2018-2025, ANY transaction type (includes condo units and co-op apartments)", q("SELECT count(*) FROM matched_all")[0][0]))
    con.execute(f"CREATE TABLE matched AS SELECT * FROM matched_all WHERE apt IS NULL AND category IN ({cats})")
    steps.append(("  of these whole-building sales (three-family, rental walk-up or elevator, 4-10 unit rentals; no apartment number)", q("SELECT count(*) FROM matched")[0][0]))
    steps.append(("  of these with a positive price", q("SELECT count(*) FROM matched WHERE price > 0")[0][0]))
    steps.append((f"price at least ${MIN_PRICE:,} and ${MIN_PRICE_PER_UNIT:,} per residential unit (arms-length proxy)", q(f"SELECT count(*) FROM matched WHERE price >= {MIN_PRICE} AND price >= {MIN_PRICE_PER_UNIT} * units_residential")[0][0]))
    con.execute(f"""CREATE TABLE arms AS SELECT bbl, sale_date, price, units_residential,
            CAST(floor((datediff('month', DATE '2018-01-01', CAST(date_trunc('month', sale_date) AS DATE)) + CASE WHEN day(sale_date) > 1 THEN 1 ELSE 0 END + 2) / 3.0) AS INTEGER) AS qs
        FROM matched WHERE price >= {MIN_PRICE} AND price >= {MIN_PRICE_PER_UNIT} * units_residential""")
    # one sale per lot-quarter, then first sale per lot; lots with a second arms-length sale inside the +-8 quarter window are dropped (contaminated)
    con.execute("""CREATE TABLE firsts AS
        SELECT bbl, min(qs) AS q0, count(*) AS n_sales, max(qs) AS q_last FROM (SELECT DISTINCT bbl, qs FROM arms) GROUP BY bbl""")
    steps.append(("distinct lots with at least one such sale", q("SELECT count(*) FROM firsts")[0][0]))
    con.execute(f"""CREATE TABLE cohort AS
        SELECT f.bbl, f.q0 FROM firsts f
        WHERE f.q0 BETWEEN {PRE} AND {LAST_Q - POST}
          AND NOT EXISTS (SELECT 1 FROM (SELECT DISTINCT bbl, qs FROM arms) a WHERE a.bbl = f.bbl AND a.qs <> f.q0 AND a.qs BETWEEN f.q0 - {PRE} AND f.q0 + {POST})""")
    n_full = q("SELECT count(*) FROM cohort")[0][0]
    steps.append((f"first sale with a full window ({PRE} quarters before, {POST} after) and no other sale inside it", n_full))
    n_relaxed = q(f"""SELECT count(*) FROM firsts f WHERE f.q0 BETWEEN 4 AND {LAST_Q - 4}""")[0][0]
    steps.append(("relaxed window (4 before, 4 after), first sales only", n_relaxed))
    never = q(f"""SELECT count(*) FROM {sp} WHERE bbl NOT IN (SELECT bbl FROM sales WHERE price > 0)""")[0][0]
    steps.append(("analysis buildings with no priced sale in 2016-2025 (candidate never-treated controls)", never))
    spine_n = q(f"SELECT count(*) FROM {sp}")[0][0]
    pd.DataFrame(steps, columns=["step", "count"]).to_csv(OUT / "attrition.csv", index=False)

    by_year = pd.DataFrame(q("SELECT year(sale_date) y, count(*) FROM arms GROUP BY 1 ORDER BY 1"), columns=["year", "arms_length_matched_sales"])
    by_year.to_csv(OUT / "arms_length_sales_by_year.csv", index=False)
    cohorts = pd.DataFrame(q("SELECT q0 + 2018 * 4 AS q_abs, count(*) FROM cohort GROUP BY 1 ORDER BY 1"), columns=["quarter_index", "treated_lots"])
    cohorts["quarter"] = [f"{2018 + (i // 4)}Q{i % 4 + 1}" for i in (cohorts.quarter_index - 2018 * 4)]
    cohorts[["quarter", "treated_lots"]].to_csv(OUT / "cohort_sizes.csv", index=False)
    small = int((cohorts.treated_lots < 25).sum())

    feasible_a = ratio >= 0.60
    feasible_b = n_full >= 800
    out = dict(acris_master_open_data_vs_dof_ratio_2021_2025=ratio, acris_passes_coverage_rule=feasible_a,
               dof_full_window_sales=n_full, dof_passes_volume_rule=feasible_b, spine_lots=spine_n, never_sold_controls=never,
               quarterly_cohorts=len(cohorts), cohorts_under_25=small,
               decision="ACRIS Master extract: NOT usable (coverage). DOF sales panel: feasible" if feasible_b else "NOT feasible",
               rule="source volume >= 60% of an independent count AND >= 800 arms-length matched sales with a full 8+8 quarter window")
    (OUT / "feasibility.json").write_text(json.dumps(out, indent=2, default=float))
    print(cov_df.to_string(index=False))
    for s, c in steps:
        print(f"{c:>9,}  {s}")
    print(json.dumps(out, indent=2, default=float))


if __name__ == "__main__":
    main()
