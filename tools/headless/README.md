# Headless batch runs

Run many AI-only campaigns on Linux without a window, dump what happens each month, and plot the ensemble.

## One campaign

```
cd <folder with the game files and assets>   # same working directory the game normally runs from
./Alice <scenario>.bin -headless -seed 1 -threads 1 -fastdemo 1 -years 100 -dump out/s1
# or for a mod:  ./Alice --mod mod/GFM.mod -headless -seed 1 -threads 1 -years 100 -dump out/s1
```

| Flag | Meaning |
|---|---|
| `-headless` | no window, every nation is run by the AI |
| `-years N` | run N game years at full speed, then exit (prints `YEAR <y> secs=...` per year) |
| `-seed N` | fixed game seed (otherwise random) |
| `-threads N` | cap worker threads. With `-threads 1` a run is reproducible: same seed, same campaign |
| `-dump DIR` | write the CSVs below into DIR |
| `-fastdemo N` | `1`: add up the daily demographic totals in one pass over the pops instead of one per key, about 10% faster on one core, same results bit for bit. `2`: run both and compare every value each day (`FASTDEMO_CHECK` lines). `3`: same with a deliberate bug, to see the check fail |
| `-shot YYYY-MM-DD MODE OUT.png` | map screenshot on that date (needs a build with `-DALICE_HEADLESS_SHOTS=ON`) |

## What `-dump` writes

Monthly, on the 1st (and on the start date):

- `nations.csv`: `date,tag,prestige,industrial_score,military_score,rank,is_gp,is_civilized,treasury,population,provinces,infamy,war_exhaustion` (nations that own at least one province)
- `prices.csv`: `date,good,price,median_price,world_supply` (`price` is the supply-weighted mean over the state markets, `median_price` the median over markets)
- `provinces.csv`: `date,province,owner,controller,population` (land provinces only; `province` is Alice's index, land provinces first, not the definition.csv id)

As they happen:

- `wars.csv`: one row per war `START`, `PEACE` (peace deal accepted) and `END`, with both sides' tags, military score, regiments, population, ships, the war score (total, from occupation, from battles), whether the two main sides are adjacent or on the same continent, and the war goals. `detail` says who won for `END`, and who demanded what for `PEACE`.
- `events.csv`: `date,kind,id,legacy_id,nation,province`, where `kind` is `nat`, `free_nat`, `prov` or `free_prov` (an event fired), `reform`, `issue` or `decision` (enacted or taken), or `gp` (the great power order after a change; `id` is the position). `id` and `nation`/`province` are Alice's internal indices.

## Many campaigns

```
tools/headless/batch.sh OUT CWD HOME SCENARIO ALICE FIRST_SEED COUNT "cores"
# e.g. 112 campaigns on cores 0-31:
tools/headless/batch.sh runs/vanilla . ~ 6BA00CA6-0.bin build/Alice 1 112 "$(seq -s' ' 0 31)"
```

One campaign per core at a time, seeds dealt round-robin. Resumable: finished campaigns leave `s<seed>.done`, failures go to `failed.txt`, wall time per campaign to `timing.csv`, and the CSVs are compressed with zstd. `YEARS=5` overrides the default of 100. `HOME` is where Alice keeps its scenarios and saves, so separate mods can use separate folders. Each campaign runs under `systemd-run --user --scope` with a 6 GB memory cap; drop that line if you do not use systemd.

## Analysis

Needs Python 3 with pandas, numpy, matplotlib and pyarrow, plus the `zstd` command.

```
cd tools/headless
python -m analysis --set Vanilla=../../runs/vanilla:1935 --set GFM=../../runs/gfm:1929 --out analysis_out
```

`--set Name=/folder[:year]` names a batch output folder; campaigns whose last dump is before `year` are skipped. Each set becomes one column in the figures. Tables are cached as parquet in `~/.cache/alice-analysis` (or `$ANALYSIS_CACHE`); `PROCS` sets how many campaigns are read in parallel.

- `--only econ`: world population, industrial score, treasury and civilized share; supply and price per good; great powers' industrial score (median campaign and 10-90% band over campaigns), as PNGs.
- `--only complexity`: rank-size of nations, concentration of land and population, growth-rate distributions, war size, length and waiting times, how fast campaigns with different seeds diverge (share of provinces with different owners), and avalanches of ownership changes; plus `complexity_summary.csv`.
