"""Momentum Scan, following the rules of the owner's Google Sheet ("Ranked Data"):

Universe: the fixed Nifty Total Market (750) list in nifty750_backtest_list.csv. A stock is ranked only if it passes three filters:
fall from all-time high < 25%, average daily turnover (close x volume, 252 sessions) > Rs 1 Cr,
and close above its 233-day SMA. Score ("Av Sharp") = average over 252/184/126/63 sessions of
(% return over the window) / (annualised volatility of daily returns). The scan lists ranks 1-99.

Model portfolio: hold the top 10; a holding is swapped only when it falls out of the top 30
(including failing a filter). Rebalanced on the last trading day of each month; everything moves
to a liquid fund when Nifty 500 closes below its 200-day SMA on that day.

The site serves a saved snapshot (momentum_state.json) and never fetches data itself. To
regenerate it, run `py momentum.py`: it downloads prices from Yahoo, then replays the strategy
from the start of the price history, so the scan, holdings, swap log and backtest all come from
the same deterministic rules. Standard library only, so the packaged EXE stays small.
"""
import csv
import json
import math
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from array import array
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone

# The tested stocks are fixed: the Nifty Total Market list as published by NSE Indices on
# 24 Sep 2026 (5 "DUMMY" placeholder rows removed). Never re-downloaded, so reruns test the same list.
UNIVERSE_FILE = "nifty750_backtest_list.csv"
INDEX_SYMBOL = "^CRSLDX"  # Nifty 500 on Yahoo
HISTORY_RANGE = "7y"
STORE_VERSION = 2  # bump when the cached price format changes

# Ranking rules (from the sheet)
LOOKBACKS = (252, 184, 126, 63)  # sessions
SMA_DAYS = 233
TURNOVER_DAYS = 252
MAX_FALL_FROM_ATH = 0.25
MIN_TURNOVER = 1e7  # Rs 1 crore
SCAN_SIZE = 99  # ranks 1-99 are listed

# Portfolio rules
TOP_N = 10
EXIT_RANK = 30
MA_DAYS = 200
COST_PER_SIDE = 0.0025
LIQUID_ANNUAL = 0.065

# Data hygiene
MAX_DAILY_MOVE = 0.60  # bigger one-day moves are treated as bad data
MAX_FFILL_DAYS = 5
MIN_COVERAGE = 0.9  # share of a window that must have data

FETCH_WORKERS = 4

IST = timezone(timedelta(hours=5, minutes=30))
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126 Safari/537.36"}
FETCH_ERRORS = (urllib.error.URLError, TimeoutError, OSError, KeyError, IndexError, TypeError, ValueError)
NAN = float("nan")

STATUS = {"running": False, "lastError": None}
_run_lock = threading.Lock()


# ---------- data ----------

def _get(url, timeout=20):
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=timeout) as response:
        return response.read()


def load_universe(root):
    """[{"symbol", "industry"}] from the fixed list in UNIVERSE_FILE (never downloaded)."""
    with open(root / UNIVERSE_FILE, encoding="utf-8", newline="") as handle:
        stocks = [{"symbol": row["Symbol"].strip(), "industry": row["Industry"].strip() or None}
                  for row in csv.DictReader(handle) if row.get("Symbol", "").strip()]
    if not stocks:
        raise ValueError(f"{UNIVERSE_FILE} is empty.")
    return stocks


def _chart(yahoo_symbol, range_, interval):
    url = (f"https://query1.finance.yahoo.com/v8/finance/chart/{urllib.parse.quote(yahoo_symbol)}"
           f"?range={range_}&interval={interval}")
    result = json.loads(_get(url))["chart"]["result"][0]
    quote = result["indicators"]["quote"][0]
    return result["timestamp"], quote


def fetch_daily(yahoo_symbol, range_):
    """{YYYY-MM-DD: [close, high, volume]}; split-adjusted, not dividend-adjusted (like GOOGLEFINANCE)."""
    stamps, quote = _chart(yahoo_symbol, range_, "1d")
    highs = quote.get("high") or [None] * len(stamps)
    volumes = quote.get("volume") or [None] * len(stamps)
    return {
        datetime.fromtimestamp(ts, tz=IST).strftime("%Y-%m-%d"): [round(c, 2), round(h, 2) if h else round(c, 2), int(v or 0)]
        for ts, c, h, v in zip(stamps, quote["close"], highs, volumes)
        if c
    }


def fetch_high_before(yahoo_symbol, before_day):
    """Highest weekly high in the stock's full history before `before_day` (for the all-time high)."""
    stamps, quote = _chart(yahoo_symbol, "max", "1wk")
    highs = [h for ts, h in zip(stamps, quote.get("high") or [])
             if h and datetime.fromtimestamp(ts, tz=IST).strftime("%Y-%m-%d") < before_day]
    return max(highs) if highs else None


def _full_history(yahoo_symbol):
    bars = fetch_daily(yahoo_symbol, HISTORY_RANGE)
    return {"bars": bars, "highBefore": fetch_high_before(yahoo_symbol, min(bars))}


def _refresh_symbol(symbol, cached):
    """Recent month merged into the cache; full history when new, stale, or re-adjusted (split)."""
    yahoo_symbol = f"{symbol}.NS"
    for attempt in range(3):
        try:
            bars = cached and cached.get("bars")
            if bars and max(bars) >= (date.today() - timedelta(days=20)).isoformat():
                recent = fetch_daily(yahoo_symbol, "1mo")
                overlap = [d for d in recent if d in bars]
                # A split re-adjusts Yahoo's whole history; if the overlap moved, refetch it all.
                if overlap and all(abs(recent[d][0] / bars[d][0] - 1) < 0.01 for d in overlap):
                    return symbol, {"bars": {**bars, **recent}, "highBefore": cached.get("highBefore")}
            return symbol, _full_history(yahoo_symbol)
        except FETCH_ERRORS:
            time.sleep(1 + attempt)
    return symbol, cached  # keep what we had (may be None for a brand-new symbol)


def refresh_prices(store, symbols):
    """Updates store in place; returns the number of symbols that couldn't be fetched."""
    if store.get("version") != STORE_VERSION:
        store.clear()
        store["version"] = STORE_VERSION
    index_bars = fetch_daily(INDEX_SYMBOL, HISTORY_RANGE)
    store["index"] = {d: bar[0] for d, bar in index_bars.items()}
    stocks = store.setdefault("stocks", {})
    with ThreadPoolExecutor(max_workers=FETCH_WORKERS) as pool:
        results = list(pool.map(lambda s: _refresh_symbol(s, stocks.get(s)), symbols))
    failures = 0
    for symbol, data in results:
        if data and data.get("bars"):
            stocks[symbol] = data
        else:
            failures += 1
    first_day = min(store["index"])
    wanted = set(symbols)
    for symbol in list(stocks):
        if symbol not in wanted:
            del stocks[symbol]  # dropped from the index
            continue
        data = stocks[symbol]
        old = [bar[1] for d, bar in data["bars"].items() if d < first_day]
        if old:  # roll trimmed highs into highBefore so the all-time high is never lost
            data["highBefore"] = max([h for h in old + [data.get("highBefore")] if h])
            data["bars"] = {d: bar for d, bar in data["bars"].items() if d >= first_day}
    return failures


# ---------- ranking ----------

def _window_mean(prefix_count, prefix_sum, t, n):
    if t - n + 1 < 0:
        return None
    k = prefix_count[t + 1] - prefix_count[t - n + 1]
    if k < n * MIN_COVERAGE:
        return None
    return (prefix_sum[t + 1] - prefix_sum[t - n + 1]) / k


class Scanner:
    """Computes each stock's filters and score at the given calendar indices.

    One pass per stock over its history with prefix sums, keeping only the aligned closes (needed
    to mark the portfolio to market) and the per-date results, so memory stays small.
    """

    def __init__(self, calendar, stocks, eval_indices):
        self.calendar = calendar
        self.closes = {}
        self.rows = {t: [] for t in eval_indices}  # t -> [(symbol, features)]
        wanted = set(eval_indices)
        for symbol, data in stocks.items():
            self._scan_stock(symbol, data, wanted)

    def _scan_stock(self, symbol, data, wanted):
        bars, n_days = data["bars"], len(self.calendar)
        closes = array("d", [NAN]) * n_days
        # prefix sums: closes (SMA), close*volume (turnover), daily returns (volatility)
        c_cnt, c_sum = array("d", [0.0]) * (n_days + 1), array("d", [0.0]) * (n_days + 1)
        tv_cnt, tv_sum = array("d", [0.0]) * (n_days + 1), array("d", [0.0]) * (n_days + 1)
        r_cnt, r_sum, r_sq = array("d", [0.0]) * (n_days + 1), array("d", [0.0]) * (n_days + 1), array("d", [0.0]) * (n_days + 1)
        ath = data.get("highBefore") or 0.0
        last, gap = None, 0
        for i, day in enumerate(self.calendar):
            bar = bars.get(day)
            if bar:
                last, gap = bar[0], 0
                ath = max(ath, bar[1], bar[0])
            elif last is not None and gap < MAX_FFILL_DAYS:
                gap += 1
            else:
                last = None
            if last is not None:
                closes[i] = last
            prev = closes[i - 1] if i else NAN
            r = last / prev - 1 if last is not None and prev == prev else None
            if r is not None and abs(r) > MAX_DAILY_MOVE:
                r = None
            c_cnt[i + 1] = c_cnt[i] + (last is not None)
            c_sum[i + 1] = c_sum[i] + (last or 0.0)
            tv_cnt[i + 1] = tv_cnt[i] + (bar is not None)
            tv_sum[i + 1] = tv_sum[i] + (bar[0] * bar[2] if bar else 0.0)
            r_cnt[i + 1] = r_cnt[i] + (r is not None)
            r_sum[i + 1] = r_sum[i] + (r or 0.0)
            r_sq[i + 1] = r_sq[i] + (r * r if r is not None else 0.0)

            if i in wanted and last is not None:
                self.rows[i].append((symbol, self._features(i, last, ath, closes, c_cnt, c_sum, tv_cnt, tv_sum, r_cnt, r_sum, r_sq)))
        self.closes[symbol] = closes

    @staticmethod
    def _features(t, cmp, ath, closes, c_cnt, c_sum, tv_cnt, tv_sum, r_cnt, r_sum, r_sq):
        sma = _window_mean(c_cnt, c_sum, t, SMA_DAYS)
        turnover = _window_mean(tv_cnt, tv_sum, t, TURNOVER_DAYS)
        fall = (ath - cmp) / ath if ath else None
        sharpes = []
        for n in LOOKBACKS:
            past = closes[t - n] if t - n >= 0 else NAN
            k = r_cnt[t + 1] - r_cnt[t - n + 1] if t - n + 1 >= 0 else 0
            if past != past or k < max(2, n * MIN_COVERAGE):
                sharpes.append(None)
                continue
            s, s2 = r_sum[t + 1] - r_sum[t - n + 1], r_sq[t + 1] - r_sq[t - n + 1]
            variance = (s2 - s * s / k) / (k - 1)
            vol = math.sqrt(variance * 252) if variance > 0 else 0.0
            # Sheet rule: plain % return over the window / annualised volatility (both x100, cancels).
            sharpes.append((cmp / past - 1) / vol if vol else None)
        return {
            "cmp": cmp, "sma": sma, "turnover": turnover, "ath": ath, "fall": fall, "sharpes": sharpes,
            "score": sum(sharpes) / len(sharpes) if all(v is not None for v in sharpes) else None,
            "passes": {
                "ath": fall is not None and fall < MAX_FALL_FROM_ATH,
                "turnover": turnover is not None and turnover > MIN_TURNOVER,
                "trend": sma is not None and cmp > sma,
            },
        }

    def ranking(self, t):
        """[(symbol, features)] passing all filters, best score first."""
        ranked = [(s, f) for s, f in self.rows[t] if f["score"] is not None and all(f["passes"].values())]
        ranked.sort(key=lambda row: row[1]["score"], reverse=True)
        return ranked


# ---------- portfolio ----------

def month_end_indices(calendar):
    """Last trading day of each completed month (the current month isn't over yet)."""
    return [i for i in range(len(calendar) - 1) if calendar[i][:7] != calendar[i + 1][:7]]


def moving_average(values, n):
    out, running = [None] * len(values), 0.0
    for i, v in enumerate(values):
        running += v
        if i >= n:
            running -= values[i - n]
        if i >= n - 1:
            out[i] = running / n
    return out


def simulate(calendar, index_closes, sma, scanner, rebalances):
    liquid_daily = (1 + LIQUID_ANNUAL) ** (1 / 252) - 1
    rebalance_set = set(rebalances)
    # `cash` is money parked in the liquid fund: everything while the market filter is off, plus
    # any sale proceeds left over when fewer than 10 stocks pass the filters.
    cash, holdings, entries = 1.0, {}, {}
    events, trades, equity = [], [], []
    for t in range(rebalances[0], len(calendar)):
        if t > rebalances[0]:
            for symbol in holdings:
                prev, cur = scanner.closes[symbol][t - 1], scanner.closes[symbol][t]
                r = cur / prev - 1 if prev == prev and cur == cur else 0.0
                holdings[symbol] *= 1 + (r if abs(r) <= MAX_DAILY_MOVE else 0.0)
            cash *= 1 + liquid_daily

        if t in rebalance_set:
            day = calendar[t]
            if index_closes[t] < sma[t]:
                if holdings:
                    for symbol, amount in holdings.items():
                        trades.append(_trade(symbol, entries[symbol], day, amount))
                        cash += amount * (1 - COST_PER_SIDE)
                    events.append({"date": day, "type": "EXIT", "sold": sorted(holdings), "bought": []})
                    holdings, entries = {}, {}
            else:
                ranks = scanner.ranking(t)
                top = {symbol for symbol, _ in ranks[:EXIT_RANK]}
                kind = "SWAP" if holdings else "ENTER"
                sold = sorted(s for s in holdings if s not in top)
                for symbol in sold:
                    amount = holdings.pop(symbol)
                    trades.append(_trade(symbol, entries.pop(symbol), day, amount))
                    cash += amount * (1 - COST_PER_SIDE)
                buys = [s for s, _ in ranks if s not in holdings][:TOP_N - len(holdings)]
                if buys:
                    share = cash * (1 - COST_PER_SIDE) / len(buys)
                    for symbol in buys:
                        holdings[symbol] = share
                        entries[symbol] = {"date": day, "price": scanner.closes[symbol][t], "amount": share}
                    cash = 0.0
                if sold or buys:
                    events.append({"date": day, "type": kind, "sold": sold, "bought": buys})
        equity.append(sum(holdings.values()) + cash)
    return {"equity": equity, "holdings": holdings, "entries": entries, "events": events, "trades": trades,
            "cash": cash / equity[-1] if equity[-1] else 0.0}


def _trade(symbol, entry, exit_day, amount):
    return {"symbol": symbol, "entry": entry["date"], "exit": exit_day, "return": amount / entry["amount"] - 1}


def _stats(dates, curve):
    years = (date.fromisoformat(dates[-1]) - date.fromisoformat(dates[0])).days / 365.25
    daily = [curve[i] / curve[i - 1] - 1 for i in range(1, len(curve))]
    mean = sum(daily) / len(daily)
    vol = math.sqrt(sum((r - mean) ** 2 for r in daily) / (len(daily) - 1)) * math.sqrt(252)
    peak, drawdown = curve[0], 0.0
    for v in curve:
        peak = max(peak, v)
        drawdown = min(drawdown, v / peak - 1)
    return {
        "cagr": (curve[-1] / curve[0]) ** (1 / years) - 1 if years > 0 else None,
        "vol": vol,
        "maxDrawdown": drawdown,
        "sharpe": (mean * 252 - LIQUID_ANNUAL) / vol if vol else None,
        "multiple": curve[-1] / curve[0],
        "years": years,
    }


def _clean(value, digits):
    return round(value, digits) if isinstance(value, float) and value == value else None


def build_state(store, universe):
    calendar = sorted(store["index"])
    index_closes = [store["index"][d] for d in calendar]
    sma = moving_average(index_closes, MA_DAYS)
    industry = {u["symbol"]: u.get("industry") for u in universe}
    stocks = {s: store["stocks"][s] for s in industry if store["stocks"].get(s)}

    last = len(calendar) - 1
    start_t = max(max(LOOKBACKS), SMA_DAYS, TURNOVER_DAYS, MA_DAYS) + 5
    rebalances = [t for t in month_end_indices(calendar) if t >= start_t]
    if not rebalances:
        raise ValueError("Not enough price history to run the strategy.")
    scanner = Scanner(calendar, stocks, rebalances + [last])
    sim = simulate(calendar, index_closes, sma, scanner, rebalances)

    start = rebalances[0]
    dates = calendar[start:]
    bench = [c / index_closes[start] for c in index_closes[start:]]

    today_rows = scanner.rows[last]
    ranks = scanner.ranking(last)
    rank_of = {symbol: i + 1 for i, (symbol, _) in enumerate(ranks)}
    features_of = dict(today_rows)
    held = sim["holdings"]
    scan = [{
        "rank": i + 1,
        "symbol": symbol,
        "industry": industry.get(symbol),
        "cmp": _clean(f["cmp"], 2),
        "score": _clean(f["score"], 3),
        "sharpe": [_clean(v, 2) for v in f["sharpes"]],
        "fall": _clean(f["fall"], 4),
        "held": symbol in held,
    } for i, (symbol, f) in enumerate(ranks[:SCAN_SIZE])]

    holdings = []
    for symbol, entry in sorted(sim["entries"].items(), key=lambda kv: rank_of.get(kv[0], 10 ** 6)):
        f = features_of.get(symbol, {})
        close = scanner.closes[symbol][last]
        close = close if close == close else None
        failed = [name for name, ok in (f.get("passes") or {}).items() if not ok]
        holdings.append({
            "symbol": symbol,
            "industry": industry.get(symbol),
            "entryDate": entry["date"],
            "entryPrice": _clean(entry["price"], 2),
            "close": _clean(close, 2),
            "return": close / entry["price"] - 1 if close and entry["price"] else None,
            "rank": rank_of.get(symbol),
            "failedFilters": failed,
        })

    # Weekly points are plenty for the chart and keep the payload small.
    curve = [{"date": d, "strategy": round(v, 4), "nifty500": round(b, 4)}
             for i, (d, v, b) in enumerate(zip(dates, sim["equity"], bench))
             if i == len(dates) - 1 or date.fromisoformat(d).weekday() == 4]
    yearly, prev_s, prev_b = [], 1.0, 1.0
    for i, d in enumerate(dates):
        if i == len(dates) - 1 or dates[i + 1][:4] != d[:4]:
            yearly.append({"year": d[:4], "strategy": sim["equity"][i] / prev_s - 1, "nifty500": bench[i] / prev_b - 1,
                           "partial": (i == len(dates) - 1) or d[:4] == dates[0][:4]})
            prev_s, prev_b = sim["equity"][i], bench[i]
    trades = sim["trades"]
    wins = sum(1 for tr in trades if tr["return"] > 0)
    scored = [f for _, f in today_rows if f["score"] is not None]

    return {
        "asOf": calendar[last],
        "computedAt": datetime.now(IST).isoformat(timespec="seconds"),
        "rules": {"lookbacks": list(LOOKBACKS), "smaDays": SMA_DAYS, "turnoverDays": TURNOVER_DAYS,
                  "maxFallFromAth": MAX_FALL_FROM_ATH, "minTurnover": MIN_TURNOVER, "scanSize": SCAN_SIZE,
                  "topN": TOP_N, "exitRank": EXIT_RANK, "maDays": MA_DAYS,
                  "costPerSide": COST_PER_SIDE, "liquidAnnual": LIQUID_ANNUAL},
        "funnel": {
            "universe": len(universe),
            "withData": len(today_rows),
            "scored": len(scored),
            "nearAth": sum(1 for f in scored if f["passes"]["ath"]),
            "liquid": sum(1 for f in scored if f["passes"]["turnover"]),
            "aboveSma": sum(1 for f in scored if f["passes"]["trend"]),
            "passedAll": len(ranks),
        },
        "market": {"close": index_closes[last], "sma": sma[last], "belowMA": index_closes[last] < sma[last]},
        "portfolio": {"mode": "INVESTED" if held else "LIQUID", "holdings": holdings, "cashShare": sim["cash"],
                      "lastRebalance": calendar[rebalances[-1]],
                      "liquidSince": next((e["date"] for e in reversed(sim["events"]) if e["type"] == "EXIT"), None) if not held else None},
        "scan": scan,
        "events": list(reversed(sim["events"]))[:24],
        "backtest": {
            "from": dates[0], "to": dates[-1],
            "strategy": _stats(dates, sim["equity"]),
            "nifty500": _stats(dates, bench),
            "yearly": yearly,
            "curve": curve,
            "rebalances": len(rebalances),
            "monthsInLiquid": sum(1 for t in rebalances if index_closes[t] < sma[t]),
            "trades": len(trades),
            "winRate": wins / len(trades) if trades else None,
        },
    }


# ---------- persistence + scheduling ----------

def _load_json(path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def _save_json(path, data):
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, separators=(",", ":")), encoding="utf-8")
    tmp.replace(path)


def run_once(root):
    """Refreshes prices for the fixed stock list and rewrites the state file. Returns the new state."""
    if not _run_lock.acquire(blocking=False):
        return None
    STATUS["running"] = True
    try:
        universe = load_universe(root)
        prices_path = root / "momentum_prices.json"
        store = _load_json(prices_path, {})
        failures = refresh_prices(store, [u["symbol"] for u in universe])
        _save_json(prices_path, store)
        state = build_state(store, universe)
        state["funnel"]["fetchFailures"] = failures
        _save_json(root / "momentum_state.json", state)
        STATUS["lastError"] = None
        return state
    except Exception as error:  # keep the scheduler alive; the page keeps showing the last state
        STATUS["lastError"] = f"{type(error).__name__}: {error}"
        return None
    finally:
        STATUS["running"] = False
        _run_lock.release()


def load_state(root):
    state = _load_json(root / "momentum_state.json", None)
    if state is None or "scan" not in state:  # none yet, or from the pre-sheet-rules version
        return {"status": "unavailable"}
    return state


if __name__ == "__main__":
    # The site only serves the saved snapshot; regenerate it by hand with `py momentum.py`.
    import sys
    from pathlib import Path

    root = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parent
    print(f"Refreshing the momentum snapshot in {root} (downloads ~750 price histories)…")
    result = run_once(root)
    if result is None:
        sys.exit(f"Failed: {STATUS['lastError']}")
    print(f"Done: prices as of {result['asOf']}, {result['funnel']['passedAll']} stocks pass the filters.")
