"""Read campaign dumps (Alice -dump dirs, or anything else that writes the same CSVs): one schema for both.

A campaign is a directory with nations.csv[.zst], prices.csv[.zst], provinces.csv[.zst] and, from Alice, wars.csv[.zst].
Columns are those written by Alice's dump_month (src/headless_run.hpp). Tables are cached as parquet in CACHE
(keyed by the source file's path, size and mtime), so a rerun reads each dump once.
"""
import hashlib, io, os, subprocess
from multiprocessing import Pool
from pathlib import Path
import pandas as pd

CACHE = Path(os.environ.get("ANALYSIS_CACHE", Path.home() / ".cache/alice-analysis"))

# optional named campaign sets: name -> (root dir, last dump year a campaign must reach to count as complete)
SETS = {}


def _src(d, name):
    for p in (d / f"{name}.csv.zst", d / f"{name}.csv"):
        if p.exists():
            return p
    return None


def table(d, name):
    """One dump table of one campaign as a DataFrame ('date' parsed for nations/prices/provinces)."""
    p = _src(Path(d), name)
    if p is None:
        raise FileNotFoundError(f"{d}/{name}.csv[.zst]")
    st = p.stat()
    key = hashlib.sha1(f"{p.resolve()}|{st.st_size}|{st.st_mtime_ns}".encode()).hexdigest()[:16]
    c = CACHE / f"{name}-{key}.parquet"
    if c.exists():
        return pd.read_parquet(c)
    raw = subprocess.run(["zstd", "-dc", p], capture_output=True, check=True).stdout if p.suffix == ".zst" else p.read_bytes()
    df = pd.read_csv(io.BytesIO(raw), keep_default_na=False, na_values=[""] if name != "nations" else [])
    if name in ("nations", "prices", "provinces"):
        df["date"] = pd.to_datetime(df["date"])
        for col in ("tag", "owner", "controller", "good"):
            if col in df:
                df[col] = df[col].astype("category")
    CACHE.mkdir(parents=True, exist_ok=True)
    tmp = c.with_suffix(f".tmp{os.getpid()}")
    df.to_parquet(tmp); tmp.rename(c)
    return df


def last_year(d):
    p = _src(Path(d), "nations")
    if p is None:
        return None
    cmd = f"zstd -dc '{p}' | tail -1" if p.suffix == ".zst" else f"tail -1 '{p}'"
    out = subprocess.run(cmd, shell=True, capture_output=True, text=True).stdout
    return int(out[:4]) if out[:4].isdigit() else None


def campaigns(root, min_last_year=None, n=None):
    """Campaign dirs under root, sorted, skipping failed.txt entries and runs that stop before min_last_year."""
    root = Path(root)
    failed = set((root / "failed.txt").read_text().split()) if (root / "failed.txt").exists() else set()
    out = []
    for d in sorted(p for p in root.iterdir() if p.is_dir()):
        if d.name in failed or d.name[1:] in failed or _src(d, "nations") is None:
            continue
        if min_last_year is not None and (last_year(d) or 0) < min_last_year:
            continue
        out.append(d)
        if n and len(out) == n:
            break
    return out


def resolve_sets(specs=None, n=None):
    """specs: list of 'Name' (from SETS) or 'Name=/path[:min_last_year]'. Returns {name: [campaign dirs]}."""
    res = {}
    if not specs and not SETS:
        raise SystemExit("give at least one --set Name=/root[:min_last_year]")
    for s in specs or list(SETS):
        if "=" in s:
            name, rest = s.split("=", 1)
            path, _, y = rest.partition(":")
            root, y = Path(path), (int(y) if y else None)
        else:
            name, (root, y) = s, SETS[s]
        res[name] = campaigns(root, y, n)
    return res


def map_campaigns(fn, dirs, procs=None):
    """fn(campaign_dir) -> small result, run in parallel; keeps memory per process to one campaign."""
    with Pool(procs or int(os.environ.get("PROCS", 8))) as pool:
        return pool.map(fn, dirs)
