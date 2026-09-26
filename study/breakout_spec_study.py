"""Backtest of the Multi Year Breakout sheet rules (the weekly MasterData / Tracker system), and of each
[PROPOSED] change to them, one at a time.

Everything is judged on weekly closes, as the sheet is reviewed on weekends:
  - Resistance R = highest weekly high from 5 years (260 weeks) ago up to 4 weeks ago; its week is the
    resistance date. Base age = (this week - resistance date) / 365, at least 2 years.
  - Vol ratio = this week's volume / average of the previous 5 weeks.
  - BREAKOUT: base >= 2 years, close 0-10% above R, vol ratio >= 1.5, close above the 30-week average.
    Buy at that weekly close; a stock not bought that week (no free slot) is not chased later unless it
    signals again.
  - Exit on a weekly close below R (stop) or below the lowest weekly low of the previous 2 weeks (trail).

Cup and handle is tested on O'Neil's rules (see Spec.ch_*), on its own and in one portfolio with the
multi-year breakouts, as the Tracker runs them. The sheet's own C&H formulas are not in this repo.

Two ways of scoring each rule set:
  - Every signal: each breakout is traded on its own, no slot limit (one trade per stock at a time).
    Shows what the rules do to the average trade, without the luck of which stocks got a slot.
  - Portfolio: 10 slots, Rs 10 lakh, idle money in one GOLDBEES pool, 0.25% a side, dividends on the
    ex-date (as in study/breakout_study.py). When more stocks break out than there are free slots,
    the longest base goes first (the sheet ranks by base age).

Universe: point-in-time Nifty 500 lists, Rs 1 crore average daily traded value over the last year.

Limits of the data:
  - Prices start in Sep 2019, so until Sep 2024 R is the high of the history there is (2-5 years), not
    of a full 5 years. A stock with a higher high before 2019 can show a breakout here that the sheet
    would call NEAR or nothing. The report shows the Sep 2024 onward part on its own.
  - There are no daily lows: a week's low is its lowest close. That is higher than the real low, so
    the 2-week-low trail and the breakout-week low sit a little higher than in the sheet.
  - Prices are split-adjusted as in study/breakout_study.py; volume is scaled by the same factor.

Output: breakout_spec_study.json
Run: py study/breakout_spec_study.py
"""
import json
import sys
from dataclasses import dataclass, replace, asdict
from datetime import date
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
import momentum_study as ms  # noqa: E402
from breakout_study import Breakouts, CAPITAL, by_year, rebased  # noqa: E402

FULL_WINDOW_FROM = "2024-09-27"  # first week-end with 5 years of prices behind it
FWD = {"3m": 13, "6m": 26, "12m": 52}  # weeks


@dataclass(frozen=True)
class Spec:
    # resistance and base
    lookback_wks: int = 260
    skip_wks: int = 4
    min_base_yrs: float = 2.0
    max_depth: float = None         # [P] max fall from R to the base low (0.5 = 50%)
    min_tests: int = 0              # [P] separate tests of R during the base
    test_band: float = 0.08         #     ... a test = a weekly high within this of R
    # volume and liquidity
    vol_rule: str = "avg5"          # "avg5" | "med10" [P] | "avg5+avg20" [P]
    vol_min: float = 1.5
    min_value20: float = 0.0        # [P] 20-day average traded value, Rs
    top_third: bool = False         # [P] breakout week closes in the top third of its range
    # entry
    max_above: float = 0.10         # close at most this far above R
    ma_wks: int = 30
    # which setups: "myb" (multi-year base) | "ch" (cup and handle) | "both" (one portfolio, as the Tracker)
    setup: str = "myb"
    # cup and handle, O'Neil: cup 7-65 weeks from the left rim, 12-35% deep, after a 30% rise; right rim
    # within 10% of the left rim; handle 1-10 weeks, at most 12% deep, in the upper half of the cup.
    # Pivot = handle high. Buy on a weekly close 0-5% above the pivot (same volume and 30-week rules).
    ch_cup: tuple = (7, 65)
    ch_depth: tuple = (0.12, 0.35)
    ch_handle_wks: int = 10
    ch_handle_depth: float = 0.12
    ch_prior_up: float = 0.30
    ch_max_above: float = 0.05
    ch_max_slots: int = None        # "both": at most this many slots in C&H, so they cannot crowd out multi-year bases
    ch_rim: str = "shortest"        # "shortest": the shortest handle that fits | "max10": the right rim is the highest
    #                                 weekly high of the last 10 weeks (what one sheet formula can do)
    ch_u: int = 0                   # at least this many weeks from the left rim down to the cup low, and from it up to the right rim
    market_wks: int = None          # buy only while the Nifty 500 closes above its N-week average (the sheet: Nifty 50, 40 weeks)
    # stops
    stop0: str = "R"                # "R": close below R (C&H: below the handle low) | "R97|low" [P]: max(0.97 R, breakout-week low)
    #                                 (C&H: 0.97 x pivot) | "pct8": 8% below the buy price (O'Neil)
    max_risk: float = None          # [P] skip if entry to stop is more than this
    breakeven_at: float = None      # [P] stop to the buy price once a weekly close is this far up
    trail: str = "low2"             # "low2" | "ma10" [P] | "ma30" (the old rule) | "none"
    #                                 | "v2": the Tracker's two stages. Until a weekly close is +20%: sell on a close below R
    #                                   (pivot) on median-10 volume ratio >= 1, or below the first stop. After: sell below
    #                                   max(first stop, buy price), or below the 10-week average
    trail_after: float = None       # [P] trail only once a weekly close is this far up
    # portfolio
    rank: str = "base"              # "base" (longest base) | "udvol" | "momentum"
    slots: int = 10
    cost: float = 0.0025
    cash_asset: str = "GOLDBEES"
    dividends: bool = True


BASE = Spec()


class Weekly:
    """Weekly bars (W x N) and the sheet's columns, from the split-adjusted daily prices."""

    def __init__(self, b):
        d = b.data
        self.b, self.d = b, d
        ends = np.flatnonzero(b.week_end)
        self.ends = ends
        self.dates = [d.calendar[t] for t in ends]
        W, N = len(ends), d.close.shape[1]
        close = np.full((W, N), np.nan)
        high = np.full((W, N), np.nan)
        low = np.full((W, N), np.nan)
        vol = np.full((W, N), np.nan)
        with np.errstate(invalid="ignore", divide="ignore"):
            vadj = d.turnover_daily / b.px  # volume scaled like the prices
        raw = ~np.isnan(d.raw_close)
        with np.errstate(all="ignore"):
            import warnings
            warnings.simplefilter("ignore", RuntimeWarning)
            for w, t in enumerate(ends):
                s = b.week_first[w]
                traded = raw[s:t + 1].any(axis=0)
                last = np.where(raw[s:t + 1], np.arange(s, t + 1)[:, None], -1).max(axis=0)
                close[w, traded] = b.px[last[traded], np.flatnonzero(traded)]
                high[w] = np.nanmax(np.where(raw[s:t + 1], b.hi[s:t + 1], np.nan), axis=0)
                low[w] = np.nanmin(np.where(raw[s:t + 1], b.px[s:t + 1], np.nan), axis=0)
                vol[w] = np.nansum(np.where(raw[s:t + 1], vadj[s:t + 1], 0.0), axis=0)
                vol[w, ~traded] = np.nan
        self.close, self.high, self.low, self.vol = close, high, low, vol
        self.W, self.N = W, N
        self.days = np.array([date.fromisoformat(x).toordinal() for x in self.dates])

        # resistance: max weekly high over weeks w-260 .. w-4
        R = np.full((W, N), np.nan)
        Rw = np.full((W, N), -1)
        h = np.where(np.isnan(high), -np.inf, high)
        for w in range(W):
            a, z = max(0, w - BASE.lookback_wks), w - BASE.skip_wks + 1
            if z - a < 1:
                continue
            win = h[a:z]
            k = win.argmax(axis=0)
            m = win[k, np.arange(N)]
            ok = m > -np.inf
            R[w, ok] = m[ok]
            Rw[w, ok] = a + k[ok]
        self.R, self.Rw = R, Rw
        with np.errstate(invalid="ignore"):
            self.base_yrs = np.where(Rw >= 0, (self.days[:, None] - self.days[np.maximum(Rw, 0)]) / 365.0, np.nan)

        self.ma = {n: self._ma(n) for n in (10, 30)}
        self.vr = {"avg5": self._vol_ratio(5, np.nanmean), "med10": self._vol_ratio(10, np.nanmedian),
                   "avg20": self._vol_ratio(20, np.nanmean),
                   "avg10": self._vol_ratio(10, np.nanmean)}
        # up/down volume over 20 weeks (ranking)
        up = close[1:] > close[:-1]
        dn = close[1:] < close[:-1]
        uv = np.vstack([np.zeros((1, N)), np.where(up, np.nan_to_num(vol[1:]), 0.0)])
        dv = np.vstack([np.zeros((1, N)), np.where(dn, np.nan_to_num(vol[1:]), 0.0)])
        cu, cd = np.cumsum(uv, axis=0), np.cumsum(dv, axis=0)
        self.udvol = np.full((W, N), np.nan)
        with np.errstate(invalid="ignore", divide="ignore"):
            self.udvol[20:] = (cu[20:] - cu[:-20]) / (cd[20:] - cd[:-20])
        # liquidity and universe at each week-end
        self.univ = np.zeros((W, N), dtype=bool)
        self.value20 = np.full((W, N), np.nan)
        self.mom = np.full((W, N), np.nan)
        for w, t in enumerate(ends):
            self.univ[w] = d.universe_mask("pit500", d.calendar[t]) & b.turn_ok[t]
            self.value20[w] = b.feat.turnover(t, 20)
        self._mom_ready = False
        self._extra = {}

    def _ma(self, n):
        c = self.close
        out = np.full(c.shape, np.nan)
        with np.errstate(all="ignore"):
            import warnings
            warnings.simplefilter("ignore", RuntimeWarning)
            for w in range(n - 1, self.W):
                win = c[w - n + 1:w + 1]
                k = (~np.isnan(win)).sum(axis=0)
                m = np.nanmean(win, axis=0)
                m[k < n * 0.9] = np.nan
                out[w] = m
        return out

    def _vol_ratio(self, n, f):
        v = self.vol
        out = np.full(v.shape, np.nan)
        with np.errstate(all="ignore"):
            import warnings
            warnings.simplefilter("ignore", RuntimeWarning)
            for w in range(n, self.W):
                ref = f(v[w - n:w], axis=0)
                out[w] = np.where(ref > 0, v[w] / ref, np.nan)
        return out

    def market_ok(self, n):
        """Bool W: the Nifty 500 weekly close is above its n-week average (True until there are n weeks)."""
        ix = self.d.index[self.ends]
        ok = np.ones(self.W, dtype=bool)
        for w in range(n - 1, self.W):
            ok[w] = ix[w] > ix[w - n + 1:w + 1].mean()
        return ok

    def momentum(self, w):
        return self.b.feat.score(self.ends[w], ms.BASE)

    def base_stats(self, w, j):
        """(depth, tests) of the base behind R at week w: the deepest fall below R after the R week, and
        how many separate times a weekly high came back within test_band of R (4 weeks apart or more)."""
        key = (w, j)
        if key in self._extra:
            return self._extra[key]
        r, rw = self.R[w, j], self.Rw[w, j]
        z = w - BASE.skip_wks + 1  # the base: after the R week, up to 4 weeks ago
        lows = self.low[rw + 1:z, j]
        depth = float(1 - np.nanmin(lows) / r) if np.isfinite(lows).any() else 0.0
        near = self.high[rw + 1:z, j] >= r * (1 - BASE.test_band)
        tests, gap, touching = 0, 0, True  # the weeks right after the high are the same move, not a test
        for x in near:
            if x:
                if not touching and gap >= 4:
                    tests += 1
                touching, gap = True, 0
            else:
                touching = False
                gap += 1
        self._extra[key] = (depth, tests)
        return depth, tests

    def cup_handle(self, sp):
        """O'Neil cup with handle finished by last week, as W x N arrays: pivot (handle high), handle low,
        cup weeks (left rim to right rim) and cup depth. The shortest handle that fits is used."""
        key = ("ch", sp.ch_cup, sp.ch_depth, sp.ch_handle_wks, sp.ch_handle_depth, sp.ch_prior_up, sp.ch_rim, sp.ch_u)
        if key in self._extra:
            return self._extra[key]
        W, N = self.W, self.N
        h = np.where(np.isnan(self.high), -np.inf, self.high)
        lo = np.where(np.isnan(self.low), np.inf, self.low)
        pivot, hlow, cupw, depth = (np.full((W, N), np.nan) for _ in range(4))
        cmin, cmax = sp.ch_cup
        cols = np.arange(N)
        for w in range(W):
            found = np.zeros(N, dtype=bool)
            if sp.ch_rim == "max10" and w >= 10:  # last occurrence of the highest high of weeks w-10 .. w-1
                rim = w - 1 - h[w - 10:w][::-1].argmax(axis=0)
            for hw in range(1, sp.ch_handle_wks + 1):
                rr = w - hw                       # right rim = first handle week
                a = rr - cmax
                if a - 13 < 0:
                    continue
                piv = h[rr]
                ok = (piv > -np.inf) & ~found
                if sp.ch_rim == "max10":
                    ok &= rim == rr
                if hw > 1:
                    ok &= h[rr + 1:w].max(axis=0) <= piv  # the handle stays under the right rim
                h_lo = lo[rr:w].min(axis=0)
                k = h[a:rr].argmax(axis=0)
                L = h[a:rr][k, cols]
                lw = a + k                         # left rim
                ok &= (rr - lw >= cmin) & (piv >= L * 0.90) & (piv <= L * 1.03)
                idx = np.arange(a, rr + 1)[:, None]
                in_cup = np.where(idx >= lw, lo[a:rr + 1], np.inf)
                cup_lo = in_cup.min(axis=0)
                if sp.ch_u:
                    ib = a + in_cup.argmin(axis=0)
                    ok &= (ib - lw >= sp.ch_u) & (rr - ib >= sp.ch_u)
                with np.errstate(invalid="ignore", divide="ignore"):
                    dep = 1 - cup_lo / L
                    ok &= (dep >= sp.ch_depth[0]) & (dep <= sp.ch_depth[1])
                    ok &= (1 - h_lo / piv <= sp.ch_handle_depth) & (h_lo >= cup_lo + 0.5 * (L - cup_lo))
                    if sp.ch_prior_up:
                        b0 = max(0, a - 52)
                        idx2 = np.arange(b0, rr)[:, None]
                        m = (idx2 >= lw - 52) & (idx2 < lw)
                        before = np.where(m, lo[b0:rr], np.inf)
                        ok &= (np.isfinite(before).sum(axis=0) >= 13) & (L >= before.min(axis=0) * (1 + sp.ch_prior_up))
                pivot[w, ok], hlow[w, ok], cupw[w, ok], depth[w, ok] = piv[ok], h_lo[ok], (rr - lw)[ok], dep[ok]
                found |= ok
        self._extra[key] = (pivot, hlow, cupw, depth)
        return self._extra[key]


class Signals:
    """sig (W x N bool) with, per signal: kind (1 multi-year base, 2 cup and handle), level (R or pivot),
    natural stop (R or handle low) and rank key (base years; cup weeks / 52 for C&H)."""

    def __init__(self, wk):
        shape = (wk.W, wk.N)
        self.sig = np.zeros(shape, dtype=bool)
        self.kind = np.zeros(shape, dtype=np.int8)
        self.level, self.nat, self.rank = (np.full(shape, np.nan) for _ in range(3))


def signals(wk, sp):
    """The sheet's BREAKOUT signals under spec `sp` (a Signals)."""
    out = Signals(wk)
    if sp.setup in ("myb", "both"):
        s = myb_signals(wk, sp)
        out.sig |= s
        out.kind[s], out.level[s], out.nat[s], out.rank[s] = 1, wk.R[s], wk.R[s], wk.base_yrs[s]
    if sp.setup in ("ch", "both"):
        pivot, hlow, cupw, _ = wk.cup_handle(sp)
        c = wk.close
        with np.errstate(invalid="ignore"):
            s = (c > pivot) & (c <= pivot * (1 + sp.ch_max_above)) & (c > wk.ma[sp.ma_wks]) & wk.univ & ~out.sig
            if sp.min_value20:
                s &= wk.value20 >= sp.min_value20
            s &= volume_ok(wk, sp) & (range_ok(wk) if sp.top_third else True)
        out.sig |= s
        out.kind[s], out.level[s], out.nat[s], out.rank[s] = 2, pivot[s], hlow[s], cupw[s] / 52
    if sp.market_wks:
        out.sig &= wk.market_ok(sp.market_wks)[:, None]
    if sp.max_risk is not None:
        for w, j in zip(*np.nonzero(out.sig)):
            if 1 - init_stop(wk, sp, out, w, j) / wk.close[w, j] > sp.max_risk:
                out.sig[w, j] = False
    return out


def volume_ok(wk, sp):
    with np.errstate(invalid="ignore"):
        if sp.vol_rule == "avg5+avg20":
            return (wk.vr["avg5"] >= sp.vol_min) & (wk.vr["avg20"] >= 1.2)
        return wk.vr[sp.vol_rule] >= sp.vol_min


def range_ok(wk):
    rng = wk.high - wk.low
    with np.errstate(invalid="ignore"):
        return (rng <= 0) | ((wk.close - wk.low) >= rng * 2 / 3)


def myb_signals(wk, sp):
    """Bool W x N: multi-year base BREAKOUT."""
    c, R = wk.close, wk.R
    with np.errstate(invalid="ignore"):
        s = (wk.base_yrs >= sp.min_base_yrs) & (c > R) & (c <= R * (1 + sp.max_above)) & (c > wk.ma[sp.ma_wks]) & wk.univ
        if sp.vol_rule == "avg5+avg20":
            s &= (wk.vr["avg5"] >= sp.vol_min) & (wk.vr["avg20"] >= 1.2)
        else:
            s &= wk.vr[sp.vol_rule] >= sp.vol_min
        if sp.min_value20:
            s &= wk.value20 >= sp.min_value20
        if sp.top_third:
            rng = wk.high - wk.low
            s &= (rng <= 0) | ((c - wk.low) >= rng * 2 / 3)
    if sp.max_depth is not None or sp.min_tests:
        for w, j in zip(*np.nonzero(s)):
            depth, tests = wk.base_stats(w, j)
            if (sp.max_depth is not None and depth > sp.max_depth) or tests < sp.min_tests:
                s[w, j] = False
    return s


def init_stop(wk, sp, S, w, j):
    if sp.stop0 == "R":
        return S.nat[w, j]
    if sp.stop0 == "pct8":
        return wk.close[w, j] * 0.92
    return max(S.level[w, j] * 0.97, wk.low[w, j])


class Trade:
    """Stop and trail for one holding, checked on each weekly close after the buy week."""

    def __init__(self, wk, sp, S, w, j):
        self.wk, self.sp, self.w0, self.j = wk, sp, w, j
        self.entry = wk.close[w, j]
        self.sl0 = init_stop(wk, sp, S, w, j)
        self.level = S.level[w, j]
        self.best = self.entry

    def exit(self, w):
        """None to hold, else the reason; call once per week after the buy week, in order."""
        wk, sp, j = self.wk, self.sp, self.j
        c = wk.close[w, j]
        if np.isnan(c):
            return None
        if sp.trail == "v2":
            self.best = max(self.best, c)
            if self.best < self.entry * 1.2:
                if c < self.level and wk.vr["med10"][w, j] >= 1:
                    return "failed"
                return "stop" if c < self.sl0 else None
            if c < max(self.sl0, self.entry):
                return "breakeven"
            return "trail" if c < wk.ma[10][w, j] else None
        stop, why = self.sl0, "stop"
        if sp.breakeven_at is not None and self.best >= self.entry * (1 + sp.breakeven_at):
            if self.entry > stop:
                stop, why = self.entry, "breakeven"
        if sp.trail != "none" and (sp.trail_after is None or self.best >= self.entry * (1 + sp.trail_after)):
            tr = (np.nanmin(wk.low[max(0, w - 2):w, j]) if sp.trail == "low2"
                  else wk.ma[10 if sp.trail == "ma10" else 30][w, j])
            if not np.isnan(tr) and tr > stop:
                stop, why = tr, "trail"
        if c < stop:
            return why
        self.best = max(self.best, c)
        return None


def every_signal(wk, sp, S, from_w=0):
    """Each signal traded on its own (one open trade per stock); returns per-trade rows."""
    out, sig = [], S.sig
    for j in range(wk.N):
        ws = np.flatnonzero(sig[from_w:, j]) + from_w
        free_from = 0
        for w in ws:
            if w < free_from:
                continue
            tr = Trade(wk, sp, S, w, j)
            why, x = "open", wk.W - 1
            for v in range(w + 1, wk.W):
                why = tr.exit(v)
                if why:
                    x = v
                    break
            else:
                why = "open"
            last = x
            while np.isnan(wk.close[last, j]):
                last -= 1
            ret = wk.close[last, j] / tr.entry * (1 - sp.cost) ** 2 - 1
            fwd = {}
            for k, n in FWD.items():
                if w + n < wk.W and not np.isnan(wk.close[w + n, j]):
                    ix = wk.d.index
                    fwd[k] = (float(wk.close[w + n, j] / wk.close[w, j] - 1),
                              float(ix[wk.ends[w + n]] / ix[wk.ends[w]] - 1))
            out.append({"j": j, "w": w, "x": last, "kind": int(S.kind[w, j]), "level": float(S.level[w, j]), "ret": float(ret), "why": why, "weeks": int(last - w), "fwd": fwd})
            free_from = x + 1
    return out


def signal_stats(rows):
    if not rows:
        return {"n": 0}
    closed = [r for r in rows if r["why"] != "open"]
    r = np.array([x["ret"] for x in rows])
    win, loss = r[r > 0], r[r <= 0]
    out = {"n": len(rows), "open": len(rows) - len(closed), "winRate": float((r > 0).mean()), "avgRet": float(r.mean()),
           "medRet": float(np.median(r)), "avgWin": float(win.mean()) if len(win) else 0.0,
           "avgLoss": float(loss.mean()) if len(loss) else 0.0,
           "payoff": float(win.mean() / -loss.mean()) if len(win) and len(loss) and loss.mean() < 0 else None,
           "medWeeks": float(np.median([x["weeks"] for x in rows])),
           "over50": int((r > 0.5).sum()), "worst": float(r.min()), "best": float(r.max()),
           "why": {k: sum(1 for x in rows if x["why"] == k) for k in ("failed", "stop", "breakeven", "trail", "open")}}
    for k in FWD:
        f = [x["fwd"][k] for x in rows if k in x["fwd"]]
        if f:
            a = np.array(f)
            out[k] = {"n": len(a), "mean": float(a[:, 0].mean()), "median": float(np.median(a[:, 0])),
                      "hit": float((a[:, 0] > 0).mean()), "excess": float((a[:, 0] - a[:, 1]).mean()),
                      "beat": float((a[:, 0] > a[:, 1]).mean())}
    return out


def portfolio(wk, sp, S, from_w, record=False):
    b, d = wk.b, wk.d
    cal = d.calendar
    t0 = wk.ends[from_w - 1] + 1 if from_w > 0 else 0
    liquid = (1 + ms.LIQUID_ANNUAL) ** (1 / ms.TRADING_DAYS) - 1
    idle_ret = d.cash_ret[sp.cash_asset] if sp.cash_asset else np.full(len(cal), liquid)
    idle_cost = sp.cost if sp.cash_asset else 0.0
    slots = [{"j": None, "v": CAPITAL / sp.slots * (1 - idle_cost)} for _ in range(sp.slots)]
    equity, trades, log = [], [], []
    skipped = 0

    def sell(s, t, why):
        proceeds = s["v"] * (1 - sp.cost)
        trades.append({"s": d.symbols[s["j"]], "in": s["day"], "out": cal[t], "inPx": s["px"], "outPx": float(d.close[t, s["j"]]),
                       "ret": proceeds / s["basis"] - 1, "pnl": proceeds - s["basis"], "why": why,
                       "weeks": int(wk.b.week_id[t] - s["w"]), "level": s["R"], "setup": s["setup"], "div": s["div"]})
        s.clear()
        s.update({"j": None, "v": proceeds * (1 - idle_cost)})

    for t in range(t0, len(cal)):
        if t > t0:
            for s in slots:
                if s["j"] is None:
                    s["v"] *= 1 + idle_ret[t]
                else:
                    r = d.ret[t, s["j"]]
                    s["v"] *= 1 + (0.0 if np.isnan(r) else r)
                    if sp.dividends and b.div[t, s["j"]]:
                        paid = s["v"] * b.div[t, s["j"]]
                        s["v"] += paid
                        s["div"] += paid
        for s in slots:
            if s["j"] is not None and np.isnan(d.close[t, s["j"]]):
                sell(s, t, "no prices")
        if b.week_end[t]:
            w = int(b.week_id[t])
            sold = set()
            for s in slots:
                if s["j"] is not None:
                    why = s["trade"].exit(w)
                    if why:
                        sold.add(s["j"])
                        sell(s, t, why)
            held = {s["j"] for s in slots if s["j"] is not None}
            cands = [j for j in np.flatnonzero(S.sig[w]) if j not in held and j not in sold]
            if sp.rank == "base":
                cands.sort(key=lambda j: -S.rank[w, j])  # multi-year bases (2+ years) before cups
            elif sp.rank == "udvol":
                cands.sort(key=lambda j: -np.nan_to_num(wk.udvol[w, j], nan=-9))
            else:
                sc = wk.momentum(w)
                cands.sort(key=lambda j: -np.nan_to_num(sc[j], nan=-99))
            free = [s for s in slots if s["j"] is None]
            pool = sum(s["v"] for s in free)
            for s in free:
                s["v"] = pool / len(free) if free else 0.0
            bought = []
            for j in cands:
                if not free:
                    skipped += 1
                    continue
                if sp.ch_max_slots is not None and S.kind[w, j] == 2 and \
                        sum(1 for x in slots if x["j"] is not None and x["setup"] == "C&H") >= sp.ch_max_slots:
                    continue
                s = free.pop(0)
                basis = s["v"] * (1 - idle_cost)
                s.update({"j": j, "v": basis * (1 - sp.cost), "basis": basis, "day": cal[t], "w": w, "px": float(d.close[t, j]),
                          "trade": Trade(wk, sp, S, w, j), "R": float(S.level[w, j]), "setup": SETUP[S.kind[w, j]], "div": 0.0})
                bought.append(d.symbols[j])
            if record:
                total = sum(s["v"] for s in slots)
                log.append({"date": cal[t], "signals": [d.symbols[j] for j in cands], "bought": bought,
                            "held": sum(s["j"] is not None for s in slots),
                            "cash": sum(s["v"] for s in slots if s["j"] is None) / total})
        equity.append(sum(s["v"] for s in slots))
    for s in slots:
        if s["j"] is not None:
            j = s["j"]
            trades.append({"s": d.symbols[j], "in": s["day"], "out": None, "inPx": s["px"], "outPx": float(d.close[-1, j]),
                           "ret": s["v"] / s["basis"] - 1, "pnl": s["v"] - s["basis"], "why": "open",
                           "weeks": int(wk.b.week_id[len(cal) - 1] - s["w"]), "level": s["R"], "setup": s["setup"], "div": s["div"]})
    return {"dates": cal[t0:], "equity": np.array(equity), "trades": trades, "log": log, "skipped": skipped, "t0": t0}


def port_stats(r):
    dates, eq = r["dates"], r["equity"]
    tr = r["trades"]
    rr = np.array([x["ret"] for x in tr]) if tr else np.array([0.0])
    return {**ms.stats(dates, eq), "endValue": float(eq[-1]), "trades": len(tr),
            "open": sum(1 for x in tr if x["out"] is None), "winRate": float((rr > 0).mean()),
            "pnl": float(sum(x["pnl"] for x in tr)), "skipped": r["skipped"],
            "avgCash": float(np.mean([x["cash"] for x in r["log"]])) if r["log"] else None}


# ---------------------------------------------------------------- the variants

CR = 1e7
SETUP = {1: "MYB", 2: "C&H"}
BEST = "sl97ma30"      # drawn next to the sheet rules in the report
BEST_BOTH = "bothbest"
CH = replace(BASE, setup="ch")
# the v2 Apps Script: MasterData entry gates and the Tracker's two-stage exits
V2MYB = replace(BASE, vol_rule="med10", top_third=True, max_depth=0.60, min_value20=5 * 1e7, stop0="R97|low", max_risk=0.10,
                market_wks=40, trail="v2")
# C&H as apps-script/BreakoutTracker.gs scans it (chFormula_): right rim = 10-week high, handle 1-8 weeks up to
# 15% deep, cup 7-65 weeks 12-40% deep with 3+ weeks each side, 25% prior rise, 1.4x the 10-week average volume;
# the same market, liquidity and 10% risk gates and two-stage exits as v2. Keep the two in sync.
V2CH = replace(V2MYB, setup="ch", top_third=False, max_depth=None, stop0="R", ch_rim="max10", ch_prior_up=0.25,
               ch_depth=(0.12, 0.40), ch_u=3, ch_handle_wks=8, ch_handle_depth=0.15, vol_rule="avg10", vol_min=1.4)
# the stricter O'Neil rules tested earlier, in the same frame
V2ONEIL = replace(V2MYB, setup="ch", top_third=False, max_depth=None, stop0="R", ch_rim="max10")
BOTH = replace(BASE, setup="both")
VARIANTS = [
    # (group, key, label, spec)
    ("Sheet rules today", "base", "Sheet rules today", BASE),
    ("Entry filters", "win5", "Entry window 0-5% above R (not 0-10%)", replace(BASE, max_above=0.05)),
    ("Entry filters", "vol2", "Vol ratio 2.0 or more (high conviction only)", replace(BASE, vol_min=2.0)),
    ("Entry filters", "med10", "Vol vs median of previous 10 weeks", replace(BASE, vol_rule="med10")),
    ("Entry filters", "avg20", "Vol 1.5x the 5-week average and 1.2x the 20-week average", replace(BASE, vol_rule="avg5+avg20")),
    ("Entry filters", "liq5", "20-day traded value Rs 5 Cr or more", replace(BASE, min_value20=5 * CR)),
    ("Entry filters", "liq10", "20-day traded value Rs 10 Cr or more", replace(BASE, min_value20=10 * CR)),
    ("Entry filters", "top3", "Breakout week closes in the top third of its range", replace(BASE, top_third=True)),
    ("Entry filters", "depth50", "Base no deeper than 50% below R", replace(BASE, max_depth=0.50)),
    ("Entry filters", "depth60", "Base no deeper than 60% below R", replace(BASE, max_depth=0.60)),
    ("Entry filters", "tests2", "At least 2 tests of R (within 8%) during the base", replace(BASE, min_tests=2)),
    ("Stops and exits", "sl97", "First stop max(0.97 R, breakout-week low)", replace(BASE, stop0="R97|low")),
    ("Stops and exits", "sl97risk", "... and skip if the stop is more than 10% below", replace(BASE, stop0="R97|low", max_risk=0.10)),
    ("Stops and exits", "pct8", "8% below the buy price (not R), 2-week-low trail", replace(BASE, stop0="pct8")),
    ("Stops and exits", "pct8ma30", "8% below the buy price, 30-week average trail", replace(BASE, stop0="pct8", trail="ma30")),
    ("Stops and exits", "be15", "Stop to the buy price once +15%", replace(BASE, breakeven_at=0.15)),
    ("Stops and exits", "be20", "Stop to the buy price once +20%", replace(BASE, breakeven_at=0.20)),
    ("Stops and exits", "trail20", "2-week-low trail only after +20% (R stop until then)", replace(BASE, trail_after=0.20)),
    ("Stops and exits", "ma10", "10-week average trail (not 2-week low)", replace(BASE, trail="ma10")),
    ("Stops and exits", "ma30", "30-week average trail (the older rule)", replace(BASE, trail="ma30")),
    ("Stops and exits", "notrail", "R stop only, no trail", replace(BASE, trail="none")),
    ("Combinations", "sl97ma30", "First stop max(0.97 R, week low) + 30-week average trail", replace(BASE, stop0="R97|low", trail="ma30")),
    ("Combinations", "sl97t20", "First stop max(0.97 R, week low) + 2-week-low trail after +20%", replace(BASE, stop0="R97|low", trail_after=0.20)),
    ("Combinations", "med10ma30", "Median-10 volume + first stop max(0.97 R, week low) + 30-week trail", replace(BASE, vol_rule="med10", stop0="R97|low", trail="ma30")),
    ("Cup and handle (O'Neil)", "ch", "Sheet exits: below the handle low, 2-week-low trail", CH),
    ("Cup and handle (O'Neil)", "chma30", "Handle-low stop, 30-week average trail", replace(CH, trail="ma30")),
    ("Cup and handle (O'Neil)", "chsl97ma30", "First stop max(0.97 pivot, week low) + 30-week trail", replace(CH, stop0="R97|low", trail="ma30")),
    ("Cup and handle (O'Neil)", "chpct8", "8% stop (O'Neil) + 2-week-low trail", replace(CH, stop0="pct8")),
    ("Cup and handle (O'Neil)", "chpct8ma30", "8% stop (O'Neil) + 30-week trail", replace(CH, stop0="pct8", trail="ma30")),
    ("Cup and handle (O'Neil)", "chdeep50", "Cups up to 50% deep, 0.97 pivot stop + 30-week trail", replace(CH, ch_depth=(0.12, 0.50), stop0="R97|low", trail="ma30")),
    ("Cup and handle (O'Neil)", "chnoprior", "No 30% prior rise needed, 0.97 pivot stop + 30-week trail", replace(CH, ch_prior_up=0.0, stop0="R97|low", trail="ma30")),
    ("Both setups in one portfolio", "both", "Multi-year + C&H, sheet exits", BOTH),
    ("Both setups in one portfolio", "bothbest", "Multi-year + C&H, 0.97 stop + 30-week trail", replace(BOTH, stop0="R97|low", trail="ma30")),
    ("Both setups in one portfolio", "bothres", "... C&H in at most 5 of the 10 slots", replace(BOTH, stop0="R97|low", trail="ma30", ch_max_slots=5)),
    ("Your v2 script", "v2myb", "Multi-year v2: median-10 vol, top third, depth 60%, Rs 5 Cr, 10% risk, market filter, two-stage exits", V2MYB),
    ("Your v2 script", "v2mybma30", "... same entry, 0.97 R stop + 30-week trail", replace(V2MYB, trail="ma30")),
    ("Your v2 script", "v2ch", "C&H as the updated sheet scans it (see apps-script/BreakoutTracker.gs), two-stage exits", V2CH),
    ("Your v2 script", "v2chma30", "... same C&H, handle-low stop + 30-week trail", replace(V2CH, trail="ma30")),
    ("Your v2 script", "v2choneil", "... stricter O'Neil (35% cup, 12% handle, 30% prior rise, no U, median-10 vol 1.5x), two-stage exits", V2ONEIL),
    ("Ranking", "udvol", "Rank same-week breakouts by up/down volume (20 weeks)", replace(BASE, rank="udvol")),
    ("Ranking", "momentum", "Rank same-week breakouts by momentum score", replace(BASE, rank="momentum")),
]


def main():
    data = ms.Data()
    feat = ms.Features(data)
    b = Breakouts(data, feat)
    wk = Weekly(b)
    # first week the rules can be measured: 2 years + 4 weeks of weekly highs, 30-week average
    from_w = next(w for w in range(wk.W) if (wk.base_yrs[w] >= 2).any())
    full_w = next(w for w, x in enumerate(wk.dates) if x >= FULL_WINDOW_FROM)
    print(f"from {wk.dates[from_w]}  full 5-year window from {wk.dates[full_w]}  to {wk.dates[-1]}")

    rows, results = [], {}
    for group, key, label, sp in VARIANTS:
        sig = signals(wk, sp)
        sig.sig[:from_w] = False
        ev = every_signal(wk, sp, sig, from_w)
        ev_recent = [x for x in ev if x["w"] >= full_w]
        pf = portfolio(wk, sp, sig, from_w, record=True)
        pf_recent = portfolio(wk, sp, sig, full_w)
        pf_liquid = portfolio(wk, replace(sp, cash_asset=None), sig, from_w)
        results[key] = (sig, ev, pf, pf_liquid)
        rows.append({"group": group, "key": key, "label": label, "spec": asdict(sp),
                     "signals": signal_stats(ev), "signalsRecent": signal_stats(ev_recent),
                     "portfolio": {**port_stats(pf), "yearly": by_year(pf["dates"], pf["equity"]),
                                   "drawdowns": ms.drawdowns(pf["dates"], pf["equity"])},
                     "portfolioRecent": port_stats(pf_recent), "portfolioLiquid": port_stats(pf_liquid)})
        s, p = rows[-1]["signals"], rows[-1]["portfolio"]
        pr, pl = rows[-1]["portfolioRecent"], rows[-1]["portfolioLiquid"]
        print(f"{key:9s} sig {s['n']:4d} win {s['winRate']*100:5.1f}% avg {s['avgRet']*100:6.1f}% med {s['medRet']*100:6.1f}% "
              f"wks {s['medWeeks']:4.0f} 6m {s.get('6m', {}).get('mean', 0)*100:6.1f}% ex {s.get('6m', {}).get('excess', 0)*100:6.1f}% | "
              f"CAGR {p['cagr']*100:5.1f}% DD {p['maxDD']*100:6.1f}% tr {p['trades']:3d} skip {p['skipped']:3d} gold {p['avgCash']*100:4.0f}% "
              f"| liquid {pl['cagr']*100:5.1f}% | since 24-09 {pr['cagr']*100:5.1f}%")

    # benchmarks over the same days as the portfolio runs
    pf = results["base"][2]
    dates, t0 = pf["dates"], pf["t0"]
    idx_eq = rebased(data.calendar, data.index, dates)
    gold_eq = CAPITAL * np.cumprod(1 + data.cash_ret["GOLDBEES"][t0:])
    bench = [{"key": "nifty500", "label": "Nifty 500 index", **ms.stats(dates, idx_eq), "yearly": by_year(dates, idx_eq)},
             {"key": "gold", "label": "GOLDBEES (buy and hold)", **ms.stats(dates, gold_eq), "yearly": by_year(dates, gold_eq)}]
    t1 = wk.ends[full_w - 1] + 1
    d1 = data.calendar[t1:]
    bench_recent = [{"key": "nifty500", **ms.stats(d1, rebased(data.calendar, data.index, d1))},
                    {"key": "gold", **ms.stats(d1, CAPITAL * np.cumprod(1 + data.cash_ret["GOLDBEES"][t1:]))}]
    for x in bench:
        print(f"{x['label']:24s} CAGR {x['cagr']*100:5.1f}% DD {x['maxDD']*100:6.1f}%")

    names = data.symbols
    _, hlow, cupw, cdep = wk.cup_handle(CH)

    def listing(key):
        """Every signal of a variant, as traded on its own."""
        return [{"s": names[x["j"]], "setup": SETUP[x["kind"]], "sig": wk.dates[x["w"]],
                 "exit": wk.dates[x["x"]] if x["why"] != "open" else None, "ret": x["ret"], "why": x["why"], "weeks": x["weeks"],
                 "base": (f"{wk.base_yrs[x['w'], x['j']]:.1f} yr base" if x["kind"] == 1 else
                          f"{cupw[x['w'], x['j']]:.0f} wk cup, {cdep[x['w'], x['j']] * 100:.0f}% deep"),
                 "above": float(wk.close[x["w"], x["j"]] / x["level"] - 1), "vr": float(wk.vr["avg5"][x["w"], x["j"]])}
                for x in results[key][1]]
    per_week = [int(results["base"][0].sig[w].sum()) for w in range(from_w, wk.W)]
    per_week_both = [int(results["both"][0].sig[w].sum()) for w in range(from_w, wk.W)]
    out = {"asOf": data.calendar[-1], "from": wk.dates[from_w], "fullFrom": wk.dates[full_w], "capital": CAPITAL,
           "variants": rows, "bench": bench, "benchRecent": bench_recent,
           "curve": [{"d": dates[i], "base": round(float(pf["equity"][i])), "nifty500": round(float(idx_eq[i])),
                      "gold": round(float(gold_eq[i])), "baseLiquid": round(float(results["base"][3]["equity"][i])),
                      "best": round(float(results[BEST][2]["equity"][i])), "bestLiquid": round(float(results[BEST][3]["equity"][i])),
                      "bothBest": round(float(results[BEST_BOTH][2]["equity"][i])),
                      "bothBestLiquid": round(float(results[BEST_BOTH][3]["equity"][i]))} for i in range(len(dates)) if i == len(dates) - 1 or b.week_end[t0 + i]],
           "signalList": {"base": listing("base"), "ch": listing("ch")}, "basePortfolioTrades": pf["trades"], "baseLog": pf["log"],
           "signalsPerWeek": {"mean": float(np.mean(per_week)), "max": int(max(per_week)),
                              "zeroWeeks": float(np.mean([x == 0 for x in per_week]))},
           "signalsPerWeekBoth": {"mean": float(np.mean(per_week_both)), "max": int(max(per_week_both)),
                                  "zeroWeeks": float(np.mean([x == 0 for x in per_week_both]))}}
    (ROOT / "breakout_spec_study.json").write_text(json.dumps(out, separators=(",", ":"), default=float), encoding="utf-8")
    print("signals per week", out["signalsPerWeek"])


if __name__ == "__main__":
    main()
