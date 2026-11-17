-- Spine: Bronx + Brooklyn residential lots with 3+ residential units, and the snapshot grid.
-- Membership uses CURRENT PLUTO (unitsres, landuse): a lot converted or demolished since t is
-- judged by today's state. That is a selection leak documented in docs/labels_and_features.md.
CREATE OR REPLACE TABLE spine_lot AS
SELECT lpad(CAST(bbl AS VARCHAR), 10, '0') AS bbl_str,   -- 10-digit string
       bbl,
       borough, cd, ct2010,
       unitsres, unitstotal, bldgclass, landuse, yearbuilt, numfloors, lotarea, bldgarea
FROM stg_pluto
WHERE borough IN ('BX', 'BK') AND unitsres >= 3 AND landuse IN (2, 3, 4);   -- walk-up, elevator, mixed use

-- Quarterly snapshots on the grid anchored at grid_base.
CREATE OR REPLACE TABLE snap AS
SELECT CAST(DATE '{{first_snapshot}}' + to_months(3 * i) AS DATE) AS snapshot_date,
       qi(CAST(DATE '{{first_snapshot}}' + to_months(3 * i) AS DATE)) AS q
FROM range(0, datediff('month', DATE '{{first_snapshot}}', DATE '{{last_snapshot}}') // 3 + 1) t(i);

-- bbl x snapshot. A lot is only in a snapshot if it already existed: yearbuilt < year(t)
-- (unknown yearbuilt is kept).
CREATE OR REPLACE TABLE spine_snap AS
SELECT s.bbl, n.snapshot_date, n.q
FROM spine_lot s JOIN snap n ON s.yearbuilt IS NULL OR s.yearbuilt < year(n.snapshot_date);
