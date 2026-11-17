"""Phase 7: build the DuckDB marts the LLM layer queries (data/processed/marts.duckdb, gitignored).

    python pipelines/build_marts.py        # about 2 minutes

Tables (documented column by column in src/nycdistress/llm/schema.py):
  buildings, building_snapshots, hpd_violations, hpd_complaints, omo_charges, litigations, vacate_orders, aep_programs,
  dob_violations, evictions.
Deliberately NOT included: litigation respondents (owner names), eviction marshals and court index numbers, registration
contacts. Rows are restricted to the analysis lots (Bronx and Brooklyn residential, 3+ units). The database is opened read-only
with external access disabled by the SQL sandbox, so a model-written query cannot read files or change anything.
"""
import time
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
PROC = ROOT / "data" / "processed"
DB = PROC / "marts.duckdb"


def raw(name):
    return f"read_parquet('{RAW / name}/part-*.parquet', union_by_name=true)"


MACROS = """
CREATE OR REPLACE MACRO norm_bbl(x) AS CAST(TRY_CAST(x AS DOUBLE) AS BIGINT);
CREATE OR REPLACE MACRO build_bbl(boro, blk, lt) AS
  TRY_CAST(boro AS BIGINT) * 1000000000 + TRY_CAST(blk AS BIGINT) * 10000 + TRY_CAST(lt AS BIGINT);
CREATE OR REPLACE MACRO d_iso(x) AS CAST(TRY_CAST(x AS TIMESTAMP) AS DATE);
CREATE OR REPLACE MACRO bbl10(x) AS lpad(CAST(x AS VARCHAR), 10, '0');
"""


def main():
    t0 = time.time()
    if DB.exists():
        DB.unlink()
    con = duckdb.connect(str(DB))
    con.execute("SET memory_limit='8GB'")
    con.execute(f"SET temp_directory='{ROOT / 'data' / 'interim' / 'duckdb_tmp'}'")
    con.execute(MACROS)
    sp = f"read_parquet('{PROC / 'spine.parquet'}')"
    con.execute(f"""CREATE TABLE buildings AS
        SELECT bbl, CASE borough WHEN 'BK' THEN 'Brooklyn' ELSE 'Bronx' END AS borough, community_district, unitsres AS units_residential,
               unitstotal AS units_total, bldgclass AS building_class, landuse AS land_use, yearbuilt AS year_built, numfloors AS floors,
               lotarea AS lot_area_sqft, bldgarea AS building_area_sqft
        FROM {sp}""")
    af = f"read_parquet('{PROC / 'phase4' / 'analysis_frame.parquet'}')"
    p3 = f"read_parquet('{PROC / 'scores_phase3.parquet'}')"
    con.execute(f"""CREATE TABLE building_snapshots AS
        SELECT a.bbl, CAST(a.snapshot_date AS DATE) AS snapshot_date, CASE a.static_borough WHEN 'BK' THEN 'Brooklyn' ELSE 'Bronx' END AS borough,
               a.community_district, CAST(a.static_unitsres AS INTEGER) AS units_residential, a.fold,
               s.score AS predicted_risk, a.p_hat AS predicted_condition, a.loudness AS complaint_loudness, a.gap_rank AS complaint_gap,
               a.silent AS gap_top_decile, a.silent_resid AS gap_model_residual_flag, a.access_blocked,
               CAST(a.viol_open_n AS INTEGER) AS open_violations, CAST(a.viol_n_12m AS INTEGER) AS violations_12m,
               CAST(a.viol_c_n_12m AS INTEGER) AS class_c_violations_12m, CAST(a.loud_prob_n_12m AS INTEGER) AS complaint_problems_12m,
               CAST(a.loud_311_n_12m AS INTEGER) AS requests_311_12m, CAST(a.evict_n_12m AS INTEGER) AS evictions_12m,
               CAST(a.dob_n_12m AS INTEGER) AS dob_violations_12m, CAST(a.prior_omo_n AS INTEGER) AS prior_omo_charges,
               CAST(a.prior_litig_n AS INTEGER) AS prior_litigations, CAST(a.prior_vacate_n AS INTEGER) AS prior_vacate_orders,
               CAST(a.prior_aep_n AS INTEGER) AS prior_aep_selections, a.loud_nacc_share_12m AS no_access_share_12m,
               CAST(a.loud_closed_n_12m AS INTEGER) AS closed_problems_12m,
               CAST(a.label_serious_any AS BOOLEAN) AS serious_event_next12, CAST(a.label_vacate_or_dobhaz_core AS BOOLEAN) AS vacate_or_dob_hazard_next12,
               CAST(a.label_omo AS BOOLEAN) AS omo_charge_next12, CAST(a.label_litigation AS BOOLEAN) AS litigation_next12,
               CAST(a.label_loud_complaints_next12 AS INTEGER) AS complaint_problems_next12
        FROM {af} a JOIN {p3} s ON s.bbl = a.bbl AND CAST(s.snapshot_date AS DATE) = CAST(a.snapshot_date AS DATE)""")
    print(f"buildings, building_snapshots ({time.time() - t0:.0f}s)", flush=True)

    con.execute(f"""CREATE TABLE hpd_violations AS
        SELECT CAST(violationid AS BIGINT) AS violation_id, bbl10(COALESCE(norm_bbl(bbl), build_bbl(boroid, block, lot))) AS bbl,
               d_iso(inspectiondate) AS inspection_date, class AS violation_class, CAST(ordernumber AS INTEGER) AS order_number,
               novdescription AS description, violationstatus AS status, currentstatus AS current_status, d_iso(currentstatusdate) AS current_status_date
        FROM {raw('hpd_violations')}
        WHERE bbl10(COALESCE(norm_bbl(bbl), build_bbl(boroid, block, lot))) IN (SELECT bbl FROM buildings)""")
    con.execute(f"""CREATE TABLE hpd_complaints AS
        SELECT CAST(problem_id AS BIGINT) AS problem_id, TRY_CAST(complaint_id AS BIGINT) AS complaint_id,
               bbl10(COALESCE(norm_bbl(bbl), build_bbl(CASE borough WHEN 'BRONX' THEN 2 WHEN 'BROOKLYN' THEN 3 END, block, lot))) AS bbl,
               d_iso(received_date) AS received_date, (type IN ('EMERGENCY', 'IMMEDIATE EMERGENCY')) AS is_emergency, major_category, minor_category,
               problem_status, d_iso(problem_status_date) AS problem_status_date,
               COALESCE(status_description ILIKE '%not able to gain access%', FALSE) AS closed_no_access
        FROM {raw('hpd_complaints')}
        WHERE bbl10(COALESCE(norm_bbl(bbl), build_bbl(CASE borough WHEN 'BRONX' THEN 2 WHEN 'BROOKLYN' THEN 3 END, block, lot))) IN (SELECT bbl FROM buildings)""")
    con.execute(f"""CREATE TABLE omo_charges AS
        SELECT CAST(omoid AS BIGINT) AS omo_id, bbl10(COALESCE(norm_bbl(bbl), build_bbl(boro_id, block, lot))) AS bbl, d_iso(omocreatedate) AS created_date,
               worktypegeneral AS work_type, omostatusreason AS status_reason, (isaep = 'AEP') AS is_aep, TRY_CAST(omoawardamount AS DOUBLE) AS award_amount
        FROM {raw('hpd_omo_charges')}
        WHERE bbl10(COALESCE(norm_bbl(bbl), build_bbl(boro_id, block, lot))) IN (SELECT bbl FROM buildings)""")
    con.execute(f"""CREATE TABLE litigations AS
        SELECT CAST(litigationid AS BIGINT) AS litigation_id, bbl10(norm_bbl(bbl)) AS bbl, d_iso(caseopendate) AS opened_date, casetype AS case_type,
               casestatus AS case_status, findingofharassment AS harassment_finding
        FROM {raw('hpd_litigations')} WHERE bbl10(norm_bbl(bbl)) IN (SELECT bbl FROM buildings)""")
    con.execute(f"""CREATE TABLE vacate_orders AS
        SELECT bbl10(norm_bbl(bbl)) AS bbl, CAST(vacate_order_number AS VARCHAR) AS vacate_order_number, d_iso(vacate_effective_date) AS effective_date,
               d_iso(actual_rescind_date) AS rescind_date, primary_vacate_reason AS reason, vacate_type, TRY_CAST(number_of_vacated_units AS INTEGER) AS units_vacated
        FROM {raw('hpd_vacate_orders')} WHERE bbl10(norm_bbl(bbl)) IN (SELECT bbl FROM buildings) AND d_iso(vacate_effective_date) <= DATE '2026-11-14'""")
    con.execute(f"""CREATE TABLE aep_programs AS
        SELECT DISTINCT bbl10(norm_bbl(bbl)) AS bbl, d_iso(aep_start_date) AS start_date, d_iso(discharge_date) AS discharge_date, aep_round
        FROM {raw('hpd_aep')} WHERE bbl10(norm_bbl(bbl)) IN (SELECT bbl FROM buildings)""")
    con.execute(f"""CREATE TABLE dob_violations AS
        SELECT CAST(isn_dob_bis_viol AS BIGINT) AS violation_id, bbl10(build_bbl(boro, block, lot)) AS bbl, CAST(TRY_STRPTIME(issue_date, '%Y%m%d') AS DATE) AS issue_date,
               violation_type_code, violation_type, description,
               (violation_type_code IN ('IMEGNCY', 'UB', 'FISPHAZ', 'EGNCY', 'AEUHAZ1')) AS is_hazard
        FROM {raw('dob_violations')} WHERE bbl10(build_bbl(boro, block, lot)) IN (SELECT bbl FROM buildings) AND TRY_STRPTIME(issue_date, '%Y%m%d') IS NOT NULL""")
    con.execute(f"""CREATE TABLE evictions AS
        SELECT bbl10(norm_bbl(bbl)) AS bbl, d_iso(executed_date) AS executed_date
        FROM {raw('evictions')}
        WHERE residential_commercial_ind = 'Residential' AND bbl10(norm_bbl(bbl)) IN (SELECT bbl FROM buildings)""")
    for tname in ("buildings", "building_snapshots", "hpd_violations", "hpd_complaints", "omo_charges", "litigations", "vacate_orders", "aep_programs", "dob_violations", "evictions"):
        n = con.execute(f"SELECT count(*) FROM {tname}").fetchone()[0]
        print(f"  {tname}: {n:,} rows", flush=True)
    con.execute("CHECKPOINT")
    con.close()
    print(f"marts.duckdb {DB.stat().st_size / 1e6:.0f} MB, done in {(time.time() - t0) / 60:.1f} min", flush=True)


if __name__ == "__main__":
    main()
