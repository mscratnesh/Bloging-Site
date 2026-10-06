"""Tests for fiidii.py (the FII/DII Activity page's data). No network: NSDL pages are small HTML snippets.
Run from the repo root with:  py -m unittest tests.test_fiidii"""

import datetime as dt
import json
import sqlite3
import sys
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import fiidii  # noqa: E402

OLD = """<p>Reporting Date Debt/Equity Gross Purchases (Rs Crore) Gross Sales(Rs Crore) Net Investment (Rs Crore)</p>
<table><tr><td>28-Jan-2005</td><td>Equity</td><td>1279.00</td><td>1080.20</td><td>198.80</td><td>45.40</td><td>Rs. 43.75</td></tr>
<tr><td>Debt</td><td>0.00</td><td>106.80</td><td>(106.80)</td><td>(24.40)</td></tr>
<tr><td>31-Jan-2005</td><td>Equity</td><td>1,524.40</td><td>892.50</td><td>632.00</td><td>144.30</td><td>Rs. 43.78</td></tr>
<tr><td>Debt</td><td>0.00</td><td>20.00</td><td>(20.00)</td><td>(4.60)</td></tr>
<tr><td>Total for January</td><td>Equity</td><td>16651.30</td><td>16194.30</td><td>457.00</td><td>105.20</td></tr>
<tr><td>Grand Total Till January 31, 2005</td><td>Equity</td><td>571594.90</td><td>442944.50</td><td>128651.00</td></tr></table>
<p>The data presented above is compiled ... on 31-Jan-2005</p>"""

NEW = """<p>Reporting Date Debt/Equity Investment Route ...</p><table>
<tr><td>01-Sep-2026</td><td>Equity</td><td>Stock Exchange</td><td>65512.88</td><td>71652.44</td><td>(6139.56)</td><td>(643.22)</td><td>Rs.95.4509</td></tr>
<tr><td>Primary market &amp; others</td><td>706.73</td><td>0.00</td><td>706.73</td><td>74.04</td></tr>
<tr><td>Sub-total</td><td>66219.61</td><td>71652.44</td><td>(5432.83)</td><td>(569.18)</td></tr>
<tr><td>Debt-General Limit</td><td>Stock Exchange</td><td>368.85</td><td>329.14</td><td>39.71</td><td>4.16</td></tr>
<tr><td>Sub-total</td><td>545.21</td><td>526.72</td><td>18.49</td><td>1.94</td></tr>
<tr><td>Debt-VRR</td><td>Sub-total</td><td>35.42</td><td>105.21</td><td>(69.79)</td><td>(7.31)</td></tr>
<tr><td>Mutual Funds</td><td>Equity schemes</td><td>42.48</td><td>18.22</td><td>24.26</td><td>2.54</td></tr>
<tr><td>Sub-total</td><td>113.42</td><td>18.91</td><td>94.51</td><td>9.89</td></tr>
<tr><td>Total</td><td>68961.71</td><td>74336.62</td><td>(5374.91)</td><td>(563.12)</td></tr></table>"""


class ParseArchive(unittest.TestCase):
    def test_old_layout_skips_month_and_all_time_totals(self):
        rows = fiidii.parse_archive(OLD)
        self.assertEqual(sorted(rows), ["2005-01-28", "2005-01-31"])
        self.assertEqual(rows["2005-01-31"], [1524.4, 892.5, 632.0, 632.0, -20.0, 0, 612.0])

    def test_new_layout_uses_sub_totals_and_total(self):
        row = fiidii.parse_archive(NEW)["2026-09-01"]
        self.assertEqual(row[:4], [65512.88, 71652.44, -6139.56, -5432.83])   # exchange buy/sell/net, all equity
        self.assertEqual(row[4], round(18.49 - 69.79, 2))                      # debt categories summed
        self.assertEqual(row[5], 94.51)                                        # MF "Equity schemes" isn't equity
        self.assertEqual(row[6], -5374.91)


class Database(unittest.TestCase):
    FD = {"date": dt.date(2026, 10, 5), "FII": {"buy": 15674.61, "sell": 20373.75, "net": -4699.14},
          "DII": {"buy": 20492.93, "sell": 15311.31, "net": 5181.62}}

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        t = Path(self.tmp.name)
        self.db, self.seed, self.legacy, self.state = t / "fiidii.db", t / "seed.db", t / "legacy", t / "state.json"
        self.state.write_text(json.dumps({"history": {"2026-10-01": {"FII": -9484.22, "DII": 10041.84},
                                                      "2026-10-05": {"FII": -4699.14, "DII": 5181.62}}}))
        patches = {"DB_PATH": self.db, "SEED_PATH": self.seed, "LEGACY_DIR": self.legacy, "REEL_STATE": self.state}
        self.saved = {k: getattr(fiidii, k) for k in patches}
        for k, v in patches.items():
            setattr(fiidii, k, v)

    def tearDown(self):
        for k, v in self.saved.items():
            setattr(fiidii, k, v)
        self.tmp.cleanup()

    def test_nse_rows_upgrade_reel_history_and_publish(self):
        self.assertTrue(fiidii.record_nse(self.FD))
        self.assertFalse(fiidii.record_nse(self.FD))                           # same figures again: no change
        out = fiidii.publish(Path(self.tmp.name) / "fiidii.json")
        self.assertEqual(out["nse"]["rows"], [["2026-10-01", None, None, -9484.22, None, None, 10041.84],
                                              ["2026-10-05", 15674.61, 20373.75, -4699.14, 20492.93, 15311.31, 5181.62]])
        self.assertEqual(json.loads((Path(self.tmp.name) / "fiidii.json").read_text())["nse"]["fields"], fiidii.NSE_FIELDS)

    def test_legacy_json_and_seed_merge_without_losing_nse_days(self):
        self.legacy.mkdir()
        (self.legacy / "nse.json").write_text(json.dumps({"2026-10-02": [1, 2, -1, 3, 1, 2]}))
        (self.legacy / "fpi_2026-09.json").write_text(json.dumps({"2026-09-01": [1, 2, -1, -1, 0, 0, -1]}))
        fiidii.record_nse(self.FD)
        fiidii.write_seed(self.seed)                                           # holds September from the legacy file
        self.db.unlink()                                                       # a fresh server with only the seed
        fiidii.record_nse(self.FD)
        out = fiidii.publish(Path(self.tmp.name) / "fiidii.json")
        self.assertEqual(out["fpi"]["rows"], [["2026-09-01", 1, 2, -1, -1, 0, 0, -1]])
        self.assertEqual([r[0] for r in out["nse"]["rows"]], ["2026-10-01", "2026-10-02", "2026-10-05"])
        with closing(sqlite3.connect(self.seed)) as seed:                      # the seed never carries NSE rows
            self.assertEqual([r[0] for r in seed.execute("SELECT name FROM sqlite_master WHERE type='table'")],
                             ["fpi_daily", "fpi_months"])


if __name__ == "__main__":
    unittest.main()
