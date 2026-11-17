-- As-of features. Every event is assigned to a quarter bucket qb = qi(event date); a snapshot t
-- has bucket q = qi(t); "dated <= t" is exactly "qb <= q". So a feature only ever sees buckets
-- <= q and cannot see anything after t.
--
-- Windows: 3m / 12m / 36m = the last 1 / 4 / 12 buckets. A window is NULL (not 0) when it reaches
-- back before the source's first covered date (q0 = first covered bucket; 0 = 2018-01-01), because
-- "no events" and "not observed" must not look the same.
--
-- Groups by column prefix:  viol_*  HPD violations (inspector-issued, mixed provenance: many follow
--   a complaint)   loud_*  tenant complaint driven (HPD complaints, 311)   evict_*  marshal evictions
--   dob_*  DOB violations   prior_*  earlier city/court events   static_*  PLUTO fields (assemble step)

-- window sum of x over the last w buckets, NULL if the window starts before the source does
CREATE OR REPLACE MACRO wsum(x, qb, q, w, q0) AS
  CASE WHEN q - w >= q0 THEN CAST(COALESCE(sum(x) FILTER (WHERE qb > q - w), 0) AS INTEGER) END;
-- cumulative sum over every bucket joined (the join already restricts qb <= q)
CREATE OR REPLACE MACRO csum(x) AS CAST(COALESCE(sum(x), 0) AS INTEGER);

-- ------------------------------------------------------------------ HPD violations
CREATE OR REPLACE TABLE ev_viol AS
SELECT bbl, qb, CAST(sum(op_n) AS INTEGER) op_n, CAST(sum(op_a) AS INTEGER) op_a, CAST(sum(op_b) AS INTEGER) op_b,
       CAST(sum(op_c) AS INTEGER) op_c, CAST(sum(op_i) AS INTEGER) op_i,
       CAST(sum(cl_n) AS INTEGER) cl_n, CAST(sum(cl_a) AS INTEGER) cl_a, CAST(sum(cl_b) AS INTEGER) cl_b,
       CAST(sum(cl_c) AS INTEGER) cl_c, CAST(sum(cl_i) AS INTEGER) cl_i
FROM (
  SELECT bbl, qi(d_insp) qb, 1 op_n, (cls = 'A')::INT op_a, (cls = 'B')::INT op_b, (cls = 'C')::INT op_c,
         (cls = 'I')::INT op_i, 0 cl_n, 0 cl_a, 0 cl_b, 0 cl_c, 0 cl_i FROM stg_violations
  UNION ALL   -- closure events: only violations whose CURRENT status is closed; qb of the close date
  SELECT bbl, qi(d_close), 0, 0, 0, 0, 0, 1, (cls = 'A')::INT, (cls = 'B')::INT, (cls = 'C')::INT, (cls = 'I')::INT
  FROM stg_violations WHERE is_closed AND d_close IS NOT NULL
) GROUP BY bbl, qb;

CREATE OR REPLACE TABLE f_viol AS
SELECT s.bbl, s.q,
  wsum(e.op_n, e.qb, s.q, 1, 0) AS viol_n_3m,  wsum(e.op_n, e.qb, s.q, 4, 0) AS viol_n_12m,  wsum(e.op_n, e.qb, s.q, 12, 0) AS viol_n_36m,
  wsum(e.op_a, e.qb, s.q, 1, 0) AS viol_a_n_3m, wsum(e.op_a, e.qb, s.q, 4, 0) AS viol_a_n_12m, wsum(e.op_a, e.qb, s.q, 12, 0) AS viol_a_n_36m,
  wsum(e.op_b, e.qb, s.q, 1, 0) AS viol_b_n_3m, wsum(e.op_b, e.qb, s.q, 4, 0) AS viol_b_n_12m, wsum(e.op_b, e.qb, s.q, 12, 0) AS viol_b_n_36m,
  wsum(e.op_c, e.qb, s.q, 1, 0) AS viol_c_n_3m, wsum(e.op_c, e.qb, s.q, 4, 0) AS viol_c_n_12m, wsum(e.op_c, e.qb, s.q, 12, 0) AS viol_c_n_36m,
  -- open at t = inspected <= t and not closed <= t. APPROXIMATION: closed-ness comes from the
  -- current status and its date (no status history). Only violations inspected since 2018 exist in
  -- the data, so older still-open violations are missing (undercount, worst in early snapshots).
  GREATEST(csum(e.op_n) - csum(e.cl_n), 0) AS viol_open_n,
  GREATEST(csum(e.op_a) - csum(e.cl_a), 0) AS viol_open_a_n,
  GREATEST(csum(e.op_b) - csum(e.cl_b), 0) AS viol_open_b_n,
  GREATEST(csum(e.op_c) - csum(e.cl_c), 0) AS viol_open_c_n
FROM spine_snap s LEFT JOIN ev_viol e ON e.bbl = s.bbl AND e.qb <= s.q
GROUP BY s.bbl, s.q;

-- ------------------------------------------------------------------ HPD complaints (loud)
-- receipt events keyed on received date; closure events keyed on the KNOWN closure date
-- (both problem and complaint CLOSE, later of the two dates). Outcome text (no-access) is only
-- counted in closure events, so it is never visible before the closure date.
CREATE OR REPLACE TABLE ev_cmp AS
SELECT bbl, qb, CAST(sum(n_prob) AS INTEGER) n_prob, CAST(sum(n_cmpl) AS INTEGER) n_cmpl,
       CAST(sum(n_emerg) AS INTEGER) n_emerg, CAST(sum(n_nonemerg) AS INTEGER) n_nonemerg,
       CAST(sum(n_heat) AS INTEGER) n_heat, CAST(sum(c_unsan) AS INTEGER) c_unsan,
       CAST(sum(c_plumb) AS INTEGER) c_plumb, CAST(sum(c_paint) AS INTEGER) c_paint,
       CAST(sum(c_door) AS INTEGER) c_door, CAST(sum(c_leak) AS INTEGER) c_leak,
       CAST(sum(c_elec) AS INTEGER) c_elec, CAST(sum(c_other) AS INTEGER) c_other,
       CAST(sum(cl_n) AS INTEGER) cl_n, CAST(sum(cl_nacc) AS INTEGER) cl_nacc
FROM (
  SELECT bbl, qi(d_recv) qb, count(*) n_prob, count(DISTINCT complaint_id) n_cmpl,
         count(*) FILTER (WHERE is_emergency) n_emerg, count(*) FILTER (WHERE NOT is_emergency) n_nonemerg,
         count(*) FILTER (WHERE cat = 'heat_hot_water') n_heat,
         count(*) FILTER (WHERE cat = 'unsanitary') c_unsan, count(*) FILTER (WHERE cat = 'plumbing') c_plumb,
         count(*) FILTER (WHERE cat = 'paint_plaster') c_paint, count(*) FILTER (WHERE cat = 'door_window') c_door,
         count(*) FILTER (WHERE cat = 'water_leak') c_leak, count(*) FILTER (WHERE cat = 'electric') c_elec,
         count(*) FILTER (WHERE cat = 'other') c_other, 0 cl_n, 0 cl_nacc
  FROM stg_complaints GROUP BY bbl, qi(d_recv)
  UNION ALL
  SELECT bbl, qi(d_closed_known), 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, count(*), count(*) FILTER (WHERE is_noaccess)
  FROM stg_complaints WHERE d_closed_known IS NOT NULL GROUP BY bbl, qi(d_closed_known)
) GROUP BY bbl, qb;

CREATE OR REPLACE TABLE f_cmp AS
SELECT s.bbl, s.q,
  wsum(e.n_prob, e.qb, s.q, 1, 0) AS loud_prob_n_3m, wsum(e.n_prob, e.qb, s.q, 4, 0) AS loud_prob_n_12m, wsum(e.n_prob, e.qb, s.q, 12, 0) AS loud_prob_n_36m,
  wsum(e.n_cmpl, e.qb, s.q, 1, 0) AS loud_cmpl_n_3m, wsum(e.n_cmpl, e.qb, s.q, 4, 0) AS loud_cmpl_n_12m, wsum(e.n_cmpl, e.qb, s.q, 12, 0) AS loud_cmpl_n_36m,
  wsum(e.n_emerg, e.qb, s.q, 1, 0) AS loud_emerg_n_3m, wsum(e.n_emerg, e.qb, s.q, 4, 0) AS loud_emerg_n_12m, wsum(e.n_emerg, e.qb, s.q, 12, 0) AS loud_emerg_n_36m,
  wsum(e.n_nonemerg, e.qb, s.q, 1, 0) AS loud_nonemerg_n_3m, wsum(e.n_nonemerg, e.qb, s.q, 4, 0) AS loud_nonemerg_n_12m, wsum(e.n_nonemerg, e.qb, s.q, 12, 0) AS loud_nonemerg_n_36m,
  wsum(e.n_heat, e.qb, s.q, 1, 0) AS loud_heat_n_3m, wsum(e.n_heat, e.qb, s.q, 4, 0) AS loud_heat_n_12m, wsum(e.n_heat, e.qb, s.q, 12, 0) AS loud_heat_n_36m,
  wsum(e.c_unsan, e.qb, s.q, 4, 0) AS loud_cat_unsanitary_n_12m, wsum(e.c_plumb, e.qb, s.q, 4, 0) AS loud_cat_plumbing_n_12m,
  wsum(e.c_paint, e.qb, s.q, 4, 0) AS loud_cat_paint_plaster_n_12m, wsum(e.c_door, e.qb, s.q, 4, 0) AS loud_cat_door_window_n_12m,
  wsum(e.c_leak, e.qb, s.q, 4, 0) AS loud_cat_water_leak_n_12m, wsum(e.c_elec, e.qb, s.q, 4, 0) AS loud_cat_electric_n_12m,
  wsum(e.c_other, e.qb, s.q, 4, 0) AS loud_cat_other_n_12m,
  GREATEST(csum(e.n_prob) - csum(e.cl_n), 0) AS loud_open_prob_n,        -- received <= t, not known closed by t
  -- outcomes of problems CLOSED within the window (by known closure date)
  wsum(e.cl_n, e.qb, s.q, 1, 0) AS loud_closed_n_3m, wsum(e.cl_n, e.qb, s.q, 4, 0) AS loud_closed_n_12m, wsum(e.cl_n, e.qb, s.q, 12, 0) AS loud_closed_n_36m,
  wsum(e.cl_nacc, e.qb, s.q, 1, 0) AS loud_nacc_n_3m, wsum(e.cl_nacc, e.qb, s.q, 4, 0) AS loud_nacc_n_12m, wsum(e.cl_nacc, e.qb, s.q, 12, 0) AS loud_nacc_n_36m
FROM spine_snap s LEFT JOIN ev_cmp e ON e.bbl = s.bbl AND e.qb <= s.q
GROUP BY s.bbl, s.q;
-- shares (NULL when nothing closed in the window or the window is incomplete)
ALTER TABLE f_cmp ADD COLUMN loud_nacc_share_12m FLOAT;
ALTER TABLE f_cmp ADD COLUMN loud_nacc_share_36m FLOAT;
UPDATE f_cmp SET loud_nacc_share_12m = CASE WHEN loud_closed_n_12m > 0 THEN loud_nacc_n_12m::FLOAT / loud_closed_n_12m END,
                 loud_nacc_share_36m = CASE WHEN loud_closed_n_36m > 0 THEN loud_nacc_n_36m::FLOAT / loud_closed_n_36m END;

-- ------------------------------------------------------------------ 311 HPD requests (loud); extract starts 2020-01-01
CREATE OR REPLACE TABLE ev_c311 AS
SELECT bbl, qi(d_created) qb, CAST(count(*) AS INTEGER) n, CAST(count(*) FILTER (WHERE is_heat) AS INTEGER) n_heat
FROM stg_c311 GROUP BY 1, 2;
CREATE OR REPLACE TABLE f_c311 AS
SELECT s.bbl, s.q,
  wsum(e.n, e.qb, s.q, 1, qi(DATE '{{c311_start}}')) AS loud_311_n_3m,
  wsum(e.n, e.qb, s.q, 4, qi(DATE '{{c311_start}}')) AS loud_311_n_12m,
  wsum(e.n, e.qb, s.q, 12, qi(DATE '{{c311_start}}')) AS loud_311_n_36m,
  wsum(e.n_heat, e.qb, s.q, 4, qi(DATE '{{c311_start}}')) AS loud_311_heat_n_12m
FROM spine_snap s LEFT JOIN ev_c311 e ON e.bbl = s.bbl AND e.qb <= s.q AND e.qb > s.q - 12
GROUP BY s.bbl, s.q;

-- ------------------------------------------------------------------ evictions (marshal executed, residential)
CREATE OR REPLACE TABLE ev_evict AS
SELECT bbl, qi(d_exec) qb, CAST(count(*) AS INTEGER) n FROM stg_evictions GROUP BY 1, 2;
CREATE OR REPLACE TABLE f_evict AS
SELECT s.bbl, s.q,
  wsum(e.n, e.qb, s.q, 4, 0) AS evict_n_12m, wsum(e.n, e.qb, s.q, 12, 0) AS evict_n_36m
FROM spine_snap s LEFT JOIN ev_evict e ON e.bbl = s.bbl AND e.qb <= s.q AND e.qb > s.q - 12
GROUP BY s.bbl, s.q;

-- ------------------------------------------------------------------ DOB violations
CREATE OR REPLACE TABLE ev_dob AS
SELECT bbl, qi(d_issue) qb, CAST(count(*) AS INTEGER) n,
       CAST(count(*) FILTER (WHERE grp = 'elevator') AS INTEGER) n_el,
       CAST(count(*) FILTER (WHERE grp = 'boiler') AS INTEGER) n_bo,
       CAST(count(*) FILTER (WHERE grp = 'construction') AS INTEGER) n_co,
       CAST(count(*) FILTER (WHERE is_hazard) AS INTEGER) n_haz,        -- only used by the labels
       CAST(count(*) FILTER (WHERE is_hazard_core) AS INTEGER) n_hazc
FROM stg_dob GROUP BY 1, 2;
CREATE OR REPLACE TABLE f_dob AS
SELECT s.bbl, s.q,
  wsum(e.n, e.qb, s.q, 4, 0) AS dob_n_12m, wsum(e.n, e.qb, s.q, 12, 0) AS dob_n_36m,
  wsum(e.n_el, e.qb, s.q, 4, 0) AS dob_elevator_n_12m, wsum(e.n_bo, e.qb, s.q, 4, 0) AS dob_boiler_n_12m,
  wsum(e.n_co, e.qb, s.q, 4, 0) AS dob_construction_n_12m
FROM spine_snap s LEFT JOIN ev_dob e ON e.bbl = s.bbl AND e.qb <= s.q AND e.qb > s.q - 12
GROUP BY s.bbl, s.q;

-- ------------------------------------------------------------------ prior city / court events
-- Counts are over everything in the extract: litigations since 2018 (extract filter), vacate orders
-- since 2012, AEP since 2007, OMO since 1998. "months since" is NULL when there is no earlier event
-- in the extract (which for litigations may be a pre-2018 event we cannot see).
CREATE OR REPLACE TABLE ev_litig AS
SELECT bbl, qi(d_open) qb, CAST(count(*) AS INTEGER) n, max(d_open) last_d FROM stg_litigations GROUP BY 1, 2;
CREATE OR REPLACE TABLE ev_omo AS
SELECT bbl, qi(d_create) qb, CAST(count(*) AS INTEGER) n, max(d_create) last_d FROM stg_omo GROUP BY 1, 2;
CREATE OR REPLACE TABLE ev_vacate AS
SELECT bbl, qb, CAST(sum(op) AS INTEGER) op, CAST(sum(cl) AS INTEGER) cl, max(last_d) last_d FROM (
  SELECT bbl, qi(d_vacate) qb, 1 op, 0 cl, d_vacate last_d FROM stg_vacate
  UNION ALL   -- rescinded: the rescind date is only used to say "no longer active" after it passes
  SELECT bbl, qi(d_rescind), 0, 1, NULL FROM stg_vacate WHERE d_rescind IS NOT NULL AND d_rescind >= d_vacate
) GROUP BY 1, 2;
CREATE OR REPLACE TABLE ev_aep AS
SELECT bbl, qb, CAST(sum(op) AS INTEGER) op, CAST(sum(cl) AS INTEGER) cl, max(last_d) last_d FROM (
  SELECT bbl, qi(d_start) qb, 1 op, 0 cl, d_start last_d FROM stg_aep
  UNION ALL
  SELECT bbl, qi(d_discharge), 0, 1, NULL FROM stg_aep WHERE d_discharge IS NOT NULL AND d_discharge >= d_start
) GROUP BY 1, 2;

CREATE OR REPLACE TABLE f_prior AS
WITH a AS (
  SELECT s.bbl, s.q, csum(e.n) AS prior_litig_n, wsum(e.n, e.qb, s.q, 4, 0) AS prior_litig_n_12m,
         datediff('month', max(e.last_d), max(s.snapshot_date)) AS prior_litig_months_since
  FROM spine_snap s LEFT JOIN ev_litig e ON e.bbl = s.bbl AND e.qb <= s.q GROUP BY s.bbl, s.q),
b AS (
  SELECT s.bbl, s.q, csum(e.n) AS prior_omo_n, wsum(e.n, e.qb, s.q, 4, 0) AS prior_omo_n_12m,
         datediff('month', max(e.last_d), max(s.snapshot_date)) AS prior_omo_months_since
  FROM spine_snap s LEFT JOIN ev_omo e ON e.bbl = s.bbl AND e.qb <= s.q GROUP BY s.bbl, s.q),
c AS (
  SELECT s.bbl, s.q, csum(e.op) AS prior_vacate_n, GREATEST(csum(e.op) - csum(e.cl), 0) AS prior_vacate_active_n,
         datediff('month', max(e.last_d), max(s.snapshot_date)) AS prior_vacate_months_since
  FROM spine_snap s LEFT JOIN ev_vacate e ON e.bbl = s.bbl AND e.qb <= s.q GROUP BY s.bbl, s.q),
d AS (
  SELECT s.bbl, s.q, csum(e.op) AS prior_aep_n, GREATEST(csum(e.op) - csum(e.cl), 0) AS prior_aep_active_n,
         datediff('month', max(e.last_d), max(s.snapshot_date)) AS prior_aep_months_since
  FROM spine_snap s LEFT JOIN ev_aep e ON e.bbl = s.bbl AND e.qb <= s.q GROUP BY s.bbl, s.q)
SELECT a.bbl, a.q, a.* EXCLUDE (bbl, q), b.* EXCLUDE (bbl, q), c.* EXCLUDE (bbl, q), d.* EXCLUDE (bbl, q)
FROM a JOIN b USING (bbl, q) JOIN c USING (bbl, q) JOIN d USING (bbl, q);
