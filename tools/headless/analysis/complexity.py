"""Complexity statistics of Vic2 campaign ensembles: Zipf rank-size, concentration (HHI/Gini),
Gibrat growth, war size/duration/waiting distributions, sensitivity to initial conditions, and
province-ownership avalanches. One column per campaign set; pooled over campaigns via load.map_campaigns.

Usage: python -m analysis.complexity [--set NAME ...] [--n N] [--out DIR]
"""
import argparse
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from analysis.load import map_campaigns, resolve_sets, table

RANKS = np.arange(1, 101)


# ---------------------------------------------------------------- per-campaign workers (top-level, small results)


def _nation_stats(d):
    """Rank-size at 4 dates, yearly nation count + Gini, and pooled yearly log population growth."""
    nat = table(d, "nations")
    pop_all = pd.to_numeric(nat["population"], errors="coerce")
    nat = nat.assign(population=pop_all)
    dates = np.sort(nat["date"].unique())
    first, last = pd.Timestamp(dates[0]).year, pd.Timestamp(dates[-1]).year
    rs = np.full((4, 100), np.nan)
    for i, y in enumerate((first, first + 30, first + 60, last)):
        d0 = dates[np.argmin(np.abs(dates - np.datetime64(pd.Timestamp(y, 1, 1))))]
        pop = nat.loc[nat["date"] == d0, "population"].dropna().to_numpy()
        pop = np.sort(pop)[::-1][:100]
        rs[i, : len(pop)] = pop
    jan = nat[nat["date"].dt.month == 1]
    jyr = jan["date"].dt.year.to_numpy()
    years = np.sort(jan["date"].dt.year.unique())
    n_nat = np.full(len(years), np.nan)
    gini = np.full(len(years), np.nan)
    for i, y in enumerate(years):
        p = jan.loc[jyr == y, "population"].dropna().to_numpy()
        n_nat[i] = len(p)
        gini[i] = _gini(p)
    piv = jan.assign(year=jyr, tag=jan["tag"].astype(str)).pivot(index="year", columns="tag", values="population")
    p = piv.sort_index().to_numpy(float)
    prev, cur = p[:-1], p[1:]
    m = (prev > 0) & (cur > 0)
    growth = np.log(cur[m] / prev[m]).astype(np.float64)
    return {"first": first, "last": last, "rs": rs, "years": years, "n_nat": n_nat, "gini": gini, "growth": growth}


def _prov_stats(d):
    """Yearly Herfindahl of province ownership, plus a (years x provinces) owner-code matrix for divergence."""
    prov = table(d, "provinces")
    own = prov["owner"].astype(object)
    own = own.where(own.notna(), "")
    jan = (prov["date"].dt.month == 1).to_numpy()
    pj = pd.DataFrame(
        {"year": prov["date"].dt.year.to_numpy()[jan], "province": prov["province"].to_numpy()[jan], "owner": own.to_numpy()[jan]}
    )
    years = np.sort(pj["year"].unique())
    yr = pj["year"].to_numpy()
    hhi = np.full(len(years), np.nan)
    for i, y in enumerate(years):
        o = pj.loc[yr == y, "owner"]
        o = o[o != ""]
        if len(o):
            s = o.value_counts().to_numpy(float)
            s = s / s.sum()
            hhi[i] = (s * s).sum()
    tags = np.array(sorted(set(pj["owner"])))
    provs = np.sort(pj["province"].unique())
    tmap = {t: i for i, t in enumerate(tags)}
    codes = np.full((len(years), len(provs)), -1, np.int32)
    codes[np.searchsorted(years, yr), np.searchsorted(provs, pj["province"].to_numpy())] = pj["owner"].map(tmap).to_numpy()
    return {"years": years, "hhi": hhi, "provs": provs, "tags": tags, "codes": codes.astype(np.int16)}


def _wars(d):
    """War START sizes and dates, END durations in days; None when the campaign has no wars table."""
    d = Path(d)
    if not ((d / "wars.csv.zst").exists() or (d / "wars.csv").exists()):
        return None
    w = table(d, "wars")
    st = w[w["event"] == "START"]
    en = w[w["event"] == "END"]
    sizes = pd.to_numeric(st["attacker_regiments"], errors="coerce") + pd.to_numeric(st["defender_regiments"], errors="coerce")
    starts = pd.to_datetime(st["date"]).to_numpy()
    dur = (pd.to_datetime(en["date"]) - pd.to_datetime(en["war_start"])).dt.total_seconds().to_numpy() / 86400.0
    return {"starts": np.sort(starts), "sizes": sizes.to_numpy(float), "durations": dur}


def _avalanches(d):
    """Number of provinces changing owner between consecutive months."""
    prov = table(d, "provinces")
    own = prov["owner"].astype(object)
    own = own.where(own.notna(), "")
    piv = prov.assign(owner=own).pivot(index="date", columns="province", values="owner").sort_index()
    a = piv.to_numpy()
    return (a[1:] != a[:-1]).sum(axis=1).astype(np.int32)


# ---------------------------------------------------------------- small stat helpers


def _gini(x):
    x = np.sort(np.asarray(x, float))
    x = x[np.isfinite(x)]
    n = len(x)
    if n == 0 or x.sum() == 0:
        return np.nan
    i = np.arange(1, n + 1)
    return 2.0 * (i * x).sum() / (n * x.sum()) - (n + 1.0) / n


def _ccdf(ax, x, **kw):
    x = np.sort(np.asarray(x, float))
    x = x[np.isfinite(x)]
    if len(x) == 0:
        return
    ax.plot(x, 1.0 - np.arange(len(x)) / len(x), **kw)


def _align(list_of_years, list_of_vals):
    """Align per-campaign (years, vals[nrow x years]) on a union year grid -> grid, (nrow, n_camp, len(grid))."""
    grid = np.sort(np.unique(np.concatenate(list_of_years)))
    nrow = list_of_vals[0].shape[0]
    M = np.full((nrow, len(list_of_years), len(grid)), np.nan)
    for k, (y, v) in enumerate(zip(list_of_years, list_of_vals)):
        M[:, k, np.searchsorted(grid, y)] = v
    return grid, M


def _medband(ax, x, M, **kw):
    ax.plot(x, np.nanmedian(M, axis=0), **kw)
    ax.fill_between(x, np.nanpercentile(M, 10, axis=0), np.nanpercentile(M, 90, axis=0), alpha=0.3, lw=0)


def _grid(nrow, names, counts, ylabels):
    fig, axes = plt.subplots(nrow, len(names), figsize=(4.4 * len(names), 3.3 * nrow), squeeze=False)
    for j, (nm, c) in enumerate(zip(names, counts)):
        axes[0][j].set_title(f"{nm} (n={c})")
    for i, lab in enumerate(ylabels):
        axes[i][0].set_ylabel(lab)
    return fig, axes


def _samey(axrow):
    lo = min(a.get_ylim()[0] for a in axrow)
    hi = max(a.get_ylim()[1] for a in axrow)
    for a in axrow:
        a.set_ylim(lo, hi)


def _save(fig, out, name):
    fig.tight_layout()
    fig.savefig(out / name, dpi=130)
    plt.close(fig)
    print(f"wrote {out / name}")


# ---------------------------------------------------------------- figures


def _fig_rank_size(res, sets, out, summary):
    names = list(sets)
    fig, axes = _grid(1, names, [len(sets[n]) for n in names], ["population (log)"])
    for j, nm in enumerate(names):
        ax = axes[0][j]
        rs = [r["rs"] for r in res[nm]]
        if not rs:
            continue
        first = int(np.median([r["first"] for r in res[nm]]))
        last = int(np.median([r["last"] for r in res[nm]]))
        for i, y in enumerate((first, first + 30, first + 60, last)):
            med = np.nanmedian(np.stack([r[i] for r in rs]), axis=0)
            ax.plot(RANKS, med, label=str(y))
        ax.set_xscale("log")
        ax.set_yscale("log")
        ax.set_xlabel("rank (log)")
        ax.legend(fontsize=8)
        med_last = np.nanmedian(np.stack([r[3] for r in rs]), axis=0)
        m = np.isfinite(med_last) & (med_last > 0) & (RANKS <= 50)
        if m.sum() > 2:
            slope = np.polyfit(np.log(RANKS[m]), np.log(med_last[m]), 1)[0]
            summary.append((nm, "rank_size_slope_r1-50_last", slope))
    _samey(axes[0])
    _save(fig, out, "complexity_rank_size.png")


def _fig_concentration(res_n, res_p, sets, out):
    names = list(sets)
    fig, axes = _grid(3, names, [len(sets[n]) for n in names], ["nations existing", "Herfindahl (provinces)", "Gini (population)"])
    for j, nm in enumerate(names):
        if not res_n[nm]:
            continue
        yrs = [r["years"] for r in res_n[nm]]
        grid, M = _align(yrs, [np.stack([r["n_nat"], r["gini"]]) for r in res_n[nm]])
        _medband(axes[0][j], grid, M[0])
        _medband(axes[2][j], grid, M[1])
        gridp, H = _align([r["years"] for r in res_p[nm]], [r["hhi"][None, :] for r in res_p[nm]])
        _medband(axes[1][j], gridp, H[0])
        for i in range(3):
            axes[i][j].set_xlabel("year")
    for i in range(3):
        _samey(axes[i])
    _save(fig, out, "complexity_concentration.png")


def _fig_growth(res, sets, out, summary):
    names = list(sets)
    fig, axes = _grid(1, names, [len(sets[n]) for n in names], ["density (log)"])
    for j, nm in enumerate(names):
        ax = axes[0][j]
        g = np.concatenate([r["growth"] for r in res[nm]]) if res[nm] else np.array([])
        if len(g) == 0:
            continue
        lo, hi = np.percentile(g, [0.5, 99.5])
        ax.hist(g, bins=np.linspace(lo, hi, 80), density=True, log=True)
        m, s = g.mean(), g.std()
        xs = np.linspace(lo, hi, 200)
        ax.plot(xs, np.exp(-0.5 * ((xs - m) / s) ** 2) / (s * np.sqrt(2 * np.pi)), "r-", label="Gaussian")
        ax.set_xlabel("yearly log growth of nation population")
        ax.legend(fontsize=8)
        summary.append((nm, "growth_excess_kurtosis", ((g - m) ** 4).mean() / s**4 - 3.0))
    _samey(axes[0])
    _save(fig, out, "complexity_growth.png")


def _fig_wars(res, sets, out, summary):
    names = list(sets)
    fig, axes = _grid(3, names, [len(sets[n]) for n in names], ["CCDF war size (log)", "CCDF duration (log)", "CCDF waiting (log)"])
    for j, nm in enumerate(names):
        got = [r for r in res[nm] if r is not None]
        if not got:
            for i in range(3):
                axes[i][j].text(0.5, 0.5, "no wars table", ha="center", transform=axes[i][j].transAxes)
            continue
        sizes = np.concatenate([r["sizes"] for r in got])
        sizes = sizes[np.isfinite(sizes) & (sizes > 0)]
        dur = np.concatenate([r["durations"] for r in got])
        dur = dur[np.isfinite(dur) & (dur > 0)]
        wt = np.concatenate([np.diff(r["starts"]).astype("timedelta64[s]").astype(float) / 86400.0 for r in got]) if len(got) else np.array([])
        wt = wt[np.isfinite(wt)]
        _ccdf(axes[0][j], sizes)
        axes[0][j].set_xscale("log")
        axes[0][j].set_yscale("log")
        axes[0][j].set_xlabel("regiments at START (log)")
        _ccdf(axes[1][j], dur)
        axes[1][j].set_xscale("log")
        axes[1][j].set_yscale("log")
        axes[1][j].set_xlabel("duration, days (log)")
        if len(wt):
            _ccdf(axes[2][j], wt)
            xs = np.linspace(0, wt.max(), 200)
            axes[2][j].plot(xs, np.exp(-xs / wt.mean()), "r-", label="exponential")
            axes[2][j].set_yscale("log")
            axes[2][j].legend(fontsize=8)
            m, s = wt.mean(), wt.std()
            summary.append((nm, "war_waiting_burstiness_B", (s - m) / (s + m)))
        axes[2][j].set_xlabel("waiting time between war STARTs, days")
        if len(sizes):
            summary.append((nm, "war_size_median_regiments", float(np.median(sizes))))
        if len(dur):
            summary.append((nm, "war_duration_median_days", float(np.median(dur))))
    for i in range(3):
        _samey(axes[i])
    _save(fig, out, "complexity_wars.png")


def _fig_divergence(res, sets, out, summary):
    names = list(sets)
    fig, axes = _grid(2, names, [len(sets[n]) for n in names], ["pair owner difference", "mean province entropy (bits)"])
    for j, nm in enumerate(names):
        got = res[nm][:30]
        if len(got) < 2:
            continue
        tags_g = sorted(set().union(*[set(r["tags"].tolist()) for r in got]))
        tmap = {t: i for i, t in enumerate(tags_g)}
        provs_g = np.sort(np.unique(np.concatenate([r["provs"] for r in got])))
        grid = np.sort(np.unique(np.concatenate([r["years"] for r in got])))
        C = len(got)
        G = np.full((C, len(grid), len(provs_g)), -1, np.int16)
        for k, r in enumerate(got):
            lut = np.array([tmap[t] for t in r["tags"]], np.int16)
            cg = np.where(r["codes"] >= 0, lut[np.clip(r["codes"], 0, None)], -1).astype(np.int16)
            G[k][np.ix_(np.searchsorted(grid, r["years"]), np.searchsorted(provs_g, r["provs"]))] = cg
        pairs = [(a, b) for a in range(C) for b in range(a + 1, C)]
        D = np.full((len(pairs), len(grid)), np.nan)
        for k, (a, b) in enumerate(pairs):
            va, vb = G[a] >= 0, G[b] >= 0
            both = va & vb
            n = both.sum(axis=1)
            nd = ((G[a] != G[b]) & both).sum(axis=1)
            D[k] = np.where(n > 0, nd / np.maximum(n, 1), np.nan)
        _medband(axes[0][j], grid, D)
        axes[0][j].set_xlabel("year")
        med = np.nanmedian(D, axis=0)
        hit = np.nonzero(med > 0.5)[0]
        summary.append((nm, "divergence_year_med_pair_diff_gt_0.5", float(grid[hit[0]]) if len(hit) else float("nan")))
        T = len(tags_g)
        H = np.full(len(grid), np.nan)
        for t in range(len(grid)):
            X = G[:, t, :]
            counts = np.zeros((T, X.shape[1]))
            for c in range(C):
                v = X[c] >= 0
                np.add.at(counts, (X[c][v], np.nonzero(v)[0]), 1)
            n = counts.sum(axis=0)
            ok = n > 0
            p = counts[:, ok] / n[ok]
            plogp = np.where(p > 0, p * np.log2(np.where(p > 0, p, 1.0)), 0.0)
            H[t] = -plogp.sum(axis=0).mean()
        axes[1][j].plot(grid, H)
        axes[1][j].set_xlabel("year")
    _samey(axes[0])
    _samey(axes[1])
    _save(fig, out, "complexity_divergence.png")


def _fig_avalanches(res, sets, out, summary):
    names = list(sets)
    fig, axes = _grid(1, names, [len(sets[n]) for n in names], ["CCDF (log)"])
    for j, nm in enumerate(names):
        counts = np.concatenate([r for r in res[nm]]) if res[nm] else np.array([])
        nz = counts[counts > 0]
        if len(nz) == 0:
            continue
        _ccdf(axes[0][j], nz)
        axes[0][j].set_xscale("log")
        axes[0][j].set_yscale("log")
        axes[0][j].set_xlabel("provinces changing owner in a month (log)")
        s = np.sort(nz)[::-1]
        k = max(1, int(np.ceil(0.01 * len(s))))
        summary.append((nm, "avalanche_top1pct_months_fraction_of_changes", float(s[:k].sum() / s.sum())))
    _samey(axes[0])
    _save(fig, out, "complexity_avalanches.png")


# ---------------------------------------------------------------- entry point


def run(sets: dict[str, list[Path]], out: Path):
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    sets = {nm: [Path(d) for d in dirs] for nm, dirs in sets.items()}
    for nm, dirs in sets.items():
        print(f"set {nm}: {len(dirs)} campaigns")
    summary = []
    res_n = {nm: map_campaigns(_nation_stats, dirs) for nm, dirs in sets.items()}
    res_p = {nm: map_campaigns(_prov_stats, dirs) for nm, dirs in sets.items()}
    res_w = {nm: map_campaigns(_wars, dirs) for nm, dirs in sets.items()}
    res_a = {nm: map_campaigns(_avalanches, dirs) for nm, dirs in sets.items()}
    for nm, dirs in sets.items():
        summary.append((nm, "n_campaigns", len(dirs)))
    _fig_rank_size(res_n, sets, out, summary)
    _fig_concentration(res_n, res_p, sets, out)
    _fig_growth(res_n, sets, out, summary)
    if any(r is not None for rs in res_w.values() for r in rs):
        _fig_wars(res_w, sets, out, summary)
    _fig_divergence(res_p, sets, out, summary)
    _fig_avalanches(res_a, sets, out, summary)
    df = pd.DataFrame(summary, columns=["set", "metric", "value"])
    df.to_csv(out / "complexity_summary.csv", index=False)
    print(f"wrote {out / 'complexity_summary.csv'} ({len(df)} rows)")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--set", action="append", dest="sets", default=None, help="Name or Name=/path[:min_last_year], repeatable")
    ap.add_argument("--n", type=int, default=None, help="campaigns per set")
    ap.add_argument("--out", default="analysis_out")
    a = ap.parse_args()
    run(resolve_sets(a.sets, a.n), Path(a.out))
