-- Final tables. Key = (bbl, snapshot_date); bbl is the 10-digit string.

-- one row per lot (attributes as of the PLUTO release; current state only)
CREATE OR REPLACE TABLE spine AS
SELECT bbl_str AS bbl, borough, cd AS community_district, ct2010 AS census_tract_2010, unitsres, unitstotal, bldgclass, landuse, yearbuilt, numfloors, lotarea, bldgarea
FROM spine_lot;

-- Static PLUTO fields only. Excluded on purpose: assessed values, exemptions, owner name/type
-- (all change over time and PLUTO keeps only the latest, so using them at old snapshots leaks the
-- future), and yearalter1/2 (the latest alteration year can postdate the snapshot).
CREATE OR REPLACE TABLE features AS
SELECT l.bbl_str AS bbl, n.snapshot_date,
  (n.q >= 12) AS meta_hist36_complete,    -- true once 36 months of history exist inside the 2018+ extract
  l.borough AS static_borough, l.unitsres AS static_unitsres, l.unitstotal AS static_unitstotal,
  l.bldgclass AS static_bldgclass, left(l.bldgclass, 1) AS static_bldgclass_letter, l.landuse AS static_landuse,
  l.yearbuilt AS static_year_built, year(n.snapshot_date) - l.yearbuilt AS static_age_at_t,
  l.numfloors AS static_numfloors, l.lotarea AS static_lotarea, l.bldgarea AS static_bldgarea,
  v.* EXCLUDE (bbl, q), c.* EXCLUDE (bbl, q), t.* EXCLUDE (bbl, q), e.* EXCLUDE (bbl, q),
  d.* EXCLUDE (bbl, q), p.* EXCLUDE (bbl, q)
FROM spine_snap n
JOIN spine_lot l ON l.bbl = n.bbl
JOIN f_viol v ON v.bbl = n.bbl AND v.q = n.q
JOIN f_cmp c ON c.bbl = n.bbl AND c.q = n.q
JOIN f_c311 t ON t.bbl = n.bbl AND t.q = n.q
JOIN f_evict e ON e.bbl = n.bbl AND e.q = n.q
JOIN f_dob d ON d.bbl = n.bbl AND d.q = n.q
JOIN f_prior p ON p.bbl = n.bbl AND p.q = n.q;

CREATE OR REPLACE TABLE labels AS
SELECT l.bbl_str AS bbl, n.snapshot_date,
  CAST(COALESCE(lv.n, 0) > 0 AS TINYINT) AS label_vacate,
  CAST(COALESCE(la.n, 0) > 0 AS TINYINT) AS label_aep,
  CAST(COALESCE(lv.n, 0) + COALESCE(la.n, 0) > 0 AS TINYINT) AS label_vacate_or_aep,   -- the rare, harder pair
  CAST(COALESCE(lo.n, 0) > 0 AS TINYINT) AS label_omo,
  CAST(COALESCE(ll.n, 0) > 0 AS TINYINT) AS label_litigation,
  CAST(COALESCE(lv.n, 0) + COALESCE(la.n, 0) + COALESCE(lo.n, 0) + COALESCE(ll.n, 0) > 0 AS TINYINT) AS label_serious_any,
  COALESCE(lc.n, 0) AS label_loud_complaints_next12,
  CAST(COALESCE(ld.n, 0) > 0 AS TINYINT) AS label_dob_hazard,                  -- DOB hazard violation, wide definition
  CAST(COALESCE(ld.n_core, 0) > 0 AS TINYINT) AS label_dob_hazard_core,        -- without the AEUHAZ1 certification failures
  CAST(COALESCE(lv.n, 0) + COALESCE(ld.n, 0) > 0 AS TINYINT) AS label_vacate_or_dobhaz,            -- Phase 4 primary outcome
  CAST(COALESCE(lv.n, 0) + COALESCE(ld.n_core, 0) > 0 AS TINYINT) AS label_vacate_or_dobhaz_core
FROM spine_snap n
JOIN spine_lot l ON l.bbl = n.bbl
LEFT JOIN lab_vacate lv ON lv.bbl = n.bbl AND lv.q = n.q
LEFT JOIN lab_aep la ON la.bbl = n.bbl AND la.q = n.q
LEFT JOIN lab_omo lo ON lo.bbl = n.bbl AND lo.q = n.q
LEFT JOIN lab_litig ll ON ll.bbl = n.bbl AND ll.q = n.q
LEFT JOIN lab_cmp lc ON lc.bbl = n.bbl AND lc.q = n.q
LEFT JOIN lab_dobhaz ld ON ld.bbl = n.bbl AND ld.q = n.q;
