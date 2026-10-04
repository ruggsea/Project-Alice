"""Economy plots: world totals, supply and median price per good, great powers' industrial score; one column per set.
Line = median campaign, band = 10-90% over campaigns (yearly means of the monthly dumps)."""
import argparse
from pathlib import Path
import numpy as np, pandas as pd
from analysis.load import table, map_campaigns, resolve_sets

GOODS = ["Grain", "Coal", "Iron", "Steel", "Cement", "Machine Parts", "Fabric", "Small Arms"]
# great powers by tag group: formables folded into their founder; TKG is HPM's Tokugawa Japan
GP = {"UK": ["ENG"], "France": ["FRA"], "Prussia/Germany": ["PRU", "GER", "NGF"], "Russia": ["RUS"],
      "Austria": ["AUS", "KUK"], "USA": ["USA"], "Sardinia/Italy": ["SAR", "ITA"], "Japan": ["JAP", "TKG"]}


def series(d):
    n = table(d, "nations"); g = n.groupby("date", observed=True)
    s = pd.DataFrame({"population": g.population.sum(), "industrial": g.industrial_score.sum(), "treasury": g.treasury.sum(),
                      "civilized_pop_share": n[n.is_civilized == 1].groupby("date").population.sum() / g.population.sum()})
    for name, tags in GP.items():
        s["ind_" + name] = n[n.tag.isin(tags)].groupby("date").industrial_score.sum().reindex(s.index).fillna(0)
    p = table(d, "prices"); p = p[p.good.isin(GOODS)]
    for col in ["median_price", "world_supply"]:
        w = p.pivot_table(index="date", columns="good", values=col, observed=True)
        for gd in w:
            s[f"{col}:{gd}"] = w[gd]
    return s.resample("YS").mean()


def run(sets, out):
    import matplotlib; matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    out = Path(out); out.mkdir(parents=True, exist_ok=True)
    res = {k: map_campaigns(series, v) for k, v in sets.items()}
    mods = list(res); cmap = plt.get_cmap("tab10"); col = {m: cmap(i) for i, m in enumerate(mods)}

    def band(ax, mod, key, scale=1, logy=False):
        df = pd.concat([s[key].rename(i) for i, s in enumerate(res[mod]) if key in s], axis=1) * scale
        if df.empty:
            return
        q = df.quantile([0.1, 0.5, 0.9], axis=1).T
        ax.fill_between(q.index, q[0.1], q[0.9], color=col[mod], alpha=0.2, lw=0)
        ax.plot(q.index, q[0.5], color=col[mod], lw=1.6)
        if logy:
            ax.set_yscale("log")

    def grid(rows, fname, title):
        fig, axs = plt.subplots(len(rows), len(mods), figsize=(4.2 * len(mods), 2.6 * len(rows)), sharex=True, squeeze=False)
        for r, (key, lab, scale, logy) in enumerate(rows):
            for c, mod in enumerate(mods):
                ax = axs[r, c]; band(ax, mod, key, scale, logy)
                if r == 0: ax.set_title(f"{mod} ({len(res[mod])} campaigns)")
                if c == 0: ax.set_ylabel(lab)
                ax.grid(alpha=0.3)
            lo = min(a.get_ylim()[0] for a in axs[r]); hi = max(a.get_ylim()[1] for a in axs[r])
            for a in axs[r]: a.set_ylim(lo, hi)
        fig.suptitle(title + "  (line = median campaign, band = 10-90%)"); fig.tight_layout(rect=(0, 0, 1, 0.97))
        fig.savefig(out / fname, dpi=130); plt.close(fig); print("wrote", out / fname, flush=True)

    grid([("population", "world pop (millions)", 1e-6, False), ("industrial", "sum of industrial scores", 1, False),
          ("treasury", "sum of treasuries (log)", 1, True), ("civilized_pop_share", "share of pop in civilized nations", 1, False)],
         "econ_world.png", "World economy")
    grid([(f"world_supply:{g}", g, 1, True) for g in GOODS], "econ_supply.png", "World supply per good (log)")
    grid([(f"median_price:{g}", g, 1, True) for g in GOODS], "econ_prices.png", "Median price over markets per good (log)")
    grid([("ind_" + name, name, 1, False) for name in GP], "econ_great_powers.png", "Great powers' industrial score")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--set", action="append"); ap.add_argument("--n", type=int, default=112)
    ap.add_argument("--out", default="analysis_out")
    a = ap.parse_args()
    run(resolve_sets(a.set, a.n), a.out)
