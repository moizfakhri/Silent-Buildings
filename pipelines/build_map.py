"""Phase 6: build the data behind the 3D map (app/web/data).

    python pipelines/build_map.py            # about 5 minutes; needs footprints (make ingest NAMES=building_footprints),
                                             # scores_phase3.parquet, scores_phase4.parquet / the Phase 4 analysis frame, and tippecanoe

Outputs under app/web/data/
  buildings.pmtiles    vector tiles, layers `scored` (lots in the spine, with 16-snapshot score strings) and `context` (every other footprint)
  facts/<prefix>.json  per-block public-record counts and score series, fetched on click (gitignored: large)
  districts.json       30 community-district shapes derived from the footprints (approximate) with aggregate series (small)
  sample/              one community district as plain GeoJSON + facts, so the site works without tiles (committed)

Each score series is a string of 16 three-digit numbers, one per snapshot (2022-01-01 .. 2025-10-01), so a snapshot slider only has to
slice a string. 999 means "no value". Per-building values are model estimates for research; no owner names are used anywhere.
"""
import ast
import json
import shutil
import subprocess
import time
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw" / "building_footprints"
PROC = ROOT / "data" / "processed"
OUT = ROOT / "app" / "web" / "data"
DEMOLISHED = {"Demolition", "Marked for Demolition", "Investigate Demolition"}
FACT_COLS = {  # name in facts -> (features column, decimals)
    "complaints12": ("loud_prob_n_12m", 0), "c311_12": ("loud_311_n_12m", 0), "open_viol": ("viol_open_n", 0), "viol12": ("viol_n_12m", 0),
    "viol_c12": ("viol_c_n_12m", 0), "evict12": ("evict_n_12m", 0), "dob12": ("dob_n_12m", 0), "omo_prior": ("prior_omo_n", 0),
    "litig_prior": ("prior_litig_n", 0), "vacate_prior": ("prior_vacate_n", 0), "aep_prior": ("prior_aep_n", 0),
}


def parse_geom(text):
    try:
        return json.loads(text)
    except ValueError:                       # footprints pulled before the pull code serialised nested values as JSON: Python repr
        return ast.literal_eval(text)


def round_coords(c, nd=6):
    if isinstance(c[0], (int, float)):
        return [round(c[0], nd), round(c[1], nd)]
    return [round_coords(x, nd) for x in c]


def three(a):
    return "".join(f"{int(v):03d}" for v in a)


def load_scores():
    """One frame of per-(bbl, snapshot) values for the 16 out-of-time snapshots."""
    con = duckdb.connect()
    p3 = f"read_parquet('{PROC / 'scores_phase3.parquet'}')"
    af = f"read_parquet('{PROC / 'phase4' / 'analysis_frame.parquet'}')"
    cols = ["bbl", "snapshot_date", "static_unitsres", "p_hat", "gap_rank", "silent", "access_blocked", "loud_nacc_share_12m", "loud_closed_n_12m",
            "community_district", "static_borough"] + sorted({c for c, _ in FACT_COLS.values()})
    df = con.sql(f"""SELECT a.{', a.'.join(cols)}, s.score AS risk
                     FROM {af} a JOIN {p3} s ON s.bbl = a.bbl AND CAST(s.snapshot_date AS DATE) = CAST(a.snapshot_date AS DATE)""").df()
    df["snapshot_date"] = pd.to_datetime(df["snapshot_date"])
    return df


def percentile_codes(mat):
    """0..998 percentile of each value within its snapshot column (NaN -> 999)."""
    out = np.full(mat.shape, 999, dtype=int)
    for j in range(mat.shape[1]):
        col = mat[:, j]
        ok = ~np.isnan(col)
        r = pd.Series(col[ok]).rank(method="average", pct=True).to_numpy()
        out[ok, j] = np.minimum((r * 998).astype(int), 998)
    return out


def main():
    t0 = time.time()
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "facts").mkdir(exist_ok=True)
    work = ROOT / "data" / "interim" / "map"
    work.mkdir(parents=True, exist_ok=True)

    df = load_scores()
    snaps = sorted(df.snapshot_date.unique())
    assert len(snaps) == 16
    spine = pd.read_parquet(PROC / "spine.parquet").set_index("bbl")
    bbls = np.array(sorted(df.bbl.unique()))
    bi = {b: i for i, b in enumerate(bbls)}
    nb = len(bbls)
    ri = df.bbl.map(bi).to_numpy()
    ci = pd.Index(snaps).get_indexer(df.snapshot_date)

    def mat(col):
        m = np.full((nb, 16), np.nan)
        m[ri, ci] = df[col].to_numpy(dtype=float)
        return m

    risk, phat, gap, nacc = mat("risk"), mat("p_hat"), mat("gap_rank"), mat("loud_nacc_share_12m")
    units = df.groupby("bbl").static_unitsres.first().reindex(bbls).to_numpy(dtype=float)
    comp_pu = mat("loud_prob_n_12m") / units[:, None]
    silent, blocked = mat("silent"), mat("access_blocked")
    codes = {
        "r": percentile_codes(risk), "c": percentile_codes(phat),
        "g": np.where(np.isnan(gap), 999, np.minimum(((np.nan_to_num(gap) + 1) / 2 * 998).astype(int), 998)),
        "a": np.where(np.isnan(nacc), 999, np.minimum((np.nan_to_num(nacc) * 998).astype(int), 998)),
        "m": np.where(np.isnan(comp_pu), 999, np.minimum((np.clip(np.nan_to_num(comp_pu), 0, 2) / 2 * 998).astype(int), 998)),
    }
    strs = {k: [three(v[i]) for i in range(nb)] for k, v in codes.items()}
    sf = ["".join("1" if x == 1 else "0" for x in np.nan_to_num(silent[i])) for i in range(nb)]
    ab = ["".join("1" if x == 1 else "0" for x in np.nan_to_num(blocked[i])) for i in range(nb)]
    print(f"score matrices built: {nb:,} lots x 16 snapshots ({time.time() - t0:.0f}s)", flush=True)

    # ------------------------------------------------------------------ footprints -> NDJSON (scored / context)
    cols = ["the_geom", "bin", "base_bbl", "mappluto_bbl", "height_roof", "construction_year", "last_status_type"]
    fp = pd.concat([pd.read_parquet(f, columns=cols) for f in sorted(RAW.glob("part-*.parquet"))], ignore_index=True)
    fp = fp[~fp.last_status_type.isin(DEMOLISHED)].reset_index(drop=True)
    fp["bbl"] = fp.base_bbl.astype(float).astype("int64").astype(str).str.zfill(10)
    alt = fp.mappluto_bbl.astype(float).astype("int64").astype(str).str.zfill(10)
    in_spine = fp.bbl.isin(bi)
    fp.loc[~in_spine & alt.isin(bi), "bbl"] = alt[~in_spine & alt.isin(bi)]
    fp["scored"] = fp.bbl.isin(bi)
    h = pd.to_numeric(fp.height_roof, errors="coerce").fillna(10.0).clip(lower=3.0) * 0.3048     # feet -> metres
    n_sc = n_ctx = 0
    sample_cd, sample_rows = None, []
    cd_counts = spine.community_district.value_counts()
    # a mid-sized district gives a sample that is neither trivial nor large
    sample_cd = (cd_counts.drop('nan', errors='ignore') - 1100).abs().idxmin()          # a district of about 1,100 lots keeps the committed sample small
    district_geoms = {}
    with open(work / "scored.ndjson", "w") as fs, open(work / "context.ndjson", "w") as fc:
        for geom_text, bin_, bbl, hm, yb, scored in zip(fp.the_geom, fp.bin, fp.bbl, h, fp.construction_year, fp.scored):
            g = parse_geom(geom_text)
            g["coordinates"] = round_coords(g["coordinates"])
            if scored:
                i = bi[bbl]
                sp = spine.loc[bbl]
                props = {"b": bbl, "n": str(bin_), "bo": sp.borough, "cd": str(sp.community_district), "u": int(units[i]), "yb": int(float(yb)) if pd.notna(yb) and float(yb) > 0 else 0,
                         "h": round(float(hm), 1), "r": strs["r"][i], "c": strs["c"][i], "g": strs["g"][i], "a": strs["a"][i], "m": strs["m"][i], "sf": sf[i], "ab": ab[i]}
                feat = {"type": "Feature", "geometry": g, "properties": props}
                fs.write(json.dumps(feat, separators=(",", ":")) + "\n")
                n_sc += 1
                district_geoms.setdefault(props["cd"], []).append(g)
                if props["cd"] == sample_cd:
                    sample_rows.append(feat)
            else:
                fc.write(json.dumps({"type": "Feature", "geometry": g, "properties": {"h": round(float(hm), 1)}}, separators=(",", ":")) + "\n")
                n_ctx += 1
    print(f"footprints: {n_sc:,} scored, {n_ctx:,} context ({time.time() - t0:.0f}s)", flush=True)

    # ------------------------------------------------------------------ facts shards (public-record counts and score series, per block)
    shards = {}
    fact_mats = {name: mat(col) for name, (col, _) in FACT_COLS.items()}
    sample_facts = {}
    for b in bbls:
        i = bi[b]
        sp = spine.loc[b]

        def arr(m, nd):
            return [None if np.isnan(x) else (int(x) if nd == 0 else round(float(x), nd)) for x in m[i]]
        rec = {"u": int(units[i]), "yb": int(sp.yearbuilt) if pd.notna(sp.yearbuilt) else None, "cls": str(sp.bldgclass), "cd": str(sp.community_district), "bo": sp.borough,
               "risk": arr(risk, 4), "cond": arr(phat, 5), "gap": arr(gap, 3), "nacc": arr(nacc, 2), "complaints_pu": arr(comp_pu, 2),
               "silent": [int(x) for x in np.nan_to_num(silent[i])], "blocked": [int(x) for x in np.nan_to_num(blocked[i])]}
        for name in FACT_COLS:
            rec[name] = arr(fact_mats[name], 0)
        shards.setdefault(b[:5], {})[b] = rec
        if str(sp.community_district) == sample_cd:
            sample_facts[b] = rec
    for k, v in shards.items():
        (OUT / "facts" / f"{k}.json").write_text(json.dumps(v, separators=(",", ":")))
    print(f"facts: {len(shards):,} shards ({time.time() - t0:.0f}s)", flush=True)

    # ------------------------------------------------------------------ district aggregates and approximate shapes
    from shapely.geometry import mapping, shape
    from shapely.ops import unary_union
    cd_of = np.array([str(spine.loc[b].community_district) for b in bbls])
    bo_of = np.array([spine.loc[b].borough for b in bbls])
    agg = {}
    for cd in sorted(set(cd_of)):
        m = cd_of == cd
        agg[cd] = {"risk": np.nanmean(risk[m], axis=0), "cond": np.nanmean(phat[m], axis=0), "gap": np.nanmean(gap[m], axis=0), "nacc": np.nanmean(nacc[m], axis=0),
                   "comp": np.nanmean(comp_pu[m], axis=0), "silent": np.nanmean(silent[m], axis=0), "n": int(m.sum())}
    feats = []
    for cd, geoms in district_geoms.items():
        if cd == "nan":                                  # 7 lots have no community district
            continue
        poly = unary_union([shape(g).buffer(0.0012) for g in geoms]).buffer(-0.0007).simplify(0.0002)
        a = agg[cd]
        # only the averages are stored: the page derives district colours from them (one scale per layer, zero-centred for the gap)
        feats.append({"type": "Feature", "geometry": mapping(poly), "properties": {
            "cd": cd, "bo": bo_of[cd_of == cd][0], "n": a["n"],
            "v": {k: [None if np.isnan(x) else round(float(x), 4) for x in a[k]] for k in ("risk", "cond", "gap", "nacc", "comp", "silent")}}})
    (OUT / "districts.json").write_text(json.dumps({"type": "FeatureCollection", "features": feats, "snapshots": [str(pd.Timestamp(s).date()) for s in snaps]}, separators=(",", ":")))
    print(f"districts: {len(feats)} ({time.time() - t0:.0f}s)", flush=True)

    # ------------------------------------------------------------------ the committed sample (one community district)
    sd = OUT / "sample"
    sd.mkdir(exist_ok=True)
    (sd / "buildings.geojson").write_text(json.dumps({"type": "FeatureCollection", "features": sample_rows, "snapshots": [str(pd.Timestamp(s).date()) for s in snaps]}, separators=(",", ":")))
    (sd / "facts.json").write_text(json.dumps(sample_facts, separators=(",", ":")))
    print(f"sample: community district {sample_cd}, {len(sample_rows):,} buildings ({time.time() - t0:.0f}s)", flush=True)

    # ------------------------------------------------------------------ vector tiles
    tipp = shutil.which("tippecanoe")
    if tipp:
        cmd = [tipp, "-o", str(OUT / "buildings.pmtiles"), "--force", "-Z11", "-z16", "--no-tile-size-limit", "--no-feature-limit", "--quiet",
               "-L", json.dumps({"file": str(work / "scored.ndjson"), "layer": "scored", "minzoom": 12, "maxzoom": 16}),
               "-L", json.dumps({"file": str(work / "context.ndjson"), "layer": "context", "minzoom": 14, "maxzoom": 16})]
        subprocess.run(cmd, check=True)
        print(f"buildings.pmtiles: {(OUT / 'buildings.pmtiles').stat().st_size / 1e6:.0f} MB ({time.time() - t0:.0f}s)", flush=True)
    else:
        print("tippecanoe not found: the site falls back to the sample GeoJSON", flush=True)
    (OUT / "meta.json").write_text(json.dumps({"snapshots": [str(pd.Timestamp(s).date()) for s in snaps], "sample_cd": sample_cd, "scored_buildings": n_sc,
                                               "context_buildings": n_ctx, "lots": nb, "built": time.strftime("%Y-%m-%dT%H:%M:%S")}))
    print(f"done in {(time.time() - t0) / 60:.1f} min", flush=True)


if __name__ == "__main__":
    main()
