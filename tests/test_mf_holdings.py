"""Tests for mf_holdings.py (the Fund Holdings Explorer's monthly job) and its routes in app.py.
No network: workbooks are built in memory and fetch_house is mocked.
Run from the repo root with:  py -m unittest tests.test_mf_holdings"""

import datetime as dt
import http.client
import io
import json
import sys
import tempfile
import threading
import unittest
import zipfile
from pathlib import Path
from unittest import mock

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import betas  # noqa: E402
import mf_holdings as mh  # noqa: E402

HEADER = ["Name of the Instrument", "ISIN", "Industry / Rating", "Quantity", "Market value (Rs. in Lakhs)", "% to NAV"]


def workbook(sheets):
    """An .xlsx in memory from {sheet name: list of rows}."""
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as xl:
        for name, rows in sheets.items():
            pd.DataFrame(rows).to_excel(xl, sheet_name=name, header=False, index=False)
    return buf.getvalue()


# SBI/Axis style: a label cell next to the name, a sheet code, a description to drop, percentages as fractions
SBI_LIKE = [
    ["SBI Mutual Fund", "007", "Back to Index"],
    ["SCHEME NAME :", "SBI Example Flexicap Fund (An open ended dynamic equity scheme)"],
    ["PORTFOLIO STATEMENT AS ON :", "2026-08-31"],
    HEADER,
    ["EQUITY & EQUITY RELATED"],
    ["ICICI Bank Ltd.", "INE090A01021", "Banks", 100, 600.0, 0.06],
    ["HDFC Bank Ltd.", "INE040A01034", "Banks", 100, 500.0, 0.05],
    ["Alphabet Inc A", "US02079K3059", "Software", 10, 200.0, 0.02],
    ["DEBT INSTRUMENTS"],
    ["7.1% GOI 2034", "IN0020240019", "Sovereign", 10, 100.0, 0.01],
    ["Grand Total", "", "", "", 1000.0, 1.0],
]
# UTI style: every scheme stacked in one sheet, a holding that looks like a fund name, a derivatives table
UTI_LIKE = [
    ["SCHEME CODE001STARTS"], ["UTI MUTUAL FUND"], ["SCHEME: UTI - Large Cap Fund"],
    HEADER, ["EQUITY AND EQUITY RELATED"],
    ["EQ - ICICI BANK LTD", "INE090A01021", "Banks", 1, 1, 9.5],
    ["INVIT - IRB INVIT FUND", "INE183W23014", "InvIT", 1, 1, 2.0],
    ["TOTAL : UTI - Large Cap Fund", "", "", "", "", 11.5],
    ["SCHEME CODE002STARTS"], ["UTI MUTUAL FUND"], ["SCHEME: UTI - Arbitrage Fund"],
    HEADER, ["EQUITY AND EQUITY RELATED"],
    ["EQ - RELIANCE INDUSTRIES LTD", "INE002A01018", "Petroleum Products", 1, 1, 60.0],
    ["TOTAL : UTI - Arbitrage Fund", "", "", "", "", 60.0],
    HEADER, ["DERIVATIVES - STOCK FUTURES"],
    ["RELIANCE FUT", "INE002A01018", "", 1, -1, -60.0],
]


class ParserTest(unittest.TestCase):
    def test_sbi_style_sheet(self):
        [scheme] = mh.parse_workbook(workbook({"SEEF": SBI_LIKE}), "sbi.xlsx")
        self.assertEqual(scheme["name"], "SBI Example Flexicap Fund")                    # label skipped, description dropped
        got = {h["isin"]: (h["kind"], h["pct"]) for h in scheme["holdings"]}
        self.assertEqual(got["INE090A01021"], ("equity", 6.0))                           # 0.06 -> 6%
        self.assertEqual(got["US02079K3059"], ("foreign", 2.0))                          # non-Indian ISIN in equity
        self.assertEqual(got["IN0020240019"], ("debt", 1.0))
        self.assertEqual(len(scheme["holdings"]), 4)                                     # stops at Grand Total

    def test_stacked_schemes_and_second_tables(self):
        schemes = mh.parse_workbook(workbook({"EXPOSURE": UTI_LIKE}), "uti.xlsx")
        self.assertEqual([s["name"] for s in schemes], ["UTI - Large Cap Fund", "UTI - Arbitrage Fund"])
        large, arb = schemes
        self.assertEqual(large["holdings"][0]["name"], "ICICI BANK LTD")                  # "EQ - " prefix dropped
        self.assertEqual(large["holdings"][1]["kind"], "reit")                           # InvIT units
        # the derivatives table has no title of its own, so it joins the scheme above (and its holding isn't taken as a name)
        self.assertEqual([(h["kind"], h["pct"]) for h in arb["holdings"]], [("equity", 60.0), ("derivative", -60.0)])

    def test_zip_of_workbooks_skips_extra_files(self):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            z.writestr("Example Flexicap.xlsx", workbook({"S": SBI_LIKE}))
            z.writestr("Divmast asof 2026.xls", b"not a workbook")                        # skipped by name
        schemes = mh.parse_file(buf.getvalue(), "portfolio.zip")
        self.assertEqual([s["name"] for s in schemes], ["SBI Example Flexicap Fund"])

    def test_unreadable_workbook(self):
        with self.assertRaises(mh.HoldingsError):
            mh.parse_workbook(b"<html>not excel</html>", "x.xls")

    def test_name_key_matches_amfi_spellings(self):
        self.assertEqual(mh.name_key("SBI Smallcap Fund"), mh.name_key("SBI Small Cap Fund - Direct Plan - Growth"))
        self.assertEqual(mh.name_key("UTI - Large Cap Fund"), mh.name_key("UTI Large Cap Fund-Growth Option- Direct"))
        self.assertNotEqual(mh.name_key("SBI Fixed Maturity Plan (FMP) - Series 1"), mh.name_key("SBI Fixed Maturity Plan (FMP) - Series 2"))


class BuildTest(unittest.TestCase):
    def scheme(self, name, isin="INE090A01021", pct=95.0):
        return {"name": name, "holdings": [{"isin": isin, "name": "ICICI Bank", "industry": "Banks", "kind": "equity", "value": 1.0, "pct": pct}]}

    def test_failed_house_keeps_last_good_month_and_publish_swaps(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp); out, cache, db = tmp / "data" / "mf_holdings", tmp / "cache", tmp / "betas.db"
            cache.mkdir()
            (cache / "uti.json").write_text(json.dumps({"asof": "2026-07-31", "schemes": [self.scheme("UTI - Large Cap Fund")]}))
            def fake(amc, month_end, session):
                if amc in ("uti", "kotak"):
                    raise mh.HoldingsError("no file for Aug 2026 yet")
                return [self.scheme(f"{mh.AMCS[amc].replace(' Mutual Fund', '')} Example {i} Fund") for i in range(6)]
            with mock.patch.object(mh, "fetch_house", side_effect=fake):
                index = mh.build(dt.date(2026, 8, 31), out, cache, db_path=db)
            self.assertEqual(index["houses"]["UTI Mutual Fund"], "2026-07-31")
            self.assertEqual(index["houses"]["SBI Mutual Fund"], "2026-08-31")
            self.assertEqual(index["count"], 10 * 6 + 1)
            uti = next(f for f in index["funds"] if f["amc"] == "UTI Mutual Fund")
            self.assertEqual((uti["asof"], uti["eq"]), ("2026-07-31", 95.0))
            held = json.loads((out / "f" / f"{uti['id']}.json").read_text(encoding="utf-8"))
            self.assertEqual(held["holdings"], [["INE090A01021", "ICICI Bank", "Banks", "equity", 95.0]])
            stocks = json.loads((out / "stocks.json").read_text(encoding="utf-8"))
            self.assertEqual(len(stocks["stocks"]["INE090A01021"]["funds"]), 61)
            self.assertFalse(out.with_name("mf_holdings.tmp").exists() or out.with_name("mf_holdings.old").exists())
            with betas.run_log(db, mh.RUN_TABLE) as database:
                status, message = database.execute("SELECT status, message FROM mf_holdings_runs").fetchone()
            self.assertEqual(status, "ok")
            self.assertIn("uti: no file for Aug 2026 yet; kept 2026-07-31", message)

    def test_too_few_houses_keeps_previous_data(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp); out = tmp / "data" / "mf_holdings"
            (out / "f").mkdir(parents=True); (out / "index.json").write_text('{"count": 900}')
            with mock.patch.object(mh, "fetch_house", side_effect=mh.HoldingsError("site down")):
                with self.assertRaises(mh.HoldingsError):
                    mh.build(dt.date(2026, 8, 31), out, tmp / "cache", db_path=tmp / "betas.db")
            self.assertEqual((out / "index.json").read_text(), '{"count": 900}')


class RouteTest(unittest.TestCase):
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

    def get(self, path):
        conn = http.client.HTTPConnection("127.0.0.1", self.server.server_address[1], timeout=10)
        conn.request("GET", path)
        r = conn.getresponse(); body = r.read(); conn.close()
        return r, body

    def test_data_files_served_and_paths_checked(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp); (d / "f").mkdir()
            (d / "index.json").write_text('{"count": 1}'); (d / "f" / "sbi-example.json").write_text('{"id": "sbi-example"}')
            with mock.patch.object(self.app, "MF_HOLDINGS_DIR", d):
                r, body = self.get("/data/mf_holdings/f/sbi-example.json")
                self.assertEqual((r.status, json.loads(body)["id"], r.getheader("Cache-Control")), (200, "sbi-example", "public, max-age=3600"))
                self.assertEqual(self.get("/data/mf_holdings/index.json")[0].status, 200)
                for bad in ("/data/mf_holdings/../betas.db", "/data/mf_holdings/f/..%2F..%2Fapp.py", "/data/mf_holdings/secret.json", "/data/mf_holdings/f/Upper.json"):
                    self.assertEqual(self.get(bad)[0].status, 404, bad)

    def test_page_redirect_and_sitemap(self):
        r, body = self.get("/mf-holdings.html")
        self.assertEqual(r.status, 200)
        self.assertIn(b"Mutual Fund investments are subject to market risks", body)
        self.assertIn(b'href="mf-holdings.html">MF Holdings Explorer</a>', body)
        self.assertEqual(self.get("/tools/mf-holdings/")[0].getheader("Location"), "/mf-holdings.html")
        self.assertIn("mf-holdings.html", self.app.SITEMAP_STATIC_PAGES)


if __name__ == "__main__":
    unittest.main()
