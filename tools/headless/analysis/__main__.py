"""cd tools/headless && python -m analysis --set Vanilla=/runs/vanilla:1935 [--set HPM=/runs/hpm:1935] [--n 112] [--only econ,complexity] [--out DIR]"""
import argparse
from analysis.load import resolve_sets

ap = argparse.ArgumentParser()
ap.add_argument("--set", action="append", help="Name=/root[:min_last_year]: a batch output folder, campaigns that end before min_last_year are skipped")
ap.add_argument("--n", type=int, default=112, help="campaigns per set")
ap.add_argument("--only", default="econ,complexity")
ap.add_argument("--out", default="analysis_out")
a = ap.parse_args()
sets = resolve_sets(a.set, a.n)
print({k: len(v) for k, v in sets.items()}, flush=True)
for part in a.only.split(","):
    __import__(f"analysis.{part}", fromlist=["run"]).run(sets, a.out)
