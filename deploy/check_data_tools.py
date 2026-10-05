"""Helper for deploy/setup_data_tools.bat: checks and one-time setup for the market-data tools
(Portfolio Beta stock and fund betas, Mutual Fund Holdings Explorer).

    py deploy/check_data_tools.py imports   # the packages the jobs need can be imported
    py deploy/check_data_tools.py spec      # LetMoneyEarn.spec bundles the Excel readers pandas loads dynamically
    py deploy/check_data_tools.py network   # this machine can reach NSE, AMFI and the fund houses

Exit code 0 = OK, 1 = something needs fixing (the message says what)."""

import importlib
import re
import shutil
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
PACKAGES = ["pandas", "requests", "openpyxl", "xlrd", "PIL", "imageio_ffmpeg", "PyInstaller"]
HIDDEN = ["openpyxl", "xlrd"]
HOSTS = {
    "NSE archives (bhavcopy)": "https://nsearchives.nseindia.com/",
    "NSE website": "https://www.nseindia.com/",
    "AMFI NAV history": "https://portal.amfiindia.com/",
    "SBI MF": "https://www.sbimf.com/",
    "ICICI Prudential MF": "https://www.icicipruamc.com/",
    "ICICI Prudential MF API": "https://apimf.icicipruamc.com/",
    "HDFC MF API": "https://cms.hdfcfund.com/",
    "HDFC MF files": "https://files.hdfcfund.com/",
    "Nippon India MF": "https://mf.nipponindiaim.com/",
    "Aditya Birla Sun Life MF": "https://mutualfund.adityabirlacapital.com/",
    "Axis MF": "https://www.axismf.com/",
    "UTI MF": "https://www.utimf.com/",
    "UTI MF files": "https://d3ce1o48hc5oli.cloudfront.net/",
    "Mirae Asset MF": "https://www.miraeassetmf.co.in/",
    "DSP MF": "https://www.dspim.com/",
    "PPFAS MF": "https://amc.ppfas.com/",
    "Motilal Oswal MF": "https://www.motilaloswalmf.com/",
}


def check_imports():
    bad = []
    for name in PACKAGES:
        try:
            mod = importlib.import_module(name)
            print(f"  OK    {name} {getattr(mod, '__version__', '')}")
        except Exception as e:
            print(f"  MISSING {name}: {type(e).__name__}: {e}")
            bad.append(name)
    return not bad


def patch_spec():
    spec = REPO / "LetMoneyEarn.spec"
    if not spec.is_file():
        print(f"  {spec.name} not found next to app.py. Copy the .spec file here first.")
        return False
    text = spec.read_text(encoding="utf-8")
    m = re.search(r"hiddenimports\s*=\s*\[(.*?)\]", text, re.S)
    if not m:
        print("  Couldn't find hiddenimports=[...] in LetMoneyEarn.spec; add  hiddenimports=['openpyxl', 'xlrd']  to Analysis(...) by hand.")
        return False
    present = set(re.findall(r"['\"]([^'\"]+)['\"]", m.group(1)))
    missing = [h for h in HIDDEN if h not in present]
    if not missing:
        print(f"  LetMoneyEarn.spec already lists {', '.join(HIDDEN)}.")
        return True
    items = sorted(present | set(HIDDEN))
    shutil.copy2(spec, spec.with_suffix(".spec.bak"))
    spec.write_text(text[:m.start()] + "hiddenimports=[" + ", ".join(repr(i) for i in items) + "]" + text[m.end():], encoding="utf-8")
    print(f"  Added {', '.join(missing)} to hiddenimports (backup: LetMoneyEarn.spec.bak).")
    return True


def check_network():
    import requests
    ok = True
    s = requests.Session()
    s.headers["User-Agent"] = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    for label, url in HOSTS.items():
        try:
            r = s.get(url, timeout=20, allow_redirects=True, stream=True)
            r.close()
            # any HTTP answer means the host is reachable; 403/404 on a bare domain is normal for APIs and file hosts
            print(f"  OK    {label:28s} HTTP {r.status_code}")
        except Exception as e:
            print(f"  FAIL  {label:28s} {type(e).__name__}: {str(e)[:90]}")
            ok = False
    if not ok:
        print("  Some hosts can't be reached. Allow outbound HTTPS (port 443) to them in the VM's firewall or proxy.")
    return ok


if __name__ == "__main__":
    step = sys.argv[1] if len(sys.argv) > 1 else ""
    run = {"imports": check_imports, "spec": patch_spec, "network": check_network}.get(step)
    if not run:
        print(__doc__)
        sys.exit(2)
    sys.exit(0 if run() else 1)
