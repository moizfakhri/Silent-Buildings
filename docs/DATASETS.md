# Dataset verification log

Checked 2026-11-13 against data.cityofnewyork.us (Socrata metadata and live queries). "Rows" are from metadata unless a live count is noted. Keys: BBL (borough-block-lot, 10 digits), BIN (building id), BuildingID (HPD's own id).

| Dataset | ID | Last updated | Rows | Date coverage seen | Join keys | Notes |
|---|---|---|---|---|---|---|
| HPD Housing Maintenance Code Violations | wvxf-dwi5 | 2026-11-12 | 8.35M metadata, **11.38M live** | inspectiondate max 2026-11-11, min is a bad value (0217) | bbl, BuildingID, RegistrationID, BIN, boroid+block+lot | **Has a `bbl` column** (0.08% null in the Phase 1 pull; an earlier note here saying there was none was wrong). It disagrees with the BBL built from boroid+block+lot in 0.42% of rows (condo billing lots, e.g. lot 29 stored as 7501). **Use the stored `bbl`, fall back to the built one** when it is null. Fields: Class A/B/C/I, status, NOV text, RentImpairing, lat/lon |
| HPD Complaints and Problems | ygpa-z7cr | 2026-10-21 | 14.1M | received 2026-10 sampled | building_id, bbl, bin | Has problem category, status_description (includes inspector no-access text) |
| 311 Service Requests 2020-Present | erm2-nwe9 | 2026-11-11 | not verified | 2020 onward | bbl, address, lat/lon | 48 columns, filter agency=HPD for housing; bbl completeness not yet measured |
| Evictions | 6z8x-wfk4 | 2026-11-01 | 136,544 | 2017-01-03 to 2026-10-30 | bbl (90.8% filled), bin | Residential/commercial flag, executed marshal evictions only |
| HPD Housing Litigations | 59kj-x8nc | 2026-11-01 | 242,293 | not fully checked | buildingid, bbl, bin | respondent free text, harassment finding, penalty |
| OMO charges | mdbu-nrqn | 2026-10-28 | not checked | | | Emergency repair, AEP, demolition work orders |
| Order to Repair/Vacate | tb8q-a3ar | 2026-11-11 | not checked | | | |
| AEP selected buildings | hcir-3275 | 2026-10-01 | not checked | | | |
| Buildings Subject to HPD Jurisdiction | kj4p-ruqc | 2026-10-28 | not checked | | BuildingID | Candidate building spine |
| DOB Violations | 3h2n-5cm9 | 2026-11-08 | 2,477,725 | | bin, boro+block+lot | Legacy BIS violations |
| DOB NOW Job Filings | w9ak-ipjd | 2026-11-10 | 981,729 | | bin, block, lot | Initial cost, stories, dwelling units before/after |
| HPD Multiple Dwelling Registrations | tesw-yqqr | 2026-11-04 | 187,127 | current state | registrationid, buildingid, bin, block+lot | Current snapshot only |
| HPD Registration Contacts | feu5-w2e2 | 2026-11-04 | 744,753 | current state | registrationid | Owner/agent names and business addresses for portfolio links |
| ACRIS Real Property Master | bnx9-e6tj | 2026-11-10 | 17,143,212 | | document_id | doc_type (DEED etc.), document_amt, document_date |
| ACRIS Real Property Legals | 8h5j-fqxa | 2026-11-10 | not checked | | document_id -> BBL | Needed to attach BBL to Master |
| ACRIS Real Property Parties | 636b-3b5g | 2026-11-10 | not checked | | document_id | Buyer/seller names |
| NYC Citywide Rolling Calendar Sales | usep-8jbt | 2026-10-15 | not checked | | BBL | Cross-check on sale prices |
| Speculation Watch List | adax-9mit | 2026-05-07 | not checked | | | Local Law 7 of 2018; related qualified-transaction list `8wi4-bsy4` |
| PLUTO | 64uk-42ks | 2026-08-24 | 858,284 | current release only | BBL | Latest release only on Socrata, historical releases via DCP. **`bbl` is stored as text like `'3085280034.00000000'`**: cast with `try_cast(bbl as double)::bigint` before joining to 10-digit BBLs |
| Building footprints | 5zhs-2jue | 2026-11-08 | 1,082,972 | | BIN, base_bbl, mappluto_bbl | height_roof, construction_year, geometry |

## Phase 1 pull (2026-11-13 to 2026-11-14 UTC)

Raw Parquet in `data/raw/<name>/` (gitignored, 871 MB, all columns as strings), pulled by `pipelines/ingest/pull_socrata.py` with keyset paging on Socrata's `:id`. Re-run the audit with `make audit` (output: `data_audit.md`). The manifest `pulled_at` for `hpd_violations` and `hpd_complaints` shows 2026-11-14 00:05 UTC only because a resumed run rewrote it; both finished earlier on 2026-11-13.

Scope: **Bronx + Brooklyn, 2018 onward** (311: 2020 onward, which is all it holds), except four tables pulled **citywide** because they are small or have no usable borough filter: `hpd_omo_charges`, `hpd_vacate_orders`, `hpd_aep`, `hpd_reg_contacts`.

| Name | Rows pulled | Server count at check | Scope / filter | Unique key and duplicates found |
|---|---|---|---|---|
| hpd_violations | 4,715,498 | 4,716,962 (+1,464 added after the pull) | boroid 2,3; inspectiondate 2018-01-01 to 2026 | violationid: 0 duplicates |
| hpd_complaints | 4,099,685 | cursor-range count matches exactly (full count(*) times out) | borough BRONX, BROOKLYN; received 2018+ | problem_id: 0 duplicates (2,408,241 distinct complaints) |
| c311_hpd | 2,928,618 | 2,926,894 earlier (+1,724 added since) | agency HPD, BX+BK, created 2018+ | unique_key: 0 duplicates |
| evictions | 67,769 | 67,769 | BX+BK, executed 2018+ | no id column |
| hpd_litigations | 52,387 | 52,387 | boroid 2,3; caseopendate 2018+ | litigationid: 0 duplicates |
| hpd_omo_charges | 517,013 | 517,013 | citywide | omoid: 0 duplicates |
| hpd_vacate_orders | 9,002 | 8,988 earlier (+14 added since) | citywide | (building_id, vacate_order_number): 0 duplicates |
| hpd_aep | 4,387 | 4,387 | citywide | (building_id, aep_start_date): **1 duplicate** |
| hpd_registrations | 106,661 | 106,661 | boroid 2,3 | registrationid: **5 duplicates** |
| hpd_reg_contacts | 744,753 | 744,753 | citywide | registrationcontactid: **1,451 duplicates** (2,381 rows involved, 1,993 distinct full rows: 388 exact repeats plus conflicting versions) |
| dob_violations | 256,821 | 256,821 | boro 2,3; issue_date 2018+ | isn_dob_bis_viol: 0 duplicates |
| pluto | 365,468 | 365,468 | borough BX, BK | bbl: 0 duplicates |

The duplicates are in the source: keyset paging cannot repeat a row, so staging needs an explicit dedupe rule (latest version per key for registrations and contacts).

### Bad and odd dates (what survived the filters)
- `hpd_violations.currentstatusdate`: 23 future values (`2108-09-07` on "NOV CERTIFIED LATE", `9202-11-10`).
- `hpd_litigations.caseopendate`: 2 values in 2030. `findingdate`: 202 values in a different format (`MM/DD/YYYY HH:MM:SS`), parseable, not bad.
- `hpd_vacate_orders.vacate_effective_date`: 15 future values, up to 2040.
- `hpd_omo_charges.omoawarddate`: 213 values before 2000, including year 0910. `omocreatedate` has 305 before 2000 (legitimately old).
- `dob_violations.issue_date`: 1 unparseable value (`33218262`). DOB dates are `YYYYMMDD` text.
- `hpd_registrations.registrationenddate`: 67,647 future values (expected, registrations run forward).
- Excluded by the 2018 filter, checked on the server: Bronx+Brooklyn HPD violations before 2018 number 2,938,679; 352,703 are before 2000, of which 134 are before 1970 (minimum year 0217; also 1903, 1909, 1930), and 185,793 fall in 1970-1989 (likely legacy records, not necessarily bad). HPD complaints have 0 rows before 2000.

### BBL quality and PLUTO coverage (Bronx/Brooklyn PLUTO)
Distinct BBLs found in PLUTO: hpd_violations 99.59%, hpd_complaints 99.54%, c311_hpd 99.21%, evictions 99.04% of distinct BBLs but only 91.4% of rows (7.5% of eviction rows have no bbl), hpd_litigations 99.82%, hpd_registrations 99.85% (built from block/lot), dob_violations 93.86% (built). hpd_omo_charges 60.2%, hpd_vacate_orders 59.4% and hpd_aep 78.0% are low only because they were pulled citywide. Unmatched BBLs that look like condo unit lots (lot >= 1001) are few (8 to 12 per table, 940 in OMO, 1,014 in DOB).

### Text
HPD `novdescription`: median 184 characters, 50.7% of rows distinct after lowercasing and digits to `#`; DOB `description`: 9.7% distinct, 14.6% null. See `PROJECT_PLAN.md` section 7.

## Access
- Public Socrata SODA API works without a key but is rate-limited and returned intermittent 503s on aggregate queries; use bulk CSV/Parquet export for the pipeline and an app token for incremental refreshes.
- All checks above were run live against data.cityofnewyork.us.

## Still to verify (Phase 1)
ECB/OATH violations, DOF tax liens and exemptions, rent stabilization building lists, heat/hot-water sensor data, FDNY incidents, DOHMH rat inspections, Local Law 84 energy data, PLUTO historical releases, ACS tract demographics (Census, not NYC Open Data), 311 bbl completeness, ACRIS Legals/Parties row counts.
