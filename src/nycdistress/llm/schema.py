"""Schema documentation shown to the model (and used by tests to keep the docs in sync with the real tables)."""

LATEST = "2025-10-01"
NOTES = [
    "All tables describe residential buildings (lots) with 3 or more residential units in Brooklyn and the Bronx. `bbl` is the 10-digit borough-block-lot key; every table joins on it.",
    f"`building_snapshots` has one row per building per quarterly snapshot_date (16 dates, 2022-01-01 to {LATEST}); the latest snapshot is DATE '{LATEST}'. Columns ending in _12m count the 12 months BEFORE the snapshot; columns ending in _next12 describe the 12 months AFTER it.",
    "Scores are model estimates: predicted_risk is the probability of any serious enforcement event next 12 months; predicted_condition is the probability of a vacate order or DOB hazard violation using no complaint information; complaint_gap compares predicted condition with complaints (positive = quieter than predicted).",
    "HPD violation_class is A, B, C or I (C = immediately hazardous). order_number identifies the violation type. DOB `is_hazard` marks emergency, unsafe-building, hazardous-facade and failure-to-certify-class-1 violations.",
    "There are no owner names or tenant data in these tables.",
]
TABLES = {
    "buildings": ("One row per analysis building.", {
        "bbl": "VARCHAR 10-digit key", "borough": "'Brooklyn' or 'Bronx'", "community_district": "3-digit district code (301-318 Brooklyn, 201-212 Bronx)",
        "units_residential": "residential units", "units_total": "all units", "building_class": "PLUTO building class, e.g. 'C1'", "land_use": "PLUTO land use code",
        "year_built": "year built (NULL if unknown)", "floors": "number of floors", "lot_area_sqft": "lot area", "building_area_sqft": "building area"}),
    "building_snapshots": ("One row per building per snapshot date: scores, flags, recent record counts, and outcomes in the next 12 months.", {
        "bbl": "key", "snapshot_date": "DATE", "borough": "borough name", "community_district": "district code", "units_residential": "units", "fold": "evaluation fold label",
        "predicted_risk": "probability 0-1 of a serious enforcement event next 12 months (all-features model)", "predicted_condition": "probability 0-1 of vacate/DOB hazard next 12 months, no complaint information",
        "complaint_loudness": "shrunk complaint problems per unit per year", "complaint_gap": "within-borough percentile gap, -1..1, positive = quieter than predicted condition",
        "gap_top_decile": "BOOLEAN in the top 10% of complaint_gap in its borough", "gap_model_residual_flag": "BOOLEAN observed complaints far below the model expectation", "access_blocked": "BOOLEAN >=3 closed problems and >=50% closed for no access",
        "open_violations": "HPD violations open at the snapshot", "violations_12m": "HPD violations issued in the prior 12 months", "class_c_violations_12m": "class C violations in the prior 12 months",
        "complaint_problems_12m": "HPD complaint problems in the prior 12 months", "requests_311_12m": "311 housing requests in the prior 12 months", "evictions_12m": "marshal evictions in the prior 12 months",
        "dob_violations_12m": "DOB violations in the prior 12 months", "prior_omo_charges": "emergency repair charges to date", "prior_litigations": "HPD litigations to date", "prior_vacate_orders": "vacate orders to date",
        "prior_aep_selections": "AEP selections to date", "no_access_share_12m": "share of problems closed in the prior 12 months that closed for no access (NULL if none closed)", "closed_problems_12m": "problems closed in the prior 12 months",
        "serious_event_next12": "BOOLEAN vacate order, OMO charge, AEP selection or litigation in the next 12 months", "vacate_or_dob_hazard_next12": "BOOLEAN vacate order or DOB hazard violation next 12 months",
        "omo_charge_next12": "BOOLEAN", "litigation_next12": "BOOLEAN", "complaint_problems_next12": "HPD complaint problems received in the next 12 months"}),
    "hpd_violations": ("HPD housing maintenance code violations since 2018.", {
        "violation_id": "BIGINT", "bbl": "key", "inspection_date": "DATE", "violation_class": "A, B, C or I", "order_number": "INTEGER violation type", "description": "violation text (public record, includes apartment locations)",
        "status": "'Open' or 'Close'", "current_status": "latest status text", "current_status_date": "DATE of latest status"}),
    "hpd_complaints": ("HPD complaint problems since 2018 (one row per problem).", {
        "problem_id": "BIGINT", "complaint_id": "BIGINT (a complaint can have several problems)", "bbl": "key", "received_date": "DATE", "is_emergency": "BOOLEAN", "major_category": "e.g. 'HEAT/HOT WATER', 'PLUMBING'",
        "minor_category": "finer category", "problem_status": "'OPEN' or 'CLOSE'", "problem_status_date": "DATE", "closed_no_access": "BOOLEAN the inspector was not able to gain access"}),
    "omo_charges": ("HPD emergency repair (OMO) charges.", {"omo_id": "BIGINT", "bbl": "key", "created_date": "DATE", "work_type": "work type code", "status_reason": "text", "is_aep": "BOOLEAN linked to AEP", "award_amount": "DOUBLE dollars"}),
    "litigations": ("HPD litigation cases since 2018.", {"litigation_id": "BIGINT", "bbl": "key", "opened_date": "DATE", "case_type": "e.g. 'Tenant Action', 'Heat and Hot Water'", "case_status": "text", "harassment_finding": "text"}),
    "vacate_orders": ("HPD vacate orders.", {"bbl": "key", "vacate_order_number": "VARCHAR", "effective_date": "DATE", "rescind_date": "DATE (NULL = still active)", "reason": "primary reason", "vacate_type": "full or partial", "units_vacated": "INTEGER"}),
    "aep_programs": ("Alternative Enforcement Program selections.", {"bbl": "key", "start_date": "DATE", "discharge_date": "DATE (NULL = still in the program)", "aep_round": "text"}),
    "dob_violations": ("DOB violations since 2018.", {"violation_id": "BIGINT", "bbl": "key", "issue_date": "DATE", "violation_type_code": "e.g. 'LBLVIO' (boiler), 'E' (elevator), 'IMEGNCY'", "violation_type": "text", "description": "text", "is_hazard": "BOOLEAN"}),
    "evictions": ("Residential marshal evictions since 2018.", {"bbl": "key", "executed_date": "DATE"}),
}


def schema_text():
    out = ["DuckDB database, read-only. Tables and columns:"]
    for t, (desc, cols) in TABLES.items():
        out.append(f"\nTABLE {t}: {desc}")
        out += [f"  {c}: {d}" for c, d in cols.items()]
    out.append("\nNotes:")
    out += [f"- {n}" for n in NOTES]
    return "\n".join(out)
