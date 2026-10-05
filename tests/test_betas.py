"""Tests for the Portfolio Beta tool: betas.py's and mf_betas.py's maths and safety checks, the NIFTY hedge
data, and the page/data routes in app.py. No network: downloads are mocked.
Run from the repo root with:  py -m unittest tests.test_betas"""

import datetime as dt
import gzip
import http.client
import json
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import betas  # noqa: E402
import mf_betas  # noqa: E402

TRUE_BETAS = {"HIGHB": 1.6, "LOWB": 0.5, "BONUSB": 1.2}


def synthetic(days=260, seed=7):
    """Bhavcopy-shaped rows (sym, close, prev, ret, date) where NIFTYBEES follows a market factor and three
    stocks have known betas. BONUSB has a 1:1 bonus mid-window: its price halves and NSE's adjusted
    previous close halves with it, so the day's return stays a normal one."""
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range("2025-01-01", periods=days)
    market = rng.normal(0.0005, 0.01, days)
    series = {"NIFTYBEES": market}
    for sym, beta in TRUE_BETAS.items():
        series[sym] = beta * market + rng.normal(0, 0.006, days)
    rows = []
    for sym, rets in series.items():
        close = 100.0
        for i, (day, r) in enumerate(zip(dates, rets)):
            prev = close
            if sym == "BONUSB" and i == days // 2:
                prev = close / 2                          # ex-date: NSE halves PrvsClsgPric
            close = prev * (1 + r)
            rows.append({"sym": sym, "close": close, "prev": prev, "ret": close / prev - 1, "date": day})
    return pd.DataFrame(rows)


class ComputeTest(unittest.TestCase):
    def test_recovers_true_betas_through_a_bonus(self):
        stocks, asof, ndays = betas.compute(synthetic(), "NIFTYBEES", 120, 0.35)
        self.assertEqual(ndays, 260)
        for sym, beta in TRUE_BETAS.items():
            self.assertAlmostEqual(stocks[sym]["b"], beta, delta=0.1, msg=sym)
            self.assertEqual(stocks[sym]["n"], 260, msg=sym)     # the bonus day is a normal day, not masked
        self.assertAlmostEqual(stocks["NIFTYBEES"]["b"], 1.0, places=6)


class BuildGuardTest(unittest.TestCase):
    def setUp(self):
        tmp = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.out, self.cache, self.db = tmp / "data" / "betas.json", tmp / "cache", tmp / "betas.db"
        self.out.parent.mkdir()
        self.previous = '{"asof":"2026-01-02","count":1234,"stocks":{}}'
        self.out.write_text(self.previous)

    def build(self, data):
        with mock.patch.object(betas, "collect", return_value=data):
            return betas.build(self.out, self.cache, dt.date(2026, 1, 2), db_path=self.db)

    def runs(self):
        with betas.run_log(self.db) as database:
            return [tuple(row) for row in database.execute("SELECT status, message FROM beta_runs ORDER BY id")]

    def assert_kept(self, data, reason):
        with self.assertRaises(betas.BetaBuildError) as caught:
            self.build(data)
        self.assertIn(reason, str(caught.exception))
        self.assertEqual(self.out.read_text(), self.previous)
        self.assertFalse(self.out.with_name("betas.json.tmp").exists())
        self.assertEqual(self.runs()[-1][0], "failed")

    def test_too_few_days_keeps_previous_file(self):
        data = synthetic()
        self.assert_kept(data[data["date"] >= data["date"].unique()[-150]], "trading days")

    def test_too_few_stocks_keeps_previous_file(self):
        self.assert_kept(synthetic(), "stocks got a beta")            # only 4 symbols, need 1,000

    def test_missing_benchmark_keeps_previous_file(self):
        data = synthetic()
        self.assert_kept(data[data["sym"] != "NIFTYBEES"], "NIFTYBEES")

    def test_nothing_downloaded_keeps_previous_file(self):
        with mock.patch.object(betas, "collect", side_effect=SystemExit("No bhavcopy files could be read.")):
            with self.assertRaises(betas.BetaBuildError):
                betas.build(self.out, self.cache, dt.date(2026, 1, 2), db_path=self.db)
        self.assertEqual(self.out.read_text(), self.previous)

    def test_good_build_replaces_file_and_logs_run(self):
        with mock.patch.object(betas, "MIN_STOCKS", 3):
            payload = self.build(synthetic())
        written = json.loads(self.out.read_text())
        self.assertEqual(written, payload)
        self.assertEqual((written["benchmark"], written["count"], written["window_days"]), ("NIFTYBEES", 4, 260))
        self.assertEqual(self.runs(), [("ok", "")])

    def test_prune_cache_drops_files_older_than_400_days(self):
        self.cache.mkdir()
        old, recent = self.cache / "cm_20240101.csv.zip", self.cache / "cm_20251201.csv.zip"
        old.write_bytes(b"x"), recent.write_bytes(b"x")
        self.assertEqual(betas.prune_cache(self.cache, dt.date(2026, 1, 2)), 1)
        self.assertFalse(old.exists())
        self.assertTrue(recent.exists())


AMFI_TEXT = """Scheme Code;NAV Name;Plan;Option;ISIN Div Payout/ISIN Growth;ISIN Div Reinvestment;Net Asset Value;Date

Open Ended Schemes ( Equity Scheme - Flexi Cap Fund )

Some Mutual Fund
111;Some Flexi Cap Fund - Direct Plan - Growth;;;INF000A01011;;101.5000;01-Jul-2026
112;Some Flexi Cap Fund - Direct Plan - IDCW;;;INF000A01029;INF000A01037;21.1000;01-Jul-2026
113;Some Flexi Cap Fund - Income Distribution cum Capital Withdrawal Growth;;;INF000A01045;;19.0000;01-Jul-2026
114;Some Flexi Cap Fund - Regular Plan - Growth;;;INF000A01052;;N.A.;01-Jul-2026

Open Ended Schemes ( Other Scheme - FoF Overseas )

Some Mutual Fund
115;Some US Tech FoF - Direct Plan - Growth;;;INF000A01060;;12.3400;01-Jul-2026

Close Ended Schemes ( Income )

Some Mutual Fund
116;Some FMP Series 9 - Growth;;;INF000A01078;;11.0000;01-Jul-2026
"""


class MutualFundTest(unittest.TestCase):
    def test_parse_keeps_open_ended_growth_plans_only(self):
        navs = mf_betas.parse_navs(AMFI_TEXT)
        self.assertEqual(list(navs["code"]), ["111", "115"])          # no IDCW, N.A. NAV or close-ended scheme
        self.assertEqual(navs.iloc[0]["isin"], "INF000A01011")
        self.assertEqual(navs.iloc[0]["cat"], "Equity Scheme - Flexi Cap Fund")
        self.assertEqual(navs.iloc[1]["cat"], "Other Scheme - FoF Overseas")

    def navs_for(self, stock_data, beta=0.8, seed=3, skip=()):
        """A fund whose daily return is beta x NIFTYBEES's plus noise, priced on the benchmark's trading
        days except those in skip (a NAV AMFI didn't publish)."""
        rng = np.random.default_rng(seed)
        bench = stock_data[stock_data["sym"] == "NIFTYBEES"].sort_values("date")
        nav, rows = 50.0, []
        for i, (day, r) in enumerate(zip(bench["date"], bench["ret"])):
            nav *= 1 + beta * r + rng.normal(0, 0.002)
            if i not in skip:
                rows.append({"code": "900", "name": "Test Fund - Direct Plan - Growth", "isin": "INF000X01011",
                             "cat": "Equity Scheme - Large Cap Fund", "date": day, "nav": nav})
        return pd.DataFrame(rows)

    def test_fund_beta_recovered_on_benchmark_days(self):
        data = synthetic()
        navs = self.navs_for(data, beta=0.8, skip={100})
        rows = mf_betas.fund_returns(navs, data[data["sym"] == "NIFTYBEES"])
        stats, _, ndays = betas.compute(rows, "NIFTYBEES", 120, mf_betas.MAX_ABS_RET)
        self.assertAlmostEqual(stats["900"]["b"], 0.8, delta=0.05)
        self.assertEqual(stats["900"]["n"], 257)       # 259 returns, less the two either side of the missing NAV
        self.assertEqual(ndays, 259)

    def test_build_guard_and_good_build(self):
        with tempfile.TemporaryDirectory() as tmp:
            out, db = Path(tmp) / "mf_betas.json", Path(tmp) / "betas.db"
            out.write_text('{"count":4000}')
            data = synthetic()
            navs = self.navs_for(data)
            with mock.patch.object(betas, "collect", return_value=data), \
                 mock.patch.object(mf_betas, "collect_navs", return_value=navs):
                with self.assertRaises(betas.BetaBuildError):
                    mf_betas.build(out, Path(tmp), Path(tmp), dt.date(2026, 1, 2), db_path=db)
                self.assertEqual(out.read_text(), '{"count":4000}')        # one fund < MIN_FUNDS: old file kept
                with mock.patch.object(mf_betas, "MIN_FUNDS", 1):
                    payload = mf_betas.build(out, Path(tmp), Path(tmp), dt.date(2026, 1, 2), db_path=db)
            fund = json.loads(out.read_text())["funds"]["900"]
            self.assertEqual(payload["count"], 1)
            self.assertEqual((fund["name"], fund["isin"], payload["cats"][fund["c"]]),
                             ("Test Fund - Direct Plan - Growth", "INF000X01011", "Equity Scheme - Large Cap Fund"))
            self.assertNotIn("NIFTYBEES", payload["funds"])
            with betas.run_log(db, mf_betas.RUN_TABLE) as database:
                self.assertEqual([r[0] for r in database.execute("SELECT status FROM mf_beta_runs ORDER BY id")], ["failed", "ok"])

    def test_overseas_names_are_flagged(self):
        for name in ("Motilal Oswal Nasdaq 100 Fund of Fund", "Some US Specific Equity FoF", "Global Innovation Fund"):
            self.assertTrue(mf_betas.OVERSEAS.search(name), name)
        for name in ("HDFC Flexi Cap Fund", "Nippon India Multi Cap Fund", "SBI Focused Equity Fund"):
            self.assertFalse(mf_betas.OVERSEAS.search(name), name)


FO_HEADER = "TradDt,FinInstrmTp,TckrSymb,XpryDt,StrkPric,OptnTp,ClsPric,UndrlygPric,OpnIntrst,TtlTradgVol,NewBrdLotQty"
FO_ROWS = """2026-10-01,IDF,NIFTY,2026-10-27,,,22530.3,22421.95,100,10,65
2026-10-01,IDF,NIFTY,2026-11-23,,,22638,22421.95,100,10,65
2026-10-01,IDO,NIFTY,2026-10-06,21000,PE,5,22421.95,100,10,65
2026-10-01,IDO,NIFTY,2026-10-27,21300,PE,52.8,22421.95,5000,900,65
2026-10-01,IDO,NIFTY,2026-10-27,21400,PE,60,22421.95,0,0,65
2026-10-01,IDO,NIFTY,2026-10-27,15000,PE,1,22421.95,50,1,65
2026-10-01,IDO,NIFTY,2026-10-27,21300,CE,1200,22421.95,50,1,65
2026-10-01,IDO,NIFTY,2026-11-23,22000,PE,250,22421.95,10,2,65
2026-10-01,IDF,BANKNIFTY,2026-10-27,,,50000,49900,10,1,30"""


class NiftyHedgeTest(unittest.TestCase):
    def test_monthly_puts_near_spot_with_open_interest(self):
        import app
        hedge = app.parse_nifty_hedge(FO_HEADER + "\n" + FO_ROWS)
        self.assertEqual((hedge["spot"], hedge["lot"]), (22421.95, 65))
        self.assertEqual([f["expiry"] for f in hedge["futures"]], ["2026-10-27", "2026-11-23"])
        # weekly 6 Oct expiry, zero-OI 21400, far 15000 strike and the call are all left out
        self.assertEqual(hedge["puts"], [{"expiry": "2026-10-27", "strikes": [[21300.0, 52.8, 5000, 900]]},
                                         {"expiry": "2026-11-23", "strikes": [[22000.0, 250.0, 10, 2]]}])

    def test_no_nifty_futures_gives_none(self):
        import app
        self.assertIsNone(app.parse_nifty_hedge(FO_HEADER + "\n" + FO_ROWS.splitlines()[-1]))


class PageTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import app
        cls.app = app
        cls.server = app.ThreadingHTTPServer(("127.0.0.1", 0), app.BlogHandler)
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def get(self, path, headers=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.server.server_address[1], timeout=10)
        conn.request("GET", path, headers=headers or {})
        response = conn.getresponse()
        body = response.read().decode("utf-8")
        conn.close()
        return response, body

    def test_page_is_served_with_disclaimer(self):
        response, body = self.get("/portfolio-beta.html")
        self.assertEqual(response.status, 200)
        self.assertIn("not a SEBI-registered investment adviser or research analyst", body)
        self.assertIn('href="portfolio-beta.html">Portfolio Beta</a>', body)

    def test_tools_url_redirects_to_page(self):
        for path in ("/tools/portfolio-beta/", "/tools/portfolio-beta"):
            response, _ = self.get(path)
            self.assertEqual((response.status, response.getheader("Location")), (301, "/portfolio-beta.html"))

    def test_betas_json_is_cached_for_an_hour_and_revalidates(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "betas.json"
            path.write_text('{"asof":"2026-01-02"}')
            with mock.patch.object(self.app, "BETA_JSON_PATH", path):
                response, body = self.get("/data/betas.json")
                self.assertEqual(response.status, 200)
                self.assertEqual(response.getheader("Content-Type"), "application/json")
                self.assertEqual(response.getheader("Cache-Control"), "public, max-age=3600")
                self.assertEqual(json.loads(body)["asof"], "2026-01-02")
                again, _ = self.get("/data/betas.json", {"If-None-Match": response.getheader("ETag")})
                self.assertEqual(again.status, 304)

    def test_mf_betas_json_is_served_gzipped(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "mf_betas.json"
            path.write_text('{"funds":{"900":{"b":0.8}}}' + " " * 5000)
            with mock.patch.object(self.app, "MF_BETA_JSON_PATH", path):
                conn = http.client.HTTPConnection("127.0.0.1", self.server.server_address[1], timeout=10)
                conn.request("GET", "/data/mf_betas.json", headers={"Accept-Encoding": "gzip, deflate"})
                response = conn.getresponse()
                raw = response.read()
                conn.close()
        self.assertEqual((response.status, response.getheader("Content-Encoding")), (200, "gzip"))
        self.assertLess(len(raw), 1000)
        self.assertEqual(json.loads(gzip.decompress(raw))["funds"]["900"]["b"], 0.8)

    def test_nifty_hedge_route(self):
        fake = {"date": "2026-10-01", "rows": [], "niftyHedge": {"spot": 22421.95, "lot": 65, "futures": [], "puts": []}}
        with mock.patch.object(self.app, "fetch_oi_change", return_value=fake):
            _, body = self.get("/api/nifty-hedge")
            _, oi = self.get("/api/oi-change")
        self.assertEqual(json.loads(body), {"date": "2026-10-01", "spot": 22421.95, "lot": 65, "futures": [], "puts": []})
        self.assertNotIn("niftyHedge", json.loads(oi))                # the OI page's payload is unchanged

    def test_sitemap_lists_page(self):
        self.assertIn("portfolio-beta.html", self.app.SITEMAP_STATIC_PAGES)


if __name__ == "__main__":
    unittest.main()
