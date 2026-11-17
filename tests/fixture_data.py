"""Tiny synthetic raw dataset (same column names and all-string types as data/raw/*) so the Phase 2
pipeline can be tested without the real data. Deterministic for a given seed.

Includes hand-placed edge cases around the snapshot 2020-01-01: events exactly on t, one day after,
exactly t +/- 12 months, plus the source quirks seen in the real data (PLUTO bbl as
'3085280034.00000000', duplicate AEP rows, vacate dates in the future, a litigation dated 2030,
violations with no stored bbl, complaints closed before they were received).
"""
import random
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

START, END = date(2018, 1, 1), date(2026, 10, 31)
N_LOTS = 40
EDGE_BBL = 3000010001  # lot 0 carries the hand-placed edge cases
STR = "string"


def iso(d):
    return None if d is None else f"{d.isoformat()}T00:00:00.000"


def rand_date(rng, lo=START, hi=END):
    return lo + timedelta(days=rng.randrange((hi - lo).days + 1))


def lot_bbl(i):
    return (3 if i % 4 else 2) * 1_000_000_000 + (1000 + i) * 10000 + 1


def make_frames(seed=1):
    rng = random.Random(seed)
    lots = [lot_bbl(i) for i in range(N_LOTS)]
    lots[0] = EDGE_BBL

    # ---------------------------------------------------------------- PLUTO
    pl = []
    for i, b in enumerate(lots):
        pl.append(dict(
            bbl=f"{b}.00000000", borough="BX" if b // 10**9 == 2 else "BK",
            cd=str(301 + i % 5), ct2010=str(100 + i), unitsres=str(2 if i == 3 else rng.choice([3, 6, 12, 40])), unitstotal="10",
            bldgclass=rng.choice(["C1", "C3", "D1", "S5"]), landuse="02" if i != 4 else "06",
            yearbuilt=str(2021 if i == 5 else 0 if i == 6 else rng.randrange(1900, 1990)),
            numfloors="3.5000000", lotarea="2500", bldgarea="5000"))
    pluto = pd.DataFrame(pl)

    def lot_cols(b):
        return dict(boro=str(b // 10**9), block=str((b // 10**4) % 10**5), lot=str(b % 10**4))

    # ---------------------------------------------------------------- HPD violations
    vio = []
    vid = 0
    for b in lots:
        for _ in range(rng.randrange(0, 40)):
            vid += 1
            d = rand_date(rng)
            closed = rng.random() < 0.7
            cs = d + timedelta(days=rng.randrange(0, 900)) if closed else d + timedelta(days=rng.randrange(0, 60))
            if vid % 211 == 0:
                cs = date(2108, 9, 7)  # garbage future status date
            lc = lot_cols(b)
            vio.append(dict(violationid=str(vid), bbl=None if vid % 17 == 0 else str(b), boroid=lc["boro"], block=lc["block"],
                            lot=lc["lot"], **{"class": rng.choice(["A", "B", "C", "I"])}, inspectiondate=iso(d),
                            currentstatusdate=iso(cs), violationstatus="Close" if closed else "Open"))
    # edge: violations exactly at t=2020-01-01 +/- 12m (class A)
    for i, d in enumerate([date(2019, 1, 1), date(2019, 1, 2), date(2020, 1, 1), date(2020, 1, 2)]):
        lc = lot_cols(EDGE_BBL)
        vio.append(dict(violationid=f"edge-v{i}", bbl=str(EDGE_BBL), boroid=lc["boro"], block=lc["block"], lot=lc["lot"],
                        **{"class": "A"}, inspectiondate=iso(d), currentstatusdate=iso(date(2020, 1, 1)),
                        violationstatus="Close"))
    violations = pd.DataFrame(vio)

    # ---------------------------------------------------------------- HPD complaints
    cats = ["HEAT/HOT WATER", "UNSANITARY CONDITION", "PLUMBING", "PAINT/PLASTER", "DOOR/WINDOW", "WATER LEAK",
            "ELECTRIC", "GENERAL", "SAFETY"]
    texts = ["The Department of Housing Preservation and Development was not able to gain access to inspect the following conditions.",
             "The Department of Housing Preservation and Development inspected the following conditions. No violations were issued.",
             "HPD inspected this condition so the complaint has been closed. Violations were issued."]
    cmp_rows, pid, cid = [], 0, 0
    for b in lots:
        for _ in range(rng.randrange(0, 15)):
            cid += 1
            rd = rand_date(rng)
            for _p in range(rng.randrange(1, 4)):
                pid += 1
                closed_p = rng.random() < 0.9
                closed_c = closed_p and rng.random() < 0.97
                ps = rd + timedelta(days=rng.randrange(-3 if pid % 40 == 0 else 0, 60))
                cs = ps + timedelta(days=rng.randrange(0, 30))
                lc = lot_cols(b)
                cmp_rows.append(dict(
                    problem_id=str(pid), complaint_id=str(cid), received_date=iso(rd),
                    borough="BRONX" if b // 10**9 == 2 else "BROOKLYN", block=lc["block"], lot=lc["lot"],
                    bbl=None if pid % 29 == 0 else str(b), type=rng.choice(["EMERGENCY", "NON EMERGENCY", "IMMEDIATE EMERGENCY"]),
                    major_category=rng.choice(cats), complaint_status="CLOSE" if closed_c else "OPEN",
                    problem_status="CLOSE" if closed_p else "OPEN", complaint_status_date=iso(cs),
                    problem_status_date=None if pid % 97 == 0 else iso(ps), status_description=rng.choice(texts)))
    for i, d in enumerate([date(2019, 1, 1), date(2019, 1, 2), date(2020, 1, 1), date(2020, 1, 2), date(2021, 1, 1), date(2021, 1, 2)]):
        lc = lot_cols(EDGE_BBL)
        cmp_rows.append(dict(problem_id=f"edge-p{i}", complaint_id=f"edge-c{i}", received_date=iso(d), borough="BROOKLYN",
                             block=lc["block"], lot=lc["lot"], bbl=str(EDGE_BBL), type="EMERGENCY",
                             major_category="HEAT/HOT WATER", complaint_status="CLOSE", problem_status="CLOSE",
                             complaint_status_date=iso(d + timedelta(days=1)), problem_status_date=iso(d),
                             status_description=texts[0]))
    complaints = pd.DataFrame(cmp_rows)

    # ---------------------------------------------------------------- 311
    c311 = pd.DataFrame([dict(unique_key=str(i), bbl=str(b), created_date=iso(rand_date(rng, date(2020, 1, 1))),
                              complaint_type=rng.choice(["HEAT/HOT WATER", "PLUMBING", "GENERAL"]))
                         for i, b in enumerate(rng.choices(lots, k=400))])

    # ---------------------------------------------------------------- evictions
    ev = pd.DataFrame([dict(bbl=str(b), executed_date=iso(rand_date(rng)),
                            residential_commercial_ind=rng.choice(["Residential", "Residential", "Commercial"]))
                       for b in rng.choices(lots, k=120)])

    # ---------------------------------------------------------------- DOB
    types = ["LBLVIO-LOW PRESSURE BOILER BOILER REQUIRED", "E-ELEVATOR ELEVATORREQUIRED",
             "C-CONSTRUCTION OTHER OPTIONAL", "AEUHAZ1-FAIL TO CERTIFY CLASS 1 NONE", "IMEGNCY-IMMEDIATE EMERGENCY",
             "UB-UNSAFE BUILDINGS NONE", "FISPHAZ-HAZARDOUS CONDITION (FACADE)"]
    dob = []
    for i, b in enumerate(rng.choices(lots, k=150)):
        lc = lot_cols(b)
        dob.append(dict(isn_dob_bis_viol=str(i), boro=lc["boro"], block=lc["block"].rjust(5, "0"), lot=lc["lot"].rjust(5, "0"),
                        issue_date=rand_date(rng).strftime("%Y%m%d"), violation_type=(vt := rng.choice(types)),
                        violation_type_code=vt.split("-")[0]))
    dob.append(dict(isn_dob_bis_viol="bad", boro="3", block="01000", lot="00001", issue_date="33218262", violation_type=types[0],
                    violation_type_code="LBLVIO"))
    dob_v = pd.DataFrame(dob)

    # ---------------------------------------------------------------- litigations
    lit = [dict(litigationid=str(i), bbl=str(b), caseopendate=iso(rand_date(rng))) for i, b in enumerate(rng.choices(lots, k=90))]
    lit += [dict(litigationid="e1", bbl=str(EDGE_BBL), caseopendate=iso(date(2030, 10, 5))),   # bad future date: dropped
            dict(litigationid="e2", bbl=None, caseopendate=iso(date(2021, 1, 1)))]               # no bbl: dropped
    litig = pd.DataFrame(lit)

    # ---------------------------------------------------------------- vacate orders
    vac = []
    for i, b in enumerate(rng.choices(lots, k=60)):
        d = rand_date(rng, date(2012, 1, 1))
        r = d + timedelta(days=rng.randrange(0, 700)) if rng.random() < 0.5 else None
        vac.append(dict(building_id=str(i), vacate_order_number=str(i), bbl=str(b), vacate_effective_date=iso(d),
                        actual_rescind_date=iso(r)))
    vac.append(dict(building_id="x", vacate_order_number="x", bbl=str(EDGE_BBL), vacate_effective_date=iso(date(2040, 8, 20)),
                    actual_rescind_date=None))                                                   # future: dropped
    vacate = pd.DataFrame(vac)

    # ---------------------------------------------------------------- AEP (with an exact duplicate)
    aep = []
    for i, b in enumerate(rng.sample(lots, 12)):
        d = rand_date(rng, date(2012, 1, 1), date(2026, 2, 1))
        r = d + timedelta(days=rng.randrange(200, 1500)) if rng.random() < 0.6 else None
        aep.append(dict(building_id=str(i), bbl=str(b), aep_start_date=iso(d), discharge_date=iso(r)))
    aep.append(dict(aep[0]))
    aep_df = pd.DataFrame(aep)

    # ---------------------------------------------------------------- OMO
    omo = []
    for i, b in enumerate(rng.choices(lots, k=300)):
        lc = lot_cols(b)
        omo.append(dict(omoid=str(i), bbl=None if i % 31 == 0 else str(b), boro_id=lc["boro"], block=lc["block"], lot=lc["lot"],
                        omocreatedate=iso(rand_date(rng, date(1999, 1, 1))), isaep="AEP" if i % 9 == 0 else None))
    lc = lot_cols(EDGE_BBL)
    for j, d in enumerate([date(2020, 1, 1), date(2020, 1, 2), date(2021, 1, 1), date(2021, 1, 2)]):
        omo.append(dict(omoid=f"edge{j}", bbl=str(EDGE_BBL), boro_id=lc["boro"], block=lc["block"], lot=lc["lot"],
                        omocreatedate=iso(d), isaep=None))
    omo_df = pd.DataFrame(omo)

    # ---------------------------------------------------------------- registrations / contacts (dup rows)
    reg = pd.DataFrame([dict(registrationid="1", buildingid="10", boroid="3", block="1000", lot="1", bin="3000001",
                             lastregistrationdate=iso(date(2025, 1, 1)), registrationenddate=iso(date(2026, 9, 1))),
                        dict(registrationid="1", buildingid="10", boroid="3", block="1000", lot="1", bin="3000001",
                             lastregistrationdate=iso(date(2020, 1, 1)), registrationenddate=iso(date(2021, 9, 1)))])
    contacts = pd.DataFrame([dict(registrationcontactid="1", registrationid="1", type="CorporateOwner", contactdescription="CO-OP",
                                  corporationname="ACME LLC", firstname=None, lastname=None, title=None, businesshousenumber="1",
                                  businessstreetname="MAIN ST", businessapartment=None, businesszip="10001"),
                             dict(registrationcontactid="1", registrationid="1", type="CorporateOwner", contactdescription="CO-OP",
                                  corporationname=None, firstname=None, lastname=None, title=None, businesshousenumber=None,
                                  businessstreetname=None, businessapartment=None, businesszip=None),
                             dict(registrationcontactid="2", registrationid="1", type="Agent", contactdescription=None,
                                  corporationname=None, firstname="A", lastname="B", title=None, businesshousenumber=None,
                                  businessstreetname=None, businessapartment=None, businesszip=None)])

    return dict(pluto=pluto, hpd_violations=violations, hpd_complaints=complaints, c311_hpd=c311, evictions=ev,
                dob_violations=dob_v, hpd_litigations=litig, hpd_vacate_orders=vacate, hpd_aep=aep_df,
                hpd_omo_charges=omo_df, hpd_registrations=reg, hpd_reg_contacts=contacts)


def write_raw(frames, raw_dir):
    """Write each frame as data/raw-style Parquet (all strings) under raw_dir/<name>/part-00000.parquet."""
    for name, df in frames.items():
        d = Path(raw_dir) / name
        d.mkdir(parents=True, exist_ok=True)
        for f in d.glob("*.parquet"):
            f.unlink()
        df.astype(STR).to_parquet(d / "part-00000.parquet", index=False)


def make_edge_frames():
    """Only the hand-placed edge rows for EDGE_BBL (everything else empty), for exact hand-checked asserts."""
    full = make_frames()
    out = {}
    for name, df in full.items():
        if name == "pluto":
            out[name] = df[df.bbl == f"{EDGE_BBL}.00000000"]
        elif name == "hpd_violations":
            out[name] = df[df.violationid.str.startswith("edge-v")]
        elif name == "hpd_complaints":
            out[name] = df[df.problem_id.str.startswith("edge-p")]
        elif name == "hpd_omo_charges":
            out[name] = df[df.omoid.str.startswith("edge")]
        else:
            out[name] = df.iloc[0:0]
    return out
