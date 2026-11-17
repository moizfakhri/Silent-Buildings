import pandas as pd

from nycdistress.sales import build_cohorts, quarter_index


def make(tmp_path, rows, spine):
    d = tmp_path / "dof"
    d.mkdir()
    cols = ["bbl", "sale_date", "sale_price", "building_class_category", "apartment_number"]
    pd.DataFrame(rows, columns=cols).to_parquet(d / "part-0.parquet")
    sp = tmp_path / "spine.parquet"
    pd.DataFrame(spine, columns=["bbl", "unitsres"]).to_parquet(sp)
    return str(d / "part-*.parquet"), str(sp)


W = "07 RENTALS - WALKUP APARTMENTS"


def test_quarter_index():
    assert quarter_index(2018, 1) == 0 and quarter_index(2018, 12) == 3 and quarter_index(2020, 5) == 9


def test_cohort_rules(tmp_path):
    rows = [
        ["2000000001", "2021-05-10", "900000", W, None],            # clean first sale, mid-window -> treated, q0 = 13
        ["2000000002", "2021-05-10", "900000", W, "4B"],            # apartment-level: not a building ownership change -> ignored, the lot stays a control
        ["2000000003", "2021-05-10", "50000", W, None],             # below the price floor
        ["2000000004", "2021-05-10", "200000", W, None],            # 200k < 25k * 10 units -> not arms-length by the per-unit rule
        ["2000000005", "2021-05-10", "900000", W, None],            # two sales a year apart -> second sale inside the window -> dropped
        ["2000000005", "2022-05-10", "950000", W, None],
        ["2000000006", "2018-03-01", "900000", W, None],            # too early: fewer than 8 quarters before
        ["2000000007", "2025-12-01", "900000", W, None],            # too late: fewer than 8 quarters after
        ["2000000008", "2021-05-10", "900000", "01 ONE FAMILY DWELLINGS", None],  # wrong category
    ]
    spine = [[f"200000000{i}", 10 if i == 4 else 6] for i in range(1, 9)] + [["2000000009", 6]]
    dof, sp = make(tmp_path, rows, spine)
    cohort, never, steps = build_cohorts(dof, sp)
    assert dict(cohort) == {"2000000001": 13}
    # controls = lots with no whole-building DOF row at all (priced or not); apartment-level rows are ignored
    assert "2000000009" in never and "2000000002" in never
    assert not {"2000000001", "2000000003", "2000000004", "2000000005", "2000000006", "2000000007"} & set(never)
    # lot 8 (one-family class) is not a whole-building row, so it can serve as a control
    assert "2000000008" in never
    assert dict(steps)["DOF sale rows in the data"] == len(rows)
