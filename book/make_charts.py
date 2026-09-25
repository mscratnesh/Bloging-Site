"""Charts and extra numbers for the momentum book.

Reads momentum_study.json (run study/momentum_study.py first) and replays the base case once for the
market-switch chart. Writes book/charts/*.png and book/book_extra.json.
Run: py book/make_charts.py
"""
import json
import sys
from datetime import date
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.dates as mdates  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT / "study"))
import momentum_study as ms  # noqa: E402

OUT = HERE / "charts"
OUT.mkdir(exist_ok=True)
S = json.loads((ROOT / "momentum_study.json").read_text(encoding="utf-8"))

STRAT, NIFTY, GRID, INK, MUTED = "#a8492f", "#667069", "#e3e5df", "#17201b", "#667069"
BLUE, GREEN, AMBER = "#2a78d6", "#2f6b46", "#c98500"
plt.rcParams.update({
    "font.family": "DejaVu Sans", "font.size": 9.5, "axes.edgecolor": "#b9beb5", "axes.labelcolor": INK,
    "xtick.color": MUTED, "ytick.color": MUTED, "axes.grid": True, "grid.color": GRID, "grid.linewidth": 0.8,
    "axes.spines.top": False, "axes.spines.right": False, "legend.frameon": False, "figure.dpi": 100,
})


def d(s):
    return date.fromisoformat(s)


def save(fig, name):
    fig.tight_layout()
    fig.savefig(OUT / name, dpi=200, facecolor="white")
    plt.close(fig)


def log_axis(ax, ticks=(0.5, 1, 1.5, 2, 3, 4, 5, 6, 8)):
    ax.set_yscale("log")
    lo, hi = ax.get_ylim()
    ax.set_yticks([t for t in ticks if lo <= t <= hi])
    ax.set_yticklabels([f"{t:g}×" for t in ticks if lo <= t <= hi])
    ax.minorticks_off()


def year_axis(ax):
    ax.xaxis.set_major_locator(mdates.YearLocator())
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))


# 1. growth of Rs 1
c = S["curve"]
x = [d(p["date"]) for p in c]
fig, ax = plt.subplots(figsize=(6.5, 3.3))
ax.plot(x, [p["strategy"] for p in c], color=STRAT, lw=2.2, label="Momentum strategy")
ax.plot(x, [p["nifty500"] for p in c], color=NIFTY, lw=1.4, ls="--", label="Nifty 500 index")
log_axis(ax)
year_axis(ax)
ax.set_ylabel("Growth of ₹1 (log scale)")
ax.legend(loc="upper left")
save(fig, "01_growth.png")

# 2. drawdowns
s_eq = np.array([p["strategy"] for p in c])
n_eq = np.array([p["nifty500"] for p in c])
fig, ax = plt.subplots(figsize=(6.5, 2.6))
ax.fill_between(x, (s_eq / np.maximum.accumulate(s_eq) - 1) * 100, 0, color=STRAT, alpha=0.25, lw=0)
ax.plot(x, (s_eq / np.maximum.accumulate(s_eq) - 1) * 100, color=STRAT, lw=1.6, label="Momentum strategy")
ax.plot(x, (n_eq / np.maximum.accumulate(n_eq) - 1) * 100, color=NIFTY, lw=1.2, ls="--", label="Nifty 500 index")
ax.set_ylabel("Below previous high (%)")
year_axis(ax)
ax.legend(loc="lower left")
save(fig, "02_drawdown.png")

# 3. yearly returns
yrs = list(S["marketMa"]["yearly"]["200"].keys())
sv = [S["marketMa"]["yearly"]["200"][y] * 100 for y in yrs]
nv = [S["marketMa"]["yearly"]["nifty500"][y] * 100 for y in yrs]
labels = [f"{y}*" if i in (0, len(yrs) - 1) else y for i, y in enumerate(yrs)]
pos = np.arange(len(yrs))
fig, ax = plt.subplots(figsize=(6.5, 3.0))
b1 = ax.bar(pos - 0.2, sv, 0.38, color=STRAT, label="Momentum strategy")
b2 = ax.bar(pos + 0.2, nv, 0.38, color="#b9beb5", label="Nifty 500 index")
for bars in (b1, b2):
    for b in bars:
        v = b.get_height()
        ax.annotate(f"{v:+.0f}%", (b.get_x() + b.get_width() / 2, v), ha="center", va="bottom" if v >= 0 else "top",
                    fontsize=7.5, color=INK, xytext=(0, 2 if v >= 0 else -2), textcoords="offset points")
ax.axhline(0, color=INK, lw=0.8)
ax.set_xticks(pos, labels)
ax.set_ylabel("Return in the year (%)")
ax.grid(axis="x", visible=False)
ax.legend(loc="upper right")
save(fig, "03_yearly.png")

# 4. survivorship
sc = S["survivorship"]["curve"]
xs = [d(p["date"]) for p in sc]
fig, ax = plt.subplots(figsize=(6.5, 3.0))
ax.plot(xs, [p["today"] for p in sc], color=NIFTY, lw=1.4, label="Today's list used for every month (biased)")
ax.plot(xs, [p["pit"] for p in sc], color=STRAT, lw=2.2, label="The list as it was each month (honest)")
log_axis(ax)
year_axis(ax)
ax.set_ylabel("Growth of ₹1 (log scale)")
ax.legend(loc="upper left")
save(fig, "04_survivorship.png")

# 5. luck test
L = S["luck"]
edges = np.array(L["binEdges"]) * 100
fig, ax = plt.subplots(figsize=(6.5, 2.7))
ax.bar(edges[:-1], L["histogram"], width=np.diff(edges), align="edge", color="#b9beb5", edgecolor="white", lw=1)
ax.axvline(L["baseCagr"] * 100, color=STRAT, lw=2.5)
ax.set_ylim(0, max(L["histogram"]) * 1.35)
ax.annotate(f"The real strategy: {L['baseCagr'] * 100:.1f}% a year", (L["baseCagr"] * 100, max(L["histogram"]) * 1.2),
            xytext=(-6, 0), textcoords="offset points", ha="right", va="center", color=STRAT, fontsize=9, fontweight="bold",
            bbox={"boxstyle": "round,pad=0.25", "fc": "white", "ec": "none"})
ax.set_xlabel("Yearly return (CAGR) of 200 copies that picked stocks at random (%)")
ax.set_ylabel("Number of copies")
ax.grid(axis="x", visible=False)
save(fig, "05_luck.png")

# 6. market switch: Nifty 500, its 200-day average, and the exits
data = ms.Data()
feat = ms.Features(data)
run = ms.backtest(feat, ms.BASE)
cal, idx = data.calendar, data.index
sma = ms.market_sma(idx, ms.BASE.market_ma)
t0 = run["rebalances"][0]
xd = [d(v) for v in cal[t0:]]
fig, ax = plt.subplots(figsize=(6.5, 3.2))
ax.plot(xd, idx[t0:], color=INK, lw=1.2, label="Nifty 500")
ax.plot(xd, sma[t0:], color=BLUE, lw=1.6, label="Its 200-day average")
spells, out_since = [], None
for ev in run["events"] + [{"type": "END", "date": cal[-1]}]:
    if ev["type"] == "EXIT":
        out_since = ev["date"]
    elif ev["type"] in ("ENTER", "END") and out_since:
        spells.append((out_since, ev["date"], ev["type"] == "END"))
        out_since = None
for a, b, _ in spells:
    ax.axvspan(d(a), d(b), color=STRAT, alpha=0.13, lw=0)
ax.plot([], [], color=STRAT, alpha=0.3, lw=8, label="Strategy in the liquid fund")
year_axis(ax)
ax.set_ylabel("Index level")
ax.legend(loc="upper left")
save(fig, "06_switch.png")

# 7. moving-average comparison
M = S["marketMa"]
mc = M["curve"]
xm = [d(p["date"]) for p in mc]
colors = {50: BLUE, 100: GREEN, 150: AMBER, 200: STRAT}
fig, ax = plt.subplots(figsize=(6.5, 3.2))
for r in M["rows"]:
    ax.plot(xm, [p[f"ma{r['ma']}"] for p in mc], color=colors[r["ma"]], lw=2.2 if r["isBase"] else 1.3,
            label=f"{r['ma']}-day average" + (" (our rule)" if r["isBase"] else ""))
ax.plot(xm, [p["nifty500"] for p in mc], color=NIFTY, lw=1.1, ls="--", label="Nifty 500 index")
log_axis(ax)
year_axis(ax)
ax.set_ylabel("Growth of ₹1 (log scale)")
ax.legend(loc="upper left", fontsize=8)
save(fig, "07_moving_averages.png")

# 8. concept: two made-up stocks, one with momentum
rng = np.random.default_rng(3)
days = np.arange(260)
a = 100 * np.exp(np.cumsum(0.0018 + 0.012 * rng.standard_normal(260)))
b = 100 * np.exp(np.cumsum(-0.0002 + 0.022 * rng.standard_normal(260)))
b = 100 + (b - 100) * (a[-1] - 100) / (b[-1] - 100)  # same gain over the year as stock A
fig, ax = plt.subplots(figsize=(6.5, 2.7))
ax.plot(days, a, color=STRAT, lw=2, label=f"Stock A: +{a[-1] - 100:.0f}%, a smooth climb (higher score)")
ax.plot(days, b, color=NIFTY, lw=1.4, label=f"Stock B: +{b[-1] - 100:.0f}%, a bumpy ride (lower score)")
ax.set_xlabel("Trading days over the past year")
ax.set_ylabel("Price (₹, started at 100)")
ax.legend(loc="upper left")
save(fig, "08_concept.png")

# numbers the book text needs that are not in momentum_study.json
extra = {
    "spells": [{"from": a, "to": None if end else b} for a, b, end in spells],
    "now": {"date": cal[-1], "nifty": float(idx[-1]), "sma": float(sma[-1])},
    "stockCount": len(data.symbols),
}
(HERE / "book_extra.json").write_text(json.dumps(extra, indent=1), encoding="utf-8")
print("charts:", sorted(p.name for p in OUT.glob("*.png")))
