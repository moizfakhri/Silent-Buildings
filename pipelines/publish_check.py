"""Pre-publication sanity check (does NOT publish or run any git command).

    python pipelines/publish_check.py

Applies .gitignore (via pathspec) to work out which files WOULD be tracked, then reports:
  - how many files and how many MB would be tracked, and the largest ones
  - tracked data files that should never be committed (parquet, duckdb, pmtiles, raw csv)
  - secrets: well-known key patterns, and any value from .env appearing in a tracked file (values are never printed)
  - personal details: local absolute home-folder paths, e-mail addresses
  - building-level content: 10-digit BBL-like tokens in tracked text files, and name-like columns in tracked CSV headers
Writes reports/publish_check.json and exits 1 if a secret or a data file would be tracked.
"""
import json
import re
import sys
from pathlib import Path

import pathspec

ROOT = Path(__file__).resolve().parents[1]
ALWAYS_SKIP = {".git"}
TEXT_EXT = {".py", ".md", ".txt", ".json", ".csv", ".sql", ".toml", ".yml", ".yaml", ".html", ".css", ".js", ".ipynb", ".geojson", ".example", ".cfg", ".ini", ".sh", ""}
DATA_EXT = {".parquet", ".duckdb", ".pmtiles", ".feather", ".pkl", ".joblib", ".npy", ".npz", ".lgb", ".sqlite", ".db"}
SECRET_PATTERNS = {
    "anthropic_key": re.compile(rb"sk-ant-[A-Za-z0-9_\-]{20,}"),
    "openai_style_key": re.compile(rb"sk-[A-Za-z0-9]{32,}"),
    "github_token": re.compile(rb"gh[pousr]_[A-Za-z0-9]{30,}"),
    "aws_access_key": re.compile(rb"AKIA[0-9A-Z]{16}"),
    "private_key_block": re.compile(rb"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    "assigned_secret": re.compile(rb"(?i)(api[_-]?key|secret|token|password)\s*[=:]\s*['\"]?[A-Za-z0-9_\-]{16,}"),
}
BBL = re.compile(rb"(?<![0-9])[1-5][0-9]{9}(?![0-9])")
LOCAL_PATH = re.compile(rb"/Users/[A-Za-z0-9._-]+")
EMAIL = re.compile(rb"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
NAMEISH = re.compile(r"(?i)owner|respondent|registrant|contact|marshal|tenant_name|first_?name|last_?name|corporation|business_name|person")


def tracked_files():
    spec = pathspec.PathSpec.from_lines("gitwildmatch", (ROOT / ".gitignore").read_text().splitlines())
    out = []
    for p in sorted(ROOT.rglob("*")):
        rel = p.relative_to(ROOT)
        if any(part in ALWAYS_SKIP for part in rel.parts) or not p.is_file():
            continue
        if spec.match_file(str(rel)) or any(spec.match_file(str(parent) + "/") for parent in rel.parents if str(parent) != "."):
            continue
        out.append(rel)
    return out


def env_values():
    f = ROOT / ".env"
    vals = []
    if f.exists():
        for line in f.read_text().splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                v = line.split("=", 1)[1].strip().strip("'\"")
                if len(v) >= 8:
                    vals.append(v.encode())
    return vals


def main():
    files = tracked_files()
    sizes = {str(f): (ROOT / f).stat().st_size for f in files}
    total = sum(sizes.values())
    res = dict(n_files=len(files), total_mb=round(total / 1e6, 2), largest=sorted(((round(s / 1e6, 2), f) for f, s in sizes.items()), reverse=True)[:12],
               over_5mb=[f for f, s in sizes.items() if s > 5e6])
    res["data_files_tracked"] = [str(f) for f in files if f.suffix.lower() in DATA_EXT]
    envs = env_values()
    secrets, bbl_hits, name_cols, personal = [], {}, [], []
    for f in files:
        data = None
        if f.suffix.lower() in TEXT_EXT and sizes[str(f)] < 20e6:
            data = (ROOT / f).read_bytes()
        if data is None:
            continue
        for name, rx in SECRET_PATTERNS.items():
            if name == "assigned_secret" and f.suffix == ".md":
                continue
            m = rx.search(data)
            if m:
                secrets.append(dict(file=str(f), pattern=name))
        if any(v in data for v in envs):
            secrets.append(dict(file=str(f), pattern="value_from_.env"))
        if f.suffix != ".js" and "vendor" not in f.parts:  # vendored libraries contain example addresses
            for label, rx in (("local_path", LOCAL_PATH), ("email", EMAIL)):
                n_p = len(rx.findall(data))
                if n_p:
                    personal.append(dict(file=str(f), kind=label, count=n_p))
        n = len(BBL.findall(data))
        if n:
            bbl_hits[str(f)] = n
        if f.suffix == ".csv":
            header = data.split(b"\n", 1)[0].decode("utf-8", "ignore")
            hit = [c for c in header.split(",") if NAMEISH.search(c)]
            if hit:
                name_cols.append(dict(file=str(f), columns=hit))
    res.update(secrets=secrets, personal_details=personal, bbl_like_tokens=bbl_hits, name_like_csv_columns=name_cols,
               unrelated_root_folders=[d.name for d in ROOT.iterdir() if d.is_dir() and d.name in ("rats_vs_trash_bins", "street-redesign-safety") and any(str(f).startswith(d.name + "/") for f in files)],
               ignore_gaps=[d for d in (".pytest_cache", ".ruff_cache") if (ROOT / d).exists() and any(str(f).startswith(d) for f in files)])
    (ROOT / "reports").mkdir(exist_ok=True)
    (ROOT / "reports" / "publish_check.json").write_text(json.dumps(res, indent=1))
    print(f"would track {res['n_files']} files, {res['total_mb']} MB")
    print("largest:", *[f"{mb} MB {f}" for mb, f in res["largest"][:6]], sep="\n  ")
    print("data files tracked:", res["data_files_tracked"] or "none")
    print("secrets:", res["secrets"] or "none")
    print("personal details (local paths, e-mails):", personal or "none")
    print("files with BBL-like tokens:", {k: v for k, v in sorted(bbl_hits.items(), key=lambda kv: -kv[1])[:10]} or "none")
    print("name-like CSV columns:", name_cols or "none")
    print("ignore gaps:", res["ignore_gaps"] or "none")
    if res["unrelated_root_folders"]:
        print("unrelated root folders (decide before publishing):", res["unrelated_root_folders"])
    return 1 if (secrets or res["data_files_tracked"] or res["over_5mb"]) else 0


if __name__ == "__main__":
    sys.exit(main())
