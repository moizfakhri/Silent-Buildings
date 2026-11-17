-- Staging: typed, cleaned, BBL keys normalised to BIGINT (10 digits), source duplicates resolved.
-- Everything is a TABLE (not a view) so later steps do not re-parse the raw strings.

-- ---------------------------------------------------------------- helpers
-- PLUTO stores bbl as text like '3085280034.00000000'; other sources use '3019940008'.
CREATE OR REPLACE MACRO norm_bbl(x) AS CAST(TRY_CAST(x AS DOUBLE) AS BIGINT);
-- BBL from borough code (1-5), tax block, tax lot.
CREATE OR REPLACE MACRO build_bbl(boro, blk, lt) AS
  TRY_CAST(boro AS BIGINT) * 1000000000 + TRY_CAST(blk AS BIGINT) * 10000 + TRY_CAST(lt AS BIGINT);
CREATE OR REPLACE MACRO d_iso(x) AS CAST(TRY_CAST(x AS TIMESTAMP) AS DATE);
-- Quarter bucket of a date on the grid anchored at grid_base: qi(d) = k means d is in
-- (base + 3(k-1) months, base + 3k months]. An event dated exactly on a grid date g belongs to the
-- bucket ENDING at g, so "dated <= snapshot t" is exactly "qi <= qi(t)".
CREATE OR REPLACE MACRO qi(x) AS CAST(floor(
  (datediff('month', DATE '{{grid_base}}', CAST(date_trunc('month', x) AS DATE))
   + CASE WHEN day(x) > 1 THEN 1 ELSE 0 END + 2) / 3.0) AS INTEGER);

-- ---------------------------------------------------------------- PLUTO (current state only)
CREATE OR REPLACE TABLE stg_pluto AS
SELECT norm_bbl(bbl) AS bbl,
       borough, cd, ct2010,
       TRY_CAST(unitsres AS INTEGER) AS unitsres,
       TRY_CAST(unitstotal AS INTEGER) AS unitstotal,
       bldgclass,
       TRY_CAST(landuse AS INTEGER) AS landuse,
       NULLIF(TRY_CAST(yearbuilt AS INTEGER), 0) AS yearbuilt,
       NULLIF(TRY_CAST(numfloors AS DOUBLE), 0) AS numfloors,
       NULLIF(TRY_CAST(lotarea AS DOUBLE), 0) AS lotarea,
       NULLIF(TRY_CAST(bldgarea AS DOUBLE), 0) AS bldgarea
FROM raw_pluto
WHERE norm_bbl(bbl) IS NOT NULL;

-- ---------------------------------------------------------------- HPD violations (inspector-issued)
-- Stored bbl first, else built from boroid/block/lot (see DATASETS.md). Closed/open uses the
-- CURRENT status only; there is no status history, so open-at-t is an approximation (see docs).
CREATE OR REPLACE TABLE stg_violations AS
SELECT COALESCE(norm_bbl(bbl), build_bbl(boroid, block, lot)) AS bbl,
       violationid,
       class AS cls,
       d_iso(inspectiondate) AS d_insp,
       (violationstatus = 'Close') AS is_closed,
       CASE WHEN violationstatus = 'Close'
            THEN GREATEST(d_iso(currentstatusdate), d_iso(inspectiondate)) END AS d_close
FROM raw_hpd_violations
WHERE d_iso(inspectiondate) IS NOT NULL
  AND d_iso(inspectiondate) <= DATE '{{data_cutoff}}'
  AND COALESCE(norm_bbl(bbl), build_bbl(boroid, block, lot)) IS NOT NULL;

-- ---------------------------------------------------------------- HPD complaints (tenant-initiated: "loud")
-- Row = one problem. d_closed_known is the earliest date at which the outcome text can be known:
-- only when BOTH problem and complaint are CLOSE, and then the later of the two status dates
-- (never earlier than the receipt date, 15k rows have status before receipt).
-- Evidence for problem-level text: status_description differs between problems of one complaint,
-- and problems close before their complaint (median lag 1 day, p99 29 days).
CREATE OR REPLACE TABLE stg_complaints AS
SELECT COALESCE(norm_bbl(bbl),
                build_bbl(CASE borough WHEN 'BRONX' THEN 2 WHEN 'BROOKLYN' THEN 3 END, block, lot)) AS bbl,
       problem_id,
       complaint_id,
       d_iso(received_date) AS d_recv,
       (type IN ('EMERGENCY', 'IMMEDIATE EMERGENCY')) AS is_emergency,
       CASE WHEN major_category = 'HEAT/HOT WATER' THEN 'heat_hot_water'
            WHEN major_category = 'UNSANITARY CONDITION' THEN 'unsanitary'
            WHEN major_category = 'PLUMBING' THEN 'plumbing'
            WHEN major_category = 'PAINT/PLASTER' THEN 'paint_plaster'
            WHEN major_category = 'DOOR/WINDOW' THEN 'door_window'
            WHEN major_category = 'WATER LEAK' THEN 'water_leak'
            WHEN major_category = 'ELECTRIC' THEN 'electric'
            ELSE 'other' END AS cat,
       CASE WHEN complaint_status = 'CLOSE' AND problem_status = 'CLOSE'
            THEN GREATEST(d_iso(complaint_status_date), d_iso(problem_status_date), d_iso(received_date))
       END AS d_closed_known,
       COALESCE(status_description ILIKE '%not able to gain access%', FALSE) AS is_noaccess
FROM raw_hpd_complaints
WHERE d_iso(received_date) IS NOT NULL
  AND d_iso(received_date) <= DATE '{{data_cutoff}}'
  AND COALESCE(norm_bbl(bbl),
               build_bbl(CASE borough WHEN 'BRONX' THEN 2 WHEN 'BROOKLYN' THEN 3 END, block, lot)) IS NOT NULL;

-- ---------------------------------------------------------------- 311 HPD service requests ("loud")
CREATE OR REPLACE TABLE stg_c311 AS
SELECT norm_bbl(bbl) AS bbl, unique_key, d_iso(created_date) AS d_created,
       (complaint_type = 'HEAT/HOT WATER') AS is_heat
FROM raw_c311_hpd
WHERE norm_bbl(bbl) IS NOT NULL AND d_iso(created_date) IS NOT NULL
  AND d_iso(created_date) <= DATE '{{data_cutoff}}';

-- ---------------------------------------------------------------- evictions (marshal-executed, residential only)
CREATE OR REPLACE TABLE stg_evictions AS
SELECT norm_bbl(bbl) AS bbl, d_iso(executed_date) AS d_exec
FROM raw_evictions
WHERE residential_commercial_ind = 'Residential' AND norm_bbl(bbl) IS NOT NULL
  AND d_iso(executed_date) IS NOT NULL AND d_iso(executed_date) <= DATE '{{data_cutoff}}';

-- ---------------------------------------------------------------- DOB violations (YYYYMMDD text dates)
CREATE OR REPLACE TABLE stg_dob AS
SELECT build_bbl(boro, block, lot) AS bbl, isn_dob_bis_viol,
       CAST(TRY_STRPTIME(issue_date, '%Y%m%d') AS DATE) AS d_issue,
       CASE WHEN violation_type ILIKE '%ELEVATOR%' THEN 'elevator'
            WHEN violation_type ILIKE '%BOILER%' THEN 'boiler'
            WHEN violation_type ILIKE 'C-CONSTRUCTION%' THEN 'construction'
            ELSE 'other' END AS grp,
       -- physical-hazard violation types, from the real DOB violation_type_code distribution:
       -- IMEGNCY immediate emergency, UB unsafe building, FISPHAZ hazardous facade condition, EGNCY emergency
       (violation_type_code IN ('IMEGNCY', 'UB', 'FISPHAZ', 'EGNCY')) AS is_hazard_core,
       -- plus AEUHAZ1: failure to certify correction of an immediately hazardous (class 1) ECB violation
       -- (about 80% of the wide events, a paperwork failure on a previously hazardous violation)
       (violation_type_code IN ('IMEGNCY', 'UB', 'FISPHAZ', 'EGNCY', 'AEUHAZ1')) AS is_hazard
FROM raw_dob_violations
WHERE build_bbl(boro, block, lot) IS NOT NULL AND TRY_STRPTIME(issue_date, '%Y%m%d') IS NOT NULL
  AND CAST(TRY_STRPTIME(issue_date, '%Y%m%d') AS DATE) <= DATE '{{data_cutoff}}';

-- ---------------------------------------------------------------- HPD litigations (city/court action)
CREATE OR REPLACE TABLE stg_litigations AS
SELECT norm_bbl(bbl) AS bbl, litigationid, d_iso(caseopendate) AS d_open
FROM raw_hpd_litigations
WHERE norm_bbl(bbl) IS NOT NULL AND d_iso(caseopendate) IS NOT NULL
  AND d_iso(caseopendate) <= DATE '{{data_cutoff}}';       -- drops the 2 rows dated 2030

-- ---------------------------------------------------------------- vacate orders
-- Only the EFFECTIVE date exists. Rule: drop dates after the data cutoff (15 rows dated up to 2040).
CREATE OR REPLACE TABLE stg_vacate AS
SELECT norm_bbl(bbl) AS bbl, building_id, vacate_order_number,
       d_iso(vacate_effective_date) AS d_vacate, d_iso(actual_rescind_date) AS d_rescind
FROM raw_hpd_vacate_orders
WHERE norm_bbl(bbl) IS NOT NULL AND d_iso(vacate_effective_date) IS NOT NULL
  AND d_iso(vacate_effective_date) <= DATE '{{data_cutoff}}';

-- ---------------------------------------------------------------- AEP (alternative enforcement program)
-- Source duplicates on (building_id, aep_start_date) are exact repeats; keep one, preferring a
-- row that has a discharge date.
CREATE OR REPLACE TABLE stg_aep AS
SELECT norm_bbl(bbl) AS bbl, building_id, d_iso(aep_start_date) AS d_start, d_iso(discharge_date) AS d_discharge
FROM raw_hpd_aep
WHERE norm_bbl(bbl) IS NOT NULL AND d_iso(aep_start_date) IS NOT NULL
QUALIFY row_number() OVER (PARTITION BY building_id, aep_start_date
                           ORDER BY (discharge_date IS NULL), discharge_date DESC) = 1;

-- ---------------------------------------------------------------- OMO / emergency repair charges
CREATE OR REPLACE TABLE stg_omo AS
SELECT COALESCE(norm_bbl(bbl), build_bbl(boro_id, block, lot)) AS bbl, omoid,
       d_iso(omocreatedate) AS d_create, (isaep = 'AEP') AS is_aep
FROM raw_hpd_omo_charges
WHERE COALESCE(norm_bbl(bbl), build_bbl(boro_id, block, lot)) IS NOT NULL
  AND d_iso(omocreatedate) IS NOT NULL AND d_iso(omocreatedate) <= DATE '{{data_cutoff}}';

-- ---------------------------------------------------------------- registrations and contacts
-- Deduplicated here for later phases (portfolio linking). NOT used as Phase 2 features:
-- both are current-state-only snapshots (a registration today says nothing about t).
-- registrations: one row per (registrationid, buildingid); newest lastregistrationdate wins.
CREATE OR REPLACE TABLE stg_registrations AS
SELECT registrationid, buildingid, boroid, block, lot, bin, d_iso(lastregistrationdate) AS d_last_reg,
       d_iso(registrationenddate) AS d_end
FROM raw_hpd_registrations
QUALIFY row_number() OVER (PARTITION BY registrationid, buildingid
                           ORDER BY d_iso(lastregistrationdate) DESC NULLS LAST, bin) = 1;
-- contacts: one row per registrationcontactid; exact repeats collapse, conflicting versions
-- resolve to the row with most non-null fields, ties broken by a hash of the row (deterministic).
CREATE OR REPLACE TABLE stg_reg_contacts AS
SELECT * FROM raw_hpd_reg_contacts
QUALIFY row_number() OVER (
  PARTITION BY registrationcontactid
  ORDER BY (CAST(corporationname IS NOT NULL AS INT) + CAST(firstname IS NOT NULL AS INT)
            + CAST(lastname IS NOT NULL AS INT) + CAST(businessstreetname IS NOT NULL AS INT)
            + CAST(businesszip IS NOT NULL AS INT) + CAST(title IS NOT NULL AS INT)) DESC,
           hash(corporationname, firstname, lastname, businesshousenumber, businessstreetname,
                businessapartment, businesszip, type, contactdescription)) = 1;
