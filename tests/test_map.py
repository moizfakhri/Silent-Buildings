import importlib.util
import json
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("build_map", ROOT / "pipelines" / "build_map.py")
bm = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bm)


def test_geometry_parses_json_and_the_old_python_repr_and_rounds():
    gj = '{"type": "Polygon", "coordinates": [[[-73.1234567891, 40.1], [-73.2, 40.2], [-73.3, 40.1], [-73.1234567891, 40.1]]]}'
    rep = "{'type': 'Polygon', 'coordinates': [[[-73.1234567891, 40.1], [-73.2, 40.2], [-73.3, 40.1], [-73.1234567891, 40.1]]]}"
    a, b = bm.parse_geom(gj), bm.parse_geom(rep)
    assert a == b and a["type"] == "Polygon"
    assert bm.round_coords(a["coordinates"])[0][0] == [-73.123457, 40.1]


def test_three_digit_strings_and_percentile_codes():
    assert bm.three([0, 5, 123, 998, 999]) == "000005123998999"
    m = np.array([[1.0, np.nan], [2.0, 5.0], [3.0, 7.0], [4.0, 9.0]])
    c = bm.percentile_codes(m)
    assert c[:, 0].tolist() == sorted(c[:, 0].tolist()) and c[0, 1] == 999          # NaN -> 999, ranks increase with the value
    assert c.max() <= 999 and (c[1:, 1] < 999).all()


def test_committed_sample_has_the_documented_format_and_no_owner_fields():
    sample = ROOT / "app" / "web" / "data" / "sample"
    if not (sample / "buildings.geojson").exists():
        pytest.skip("map data not built")
    g = json.loads((sample / "buildings.geojson").read_text())
    n = len(g["snapshots"])
    assert n == 16 and g["features"]
    allowed = {"b", "n", "bo", "cd", "u", "yb", "h", "r", "c", "g", "a", "m", "sf", "ab"}
    for f in g["features"][:500]:
        p = f["properties"]
        assert set(p) == allowed                                                    # nothing else (no owner or name fields) in the tiles
        for k in "rcgam":
            assert len(p[k]) == 3 * n and p[k].isdigit()
        assert len(p["sf"]) == n and len(p["ab"]) == n and set(p["sf"] + p["ab"]) <= {"0", "1"}
        assert p["h"] >= 0.9 and len(p["b"]) == 10
    facts = json.loads((sample / "facts.json").read_text())
    rec = next(iter(facts.values()))
    assert set(rec) >= {"risk", "cond", "gap", "nacc", "silent", "blocked", "open_viol", "viol12", "complaints12"}
    banned = ("owner", "name", "landlord", "contact", "corporation", "tenant")
    assert not any(b in k.lower() for k in rec for b in banned)
    assert all(len(rec[k]) == n for k in ("risk", "cond", "gap", "nacc", "complaints12"))


def test_districts_file_has_30_districts_with_aggregates_only():
    p = ROOT / "app" / "web" / "data" / "districts.json"
    if not p.exists():
        pytest.skip("map data not built")
    d = json.loads(p.read_text())
    assert len(d["features"]) == 30
    props = d["features"][0]["properties"]
    assert set(props) == {"cd", "bo", "n", "v"} and set(props["v"]) == {"risk", "cond", "gap", "nacc", "comp", "silent"}
