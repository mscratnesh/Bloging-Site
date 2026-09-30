"""Downloads NSE's daily F&O bhavcopy (every future and option contract, every session) for a study.

NSE has published it in two formats:
  up to 5 Jul 2024   content/historical/DERIVATIVES/2016/OCT/fo03OCT2016bhav.csv.zip   (old flat CSV)
  from 8 Jul 2024    content/fo/BhavCopy_NSE_FO_0_0_0_20240708_F_0000.csv.zip        (UDiFF)
Both are read into one schema:
  date, instrument (FUTIDX FUTSTK OPTIDX OPTSTK), symbol, expiry, strike, option_type (CE PE, blank for futures),
  open, high, low, close, settle, contracts, value_lakh (notional, Rs lakh), oi, chg_oi (both in shares),
  underlying (spot close, UDiFF days only), lot_size (UDiFF days only)
Steps:
  1. Tries every weekday plus NSE's weekend sessions (budget days, Muhurat) from START to today. A 404
     is a holiday and is noted in raw/missing.txt so later runs don't ask again (the last 7 days are always retried).
  2. Keeps each zip as NSE sent it, in study/fno_bhavcopy/raw/<year>/, so the parse can be redone offline.
  3. Writes study/fno_bhavcopy/fo_<year>.parquet, one file a year, rebuilt only when that year gained days.
Run: py study/fetch_fno_bhavcopy.py [start YYYY-MM-DD]     (default: ten years back; needs pandas, pyarrow, requests)
"""
import io
import sys
import time
import zipfile
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import requests

OUT = Path(__file__).parent / 'fno_bhavcopy'
RAW = OUT / 'raw'
MISSING = RAW / 'missing.txt'
UDIFF_FROM = date(2024, 7, 8)
BASE = 'https://nsearchives.nseindia.com/content'
HEADERS = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
                         '(KHTML, like Gecko) Chrome/126.0 Safari/537.36',
           'Referer': 'https://www.nseindia.com/'}
WORKERS = 4
MONTHS = 'JAN FEB MAR APR MAY JUN JUL AUG SEP OCT NOV DEC'.split()
UDIFF_TYPES = {'IDF': 'FUTIDX', 'STF': 'FUTSTK', 'IDO': 'OPTIDX', 'STO': 'OPTSTK'}
COLUMNS = ['date', 'instrument', 'symbol', 'expiry', 'strike', 'option_type', 'open', 'high', 'low', 'close',
           'settle', 'contracts', 'value_lakh', 'oi', 'chg_oi', 'underlying', 'lot_size']


def url(d):
    if d >= UDIFF_FROM:
        return f'{BASE}/fo/BhavCopy_NSE_FO_0_0_0_{d:%Y%m%d}_F_0000.csv.zip'
    mon = MONTHS[d.month - 1]
    return f'{BASE}/historical/DERIVATIVES/{d.year}/{mon}/fo{d:%d}{mon}{d.year}bhav.csv.zip'


def raw_path(d):
    return RAW / str(d.year) / f'fo_{d:%Y%m%d}.csv.zip'


def days(start, end):
    """Weekdays plus any weekend session NSE held (Muhurat trading, budget Saturdays)."""
    out = {start + timedelta(n) for n in range((end - start).days + 1)}
    out = {d for d in out if d.weekday() < 5}
    try:
        import pandas_market_calendars as pmc
        sessions = pmc.get_calendar('XNSE').valid_days(start, end)
        out |= {s.date() for s in sessions}
    except Exception:
        pass
    return sorted(out)


def fetch(session, d):
    """'ok', 'missing' (NSE has no file: a holiday) or 'failed'."""
    for attempt in range(4):
        try:
            r = session.get(url(d), headers=HEADERS, timeout=60)
        except requests.RequestException:
            time.sleep(2 * (attempt + 1))
            continue
        if r.status_code == 404:
            return 'missing'
        if r.status_code == 200 and r.content[:2] == b'PK':
            path = raw_path(d)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.with_suffix('.tmp').write_bytes(r.content)
            path.with_suffix('.tmp').replace(path)
            return 'ok'
        time.sleep(2 * (attempt + 1))
    return 'failed'


def read_csv(path):
    with zipfile.ZipFile(path) as z:
        return pd.read_csv(io.BytesIO(z.read(z.namelist()[0])), low_memory=False)


def parse(path, d):
    df = read_csv(path)
    df.columns = [c.strip() for c in df.columns]
    if d < UDIFF_FROM:
        out = pd.DataFrame({
            'instrument': df['INSTRUMENT'].str.strip(), 'symbol': df['SYMBOL'].str.strip(),
            'expiry': pd.to_datetime(df['EXPIRY_DT'], format='%d-%b-%Y'),
            'strike': df['STRIKE_PR'], 'option_type': df['OPTION_TYP'].str.strip(),
            'open': df['OPEN'], 'high': df['HIGH'], 'low': df['LOW'], 'close': df['CLOSE'],
            'settle': df['SETTLE_PR'], 'contracts': df['CONTRACTS'], 'value_lakh': df['VAL_INLAKH'],
            'oi': df['OPEN_INT'], 'chg_oi': df['CHG_IN_OI'], 'underlying': float('nan'), 'lot_size': pd.NA})
    else:
        out = pd.DataFrame({
            'instrument': df['FinInstrmTp'].map(UDIFF_TYPES), 'symbol': df['TckrSymb'].str.strip(),
            'expiry': pd.to_datetime(df['XpryDt']),
            'strike': df['StrkPric'].fillna(0), 'option_type': df['OptnTp'].fillna('XX').str.strip(),
            'open': df['OpnPric'], 'high': df['HghPric'], 'low': df['LwPric'], 'close': df['ClsPric'],
            'settle': df['SttlmPric'], 'contracts': df['TtlTradgVol'], 'value_lakh': df['TtlTrfVal'] / 1e5,
            'oi': df['OpnIntrst'], 'chg_oi': df['ChngInOpnIntrst'], 'underlying': df['UndrlygPric'],
            'lot_size': df['NewBrdLotQty']})
    out['option_type'] = out['option_type'].replace('XX', '')
    out.insert(0, 'date', pd.Timestamp(d))
    return out[COLUMNS]


def write_year(year):
    files = sorted((RAW / str(year)).glob('fo_*.csv.zip'))
    if not files:
        return 0
    frames = []
    for f in files:
        d = date(int(f.name[3:7]), int(f.name[7:9]), int(f.name[9:11]))
        try:
            frames.append(parse(f, d))
        except Exception as e:
            print(f'  could not read {f.name}: {e}')
    df = pd.concat(frames, ignore_index=True)
    df = df.astype({'instrument': 'category', 'symbol': 'category', 'option_type': 'category',
                    'contracts': 'int64', 'oi': 'int64', 'chg_oi': 'int64', 'lot_size': 'Int32',
                    'strike': 'float64', 'underlying': 'float64'})
    df.to_parquet(OUT / f'fo_{year}.parquet', index=False, compression='zstd')
    return len(frames)


def main():
    end = date.today()
    start = date.fromisoformat(sys.argv[1]) if len(sys.argv) > 1 else end.replace(year=end.year - 10)
    RAW.mkdir(parents=True, exist_ok=True)
    missing = set(MISSING.read_text().split()) if MISSING.exists() else set()
    recent = end - timedelta(7)
    todo = [d for d in days(start, end)
            if not raw_path(d).exists() and (d.isoformat() not in missing or d >= recent)]
    print(f'{start} to {end}: {len(todo)} sessions to fetch')

    changed, failed = set(), []
    with requests.Session() as session, ThreadPoolExecutor(WORKERS) as pool:
        for n, (d, result) in enumerate(zip(todo, pool.map(lambda d: fetch(session, d), todo)), 1):
            if result == 'ok':
                changed.add(d.year)
            elif result == 'missing' and d < recent:
                missing.add(d.isoformat())
            elif result == 'failed':
                failed.append(d)
            if n % 100 == 0 or n == len(todo):
                print(f'  {n}/{len(todo)}  up to {d}  ({len(failed)} failed)')
                MISSING.write_text('\n'.join(sorted(missing)))
    MISSING.write_text('\n'.join(sorted(missing)))

    for year in range(start.year, end.year + 1):
        if year in changed or not (OUT / f'fo_{year}.parquet').exists():
            n = write_year(year)
            if n:
                print(f'  fo_{year}.parquet: {n} sessions')
    if failed:
        print(f'{len(failed)} days failed (network or NSE blocking); run again to retry: '
              + ', '.join(map(str, failed[:10])) + (' ...' if len(failed) > 10 else ''))


if __name__ == '__main__':
    main()
