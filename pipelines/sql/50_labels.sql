-- Forward labels over (t, t + 12 months] = buckets q+1 .. q+4. Features only use buckets <= q, so the
-- two windows share no bucket and no date (an event exactly ON t is a feature, never a label).
-- Dates used: vacate_effective_date (cleaned: not after the data cutoff), aep_start_date,
-- omocreatedate, caseopendate, and received_date for complaint problems.
-- Each count is aggregated separately and joined later (joining all sources at once would
-- multiply rows).
CREATE OR REPLACE TABLE lab_vacate AS
SELECT s.bbl, s.q, CAST(sum(e.op) AS INTEGER) AS n FROM spine_snap s
JOIN ev_vacate e ON e.bbl = s.bbl AND e.qb > s.q AND e.qb <= s.q + 4 GROUP BY 1, 2;

CREATE OR REPLACE TABLE lab_aep AS
SELECT s.bbl, s.q, CAST(sum(e.op) AS INTEGER) AS n FROM spine_snap s
JOIN ev_aep e ON e.bbl = s.bbl AND e.qb > s.q AND e.qb <= s.q + 4 GROUP BY 1, 2;

CREATE OR REPLACE TABLE lab_omo AS
SELECT s.bbl, s.q, CAST(sum(e.n) AS INTEGER) AS n FROM spine_snap s
JOIN ev_omo e ON e.bbl = s.bbl AND e.qb > s.q AND e.qb <= s.q + 4 GROUP BY 1, 2;

CREATE OR REPLACE TABLE lab_litig AS
SELECT s.bbl, s.q, CAST(sum(e.n) AS INTEGER) AS n FROM spine_snap s
JOIN ev_litig e ON e.bbl = s.bbl AND e.qb > s.q AND e.qb <= s.q + 4 GROUP BY 1, 2;

CREATE OR REPLACE TABLE lab_cmp AS
SELECT s.bbl, s.q, CAST(sum(e.n_prob) AS INTEGER) AS n FROM spine_snap s
JOIN ev_cmp e ON e.bbl = s.bbl AND e.qb > s.q AND e.qb <= s.q + 4 GROUP BY 1, 2;

-- DOB physical-hazard violations issued in the window (the least tenant-driven outcome we have)
CREATE OR REPLACE TABLE lab_dobhaz AS
SELECT s.bbl, s.q, CAST(sum(e.n_haz) AS INTEGER) AS n, CAST(sum(e.n_hazc) AS INTEGER) AS n_core FROM spine_snap s
JOIN ev_dob e ON e.bbl = s.bbl AND e.qb > s.q AND e.qb <= s.q + 4 GROUP BY 1, 2;
