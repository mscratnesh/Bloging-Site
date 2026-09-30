"""NIFTY Supertrend butterfly study on the F&O bhavcopy (study/fetch_fno_bhavcopy.py downloads it).

Signal: Supertrend(10, 3) on NIFTY daily and weekly bars. The week in progress counts as a bar so far, as the
chart shows it at that day's close.
Rule: enter when daily and weekly are the same colour, on that side; exit when the weekly changes colour, and
  enter again when the two next agree. A position still on at its expiry settles there; a new one opens at that
  close only if daily and weekly still agree on the same side, else it waits flat for the next entry signal.
Size: SETS sets a position, compared three ways
  A  all sets run to the weekly flip or expiry
  B  one set is booked as the open profit a set first reaches each of SCALE, and the last set runs as in A
  C  all sets run as in A, or are all booked once the open profit a set reaches BOOK_ALL; the position then
     waits flat for the next entry signal and re-enters in a later expiry than the booked one, REENTRY_DTE to
     MAX_DTE days out, with open interest on every leg (none that day: stay out, look again next signal)
Trade: a 1-2-1 butterfly with 1000-point wings
  green: buy 1 CE at the nearest ITM 1000 strike, sell 2 CE 1000 higher, buy 1 CE 2000 higher
  red:   buy 1 PE at the nearest ITM 1000 strike, sell 2 PE 1000 lower,  buy 1 PE 2000 lower
Expiry (60 to 190 days out): the nearest Mar/Jun/Sep/Dec monthly expiry if every leg has open interest,
  else the nearest monthly expiry that has it, else the nearest one listed (flagged).
Fills: signal at a day's close, trade at the next session's close. A leg that traded is priced at its close,
  one that didn't at NSE's settlement (theoretical) price. Expiry settles at intrinsic value on the NIFTY close.
  Cost: COST points per option per trade (4 options a structure), none at expiry settlement.
Rupees are for the whole position (SETS sets, 1 lot a leg each) at today's lot of 65 for every year, so years
  compare (NSE's lot was 75, 50 and 25 at times; a real position then made or lost that much more or less).
Output: study/fly_study.json and study/fly_report.html (local only)
Run: py study/fly_study.py        (after study/fetch_fno_bhavcopy.py; needs pandas, pyarrow, yfinance)
"""
import bisect
import json
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
FNO = HERE / 'fno_bhavcopy'
NIFTY_CSV = HERE / 'nifty_daily.csv'
PERIOD, MULT = 10, 3
WIDTH = 1000
MIN_DTE = 60
MAX_DTE = 190     # about two quarters: further out, NIFTY's 1000 strikes barely trade
REENTRY_DTE = 90  # C: least days to expiry for a re-entry after the position is booked
QUARTERS = {3, 6, 9, 12}
COST = 1.0
LOT = 65          # NIFTY lot today, used for every year so rupees compare across the study
SETS = 4
SCALE = [8000, 10000, 12000]
BOOK_ALL = 15000
VARIANTS = {'A': (f'{SETS} sets, all run to weekly flip or expiry', None, None),
            'B': (f'{SETS} sets, book 1 at ' + ', '.join(f'₹{x // 1000}k' for x in SCALE) + ', last runs', SCALE, None),
            'C': (f'{SETS} sets, all run or all booked at ₹{BOOK_ALL // 1000}k a set', None, BOOK_ALL)}
QTY = (1, -2, 1)


def nifty():
    """NIFTY daily OHLC from Yahoo, cached in study/nifty_daily.csv and refreshed each run."""
    try:
        import yfinance as yf
        d = yf.download('^NSEI', start='2007-09-17', progress=False, auto_adjust=False)
        d.columns = [c[0] for c in d.columns]
        d = d[['Open', 'High', 'Low', 'Close']].dropna()
        if len(d) > 1000:
            d.to_csv(NIFTY_CSV)
    except Exception as e:
        print(f'Yahoo refresh failed ({e}); using {NIFTY_CSV.name}')
    d = pd.read_csv(NIFTY_CSV, index_col=0, parse_dates=True)
    return d[d.High >= d.Low]


def st_step(st, h, l, c):
    """One Supertrend bar (TradingView's rules, ATR by Wilder smoothing). State: n, tr sum, atr, upper, lower, up, prev close."""
    n, trsum, atr, fu, fl, up, pc = st
    tr = h - l if pc is None else max(h - l, abs(h - pc), abs(l - pc))
    n += 1
    if n < PERIOD:
        return n, trsum + tr, None, None, None, False, c
    atr = (trsum + tr) / PERIOD if n == PERIOD else (atr * (PERIOD - 1) + tr) / PERIOD
    mid = (h + l) / 2
    bu, bl = mid + MULT * atr, mid - MULT * atr
    if fu is not None:
        bu = bu if bu < fu or pc > fu else fu
        bl = bl if bl > fl or pc < fl else fl
    up = c >= bl if up else c > bu
    return n, trsum, atr, bu, bl, up, c


def supertrend_live(df, key):
    """Colour at each day's close (True green, None before the ATR has PERIOD bars) and the Supertrend line
    (the lower band when green, the upper when red); key groups days into bars."""
    st = (0, 0.0, None, None, None, False, None)
    colour, line, hi, lo = [], [], -math.inf, math.inf
    k = list(key)
    for i, (h, l, c) in enumerate(zip(df.High, df.Low, df.Close)):
        if i == 0 or k[i] != k[i - 1]:
            hi, lo = -math.inf, math.inf
        hi, lo = max(hi, h), min(lo, l)
        tent = st_step(st, hi, lo, c)
        ready = tent[2] is not None
        colour.append(tent[5] if ready else None)
        line.append((tent[4] if tent[5] else tent[3]) if ready else None)
        if i == len(k) - 1 or k[i + 1] != k[i]:
            st = tent
    return pd.Series(colour, index=df.index), pd.Series(line, index=df.index, dtype=float)


def signals(px):
    """Daily and weekly colour and line."""
    iso = px.index.isocalendar()
    d, dl = supertrend_live(px, range(len(px)))
    w, wl = supertrend_live(px, zip(iso.year, iso.week))
    return pd.DataFrame({'D': d, 'W': w, 'Dl': dl, 'Wl': wl})


def load_options():
    frames = []
    for f in sorted(FNO.glob('fo_*.parquet')):
        df = pd.read_parquet(f, columns=['date', 'expiry', 'strike', 'option_type', 'close', 'settle', 'contracts', 'oi'],
                             filters=[('symbol', '==', 'NIFTY'), ('instrument', '==', 'OPTIDX')])
        frames.append(df[df.strike % WIDTH == 0])
    df = pd.concat(frames, ignore_index=True)
    df['option_type'] = df.option_type.astype(str)
    df['expiry'] = df.expiry.astype('datetime64[ns]')
    df['date'] = df.date.astype('datetime64[ns]')
    traded = df.contracts > 0
    df['price'] = np.where(traded | (df.settle <= 0), df.close, df.settle)
    return df, traded


class Book:
    def __init__(self, df, traded):
        self.q = {k: (p, t, o) for k, p, t, o in zip(
            zip(df.date, df.expiry, df.strike, df.option_type), df.price, traded, df.oi)}
        self.listed = {d: [pd.Timestamp(e) for e in es] for d, es in df.groupby('date').expiry.unique().items()}

    def monthly(self, d):
        """The last expiry of each month among those listed on d. From Sep 2025 NSE moved NIFTY expiry to Tuesday
        and re-dated open contracts, so this is read per day, not from all expiries ever seen."""
        last = {}
        for e in self.listed.get(d, []):
            if e > last.get((e.year, e.month), e - pd.Timedelta(days=1)):
                last[(e.year, e.month)] = e
        return list(last.values())

    def choose(self, d, spot, side, after=None):
        """after: the expiry of a position booked at BOOK_ALL; then only later expiries REENTRY_DTE+ days out with
        open interest on every leg, else None (the caller stays flat and looks again at the next signal)."""
        k1 = math.floor(spot / WIDTH) * WIDTH if side == 'CE' else math.ceil(spot / WIDTH) * WIDTH
        step = WIDTH if side == 'CE' else -WIDTH
        ks = [k1, k1 + step, k1 + 2 * step]
        cands = sorted(e for e in self.monthly(d) if MIN_DTE <= (e - d).days <= MAX_DTE)
        strict = after is not None
        if strict:
            cands = [e for e in cands if e > after and (e - d).days >= REENTRY_DTE]
        order = [e for e in cands if e.month in QUARTERS][:1] + cands
        rows = {e: [self.q.get((d, e, float(k), side)) for k in ks] for e in order}
        # a long butterfly always costs between 0 and the wing width; outside that the prices are stale
        # settlement estimates on legs that didn't trade, so that expiry is skipped
        rows = {e: r for e, r in rows.items()
                if all(r) and 0 < sum(q * x[0] for q, x in zip(QTY, r)) < WIDTH}
        for e in order:
            if e in rows and all(r[2] > 0 for r in rows[e]):
                return e, ks, 'quarterly' if e.month in QUARTERS else 'monthly', rows[e]
        for e in order:
            if e in rows and not strict:
                return e, ks, 'no open interest', rows[e]
        return None


def intrinsic(side, k, s):
    return max(s - k, 0.0) if side == 'CE' else max(k - s, 0.0)


def run(book, days, spot, sig, sets=1, scale=None, book_all=None):
    """sets: sets a position. scale: rupee levels of open profit a set, e.g. [8000, 10000, 12000]; one set is booked
    at each level as the profit per set first reaches it, the rest run to the weekly flip or expiry.
    book_all: rupees of open profit a set at which every set is booked; the position then waits flat and
    re-enters in a later expiry (Book.choose's after)."""
    assert len(scale or []) < sets
    pos, pending, booked = None, None, None
    trades, curve, realized = [], [], 0.0
    prev_w = None
    levels = list(scale or [])

    def entry(d):
        """The side the entry rule allows at d's close: daily and weekly the same colour."""
        s = sig.loc[d]
        if s.D is None or s.W is None or s.D != s.W:
            return None
        return 'CE' if s.W else 'PE'

    def last_day(e):
        """An expiry on a holiday moves to the session before, while the file keeps the listed date."""
        return days[bisect.bisect_right(days, e) - 1] if e <= days[-1] else e

    def value(p, d):
        if d == p['last_day']:
            prices = [intrinsic(p['side'], k, spot[d]) for k in p['ks']]
        else:
            prices = []
            for j, k in enumerate(p['ks']):
                r = book.q.get((d, p['expiry'], float(k), p['side']))
                if r:
                    p['last'][j] = r[0]
                prices.append(p['last'][j])
        return sum(q * x for q, x in zip(QTY, prices)), prices

    def mark(p, d):
        """Rupees of one set (LOT units a leg), marked daily."""
        if p['marked'] != d:
            v = value(p, d)[0]
            p['rs'] += (v - p['v_prev']) * LOT
            p['v_prev'], p['marked'] = v, d

    def open_(d, side, why):
        nonlocal booked
        got = book.choose(d, spot[d], side, booked)
        if not got:
            return None
        booked = None
        e, ks, tier, rows = got
        prices = [r[0] for r in rows]
        v = sum(q * x for q, x in zip(QTY, prices))
        return {'side': side, 'expiry': e, 'last_day': last_day(e), 'ks': ks, 'tier': tier, 'entry': d,
                'spot_in': spot[d], 'prices_in': prices, 'value_in': v, 'why_in': why, 'v_prev': v, 'marked': d,
                'untraded': sum(not r[1] for r in rows), 'last': prices[:], 'rs': -COST * 4 * LOT,
                'sets': sets, 'levels': levels[:]}

    def close_(p, d, why, sets):
        """Close `sets` of the position's sets at today's close (each set's rupees in p['rs'])."""
        nonlocal realized
        mark(p, d)
        v, prices = value(p, d)
        at_expiry = d == p['last_day']
        cost = COST * 4 * (1 if at_expiry else 2)
        rs = p['rs'] - (0 if at_expiry else COST * 4 * LOT)
        gross = v - p['value_in']
        untraded = p['untraded'] + (0 if at_expiry else sum(
            not (book.q.get((d, p['expiry'], float(k), p['side'])) or (0, False))[1] for k in p['ks']))
        realized += rs * sets
        p['sets'] -= sets
        trades.append({'in': str(p['entry'].date()), 'out': str(d.date()), 'side': p['side'],
                       'expiry': str(p['expiry'].date()), 'ks': p['ks'], 'tier': p['tier'],
                       'spot_in': round(p['spot_in'], 2), 'spot_out': round(spot[d], 2),
                       'prices_in': [round(x, 2) for x in p['prices_in']], 'prices_out': [round(x, 2) for x in prices],
                       'debit': round(p['value_in'], 2), 'exit_value': round(v, 2),
                       'gross': round(gross, 2), 'net': round(gross - cost, 2), 'sets': sets, 'rs': round(rs * sets),
                       'days': (d - p['entry']).days, 'why_in': p['why_in'], 'why_out': why, 'untraded': untraded})

    for d in days:
        # a contract NSE re-dated (the 2025 move to Tuesday expiry) is followed to its new date
        if pos and d < pos['last_day'] and pos['expiry'] not in book.listed.get(d, []):
            same = [e for e in book.monthly(d) if (e.year, e.month) == (pos['expiry'].year, pos['expiry'].month)]
            if same:
                pos['expiry'], pos['last_day'] = same[0], last_day(same[0])
        # 1. an expiry today settles; a new position opens at this close only if daily and weekly still agree
        #    on the same side, else it waits flat for the next entry signal
        if pos and d == pos['last_day']:
            side = pos['side']
            ok = not pending and entry(d) == side
            close_(pos, d, 'expiry, rolled' if ok else 'expiry', pos['sets'])
            pos = open_(d, side, 'roll') if ok else None
        # 2. yesterday's signal, filled at today's close
        if pending:
            act, side, why = pending
            pending = None
            if act in ('close', 'reverse') and pos:
                close_(pos, d, 'weekly flip', pos['sets'])
                pos = None
            if act in ('open', 'reverse') and not pos:
                pos = open_(d, side, why)
        # 3. mark to market; one set is booked at each level the profit a set reaches, the last set runs on
        if pos:
            mark(pos, d)
            while pos['levels'] and pos['rs'] >= pos['levels'][0] and pos['entry'] != d and d != pos['last_day']:
                close_(pos, d, f"booked at \u20b9{pos['levels'].pop(0):,}", 1)
            if book_all and pos['rs'] >= book_all and pos['entry'] != d and d != pos['last_day']:
                booked = pos['expiry']
                close_(pos, d, f'all booked at \u20b9{book_all:,}', pos['sets'])
                pos = None
        curve.append(round(realized + (pos['rs'] * pos['sets'] if pos else 0.0)))
        # 4. today's close sets tomorrow's trade
        W = sig.loc[d].W
        flipped = prev_w is not None and W is not None and W != prev_w
        prev_w = W
        want = entry(d)
        if pos:
            if flipped and W != (pos['side'] == 'CE'):
                pending = ('reverse', want, 'signal') if want else ('close', None, None)
        elif want:
            pending = ('open', want, 'signal')

    openpos = None
    if pos:
        v, prices = value(pos, days[-1])
        openpos = {'in': str(pos['entry'].date()), 'side': pos['side'], 'expiry': str(pos['expiry'].date()),
                   'ks': pos['ks'], 'tier': pos['tier'], 'spot_in': round(pos['spot_in'], 2),
                   'prices_in': [round(x, 2) for x in pos['prices_in']], 'prices_now': [round(x, 2) for x in prices],
                   'debit': round(pos['value_in'], 2), 'value_now': round(v, 2),
                   'open_pnl': round(v - pos['value_in'] - COST * 4, 2), 'rs': round(pos['rs']), 'sets': pos['sets']}
    return trades, curve, openpos, pending


def stats(trades, curve, sets):
    """Per closed position (all its sets, booked or run out), so the variants compare trade for trade."""
    positions = {}
    for t in trades:
        positions.setdefault(t['in'], []).append(t)
    done = [ts for ts in positions.values() if sum(t['sets'] for t in ts) == sets]
    rs = np.array([sum(t['rs'] for t in ts) for ts in done]) if done else np.zeros(0)
    c = np.array(curve)
    dd = c - np.maximum.accumulate(np.maximum(c, 0))
    years = {}
    for t in trades:
        years[t['out'][:4]] = round(years.get(t['out'][:4], 0) + t['rs'])
    return {'trades': len(done), 'wins': int((rs > 0).sum()), 'net': round(sum(t['rs'] for t in trades)),
            'avg': round(float(rs.mean())) if len(rs) else 0, 'best': round(float(rs.max())) if len(rs) else 0,
            'worst': round(float(rs.min())) if len(rs) else 0,
            'avg_debit': round(float(np.mean([ts[0]['debit'] * LOT * sets for ts in done]))) if done else 0,
            'maxdd': round(float(dd.min())), 'final': round(float(c[-1])) if len(c) else 0,
            'years': years, 'avg_days': round(float(np.mean([max(t['days'] for t in ts) for ts in done])), 1) if done else 0,
            'booked': sum(t['sets'] for t in trades if 'booked' in t['why_out']),
            'untraded_fills': int(sum(t['untraded'] for t in trades)),
            'tiers': {k: sum(ts[0]['tier'] == k for ts in done) for k in ('quarterly', 'monthly', 'no open interest')}}


def runs(series, days):
    """[start, end, colour] runs of a signal, for the colour strip."""
    out = []
    for d in days:
        v = series.loc[d]
        v = None if v is None or (isinstance(v, float) and math.isnan(v)) else bool(v)
        if out and out[-1][2] == v:
            out[-1][1] = str(d.date())
        else:
            out.append([str(d.date()), str(d.date()), v])
    return out


def main():
    sys.stdout.reconfigure(encoding='utf-8')
    px = nifty()
    sig = signals(px)
    df, traded = load_options()
    book = Book(df, traded)
    days = sorted(set(book.listed) & set(px.index))
    missing = sorted(set(book.listed) - set(px.index))
    print(f'{len(days)} sessions {days[0].date()} to {days[-1].date()}'
          + (f'; {len(missing)} bhavcopy days missing from Yahoo: {[str(m.date()) for m in missing[:5]]}' if missing else ''))
    spot = px.Close.to_dict()

    last = sig.loc[days[-1]]
    out = {'asof': str(days[-1].date()), 'start': str(days[0].date()), 'cost': COST, 'lot': LOT, 'sets': SETS,
           'scale': SCALE, 'book_all': BOOK_ALL, 'reentry_dte': REENTRY_DTE, 'width': WIDTH, 'min_dte': MIN_DTE, 'max_dte': MAX_DTE, 'dates': [str(d.date()) for d in days],
           'today': {'D': None if last.D is None else bool(last.D), 'W': None if last.W is None else bool(last.W),
                     'spot': round(spot[days[-1]], 2), 'Dl': round(last.Dl, 2), 'Wl': round(last.Wl, 2)},
           'strip': {k: runs(sig[k], days) for k in 'DW'}, 'variants': {}}
    for v, (name, scale, book_all) in VARIANTS.items():
        trades, curve, openpos, pending = run(book, days, spot, sig, SETS, scale, book_all)
        st = stats(trades, curve, SETS)
        out['variants'][v] = {'name': name, 'trades': trades, 'curve': curve, 'open': openpos, 'stats': st,
                              'pending': list(pending) if pending else None}
        print(f"{v} {name}: {st['trades']} closes, net Rs {st['final']:+,} incl. open, "
              f"max drawdown Rs {st['maxdd']:,}, legs priced at settlement {st['untraded_fills']}")
        print('   by year:', st['years'])
    (HERE / 'fly_study.json').write_text(json.dumps(out), encoding='utf-8')
    import fly_report
    fly_report.build(out)
    print('wrote study/fly_study.json and study/fly_report.html')


if __name__ == '__main__':
    main()
