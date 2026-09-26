"""Builds the all-NSE price cache for study/momentum_nse_study.py from the raw NSE daily file.

Input:
  study/NSE_all_stocks_daily_2015_onwards.parquet   raw NSE bhavcopy rows (EQ, BE, BZ), not adjusted
Steps:
  1. Renames: NSE lists a renamed stock under its new symbol from the next day (ZOMATO -> ETERNAL).
     A symbol that stops trading is joined to one that starts within 3 trading days at an opening price
     within 3% of its last close, plus the known pairs in study/renames.py. Mergers and demergers
     (price changes on the switch) are not joined: the stock just stops, as it did for its holders.
  2. Splits and bonus issues from NSE's corporate-actions list (cached in study/nse_corporate_actions.json):
     'Bonus 1:2' = 1.5, a face-value split from Rs 10 to Rs 2 = 5, both on one day multiply. Prices
     before the ex-date are divided by the ratio (traded value is unchanged). A gap of 23% or more at a
     whole ratio (1.33, 1.5, 2, 3, 5, 10 ...) from a close of Rs 5 or more, with volume rising to match, and no
     NSE record near it, is adjusted too (from prices alone; listed as such in study/nse_events.json).
     An NSE record with no matching gap uses the ex-date's own gap if it is 30% or more, else is skipped.
  3. Drops ETFs: NSE's current ETF list (study/nse_etf_list.csv), older ETF symbols by hand (OLD_ETFS),
     and anything that tracks the Nifty 500 (correlation over 0.95) or barely moves (under 10% a year).
  4. Keeps stocks whose 1-year average traded value ever passed Rs 80 lakh (the study floor is Rs 1 crore).
  5. Nifty 500 index (^CRSLDX) from Yahoo, cached in study/nse_index.json.
Output:
  study/nse_prices.npz   calendar, symbols, adjusted close/high/low, traded value, EQ-series flag, index
  study/nse_events.json  every join and adjustment made, for checking
Run: py study/nse_data.py        (needs pandas, pyarrow, numpy, curl; yfinance for the index on the first run)
"""
import json
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
PARQUET = HERE / "NSE_all_stocks_daily_2015_onwards.parquet"
ACTIONS = HERE / "nse_corporate_actions.json"
INDEX_FILE = HERE / "nse_index.json"
OUT = HERE / "nse_prices.npz"
EVENTS = HERE / "nse_events.json"

MIN_TURNOVER_EVER = 8e6
JOIN_DAYS = 3
JOIN_TOL = 0.03
# bonus a:b gives (a+b)/b; splits 2, 2.5, 4, 5, 10 ...; both on one day multiply
BROAD = sorted({round((a + b) / b, 4) for a in range(1, 11) for b in range(1, 11) if (a + b) / b > 1.05}
               | {2.0, 2.5, 4.0, 5.0, 10.0, 20.0, 25.0, 50.0, 100.0, 6.0, 8.0, 15.0, 30.0})
OLD_ETFS = set("""
AXISBNKETF AXISBPSETF AXISCETF AXISGOLD AXISHCETF AXISILVER AXISNIFTY AXISTECETF AXSENSEX BANKETFADD CRMFGETF
DSPBANKETF DSPGOLDETF DSPITETF DSPN50ETF DSPNEWETF DSPPSBKETF DSPPVBKETF DSPQ50ETF DSPSENXETF DSPSILVETF EBBETF0423
EBBETF0425 GOLDETFADD GOLDSHARE HBANKETF HDFCMFGETF HDFCNIFETF HDFCSENETF IBMFNIFTY ICICI10GS ICICI500 ICICI5GSEC
ICICIALPLV ICICIAUTO ICICIBANKN ICICIBANKP ICICICOMMO ICICICONSU ICICIFIN ICICIFMCG ICICIGOLD ICICIINFRA ICICILIQ
ICICILOVOL ICICIM150 ICICIMCAP ICICIMOM30 ICICINF100 ICICINIFTY ICICINV20 ICICINXT50 ICICIPHARM ICICIQTY30 ICICISENSX
ICICISILVE ICICITECH IDBIGOLD IGOLD IIFLNIFTY INIFTY ISENSEX ITETFADD KOTAKALPHA KOTAKBKETF KOTAKCONS KOTAKGOLD
KOTAKIT KOTAKLIQ KOTAKLOVOL KOTAKMID50 KOTAKMNC KOTAKNIFTY KOTAKNV20 KOTAKPSUBK KOTAKSILVE KTKNV20ETF LICNFENGP
LICNMFET LOWVOLIWIN MAESGETF MAFSETF MAGOLDETF MAGS813ETF MAM150ETF MAMFGETF MAN50ETF MANV30F MANXT50 MASILVER MGOLD
MIDCAPIWIN N100 NAVINIFTY NCPSESDL24 NETFAUTO NETFCONSUM NETFDIVOPP NETFGILT5Y NETFIT NETFLTGILT NETFMID150 NETFNIF100
NETFNV20 NETFPHARMA NETFSDL26 NETFSILVER NIF100IWIN NIF10GETF NIF5GETF NIFITETF NIFMID150 NIFTY50ADD NIFTYEES
NIFTYIWIN NV20IWIN PSUBANKICI RELGOLD RELGRNIFTY RELNIFTY RETFMID150 RRSLGETF SBIGETS SDL24BEES SDL26BEES SENSEXIWIN
SETFBANK SETFNIFJR SETFNIFTY SILVERETF SILVERTUC SILVRETF SSDL UTIBANKETF UTINEXT50 UTINIFTETF UTISENSETF UTISXN50
""".split())
STRICT = (4 / 3, 1.5, 5 / 3, 2.0, 2.5, 3.0, 4.0, 5.0, 6.0, 10.0, 20.0)


def nearest(f, choices, tol):
    best = min(choices, key=lambda c: abs(f / c - 1))
    return best if abs(f / best - 1) <= tol else None


def load():
    df = pd.read_parquet(PARQUET)
    df["series"] = df["series"].astype(str)
    df = df.sort_values(["symbol", "date", "series"]).drop_duplicates(["symbol", "date"], keep="first")  # EQ < BE < BZ
    df["date"] = df["date"].dt.strftime("%Y-%m-%d")
    return df.reset_index(drop=True)


def join_renames(df, calendar):
    from renames import RENAMES
    pos = {d: i for i, d in enumerate(calendar)}
    g = df.groupby("symbol", sort=False)
    first = g.head(1).set_index("symbol")
    last = g.tail(1).set_index("symbol")
    starts = {}
    for s, row in first.iterrows():
        starts.setdefault(pos[row["date"]], []).append(s)
    end = len(calendar) - 1
    nxt = {}
    for s, row in last.iterrows():
        i = pos[row["date"]]
        if i >= end:
            continue
        if s in RENAMES and RENAMES[s] in first.index and pos[first.loc[RENAMES[s], "date"]] > i:
            nxt[s] = RENAMES[s]
            continue
        cands = [(abs(first.loc[b, "open"] / row["close"] - 1), b)
                 for k in range(1, JOIN_DAYS + 1) for b in starts.get(i + k, [])]
        cands = [c for c in cands if c[0] <= JOIN_TOL]
        if cands:
            nxt[s] = min(cands)[1]
    taken = {}
    for a, b in sorted(nxt.items()):  # one successor per new symbol
        if b not in taken.values():
            taken[a] = b
    final = {}
    for s in df["symbol"].unique():
        t, seen = s, {s}
        while t in taken and taken[t] not in seen:
            t = taken[t]
            seen.add(t)
        final[s] = t
    df["stock"] = df["symbol"].map(final)
    joins = [{"from": a, "to": b, "on": first.loc[b, "date"]} for a, b in sorted(taken.items())]
    return df.sort_values(["stock", "date"]).reset_index(drop=True), joins


def etf_stocks(df):
    import csv
    etfs = OLD_ETFS | {r["Symbol"].strip() for r in csv.DictReader((HERE / "nse_etf_list.csv").open(encoding="utf-8-sig"))}
    return set(df.loc[df["symbol"].isin(etfs), "stock"].unique())


def index_like(df, index, calendar):
    """Stocks that move with the Nifty 500 almost exactly, or hardly move at all: funds, not companies."""
    idx = pd.Series(index, index=calendar).pct_change()
    out = {}
    for s, g in df.groupby("stock", sort=False):
        r = g.set_index("date")["close"].pct_change().dropna()
        r = r[r.abs() < 0.2]
        if len(r) < 120:
            continue
        vol = r.std() * np.sqrt(252)
        corr = r.corr(idx.reindex(r.index))
        if vol < 0.10 or corr > 0.95:
            out[s] = {"vol": round(float(vol), 3), "corr": round(float(corr), 3)}
    return out


def liquid_stocks(df):
    tv = (df["close"] * df["volume"]).groupby(df["stock"]).transform(lambda x: x.rolling(252, min_periods=200).mean())
    return set(df.loc[tv > MIN_TURNOVER_EVER, "stock"].unique())


def nse_actions():
    """Splits and bonus issues from NSE's corporate-actions list, one request per year, cached."""
    import re
    import subprocess
    from datetime import datetime
    cache = json.loads(ACTIONS.read_text(encoding="utf-8")) if ACTIONS.exists() else {}
    this_year = datetime.now().year
    todo = [y for y in range(2015, this_year + 1) if str(y) not in cache or y == this_year]
    if todo:
        ua = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
        jar = str(HERE / ".nse_cookies.txt")
        subprocess.run(["curl", "-s", "-c", jar, "-A", ua, "https://www.nseindia.com/", "-o", "nul"], check=False)
        for y in todo:
            url = (f"https://www.nseindia.com/api/corporates-corporateActions?index=equities"
                   f"&from_date=01-01-{y}&to_date=31-12-{y}")
            raw = subprocess.run(["curl", "-s", "-b", jar, "-A", ua, "-H",
                                  "Referer: https://www.nseindia.com/companies-listing/corporate-filings-actions", url],
                                 capture_output=True, text=True, encoding="utf-8").stdout
            rows = json.loads(raw)
            cache[str(y)] = [{"symbol": r["symbol"], "exDate": r["exDate"], "subject": r["subject"].strip()}
                             for r in rows if re.search(r"bonus|split|sub-division|subdivision", r["subject"], re.I)]
            print(f"  NSE {y}: {len(cache[str(y)])} splits/bonuses")
        ACTIONS.write_text(json.dumps(cache, indent=0), encoding="utf-8")
        Path(jar).unlink(missing_ok=True)
    out = []
    for rows in cache.values():
        for r in rows:
            ratio = action_ratio(r["subject"])
            if ratio:
                day = datetime.strptime(r["exDate"], "%d-%b-%Y").strftime("%Y-%m-%d")
                out.append((r["symbol"], day, ratio, r["subject"]))
    return out


def action_ratio(subject):
    """'Bonus 1:2' -> 1.5; 'Face Value Split (Sub-Division) - From Rs 10/- Per Share To Re 1/- Per Share' -> 10.
    A subject with both multiplies them."""
    import re
    ratio = 1.0
    for a, b in re.findall(r"bonus\s*(\d+)\s*:\s*(\d+)", subject, re.I):
        ratio *= (int(a) + int(b)) / int(b)
    m = re.search(r"from\s*r[se]\.?\s*([\d.]+).*?to\s*r[se]\.?\s*([\d.]+)", subject, re.I)
    if m and float(m.group(2)) > 0:
        ratio *= float(m.group(1)) / float(m.group(2))
    return ratio if ratio > 1.001 else None


def adjust(df, actions, stock_of):
    """Divides prices before each split/bonus by its ratio. NSE's list gives the day and ratio; where the
    prices show the gap a day or two off the ex-date, that day is used. A large unexplained gap at a whole
    ratio with the matching rise in volume (a stock missing from NSE's list) is adjusted too."""
    by_stock = {}
    for sym, day, ratio, subject in actions:
        st = stock_of.get(sym)
        if st:
            by_stock.setdefault(st, {}).setdefault(day, [1.0, subject])[0] *= ratio  # same day: multiply
    events = []
    parts = []
    for s, g in df.groupby("stock", sort=False):
        g = g.copy()
        close, opn, vol = g["close"].to_numpy(), g["open"].to_numpy(), g["volume"].to_numpy(float)
        dates = g["date"].to_numpy()
        with np.errstate(invalid="ignore", divide="ignore"):
            gaps = np.concatenate([[1.0], close[:-1] / opn[1:]])
        factor = np.ones(len(g))
        used = set()
        for day, (ratio, subject) in sorted(by_stock.get(s, {}).items()):
            i = int(np.searchsorted(dates, day))
            if i >= len(g) or i == 0:
                continue  # before the data starts or after it ends
            near = [k for k in range(max(1, i - 2), min(len(g), i + 3)) if abs(gaps[k] / ratio - 1) < 0.15]
            if near:
                k, how = min(near, key=lambda k: abs(k - i)), "nse"
            elif gaps[i] >= 1.3:  # ratio off (DANGEE: listed 15, prices show 12.5): trust the prices
                k, how, ratio = i, "nse date, price ratio", float(gaps[i])
            else:
                events.append({"stock": s, "date": dates[i], "ratio": round(ratio, 4), "gap": round(float(gaps[i]), 3),
                               "how": "skipped: no gap in prices", "subject": subject})
                continue
            factor[:k] *= ratio
            used.add(k)
            events.append({"stock": s, "date": dates[k], "ratio": round(ratio, 4), "gap": round(float(gaps[k]), 3),
                           "how": how, "subject": subject})
        for i in np.flatnonzero(gaps >= 1.3):
            if any(abs(i - k) <= 3 for k in used) or close[i - 1] < 5:
                continue  # under Rs 5 one tick (0.05) is a big move: 0.10 -> 0.05 looks like a 1:1 bonus
            snap = nearest(gaps[i], STRICT, 0.04)
            if snap:
                before = np.median(vol[max(0, i - 10):i])
                after = np.median(vol[i:i + 10])
                if before > 0 and after / before >= 0.4 * snap:
                    factor[:i] *= snap
                    events.append({"stock": s, "date": dates[i], "ratio": round(snap, 4), "gap": round(float(gaps[i]), 3),
                                   "how": "prices"})
        g["close"] /= factor
        g["high"] /= factor
        g["low"] /= factor
        parts.append(g)
    return pd.concat(parts, ignore_index=True), events


def nifty500(calendar):
    if INDEX_FILE.exists():
        idx = json.loads(INDEX_FILE.read_text(encoding="utf-8"))
    else:
        import yfinance as yf
        d = yf.download("^CRSLDX", start="2014-01-01", progress=False, auto_adjust=False)["Close"].squeeze().dropna()
        idx = {k.strftime("%Y-%m-%d"): float(v) for k, v in d.items()}
        INDEX_FILE.write_text(json.dumps(idx), encoding="utf-8")
    keys = sorted(idx)
    out, j, last = np.full(len(calendar), np.nan), 0, np.nan
    for i, day in enumerate(calendar):
        while j < len(keys) and keys[j] <= day:
            last = idx[keys[j]]
            j += 1
        out[i] = last
    return out


def main():
    import sys
    sys.path.insert(0, str(HERE))
    df = load()
    calendar = sorted(df["date"].unique())
    print(f"{len(df)} rows, {df['symbol'].nunique()} symbols, {calendar[0]} to {calendar[-1]}")
    df, joins = join_renames(df, calendar)
    print(f"{len(joins)} renames joined")
    index = nifty500(calendar)
    etfs = etf_stocks(df)
    df = df[~df["stock"].isin(etfs)].reset_index(drop=True)
    keep = liquid_stocks(df)
    df = df[df["stock"].isin(keep)].reset_index(drop=True)
    funds = index_like(df, index, calendar)
    keep -= set(funds)
    df = df[df["stock"].isin(keep)].reset_index(drop=True)
    print(f"dropped {len(etfs)} ETFs by name and {len(funds)} by behaviour: {funds}")
    print(f"{len(keep)} stocks ever above Rs {MIN_TURNOVER_EVER / 1e7:.1f} Cr a day")
    actions = nse_actions()
    stock_of = dict(zip(df["symbol"], df["stock"]))
    df["value"] = df["close"] * df["volume"]  # traded value, the same before and after adjusting
    df, events = adjust(df, actions, stock_of)
    events_done = [e for e in events if not e["how"].startswith("skipped")]
    hows = pd.Series([e["how"] for e in events]).value_counts().to_dict()
    print(f"{len(events_done)} splits/bonuses adjusted: {hows}")

    stocks = sorted(keep)
    col = {s: j for j, s in enumerate(stocks)}
    pos = {d: i for i, d in enumerate(calendar)}
    T, N = len(calendar), len(stocks)
    ti = df["date"].map(pos).to_numpy()
    tj = df["stock"].map(col).to_numpy()
    arrays = {}
    for name in ("close", "high", "low", "value"):
        a = np.full((T, N), np.nan, dtype=np.float64)
        a[ti, tj] = df[name].to_numpy()
        arrays[name] = a
    eq = np.zeros((T, N), dtype=bool)
    eq[ti, tj] = (df["series"] == "EQ").to_numpy()
    np.savez_compressed(OUT, calendar=np.array(calendar), symbols=np.array(stocks), eq=eq,
                        index=index, **arrays)
    EVENTS.write_text(json.dumps({"joins": joins, "adjustments": events, "etfs": sorted(etfs), "indexLike": funds}, indent=1), encoding="utf-8")
    print("wrote", OUT, "and", EVENTS)


if __name__ == "__main__":
    main()
