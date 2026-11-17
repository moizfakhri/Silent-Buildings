# Data audit (generated)

Generated 2026-11-14 00:42 UTC from data/raw/.


## Headline numbers

- BBL join coverage to PLUTO, HPD violations (stored bbl): 99.59% of distinct BBLs, 99.68% of rows (0.08% of rows have no bbl)
- HPD complaint inspector no-access: 15.68% of 4,099,685 problem rows and 16.66% of 2,408,241 distinct complaints (19.62% of rows with the broader 'unable to complete' wording)
- No-access rate by borough: BRONX 13.88%; BROOKLYN 17.72%
- No-access rate by year: 2018 18.00%; 2019 20.23%; 2020 17.49%; 2021 13.76%; 2022 14.59%; 2023 13.69%; 2024 15.91%; 2025 15.21%; 2026 13.66%
- hpd_violations.novdescription: 50.68% of rows distinct after normalizing; top 100 texts cover 19.77%; 0.00% null
- dob_violations.description: 9.67% of rows distinct after normalizing; top 100 texts cover 88.82%; 14.60% null

## Row counts and manifests

- hpd_violations: 4,715,498 rows, 41 columns, manifest complete=True, pulled 2026-11-14T00:05
- hpd_complaints: 4,099,685 rows, 33 columns, manifest complete=True, pulled 2026-11-14T00:05
- c311_hpd: 2,928,618 rows, 35 columns, manifest complete=True, pulled 2026-11-14T00:20
- evictions: 67,769 rows, 20 columns, manifest complete=True, pulled 2026-11-14T00:21
- hpd_litigations: 52,387 rows, 24 columns, manifest complete=True, pulled 2026-11-14T00:21
- hpd_omo_charges: 517,013 rows, 32 columns, manifest complete=True, pulled 2026-11-14T00:25
- hpd_vacate_orders: 9,002 rows, 20 columns, manifest complete=True, pulled 2026-11-14T00:25
- hpd_aep: 4,387 rows, 19 columns, manifest complete=True, pulled 2026-11-14T00:25
- hpd_registrations: 106,661 rows, 16 columns, manifest complete=True, pulled 2026-11-14T00:25
- hpd_reg_contacts: 744,753 rows, 15 columns, manifest complete=True, pulled 2026-11-14T00:29
- dob_violations: 256,821 rows, 18 columns, manifest complete=True, pulled 2026-11-14T00:31
- pluto: 365,468 rows, 97 columns, manifest complete=True, pulled 2026-11-14T00:37

## Key uniqueness

- hpd_violations key (violationid): 4,715,498 rows, 4,715,498 distinct, duplicates 0
- hpd_complaints key (problem_id): 4,099,685 rows, 4,099,685 distinct, duplicates 0
- c311_hpd key (unique_key): 2,928,618 rows, 2,928,618 distinct, duplicates 0
- hpd_litigations key (litigationid): 52,387 rows, 52,387 distinct, duplicates 0
- hpd_omo_charges key (omoid): 517,013 rows, 517,013 distinct, duplicates 0
- hpd_vacate_orders key (building_id, vacate_order_number): 9,002 rows, 9,002 distinct, duplicates 0
- hpd_registrations key (registrationid): 106,661 rows, 106,656 distinct, duplicates 5
- hpd_reg_contacts key (registrationcontactid): 744,753 rows, 743,302 distinct, duplicates 1,451
- dob_violations key (isn_dob_bis_viol): 256,821 rows, 256,821 distinct, duplicates 0
- pluto key (bbl): 365,468 rows, 365,468 distinct, duplicates 0
- hpd_aep key (building_id, aep_start_date): 4,387 rows, 4,386 distinct, duplicates 1

## Date sanity (only what survived the ingest filters)

- hpd_violations.inspectiondate: non-null 4,715,498; unparseable 0; range 2018-01-01 to 2026-11-11; before 2000 0; in the future 0
- hpd_violations.novissueddate: non-null 4,362,283; unparseable 0; range 2018-01-02 to 2026-11-10; before 2000 0; in the future 0
- hpd_violations.currentstatusdate: non-null 4,715,498; unparseable 0; range 2018-01-02 to 9202-11-10; before 2000 0; in the future 23
- hpd_complaints.received_date: non-null 4,099,685; unparseable 0; range 2018-01-01 to 2026-11-13; before 2000 0; in the future 0
- hpd_complaints.complaint_status_date: non-null 4,099,685; unparseable 0; range 2018-01-01 to 2026-11-13; before 2000 0; in the future 0
- hpd_complaints.problem_status_date: non-null 4,099,444; unparseable 0; range 2018-01-01 to 2026-11-13; before 2000 0; in the future 0
- c311_hpd.created_date: non-null 2,928,618; unparseable 0; range 2020-01-01 to 2026-11-11; before 2000 0; in the future 0
- c311_hpd.closed_date: non-null 2,887,918; unparseable 0; range 2020-01-01 to 2026-11-11; before 2000 0; in the future 0
- evictions.executed_date: non-null 67,769; unparseable 0; range 2018-01-02 to 2026-11-12; before 2000 0; in the future 0
- hpd_litigations.caseopendate: non-null 52,387; unparseable 0; range 2018-01-02 to 2030-10-05; before 2000 0; in the future 2
- hpd_litigations.findingdate: non-null 202; unparseable 202; range None to None; before 2000 0; in the future 0
- hpd_omo_charges.omocreatedate: non-null 517,013; unparseable 0; range 1998-07-13 to 2026-11-12; before 2000 305; in the future 0
- hpd_omo_charges.omoawarddate: non-null 497,011; unparseable 0; range 0910-04-11 to 2026-11-12; before 2000 213; in the future 0
- hpd_vacate_orders.vacate_effective_date: non-null 9,002; unparseable 0; range 2012-01-05 to 2040-08-20; before 2000 0; in the future 15
- hpd_vacate_orders.actual_rescind_date: non-null 4,455; unparseable 0; range 2008-08-16 to 2026-11-12; before 2000 0; in the future 0
- hpd_aep.aep_start_date: non-null 4,387; unparseable 0; range 2007-11-13 to 2026-02-02; before 2000 0; in the future 0
- hpd_aep.discharge_date: non-null 3,529; unparseable 0; range 2007-12-21 to 2026-10-22; before 2000 0; in the future 0
- hpd_registrations.lastregistrationdate: non-null 105,288; unparseable 0; range 1993-04-01 to 2026-10-30; before 2000 1,018; in the future 0
- hpd_registrations.registrationenddate: non-null 106,661; unparseable 0; range 1994-05-31 to 2027-09-01; before 2000 948; in the future 67,647
- dob_violations.issue_date: non-null 256,821; unparseable 1; range 2018-01-01 to 2026-11-11; before 2000 0; in the future 0
- dob_violations.disposition_date: non-null 132,137; unparseable 0; range 2018-01-04 to 2026-11-12; before 2000 0; in the future 0

## BBL quality and join coverage to PLUTO (PLUTO is Bronx/Brooklyn only)

- hpd_violations (stored bbl): 4,715,498 rows, null/unusable bbl 3,786 (0.08%); distinct bbl 109,812, in PLUTO 109,359 (99.59%); rows with a PLUTO match 99.68%; unmatched distinct bbl that look like condo unit lots (lot >= 1001): 12
- hpd_violations (built from boroid/block/lot): 4,715,498 rows, null/unusable bbl 0 (0.00%); distinct bbl 109,972, in PLUTO 109,529 (99.60%); rows with a PLUTO match 99.61%; unmatched distinct bbl that look like condo unit lots (lot >= 1001): 10
- hpd_complaints (stored bbl): 4,099,685 rows, null/unusable bbl 10,747 (0.26%); distinct bbl 85,391, in PLUTO 84,995 (99.54%); rows with a PLUTO match 99.23%; unmatched distinct bbl that look like condo unit lots (lot >= 1001): 10
- c311_hpd: 2,928,618 rows, null/unusable bbl 10,067 (0.34%); distinct bbl 75,555, in PLUTO 74,956 (99.21%); rows with a PLUTO match 99.06%; unmatched distinct bbl that look like condo unit lots (lot >= 1001): 9
- evictions: 67,769 rows, null/unusable bbl 5,094 (7.52%); distinct bbl 23,252, in PLUTO 23,028 (99.04%); rows with a PLUTO match 91.36%; unmatched distinct bbl that look like condo unit lots (lot >= 1001): 8
- hpd_litigations: 52,387 rows, null/unusable bbl 45 (0.09%); distinct bbl 19,917, in PLUTO 19,882 (99.82%); rows with a PLUTO match 99.76%; unmatched distinct bbl that look like condo unit lots (lot >= 1001): 5
- hpd_omo_charges: 517,013 rows, null/unusable bbl 1,105 (0.21%); distinct bbl 68,821, in PLUTO 41,446 (60.22%); rows with a PLUTO match 69.44%; unmatched distinct bbl that look like condo unit lots (lot >= 1001): 940
- hpd_vacate_orders: 9,002 rows, null/unusable bbl 11 (0.12%); distinct bbl 8,042, in PLUTO 4,773 (59.35%); rows with a PLUTO match 60.24%; unmatched distinct bbl that look like condo unit lots (lot >= 1001): 67
- hpd_aep: 4,387 rows, null/unusable bbl 4 (0.09%); distinct bbl 3,628, in PLUTO 2,829 (77.98%); rows with a PLUTO match 78.05%; unmatched distinct bbl that look like condo unit lots (lot >= 1001): 9
- hpd_registrations (built): 106,661 rows, null/unusable bbl 0 (0.00%); distinct bbl 102,068, in PLUTO 101,918 (99.85%); rows with a PLUTO match 99.85%; unmatched distinct bbl that look like condo unit lots (lot >= 1001): 8
- dob_violations (built): 256,821 rows, null/unusable bbl 24 (0.01%); distinct bbl 55,571, in PLUTO 52,157 (93.86%); rows with a PLUTO match 95.59%; unmatched distinct bbl that look like condo unit lots (lot >= 1001): 1,014
- hpd_violations stored bbl equals boroid/block/lot-built bbl in 4,691,927 of 4,711,712 rows (99.58%)

## HPD complaints: inspector no-access (censoring check)

- problem rows 4,099,685; distinct complaints 2,408,241
- strict 'not able to gain access' rows: 642,865 (15.68%); distinct complaints 401,107 (16.66%)
- broad (strict + 'unable to complete the inspection'): 804,248 (19.62%)
- strict rate by borough: BRONX 13.88%; BROOKLYN 17.72%
- strict rate by year: 2018 18.00%; 2019 20.23%; 2020 17.49%; 2021 13.76%; 2022 14.59%; 2023 13.69%; 2024 15.91%; 2025 15.21%; 2026 13.66%
- top status texts: [('The Department of Housing Preservation and Development inspected the following conditions.', 1659213), ('More than one complaint was received for this building-wide condition. This complaint stat', 629752), ('The Department of Housing Preservation and Development was not able to gain access to insp', 333306), ('HPD conducted an inspection of this complaint. The conditions observed by the inspector di', 230814), ('HPD inspected this condition so the complaint has been closed. Violations were issued. The', 217804), ('The Department of Housing Preservation and Development was not able to gain access to your', 187694)]

## Text diversity (how templated are violation descriptions)

- hpd_violations.novdescription: 4,715,490 non-null; 2,728,252 distinct raw (57.86%); 2,390,022 distinct after lowercasing + digits->'#' (50.68%); top 10 / 100 / 1000 normalized texts cover 16.54% / 19.77% / 25.30% of rows
- dob_violations.description: 219,337 non-null; 24,178 distinct raw (11.02%); 21,219 distinct after lowercasing + digits->'#' (9.67%); top 10 / 100 / 1000 normalized texts cover 80.90% / 88.82% / 90.58% of rows
