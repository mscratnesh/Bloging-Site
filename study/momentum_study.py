"""Momentum strategy study: survivorship bias, parameter sensitivity, timing, costs/taxes/capacity,
and risk & robustness for the Momentum Scan rules.

Inputs (all local, no downloads):
  momentum_prices.json            price cache built by momentum.py (the 750 tested stocks + Nifty 500)
  study/prices_extra.json         past Nifty 500 members outside the 750 (study/fetch_extra_prices.py)
  study/constituents/*.csv        point-in-time Nifty 500 lists (study/fetch_constituents.py)
  nifty750_backtest_list.csv      the fixed 750 list
Output:
  momentum_study.json             everything the study page (momentum-study.html) shows

Run: py study/momentum_study.py      (needs numpy; offline analysis, not part of the site EXE)
"""
import csv
import json
import math
import sys
from dataclasses import dataclass, replace
from datetime import date, datetime
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
from renames import RENAMES  # noqa: E402

TRADING_DAYS = 252
MAX_DAILY_MOVE = 0.60
MAX_FFILL = 5
COVERAGE = 0.9
LIQUID_ANNUAL = 0.065
ALL_LOOKBACKS = (21, 63, 126, 184, 189, 252)
TAX_CHANGE = "2024-07-23"  # Budget 2024: STCG 15% -> 20%, LTCG 10% -> 12.5%


@dataclass(frozen=True)
class Params:
    lookbacks: tuple = (252, 184, 126, 63)
    annualise: bool = False          # sheet rule: plain % return / annualised vol
    max_fall: float = 0.25           # None = no ATH filter
    sma_days: int = 233              # None = no trend filter
    min_turnover: float = 1e7        # Rs per day
    top_n: int = 10
    exit_rank: int = 30
    market_ma: int = 200             # None = never go to the liquid fund
    market_check: str = "monthly"    # "monthly" | "daily"
    rebalance: str = "month_end"     # "month_end" | "offset:k" (k trading days before) | "mid_month" | "quarterly"
    cost: float = 0.0025             # per side
    universe: str = "fixed750"       # "fixed750" | "today500" | "pit500"
    taxes: bool = False
    # Extra exit: sell a holding that falls `stop_pct` within the month.
    #   "from_rebalance": daily, close <= (1 - stop_pct) x its close at the last rebalance (or buy price)
    #   "trailing":       daily, close <= (1 - stop_pct) x its highest close since the last rebalance
    #   "month_end":      at the rebalance, if it fell stop_pct or more since the previous rebalance
    # Stopped-out money waits in the liquid fund until the next rebalance refills the slot.
    stop_mode: str = None
    stop_pct: float = 0.10


BASE = Params()


# ---------------------------------------------------------------- data

class Data:
    def __init__(self):
        store = json.loads((ROOT / "momentum_prices.json").read_text(encoding="utf-8"))
        extra = json.loads((HERE / "prices_extra.json").read_text(encoding="utf-8"))
        self.calendar = sorted(store["index"])
        self.day_index = {d: i for i, d in enumerate(self.calendar)}
        self.index = np.array([store["index"][d] for d in self.calendar])

        stocks = dict(store["stocks"])
        for old, data in extra.items():  # past members, keyed by their current symbol
            stocks.setdefault(data.get("yahooSymbol", old), data)
        self.symbols = sorted(stocks)
        self.col = {s: j for j, s in enumerate(self.symbols)}
        T, N = len(self.calendar), len(self.symbols)
        close = np.full((T, N), np.nan)
        high = np.full((T, N), np.nan)
        volume = np.full((T, N), np.nan)
        high_before = np.zeros(N)
        for j, s in enumerate(self.symbols):
            bars = stocks[s]["bars"]
            high_before[j] = stocks[s].get("highBefore") or 0.0
            for d, (c, h, v) in bars.items():
                i = self.day_index.get(d)
                if i is not None:
                    close[i, j], high[i, j], volume[i, j] = c, h, v
        self.raw_close = close.copy()
        # forward-fill short gaps only
        filled, gap = close.copy(), np.zeros(N)
        for i in range(1, T):
            missing = np.isnan(filled[i])
            gap = np.where(missing, gap + 1, 0)
            use = missing & (gap <= MAX_FFILL)
            filled[i, use] = filled[i - 1, use]
        self.close = filled
        with np.errstate(invalid="ignore", divide="ignore"):
            r = filled[1:] / filled[:-1] - 1
        r[np.abs(r) > MAX_DAILY_MOVE] = np.nan
        self.ret = np.vstack([np.full((1, N), np.nan), r])
        self.turnover_daily = close * volume  # only on days with a real bar
        self.ath = np.fmax.accumulate(np.vstack([high_before[None, :], np.fmax(high, close)]), axis=0)[1:]
        self._universes()

    def _universes(self):
        fixed = [row["Symbol"] for row in csv.DictReader((ROOT / "nifty750_backtest_list.csv").open(encoding="utf-8"))]
        self.fixed750 = self._mask(fixed)
        snaps = []
        for path in sorted((HERE / "constituents").glob("nifty500_*.csv")):
            symbols = [row["Symbol"] for row in csv.DictReader(path.open(encoding="utf-8"))]
            snaps.append((path.stem.split("_")[1], symbols))
        self.snapshots = snaps
        self.today500 = self._mask(snaps[-1][1])
        self.pit = [(d, self._mask(s), s) for d, s in snaps]

    def canonical(self, symbol):
        if symbol in self.col:
            return symbol
        renamed = RENAMES.get(symbol)
        return renamed if renamed in self.col else None

    def _mask(self, symbols):
        m = np.zeros(len(self.symbols), dtype=bool)
        for s in symbols:
            c = self.canonical(s)
            if c:
                m[self.col[c]] = True
        return m

    def universe_mask(self, name, day):
        if name == "fixed750":
            return self.fixed750
        if name == "today500":
            return self.today500
        mask = self.pit[0][1]
        for d, m, _ in self.pit:  # latest snapshot on or before the day
            if d <= day:
                mask = m
        return mask

    def coverage(self):
        rows = []
        for d, _, symbols in self.pit:
            have = sum(1 for s in symbols if self.canonical(s))
            rows.append({"date": d, "members": len(symbols), "withPrices": have,
                         "missing": sorted(s for s in symbols if not self.canonical(s))})
        return rows


class Features:
    """Rolling statistics as T x N arrays (computed once, shared by every variant)."""

    def __init__(self, data):
        d = data
        T, N = d.close.shape
        ok = ~np.isnan(d.ret)
        r0 = np.where(ok, d.ret, 0.0)
        self.c_cnt = np.vstack([np.zeros(N), np.cumsum(ok, axis=0)])
        self.c_sum = np.vstack([np.zeros(N), np.cumsum(r0, axis=0)])
        self.c_sq = np.vstack([np.zeros(N), np.cumsum(r0 * r0, axis=0)])
        cl_ok = ~np.isnan(d.close)
        self.p_cnt = np.vstack([np.zeros(N), np.cumsum(cl_ok, axis=0)])
        self.p_sum = np.vstack([np.zeros(N), np.cumsum(np.where(cl_ok, d.close, 0.0), axis=0)])
        tv_ok = ~np.isnan(d.turnover_daily)
        self.t_cnt = np.vstack([np.zeros(N), np.cumsum(tv_ok, axis=0)])
        self.t_sum = np.vstack([np.zeros(N), np.cumsum(np.where(tv_ok, d.turnover_daily, 0.0), axis=0)])
        self.data = d
        self._cache = {}

    def _window(self, cnt, s, t, n):
        if t - n + 1 < 0:
            return np.full(cnt.shape[1], np.nan), np.zeros(cnt.shape[1])
        k = cnt[t + 1] - cnt[t - n + 1]
        return s[t + 1] - s[t - n + 1], k

    def sharpe(self, t, n, annualise):
        key = ("sh", t, n, annualise)
        if key in self._cache:
            return self._cache[key]
        d = self.data
        out = np.full(d.close.shape[1], np.nan)
        if t - n >= 0:
            s, k = self._window(self.c_cnt, self.c_sum, t, n)
            s2, _ = self._window(self.c_cnt, self.c_sq, t, n)
            with np.errstate(invalid="ignore", divide="ignore"):
                var = (s2 - s * s / k) / (k - 1)
                vol = np.sqrt(var * TRADING_DAYS)
                ret = d.close[t] / d.close[t - n] - 1
                if annualise:
                    ret = (1 + ret) ** (TRADING_DAYS / n) - 1
                out = ret / vol
            out[(k < max(2, n * COVERAGE)) | ~(vol > 0)] = np.nan
        self._cache[key] = out
        return out

    def sma(self, t, n):
        s, k = self._window(self.p_cnt, self.p_sum, t, n)
        with np.errstate(invalid="ignore", divide="ignore"):
            out = s / k
        out[k < n * COVERAGE] = np.nan
        return out

    def turnover(self, t, n=TRADING_DAYS):
        s, k = self._window(self.t_cnt, self.t_sum, t, n)
        with np.errstate(invalid="ignore", divide="ignore"):
            out = s / k
        out[k < n * COVERAGE] = np.nan
        return out

    def score(self, t, p):
        parts = [self.sharpe(t, n, p.annualise) for n in p.lookbacks]
        return np.mean(parts, axis=0)  # NaN if any part is NaN

    def ranking(self, t, p, universe):
        """Column indices passing universe + filters, best score first."""
        d = self.data
        cmp = d.close[t]
        ok = universe & ~np.isnan(cmp)
        score = self.score(t, p)
        ok &= ~np.isnan(score)
        if p.max_fall is not None:
            with np.errstate(invalid="ignore"):
                ok &= (d.ath[t] - cmp) / d.ath[t] < p.max_fall
        if p.sma_days:
            with np.errstate(invalid="ignore"):
                ok &= cmp > self.sma(t, p.sma_days)
        if p.min_turnover:
            with np.errstate(invalid="ignore"):
                ok &= self.turnover(t) > p.min_turnover
        idx = np.flatnonzero(ok)
        return idx[np.argsort(-score[idx], kind="stable")]


# ---------------------------------------------------------------- backtest

def rebalance_days(calendar, rule, start):
    months = {}
    for i, d in enumerate(calendar):
        months.setdefault(d[:7], []).append(i)
    current = calendar[-1][:7]
    out = []
    for month, idx in months.items():
        if month == current:
            continue  # month not finished
        if rule == "month_end":
            t = idx[-1]
        elif rule.startswith("offset:"):
            k = int(rule.split(":")[1])
            t = idx[max(0, len(idx) - 1 - k)]
        elif rule == "mid_month":
            t = next((i for i in idx if int(calendar[i][8:]) >= 15), idx[-1])
        elif rule == "quarterly":
            if month[5:] not in ("03", "06", "09", "12"):
                continue
            t = idx[-1]
        else:
            raise ValueError(rule)
        if t >= start:
            out.append(t)
    return out


def market_sma(index, n):
    out = np.full(len(index), np.nan)
    c = np.concatenate([[0.0], np.cumsum(index)])
    out[n - 1:] = (c[n:] - c[:-n]) / n
    return out


class Tax:
    """Indian capital-gains tax on realised gains, settled each financial year (April-March).

    STCG (held < 12 months) 15% / LTCG 10% before 23 Jul 2024, then 20% / 12.5%. Short-term losses
    offset any gains, long-term losses only long-term gains; unused losses carry forward. The LTCG
    exemption (Rs 1-1.25 lakh a year) is ignored, so this slightly overstates tax on small accounts.
    """

    def __init__(self):
        self.st = self.lt = 0.0  # tax due this FY, already rate-weighted
        self.carry_st = self.carry_lt = 0.0
        self.st_gain = self.lt_gain = 0.0
        self.paid = 0.0

    def realise(self, gain, held_days, day):
        long_term = held_days >= 365
        new = day >= TAX_CHANGE
        rate = (0.125 if new else 0.10) if long_term else (0.20 if new else 0.15)
        # keep gains per type with their rate weight (approximation: weight by the sale-date rate)
        if long_term:
            self.lt_gain += gain
            self.lt += gain * rate
        else:
            self.st_gain += gain
            self.st += gain * rate

    def settle(self):
        """Returns the tax payable for the FY just ended (as a fraction of portfolio units)."""
        st_net = self.st_gain + self.carry_st
        lt_net = self.lt_gain + self.carry_lt
        # effective rates this FY (gain-weighted), defaulting to the current rates
        st_rate = self.st / self.st_gain if self.st_gain > 0 else 0.20
        lt_rate = self.lt / self.lt_gain if self.lt_gain > 0 else 0.125
        if st_net < 0:  # ST losses can offset LT gains
            lt_net += st_net
            st_net = 0.0
        tax = max(st_net, 0) * st_rate + max(lt_net, 0) * lt_rate
        self.carry_st = 0.0
        self.carry_lt = min(lt_net, 0.0)
        self.st = self.lt = self.st_gain = self.lt_gain = 0.0
        self.paid += tax
        return tax


def backtest(feat, p, rng=None, record=False):
    """Replays the strategy. With rng, picks random stocks from the filtered list (luck test)."""
    d = feat.data
    cal = d.calendar
    start = max(max(p.lookbacks), p.sma_days or 0, TRADING_DAYS, p.market_ma or 0) + 5
    rebal = rebalance_days(cal, p.rebalance, start)
    rebal_set = set(rebal)
    sma = market_sma(d.index, p.market_ma) if p.market_ma else None
    liquid_daily = (1 + LIQUID_ANNUAL) ** (1 / TRADING_DAYS) - 1

    cash, hold, entry = 1.0, {}, {}
    ref, peak = {}, {}  # per holding: close at the last rebalance, highest close since then
    tax = Tax() if p.taxes else None
    equity, trades, events, turnover_traded = [], [], [], 0.0
    exposure, positions_log = [], []
    t0 = rebal[0]
    for t in range(t0, len(cal)):
        day = cal[t]
        if t > t0:
            for j in hold:
                r = d.ret[t, j]
                hold[j] *= 1 + (0.0 if np.isnan(r) else r)
            cash *= 1 + liquid_daily
            if tax and day[5:7] == "04" and cal[t - 1][5:7] == "03":  # new financial year
                due = tax.settle()
                total = cash + sum(hold.values())
                if due > 0 and total > 0:
                    scale = 1 - due / total
                    cash *= scale
                    hold = {j: v * scale for j, v in hold.items()}
                    entry = {j: {**e, "basis": e["basis"] * scale} for j, e in entry.items()}

        # Daily stop within the month (rebalance days are handled by the rebalance itself).
        if p.stop_mode in ("from_rebalance", "trailing") and hold and t not in rebal_set:
            stopped = []
            for j in hold:
                price = d.close[t, j]
                if np.isnan(price):
                    continue
                peak[j] = max(peak[j], price)
                level = (peak[j] if p.stop_mode == "trailing" else ref[j]) * (1 - p.stop_pct)
                if price <= level:
                    stopped.append(j)
            for j in stopped:
                v = hold.pop(j)
                proceeds = v * (1 - p.cost)
                _close_trade(trades, entry.pop(j), j, day, proceeds, tax, cal)
                cash += proceeds
                turnover_traded += v
            if stopped:
                events.append({"date": day, "type": "STOP", "n": len(stopped)})

        below = sma is not None and not np.isnan(sma[t]) and d.index[t] < sma[t]
        force_exit = p.market_check == "daily" and below and hold and t not in rebal_set
        if (t in rebal_set and below) or force_exit:
            if hold:
                for j, v in hold.items():
                    proceeds = v * (1 - p.cost)
                    _close_trade(trades, entry.pop(j), j, day, proceeds, tax, cal)
                    cash += proceeds
                    turnover_traded += v
                events.append({"date": day, "type": "EXIT", "n": len(hold)})
                hold = {}
        elif t in rebal_set:
            universe = d.universe_mask(p.universe, day)
            order = feat.ranking(t, p, universe)
            if rng is not None:
                # Luck test: same filters and turnover discipline, but no ranking. Keep a holding
                # while it still passes the filters; replacements are picked at random.
                top = set(order.tolist())
                order = rng.permutation(order)
            else:
                top = set(order[:p.exit_rank].tolist())
            was_empty = not hold
            fell = lambda j: (p.stop_mode == "month_end" and not np.isnan(d.close[t, j])
                              and d.close[t, j] <= ref[j] * (1 - p.stop_pct))
            sold = [j for j in hold if j not in top or fell(j)]
            for j in sold:
                v = hold.pop(j)
                proceeds = v * (1 - p.cost)
                _close_trade(trades, entry.pop(j), j, day, proceeds, tax, cal)
                cash += proceeds
                turnover_traded += v
            fell_now = {j for j in sold if fell(j)}  # don't buy straight back what the stop just sold
            buys = [j for j in order.tolist() if j not in hold and j not in fell_now][:p.top_n - len(hold)]
            if buys and cash > 0:
                share = cash * (1 - p.cost) / len(buys)
                for j in buys:
                    hold[j] = share
                    entry[j] = {"day": day, "t": t, "basis": share, "price": d.close[t, j]}
                    turnover_traded += share
                    if record:
                        positions_log.append({"t": t, "col": j, "value": share})
                cash = 0.0
            if sold or buys:
                events.append({"date": day, "type": "ENTER" if was_empty else "SWAP", "n": len(sold) + len(buys)})
        if t in rebal_set:  # the stop is measured from each rebalance's close
            for j in hold:
                price = d.close[t, j]
                ref[j] = peak[j] = price if not np.isnan(price) else entry[j]["price"]
        total = cash + sum(hold.values())
        equity.append(total)
        if record:
            exposure.append((t, dict(hold), cash))

    result = {"equity": np.array(equity), "dates": cal[t0:], "trades": trades, "events": events,
              "turnover": turnover_traded, "taxPaid": tax.paid if tax else 0.0, "rebalances": rebal}
    if record:
        result["exposure"] = exposure
        result["buys"] = positions_log
    return result


def _close_trade(trades, e, j, day, proceeds, tax, cal):
    held = (date.fromisoformat(day) - date.fromisoformat(e["day"])).days
    trades.append({"col": j, "entry": e["day"], "exit": day, "ret": proceeds / e["basis"] - 1, "days": held})
    if tax:
        tax.realise(proceeds - e["basis"], held, day)


# ---------------------------------------------------------------- metrics

def stats(dates, eq):
    years = (date.fromisoformat(dates[-1]) - date.fromisoformat(dates[0])).days / 365.25
    daily = eq[1:] / eq[:-1] - 1
    vol = daily.std(ddof=1) * math.sqrt(TRADING_DAYS)
    peak = np.maximum.accumulate(eq)
    dd = eq / peak - 1
    cagr = (eq[-1] / eq[0]) ** (1 / years) - 1
    downside = daily[daily < 0].std(ddof=1) * math.sqrt(TRADING_DAYS)
    return {
        "cagr": cagr, "vol": vol, "maxDD": float(dd.min()),
        "sharpe": (daily.mean() * TRADING_DAYS - LIQUID_ANNUAL) / vol if vol else None,
        "sortino": (daily.mean() * TRADING_DAYS - LIQUID_ANNUAL) / downside if downside else None,
        "calmar": cagr / abs(dd.min()) if dd.min() < 0 else None,
        "multiple": float(eq[-1] / eq[0]),
    }


def summary(run):
    s = stats(run["dates"], run["equity"])
    trades = run["trades"]
    years = (date.fromisoformat(run["dates"][-1]) - date.fromisoformat(run["dates"][0])).days / 365.25
    s["trades"] = len(trades)
    s["winRate"] = float(np.mean([tr["ret"] > 0 for tr in trades])) if trades else None
    s["turnoverPerYear"] = run["turnover"] / float(np.mean(run["equity"])) / years / 2  # one-way
    s["avgHoldDays"] = float(np.mean([tr["days"] for tr in trades])) if trades else None
    return s


def drawdowns(dates, eq, top=5):
    peak_i, out, i = 0, [], 1
    peak = eq[0]
    in_dd = False
    trough_i = 0
    for i in range(1, len(eq)):
        if eq[i] >= peak:
            if in_dd:
                out.append((peak_i, trough_i, i))
                in_dd = False
            peak, peak_i = eq[i], i
        else:
            if not in_dd:
                in_dd, trough_i = True, i
            if eq[i] < eq[trough_i]:
                trough_i = i
    if in_dd:
        out.append((peak_i, trough_i, None))
    rows = [{"peak": dates[a], "trough": dates[b], "recovered": dates[c] if c is not None else None,
             "depth": float(eq[b] / eq[a] - 1),
             "daysDown": (date.fromisoformat(dates[b]) - date.fromisoformat(dates[a])).days,
             "daysToRecover": (date.fromisoformat(dates[c]) - date.fromisoformat(dates[b])).days if c is not None else None}
            for a, b, c in out]
    return sorted(rows, key=lambda r: r["depth"])[:top]


def monthly_returns(dates, eq):
    months, last = [], None
    for i, d in enumerate(dates):
        if i == len(dates) - 1 or dates[i + 1][:7] != d[:7]:
            if last is not None:
                months.append((d[:7], float(eq[i] / eq[last] - 1)))
            last = i
    return months


def rolling(dates, eq, bench, window_days):
    out = []
    for i in range(window_days, len(eq), 5):
        out.append({"date": dates[i], "strategy": float(eq[i] / eq[i - window_days] - 1),
                    "nifty500": float(bench[i] / bench[i - window_days] - 1)})
    return out


def equal_weight_universe(feat, universe_name, t0):
    """Equal-weight, monthly-rebalanced portfolio of every stock in the universe (same bias)."""
    d = feat.data
    rebal = set(rebalance_days(d.calendar, "month_end", t0))
    value, weights, curve = 1.0, None, []
    for t in range(t0, len(d.calendar)):
        if weights is not None:
            r = d.ret[t][weights]
            value *= 1 + float(np.nanmean(r)) if np.any(~np.isnan(r)) else 1
        if t == t0 or t in rebal:
            mask = d.universe_mask(universe_name, d.calendar[t]) & ~np.isnan(d.close[t])
            weights = np.flatnonzero(mask)
        curve.append(value)
    return np.array(curve)


# ---------------------------------------------------------------- study

def main():
    data = Data()
    feat = Features(data)
    cal = data.calendar
    out = {"generatedAt": datetime.now().isoformat(timespec="seconds"), "asOf": cal[-1], "base": BASE.__dict__}

    def run(p, **kw):
        return backtest(feat, p, **kw)

    def row(label, p, extra=None):
        r = run(p)
        s = summary(r)
        s.update({"label": label, "from": r["dates"][0], "to": r["dates"][-1]})
        if extra:
            s.update(extra)
        return s, r

    # --- base case (the strategy's own rules) + benchmarks
    base_s, base = row("Base case (sheet rules)", BASE, {"taxPaid": 0})
    dates = base["dates"]
    t0 = base["rebalances"][0]
    bench = data.index[t0:] / data.index[t0]
    ew750 = equal_weight_universe(feat, "fixed750", t0)
    out["baseCase"] = base_s
    out["benchmarks"] = [
        {"label": "Nifty 500 (price index)", **stats(dates, bench)},
        {"label": "Equal-weight Nifty 750 (same stock list)", **stats(dates, ew750)},
    ]

    # --- 1. survivorship bias
    surv = []
    curves = {}
    for label, uni in (("Today's Nifty 500 list, used for every month", "today500"),
                       ("Point-in-time Nifty 500 lists", "pit500")):
        s, r = row(label, replace(BASE, universe=uni))
        ew = equal_weight_universe(feat, uni, r["rebalances"][0])
        s["equalWeight"] = stats(r["dates"], ew)
        s["excessOverEW"] = s["cagr"] - s["equalWeight"]["cagr"]
        surv.append(s)
        curves[uni] = r
    out["survivorship"] = {
        "runs": surv,
        "biasCagr": surv[0]["cagr"] - surv[1]["cagr"],
        "coverage": [c for c in data.coverage() if c["date"] >= "2020-01-01"],
        "curve": _curve(curves["today500"]["dates"], {"today": curves["today500"]["equity"], "pit": curves["pit500"]["equity"]}),
    }

    # --- 2. parameter sensitivity (one change at a time from the base case)
    groups = {
        "Stocks held (top N)": [(f"Top {n}", replace(BASE, top_n=n, exit_rank=max(BASE.exit_rank, n))) for n in (5, 10, 15, 20)],
        "Exit rank (buffer)": [(f"Sell when out of top {k}" + (" (no buffer)" if k == 10 else ""), replace(BASE, exit_rank=k)) for k in (10, 20, 30, 50)],
        "Lookbacks": [
            ("252/184/126/63 (sheet)", BASE),
            ("252/189/126/63", replace(BASE, lookbacks=(252, 189, 126, 63))),
            ("12 months only", replace(BASE, lookbacks=(252,))),
            ("6 months only", replace(BASE, lookbacks=(126,))),
            ("12 and 6 months", replace(BASE, lookbacks=(252, 126))),
            ("6 and 3 months", replace(BASE, lookbacks=(126, 63))),
        ],
        "Score formula": [
            ("% return / annualised vol (sheet)", BASE),
            ("Annualised return / annualised vol", replace(BASE, annualise=True)),
        ],
        "Near all-time high filter": [(label, replace(BASE, max_fall=v)) for label, v in
                                      (("Within 15%", 0.15), ("Within 25% (sheet)", 0.25), ("Within 35%", 0.35), ("No ATH filter", None))],
        "Trend filter": [(label, replace(BASE, sma_days=v)) for label, v in
                         (("Above SMA233 (sheet)", 233), ("Above SMA200", 200), ("Above SMA100", 100), ("No trend filter", None))],
        "Market filter (Nifty 500)": [
            ("200-DMA, checked at month-end (base)", BASE),
            ("200-DMA, checked daily", replace(BASE, market_check="daily")),
            ("100-DMA, checked at month-end", replace(BASE, market_ma=100)),
            ("No market filter (always invested)", replace(BASE, market_ma=None)),
        ],
        "Rebalance frequency": [
            ("Monthly (base)", BASE),
            ("Quarterly", replace(BASE, rebalance="quarterly")),
        ],
    }
    sens = []
    for group, variants in groups.items():
        rows = []
        for label, p in variants:
            s, _ = row(label, p)
            s["isBase"] = p == BASE
            rows.append(s)
        sens.append({"group": group, "rows": rows})
    out["sensitivity"] = sens

    # heat map: top N x exit rank
    grid = []
    for n in (5, 10, 15, 20):
        for k in (10, 20, 30, 50):
            if k < n:
                continue
            s = summary(run(replace(BASE, top_n=n, exit_rank=k)))
            grid.append({"topN": n, "exitRank": k, "cagr": s["cagr"], "maxDD": s["maxDD"], "sharpe": s["sharpe"]})
    out["grid"] = grid

    # --- 3. timing luck: which day of the month you rebalance on
    timing = []
    for label, rule in (("Last trading day (base)", "month_end"), ("1 day before month-end", "offset:1"),
                        ("2 days before", "offset:2"), ("3 days before", "offset:3"), ("5 days before", "offset:5"),
                        ("Mid-month (15th)", "mid_month")):
        s, _ = row(label, replace(BASE, rebalance=rule))
        timing.append(s)
    out["timing"] = timing

    # --- 4. luck test: random picks from the same filtered list
    rng = np.random.default_rng(7)
    random_cagr = []
    for _ in range(200):
        r = backtest(feat, BASE, rng=rng)
        random_cagr.append(stats(r["dates"], r["equity"])["cagr"])
    random_cagr = np.array(random_cagr)
    out["luck"] = {
        "runs": len(random_cagr),
        "percentiles": {str(q): float(np.percentile(random_cagr, q)) for q in (5, 25, 50, 75, 95)},
        "baseCagr": base_s["cagr"],
        "shareBeaten": float(np.mean(random_cagr < base_s["cagr"])),
        "histogram": np.histogram(random_cagr, bins=20)[0].tolist(),
        "binEdges": np.histogram(random_cagr, bins=20)[1].tolist(),
    }

    # --- 5. costs, taxes, capacity
    cost_rows = []
    for c in (0.001, 0.0025, 0.005, 0.01):
        s, _ = row(f"{c * 100:.2g}% per side", replace(BASE, cost=c))
        cost_rows.append(s)
    tax_s, tax_run = row("After Indian capital-gains tax", replace(BASE, taxes=True))
    tax_s["taxPaid"] = tax_run["taxPaid"]
    out["costs"] = {"rows": cost_rows, "afterTax": tax_s, "preTax": base_s}
    out["capacity"] = capacity(feat, run(BASE, record=True))

    # --- 6. risk & robustness
    eq = base["equity"]
    months = monthly_returns(dates, eq)
    bench_months = dict(monthly_returns(dates, bench))
    mr = np.array([m[1] for m in months])
    out["risk"] = {
        "drawdowns": drawdowns(dates, eq),
        "benchDrawdowns": drawdowns(dates, bench, top=3),
        "timeUnderwater": float(np.mean(eq < np.maximum.accumulate(eq))),
        "monthly": {
            "count": len(mr), "positive": float(np.mean(mr > 0)), "best": float(mr.max()), "worst": float(mr.min()),
            "median": float(np.median(mr)),
            "beatNifty": float(np.mean([m[1] > bench_months.get(m[0], 0) for m in months])),
            "histogram": np.histogram(mr, bins=np.arange(-0.25, 0.30, 0.025))[0].tolist(),
            "binEdges": np.arange(-0.25, 0.30, 0.025).round(3).tolist(),
            "table": months,
        },
        "rolling12": rolling(dates, eq, bench, 252),
        "rolling36": rolling(dates, eq, bench, 756),
        "trades": trade_stats(base["trades"], data),
        "industry": industry_exposure(feat, run(BASE, record=True)),
    }
    out["curve"] = _curve(dates, {"strategy": eq, "nifty500": bench, "ew750": ew750})
    out["stopLoss"] = stop_loss_study(feat)

    (ROOT / "momentum_study.json").write_text(json.dumps(out, separators=(",", ":"), default=_json_default), encoding="utf-8")
    print_summary(out)


STOP_VARIANTS = (
    (None, "No stop (base)"),
    ("from_rebalance", "Daily: 10% below the month-start price"),
    ("trailing", "Daily trailing: 10% below the month's high"),
    ("month_end", "Month-end: fell 10% or more over the month"),
)
UNIVERSES = (("fixed750", "Nifty 750, today's list"), ("today500", "Nifty 500, today's list"),
             ("pit500", "Nifty 500, point-in-time"))


def stop_loss_study(feat):
    """Tests an extra 'exit if it falls 10% within the month' rule, on biased and unbiased lists."""
    d = feat.data
    grid = []
    for uni, uni_label in UNIVERSES:
        cells = []
        for mode, _ in STOP_VARIANTS:
            s = summary(backtest(feat, replace(BASE, universe=uni, stop_mode=mode)))
            cells.append({"cagr": s["cagr"], "maxDD": s["maxDD"], "sharpe": s["sharpe"], "turnover": s["turnoverPerYear"]})
        grid.append({"universe": uni_label, "cells": cells})

    thresholds = []
    for level in (0.07, 0.10, 0.15, 0.20):
        s = summary(backtest(feat, replace(BASE, universe="pit500", stop_mode="from_rebalance", stop_pct=level)))
        thresholds.append({"level": level, "cagr": s["cagr"], "maxDD": s["maxDD"], "sharpe": s["sharpe"]})

    # What happened to stocks after the daily stop sold them (until the next rebalance)?
    after = []
    for uni in ("fixed750", "pit500"):
        run = backtest(feat, replace(BASE, universe=uni, stop_mode="from_rebalance"))
        rebal = run["rebalances"]
        for tr in run["trades"]:
            t_exit = d.day_index[tr["exit"]]
            nxt = next((t for t in rebal if t > t_exit), None)
            if t_exit not in rebal and nxt is not None:
                after.append(d.close[nxt, tr["col"]] / d.close[t_exit, tr["col"]] - 1)
    after = np.array(after)

    market = []
    for uni, uni_label in UNIVERSES:
        row = {"universe": uni_label}
        for key, p in (("monthEnd", BASE), ("daily", replace(BASE, market_check="daily")),
                       ("dailyPlusStop", replace(BASE, market_check="daily", stop_mode="from_rebalance"))):
            s = summary(backtest(feat, replace(p, universe=uni)))
            row[key] = {"cagr": s["cagr"], "maxDD": s["maxDD"], "sharpe": s["sharpe"]}
        market.append(row)

    return {"variants": [label for _, label in STOP_VARIANTS], "grid": grid, "thresholds": thresholds,
            "afterStop": {"count": len(after), "median": float(np.median(after)),
                          "rebounded": float(np.mean(after > 0)), "fellFurther": float(np.mean(after < 0))},
            "marketFilter": market}


def capacity(feat, run):
    """Position size vs the stock's average daily turnover, for different starting capital."""
    d = feat.data
    eq = run["equity"]
    t0 = run["rebalances"][0]
    rows = []
    for capital in (1e6, 1e7, 1e8, 1e9):
        ratios = []
        for b in run["buys"]:
            t, j = b["t"], b["col"]
            adv = feat.turnover(t, 20)[j]  # last month's average daily turnover
            if adv and not np.isnan(adv):
                ratios.append(capital * b["value"] / adv)
        ratios = np.array(ratios)
        rows.append({"capital": capital, "buys": len(ratios),
                     "medianShareOfAdv": float(np.median(ratios)),
                     "p90ShareOfAdv": float(np.percentile(ratios, 90)),
                     "over10pct": float(np.mean(ratios > 0.10)),
                     "over25pct": float(np.mean(ratios > 0.25))})
    return rows


def trade_stats(trades, data):
    rets = np.array([t["ret"] for t in trades])
    wins, losses = rets[rets > 0], rets[rets <= 0]
    best = sorted(trades, key=lambda t: -t["ret"])[:5]
    worst = sorted(trades, key=lambda t: t["ret"])[:5]
    fmt = lambda t: {"symbol": data.symbols[t["col"]], "entry": t["entry"], "exit": t["exit"], "ret": t["ret"]}
    top5_share = float(np.sum(sorted(rets, reverse=True)[:5]) / np.sum(rets[rets > 0])) if len(wins) else None
    return {"count": len(rets), "winRate": float(np.mean(rets > 0)), "avgWin": float(wins.mean()) if len(wins) else None,
            "avgLoss": float(losses.mean()) if len(losses) else None,
            "payoff": float(wins.mean() / abs(losses.mean())) if len(wins) and len(losses) else None,
            "medianHoldDays": float(np.median([t["days"] for t in trades])),
            "top5ShareOfGains": top5_share, "best": [fmt(t) for t in best], "worst": [fmt(t) for t in worst]}


def industry_exposure(feat, run):
    industry = {row["Symbol"]: row["Industry"] for row in csv.DictReader((ROOT / "nifty750_backtest_list.csv").open(encoding="utf-8"))}
    d = feat.data
    max_share, counts, samples = [], {}, 0
    for t, hold, cash in run["exposure"][::21]:
        total = cash + sum(hold.values())
        if not hold:
            continue
        by = {}
        for j, v in hold.items():
            name = industry.get(d.symbols[j], "Other")
            by[name] = by.get(name, 0) + v / total
        max_share.append(max(by.values()))
        for name, w in by.items():
            counts[name] = counts.get(name, 0) + w
        samples += 1
    avg = sorted(((k, v / samples) for k, v in counts.items()), key=lambda kv: -kv[1])[:8]
    return {"avgMaxIndustryWeight": float(np.mean(max_share)), "peakIndustryWeight": float(np.max(max_share)),
            "avgWeights": [{"industry": k, "weight": v} for k, v in avg]}


def _curve(dates, series):
    keep = [i for i, d in enumerate(dates) if i == len(dates) - 1 or date.fromisoformat(d).weekday() == 4]
    return [{"date": dates[i], **{k: round(float(v[i] / v[0]), 4) for k, v in series.items()}} for i in keep]


def _json_default(value):
    if isinstance(value, (np.floating, np.integer)):
        return value.item()
    if isinstance(value, np.bool_):
        return bool(value)
    raise TypeError(type(value))


def print_summary(out):
    pct = lambda v: "-" if v is None else f"{v * 100:6.1f}%"
    b = out["baseCase"]
    print(f"BASE {b['from']}..{b['to']}: CAGR {pct(b['cagr'])} maxDD {pct(b['maxDD'])} sharpe {b['sharpe']:.2f} "
          f"win {pct(b['winRate'])} turnover/yr {b['turnoverPerYear']:.1f}x")
    for x in out["benchmarks"]:
        print(f"  bench {x['label']}: CAGR {pct(x['cagr'])} maxDD {pct(x['maxDD'])}")
    print("SURVIVORSHIP:")
    for s in out["survivorship"]["runs"]:
        print(f"  {s['label']}: CAGR {pct(s['cagr'])} maxDD {pct(s['maxDD'])} | EW {pct(s['equalWeight']['cagr'])} excess {pct(s['excessOverEW'])}")
    print(f"  bias (CAGR) {pct(out['survivorship']['biasCagr'])}; coverage {[(c['date'], c['withPrices'], c['members']) for c in out['survivorship']['coverage']]}")
    for g in out["sensitivity"]:
        print(g["group"])
        for r in g["rows"]:
            print(f"   {r['label']:42} CAGR {pct(r['cagr'])} maxDD {pct(r['maxDD'])} sharpe {r['sharpe']:.2f} turnover {r['turnoverPerYear']:.1f}x")
    print("TIMING:", [(r["label"], pct(r["cagr"])) for r in out["timing"]])
    l = out["luck"]
    print(f"LUCK: random median {pct(l['percentiles']['50'])}, 5-95% {pct(l['percentiles']['5'])}..{pct(l['percentiles']['95'])}; base beats {l['shareBeaten']:.0%}")
    print("COSTS:", [(r["label"], pct(r["cagr"])) for r in out["costs"]["rows"]], "after tax", pct(out["costs"]["afterTax"]["cagr"]))
    print("CAPACITY:", [(f"{c['capital']:.0e}", pct(c["medianShareOfAdv"]), pct(c["over10pct"])) for c in out["capacity"]])
    rk = out["risk"]
    print("DRAWDOWNS:", [(d["peak"], d["trough"], d["recovered"], pct(d["depth"])) for d in rk["drawdowns"]])
    print("MONTHLY:", {k: v for k, v in rk["monthly"].items() if k not in ("histogram", "binEdges", "table")})
    print("TRADES:", {k: v for k, v in rk["trades"].items() if k not in ("best", "worst")})
    print("INDUSTRY:", rk["industry"])


if __name__ == "__main__":
    main()
