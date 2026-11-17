"""Gold questions with reference SQL for execution-accuracy evaluation of text-to-SQL.

Each item: id, category, question, sql, ordered (True when row order is part of the answer). The reference SQL is hand written
against the marts schema and was executed to check it returns a non-empty result.
"""
L = "DATE '2025-10-01'"
GOLD = [
    # ---- basics
    dict(id=1, cat="count", q="How many buildings are in the analysis?", sql="SELECT count(*) FROM buildings"),
    dict(id=2, cat="group", q="How many buildings are there in each borough?", sql="SELECT borough, count(*) FROM buildings GROUP BY borough"),
    dict(id=3, cat="filter", q="How many buildings have at least 50 residential units?", sql="SELECT count(*) FROM buildings WHERE units_residential >= 50"),
    dict(id=4, cat="aggregate", q="What is the average number of residential units per building in Brooklyn?", sql="SELECT avg(units_residential) FROM buildings WHERE borough = 'Brooklyn'"),
    dict(id=5, cat="aggregate", q="How many snapshot dates are there, and what are the first and the last?", sql="SELECT count(DISTINCT snapshot_date), min(snapshot_date), max(snapshot_date) FROM building_snapshots"),
    dict(id=6, cat="topk", q="Which community district has the most buildings?", sql="SELECT community_district FROM buildings GROUP BY 1 ORDER BY count(*) DESC, 1 LIMIT 1", ordered=True),
    dict(id=7, cat="filter", q="How many buildings were built before 1920?", sql="SELECT count(*) FROM buildings WHERE year_built < 1920"),
    dict(id=8, cat="filter", q="How many buildings have more than 10 floors?", sql="SELECT count(*) FROM buildings WHERE floors > 10"),
    dict(id=9, cat="topk", q="Which building has the most residential units, and how many units does it have?", sql="SELECT bbl, units_residential FROM buildings ORDER BY units_residential DESC, bbl LIMIT 1", ordered=True),
    dict(id=10, cat="group", q="How many buildings are there in each building class letter (the first character of building_class)?", sql="SELECT substr(building_class, 1, 1) AS letter, count(*) FROM buildings GROUP BY 1"),
    # ---- latest-snapshot analytics
    dict(id=11, cat="snapshot", q="In the latest snapshot, how many buildings are in the top decile of the complaint gap?", sql=f"SELECT count(*) FROM building_snapshots WHERE snapshot_date = {L} AND gap_top_decile"),
    dict(id=12, cat="snapshot", q="In the latest snapshot, what is the average predicted risk in the Bronx and in Brooklyn?", sql=f"SELECT borough, avg(predicted_risk) FROM building_snapshots WHERE snapshot_date = {L} GROUP BY borough"),
    dict(id=13, cat="snapshot", q="In the latest snapshot, how many buildings had no complaint problems in the prior 12 months?", sql=f"SELECT count(*) FROM building_snapshots WHERE snapshot_date = {L} AND complaint_problems_12m = 0"),
    dict(id=14, cat="aggregate", q="Across all snapshots, what percentage of building-snapshots have zero complaint problems in the prior 12 months?", sql="SELECT 100.0 * avg(CASE WHEN complaint_problems_12m = 0 THEN 1 ELSE 0 END) FROM building_snapshots"),
    dict(id=15, cat="topk", q="Which five community districts have the highest average predicted risk in the latest snapshot?", sql=f"SELECT community_district FROM building_snapshots WHERE snapshot_date = {L} GROUP BY 1 ORDER BY avg(predicted_risk) DESC, 1 LIMIT 5", ordered=True),
    dict(id=16, cat="snapshot", q="How many buildings are access-blocked in the latest snapshot?", sql=f"SELECT count(*) FROM building_snapshots WHERE snapshot_date = {L} AND access_blocked"),
    dict(id=17, cat="group", q="For the latest snapshot, what is the total number of complaint problems in the prior 12 months in each borough?", sql=f"SELECT borough, sum(complaint_problems_12m) FROM building_snapshots WHERE snapshot_date = {L} GROUP BY borough"),
    dict(id=18, cat="snapshot", q="In the latest snapshot, how many buildings have at least 10 open violations?", sql=f"SELECT count(*) FROM building_snapshots WHERE snapshot_date = {L} AND open_violations >= 10"),
    dict(id=19, cat="group", q="For each snapshot date, how many buildings had a serious event in the following 12 months? Order by date.", sql="SELECT snapshot_date, count(*) FILTER (WHERE serious_event_next12) FROM building_snapshots GROUP BY 1 ORDER BY 1", ordered=True),
    dict(id=20, cat="group", q="In the latest snapshot, what is the average predicted condition of access-blocked buildings versus the others?", sql=f"SELECT access_blocked, avg(predicted_condition) FROM building_snapshots WHERE snapshot_date = {L} GROUP BY access_blocked"),
    dict(id=21, cat="aggregate", q="In the latest snapshot, what is the correlation between predicted risk and complaint problems in the prior 12 months?", sql=f"SELECT corr(predicted_risk, complaint_problems_12m) FROM building_snapshots WHERE snapshot_date = {L}"),
    dict(id=22, cat="snapshot", q="In the latest snapshot, how many buildings have had at least 5 emergency repair (OMO) charges to date?", sql=f"SELECT count(*) FROM building_snapshots WHERE snapshot_date = {L} AND prior_omo_charges >= 5"),
    # ---- violations
    dict(id=23, cat="count", q="How many HPD violations are recorded in total?", sql="SELECT count(*) FROM hpd_violations"),
    dict(id=24, cat="filter", q="How many class C violations were inspected in 2024?", sql="SELECT count(*) FROM hpd_violations WHERE violation_class = 'C' AND year(inspection_date) = 2024"),
    dict(id=25, cat="join", q="How many HPD violations were inspected in 2023 in buildings located in the Bronx?", sql="SELECT count(*) FROM hpd_violations v JOIN buildings b USING (bbl) WHERE b.borough = 'Bronx' AND year(v.inspection_date) = 2023"),
    dict(id=26, cat="topk", q="Which violation class is the most common?", sql="SELECT violation_class FROM hpd_violations GROUP BY 1 ORDER BY count(*) DESC, 1 LIMIT 1", ordered=True),
    dict(id=27, cat="filter", q="How many HPD violations are currently open?", sql="SELECT count(*) FROM hpd_violations WHERE status = 'Open'"),
    dict(id=28, cat="topk", q="What are the five most common violation order numbers?", sql="SELECT order_number FROM hpd_violations GROUP BY 1 ORDER BY count(*) DESC, 1 LIMIT 5", ordered=True),
    dict(id=29, cat="distinct", q="How many distinct buildings had at least one class C violation inspected in 2024?", sql="SELECT count(DISTINCT bbl) FROM hpd_violations WHERE violation_class = 'C' AND year(inspection_date) = 2024"),
    dict(id=30, cat="aggregate", q="On average, how many HPD violations per building were inspected in 2024 (counting all buildings in the analysis)?", sql="SELECT 1.0 * (SELECT count(*) FROM hpd_violations WHERE year(inspection_date) = 2024) / (SELECT count(*) FROM buildings)"),
    dict(id=31, cat="text", q="How many HPD violations mention mold in their description?", sql="SELECT count(*) FROM hpd_violations WHERE description ILIKE '%MOLD%'"),
    dict(id=32, cat="group", q="How many HPD violations were inspected in each year from 2018 to 2025? Order by year.", sql="SELECT year(inspection_date), count(*) FROM hpd_violations WHERE year(inspection_date) BETWEEN 2018 AND 2025 GROUP BY 1 ORDER BY 1", ordered=True),
    # ---- complaints
    dict(id=33, cat="filter", q="How many complaint problems are in the HEAT/HOT WATER category?", sql="SELECT count(*) FROM hpd_complaints WHERE major_category = 'HEAT/HOT WATER'"),
    dict(id=34, cat="aggregate", q="What share of complaint problems are emergencies? Give a percentage.", sql="SELECT 100.0 * avg(CASE WHEN is_emergency THEN 1 ELSE 0 END) FROM hpd_complaints"),
    dict(id=35, cat="topk", q="What are the three major complaint categories with the most problems?", sql="SELECT major_category FROM hpd_complaints GROUP BY 1 ORDER BY count(*) DESC, 1 LIMIT 3", ordered=True),
    dict(id=36, cat="aggregate", q="How many complaint problems closed with no inspector access, and what percentage of all problems is that?", sql="SELECT count(*) FILTER (WHERE closed_no_access), 100.0 * avg(CASE WHEN closed_no_access THEN 1 ELSE 0 END) FROM hpd_complaints"),
    dict(id=37, cat="group", q="How many complaint problems were received in each year from 2022 to 2025? Order by year.", sql="SELECT year(received_date), count(*) FROM hpd_complaints WHERE year(received_date) BETWEEN 2022 AND 2025 GROUP BY 1 ORDER BY 1", ordered=True),
    dict(id=38, cat="distinct", q="How many distinct buildings had a HEAT/HOT WATER complaint problem received in 2025?", sql="SELECT count(DISTINCT bbl) FROM hpd_complaints WHERE major_category = 'HEAT/HOT WATER' AND year(received_date) = 2025"),
    dict(id=39, cat="join", q="Which borough has more complaint problems, Brooklyn or the Bronx?", sql="SELECT b.borough FROM hpd_complaints c JOIN buildings b USING (bbl) GROUP BY 1 ORDER BY count(*) DESC LIMIT 1", ordered=True),
    # ---- other events
    dict(id=40, cat="filter", q="How many emergency repair (OMO) charges were created since 2023-01-01?", sql="SELECT count(*) FROM omo_charges WHERE created_date >= DATE '2023-01-01'"),
    dict(id=41, cat="filter", q="How many OMO charges are linked to the Alternative Enforcement Program?", sql="SELECT count(*) FROM omo_charges WHERE is_aep"),
    dict(id=42, cat="filter", q="How many HPD litigation cases were opened in 2024?", sql="SELECT count(*) FROM litigations WHERE year(opened_date) = 2024"),
    dict(id=43, cat="topk", q="What are the three most common HPD litigation case types?", sql="SELECT case_type FROM litigations GROUP BY 1 ORDER BY count(*) DESC, 1 LIMIT 3", ordered=True),
    dict(id=44, cat="join", q="How many vacate orders are there for buildings in Brooklyn?", sql="SELECT count(*) FROM vacate_orders v JOIN buildings b USING (bbl) WHERE b.borough = 'Brooklyn'"),
    dict(id=45, cat="filter", q="How many vacate orders have not been rescinded (still active)?", sql="SELECT count(*) FROM vacate_orders WHERE rescind_date IS NULL"),
    dict(id=46, cat="distinct", q="How many buildings have been selected for the Alternative Enforcement Program at least once?", sql="SELECT count(DISTINCT bbl) FROM aep_programs"),
    dict(id=47, cat="filter", q="How many DOB violations are hazard violations?", sql="SELECT count(*) FROM dob_violations WHERE is_hazard"),
    dict(id=48, cat="filter", q="How many residential evictions were executed in 2024?", sql="SELECT count(*) FROM evictions WHERE year(executed_date) = 2024"),
    dict(id=49, cat="join", q="How many evictions were executed in each borough?", sql="SELECT b.borough, count(*) FROM evictions e JOIN buildings b USING (bbl) GROUP BY 1"),
    # ---- cross-table and harder
    dict(id=50, cat="topk", q="Which building has the most open HPD violations in the latest snapshot?", sql=f"SELECT bbl FROM building_snapshots WHERE snapshot_date = {L} ORDER BY open_violations DESC, bbl LIMIT 1", ordered=True),
    dict(id=51, cat="join", q="How many buildings have both at least one vacate order and at least one AEP selection?", sql="SELECT count(*) FROM (SELECT DISTINCT bbl FROM vacate_orders) v JOIN (SELECT DISTINCT bbl FROM aep_programs) a USING (bbl)"),
    dict(id=52, cat="aggregate", q="Among buildings in the top decile of the complaint gap in the latest snapshot, what share had a serious event in the following 12 months?", sql=f"SELECT avg(CASE WHEN serious_event_next12 THEN 1.0 ELSE 0.0 END) FROM building_snapshots WHERE snapshot_date = {L} AND gap_top_decile"),
    dict(id=53, cat="group", q="Across all snapshots, compare the share of buildings with a serious event in the next 12 months for access-blocked buildings versus the others.", sql="SELECT access_blocked, avg(CASE WHEN serious_event_next12 THEN 1.0 ELSE 0.0 END) FROM building_snapshots GROUP BY access_blocked"),
    dict(id=54, cat="join", q="How many Bronx buildings built before 1940 had a class C violation inspected in 2025?", sql="SELECT count(DISTINCT b.bbl) FROM buildings b JOIN hpd_violations v USING (bbl) WHERE b.borough = 'Bronx' AND b.year_built < 1940 AND v.violation_class = 'C' AND year(v.inspection_date) = 2025"),
    dict(id=55, cat="topk", q="Which community district has the highest share of buildings with zero complaint problems in the prior 12 months in the latest snapshot? Ignore buildings that have no community district.", sql=f"SELECT community_district FROM building_snapshots WHERE snapshot_date = {L} AND community_district IS NOT NULL GROUP BY 1 ORDER BY avg(CASE WHEN complaint_problems_12m = 0 THEN 1.0 ELSE 0.0 END) DESC, 1 LIMIT 1", ordered=True),
    dict(id=56, cat="aggregate", q="How many buildings received more than 100 complaint problems in 2024?", sql="SELECT count(*) FROM (SELECT bbl FROM hpd_complaints WHERE year(received_date) = 2024 GROUP BY bbl HAVING count(*) > 100)"),
    dict(id=57, cat="aggregate", q="What is the median number of residential units among buildings with an HPD litigation opened in 2024?", sql="SELECT median(units_residential) FROM buildings WHERE bbl IN (SELECT bbl FROM litigations WHERE year(opened_date) = 2024)"),
    dict(id=58, cat="topk", q="In which year were the most OMO charges created?", sql="SELECT year(created_date) FROM omo_charges GROUP BY 1 ORDER BY count(*) DESC, 1 LIMIT 1", ordered=True),
]
for g in GOLD:
    g.setdefault("ordered", False)
    g["question"] = g.pop("q")
