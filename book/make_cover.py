"""Front cover for the momentum book: a full-bleed A4 image drawn from the study's growth curve.

Reads momentum_study.json and writes book/charts/cover.png (build_book.js places it as page one).
Run: py book/make_cover.py
"""
import json
from datetime import date
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
S = json.loads((ROOT / "momentum_study.json").read_text(encoding="utf-8"))
B, N = S["baseCase"], S["benchmarks"][0]

BG, CREAM, ACCENT, SOFT_ACCENT, MUTED, RULE = "#17201b", "#f3efe8", "#d0643f", "#a8492f", "#8e978f", "#2a342e"
MON = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def fmonth(s):
    return f"{MON[int(s[5:7]) - 1]} {s[:4]}"


W, H = 8.27, 11.69  # A4 in inches
fig = plt.figure(figsize=(W, H), facecolor=BG)
serif = {"family": "Georgia"}
sans = {"family": "DejaVu Sans"}

# the growth curve, filling the lower half of the page from edge to edge
c = S["curve"]
t = np.array([(date.fromisoformat(p["date"]) - date.fromisoformat(c[0]["date"])).days for p in c], float)
s_eq = np.log(np.array([p["strategy"] for p in c]))
n_eq = np.log(np.array([p["nifty500"] for p in c]))
ax = fig.add_axes([0, 0.13, 1, 0.52])
ax.set_facecolor(BG)
ax.axis("off")
lo, hi = min(s_eq.min(), n_eq.min()), s_eq.max()
pad = 0.09 * (t[-1] - t[0])  # side margins to match the type; the scale labels sit in the left one
ax.set_xlim(t[0] - pad, t[-1] + pad)
ax.set_ylim(lo - 0.35 * (hi - lo), hi + 0.08 * (hi - lo))
y0 = ax.get_ylim()[0]
for m in (1, 1.5, 2, 3, 4, 5):  # faint log-scale rules at 1x, 1.5x, 2x ...
    ax.axhline(np.log(m), color=RULE, lw=0.8, zorder=0)
    ax.text(t[0] - pad * 0.25, np.log(m), f"{m:g}×", color=MUTED, fontsize=7.5, alpha=0.8, ha="right", va="center", **sans)
# fill under the curve, fading from the accent to the background towards the foot of the page
area = ax.fill_between(t, s_eq, y0, color="none", lw=0)
fade = np.linspace(0, 0.30, 256)[:, None]
img = ax.imshow(np.dstack([np.full((256, 1, 3), matplotlib.colors.to_rgb(SOFT_ACCENT)), fade]), aspect="auto",
                extent=(t[0], t[-1], y0, hi), origin="lower", zorder=1)
img.set_clip_path(area.get_paths()[0], transform=ax.transData)
ax.plot(t, n_eq, color=MUTED, lw=1.3, ls=(0, (4, 3)), alpha=0.9, zorder=2)
ax.plot(t, s_eq, color=ACCENT, lw=3.2, solid_capstyle="round", zorder=3)
ax.scatter([t[-1]], [s_eq[-1]], s=70, color=ACCENT, zorder=5, edgecolors=BG, linewidths=2)
ax.annotate(f"₹1 lakh → ₹{B['multiple']:.2f} lakh", (t[-1], s_eq[-1]), xytext=(0, 18), textcoords="offset points",
            ha="right", color=CREAM, fontsize=11, fontweight="bold", **sans)
ax.annotate(f"Nifty 500: ₹{N['multiple']:.2f} lakh", (t[-1], n_eq[-1]), xytext=(0, -20), textcoords="offset points",
            ha="right", color=MUTED, fontsize=9, **sans)

# type
fig.text(0.09, 0.915, "LET MONEY EARN  ·  RESEARCH", color=ACCENT, fontsize=10.5, fontweight="bold", **sans)
fig.lines.append(plt.Line2D([0.09, 0.20], [0.897, 0.897], color=ACCENT, lw=2, transform=fig.transFigure))
fig.text(0.087, 0.80, "Riding", color=CREAM, fontsize=66, fontweight="bold", **serif)
fig.text(0.087, 0.725, "the Winners", color=CREAM, fontsize=66, fontweight="bold", **serif)
fig.text(0.09, 0.672, "A plain-English study of momentum investing in India", color=CREAM, fontsize=15, alpha=0.85, **serif)
fig.text(0.09, 0.648, "The Nifty 500, every NSE stock, and ETFs", color=MUTED, fontsize=12.5, style="italic", **serif)

fig.lines.append(plt.Line2D([0.09, 0.91], [0.095, 0.095], color=RULE, lw=1, transform=fig.transFigure))
fig.text(0.09, 0.062, f"{B['cagr'] * 100:.1f}% a year", color=CREAM, fontsize=13, fontweight="bold", **sans)
fig.text(0.09, 0.040, f"Nifty 500 momentum rules, {fmonth(B['from'])} to {fmonth(B['to'])}, tested the honest way",
         color=MUTED, fontsize=9, **sans)
fig.text(0.91, 0.051, "letmoneyearn.in", color=MUTED, fontsize=9.5, ha="right", **sans)

out = HERE / "charts" / "cover.png"
fig.savefig(out, dpi=250, facecolor=BG)
print("wrote", out)
