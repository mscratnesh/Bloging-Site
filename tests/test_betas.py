"""Tests for the Portfolio Beta tool: betas.py's maths and safety checks, and the page/data routes in app.py.
No network: collect() is mocked. Run from the repo root with:  py -m unittest tests.test_betas"""

import datetime as dt
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

    def test_sitemap_lists_page(self):
        self.assertIn("portfolio-beta.html", self.app.SITEMAP_STATIC_PAGES)


if __name__ == "__main__":
    unittest.main()
