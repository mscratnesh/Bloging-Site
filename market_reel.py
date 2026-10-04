"""Daily 2-minute market data reel, built and posted to Instagram by the site server itself.

Scenes (English, music only): FII/DII cash flows, FII/DII trend (once 3+ days are saved), index futures
long/short by participant, NIFTY/BANKNIFTY F&O, OI change across all F&O stocks, the four buildups,
and a disclaimer outro. Each scene is drawn once with Pillow; ffmpeg joins them with crossfades and
adds the background music. Everything happens in a temporary folder that is deleted afterwards, so
nothing but two small files sits next to the server:

  instagram.env            INSTAGRAM_USER_ID and INSTAGRAM_TOKEN (you create it; posting is off without it)
  market_reel_state.json   saved FII/DII history and the dates already posted

Data: NSE's provisional FII/DII figures, the participant-wise OI file and the F&O bhavcopy (through
app.fetch_oi_change). The brand background, music, fonts and an ffmpeg binary are bundled into the
executable (see LetMoneyEarn.spec); from source they come from market-reel/assets and imageio-ffmpeg.

Test from source:  python market_reel.py --force --no-post --out preview.mp4
"""
import csv, http.cookiejar, json, subprocess, sys, tempfile, time, urllib.error, urllib.parse, urllib.request, uuid
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

IST = timezone(timedelta(hours=5, minutes=30))
W, H = 1080, 1920
TARGET = 120                     # seconds
XFADE = 0.5                      # crossfade between scenes
MIN_D = {"intro": 5, "fiidii": 18, "trend": 12, "participants": 18, "indices": 20, "oisummary": 20, "buildup": 22, "outro": 7}
MONTHS = "Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec".split()
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126 Safari/537.36",
      "Accept": "application/json,text/html,*/*", "Accept-Language": "en-US,en;q=0.9"}
GRAPH = "https://graph.instagram.com/v21.0"
UPLOAD_URL = "https://uguu.se/upload"
WHATSAPP = "https://chat.whatsapp.com/FP1WNN227pPGTvGQ1sYbmW"
HASHTAGS = "#FII #DII #Nifty #OpenInterest #StockMarketIndia"      # Instagram allows at most 5
KINDS = (("Long buildup", "Long Buildup", (True, True), (110, 224, 138)),
         ("Short covering", "Short Covering", (True, False), (184, 224, 122)),
         ("Short buildup", "Short Buildup", (False, True), (255, 123, 107)),
         ("Long unwinding", "Long Unwinding", (False, False), (240, 179, 106)))
DISCLAIMER = [
    "This video is for educational and information purposes only. It is not investment or trading advice.",
    "Figures are from public NSE data (provisional) and may be revised.",
    "Stock names are shown only as data, not as a recommendation to buy or sell. F&O trading carries a high risk of loss.",
    "Ratnesh Kumar Singh — NISM certified Mutual Fund Distributor (AMFI ARN-132137). Not a SEBI-registered Research Analyst.",
    "Consult your financial adviser before investing.",
]

CREAM, GOLD, MUTED, GREEN, RED = (255, 248, 230), (245, 192, 74), (200, 214, 200), (110, 224, 138), (255, 123, 107)


def asset_dir():
    if getattr(sys, "frozen", False):
        return Path(sys._MEIPASS) / "market_reel_assets"
    return Path(__file__).resolve().parent / "market-reel" / "assets"


def ffmpeg_exe():
    bundled = sorted(asset_dir().glob("ffmpeg*.exe"))
    if bundled:
        return str(bundled[0])
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except ImportError:
        return "ffmpeg"


# ---- data -----------------------------------------------------------------
def fetch_fiidii():
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
    headers = dict(UA, Referer="https://www.nseindia.com/reports/fii-dii")
    opener.open(urllib.request.Request("https://www.nseindia.com/reports/fii-dii", headers=headers), timeout=30).read()
    rows = json.loads(opener.open(urllib.request.Request("https://www.nseindia.com/api/fiidiiTradeReact", headers=headers), timeout=30).read())
    out = {}
    for r in rows:
        out["FII" if r["category"].startswith("FII") else "DII"] = {k: float(r[k + "Value"]) for k in ("buy", "sell", "net")}
        out["date"] = datetime.strptime(r["date"], "%d-%b-%Y").date()
    return out


def participant_oi(day):
    url = f"https://nsearchives.nseindia.com/content/nsccl/fao_participant_oi_{day:%d%m%Y}.csv"
    try:
        text = urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=30).read().decode("utf-8-sig")
    except OSError:
        return None
    out = {}
    for r in csv.DictReader(text.splitlines()[1:]):          # first line is a title
        r = {k.strip(): v for k, v in r.items() if k}
        name = (r.get("Client Type") or "").strip()
        if name in ("Client", "DII", "FII", "Pro"):
            out[name] = (float(r["Future Index Long"]), float(r["Future Index Short"]))
    return out or None


def collect(fd, parts, prev, oi, history):
    day = fd["date"]
    last = sorted(history.items())[-5:]
    participants = []
    for name in ("FII", "DII", "Pro", "Client"):
        lo, sh = parts[name]
        chg = (lo - sh) - (prev[name][0] - prev[name][1]) if prev and name in prev else None
        participants.append({"name": name, "long": lo, "short": sh, "netChg": chg})
    rows = oi.get("rows", [])
    keep = ("symbol", "price", "priceChgPct", "futOiChgPct", "pcr", "buildup", "ceOiChg", "peOiChg")
    indices = sorted(({k: r.get(k) for k in keep} for r in rows if r["symbol"] in ("NIFTY", "BANKNIFTY")),
                     key=lambda r: r["symbol"] != "NIFTY")
    stocks = [r for r in rows if not r["index"] and r.get("futOiChgPct") is not None and r.get("priceChgPct") is not None]
    # rank by the rupee value of OI added or cut, so a thinly held stock with a big % jump does not crowd the list
    value = lambda r: r["futOiChg"] * (r["price"] or 0)
    brief = lambda rs: [{k: r[k] for k in ("symbol", "priceChgPct", "futOiChgPct")} for r in rs]
    return {
        "date": day.isoformat(), "dateEn": f"{day.day} {MONTHS[day.month - 1]} {day.year}",
        "fiidii": {"FII": fd["FII"], "DII": fd["DII"]},
        "history": [{"label": f"{date.fromisoformat(d).day} {MONTHS[date.fromisoformat(d).month - 1]}", **v} for d, v in last]
                   if len(last) >= 3 else [],
        "participants": participants, "indices": indices,
        "counts": {k: sum(r["buildup"] == k for r in stocks) for k, *_ in KINDS},
        "gainers": brief(sorted((r for r in stocks if r["futOiChg"] > 0), key=lambda r: -value(r))[:3]),
        "losers": brief(sorted((r for r in stocks if r["futOiChg"] < 0), key=value)[:3]),
        "buildups": {k: brief(sorted((r for r in stocks if r["buildup"] == k), key=lambda r: -abs(value(r)))[:3]) for k, *_ in KINDS},
    }


# ---- drawing --------------------------------------------------------------
class Canvas:
    def __init__(self, bg, dim):
        from PIL import Image, ImageDraw, ImageFont
        self.Image, self.ImageDraw, self.ImageFont = Image, ImageDraw, ImageFont
        self.img = bg.copy()
        if dim:
            veil = Image.new("RGBA", (W, H), (4, 32, 15, int(232 * dim)))
            self.img = Image.alpha_composite(self.img, veil)
        self.d = ImageDraw.Draw(self.img)
        self.fonts = {}

    def font(self, size, weight="bold"):
        key = (size, weight)
        if key not in self.fonts:
            name = {"bold": "Mukta-Bold.ttf", "medium": "Mukta-Medium.ttf", "regular": "Mukta-Regular.ttf"}[weight]
            self.fonts[key] = self.ImageFont.truetype(str(asset_dir() / name), size)
        return self.fonts[key]

    def text(self, xy, s, size, fill=CREAM, weight="bold", anchor="ms"):
        self.d.text(xy, s, font=self.font(size, weight), fill=fill, anchor=anchor)

    def width(self, s, size, weight="bold"):
        return self.d.textlength(s, font=self.font(size, weight))

    def box(self, x, y, w, h, r, fill, outline=None):
        """Rounded rectangle; fill may carry alpha (blended onto the frame)."""
        layer = self.Image.new("RGBA", (W, H), (0, 0, 0, 0))
        self.ImageDraw.Draw(layer).rounded_rectangle((x, y, x + w, y + h), radius=r, fill=fill, outline=outline, width=2 if outline else 0)
        self.img.alpha_composite(layer)
        self.d = self.ImageDraw.Draw(self.img)

    def arrow(self, x, y, up, size, fill):
        """Small triangle centred on x, with its base on baseline y (Mukta has no arrow glyphs)."""
        s = size * .3
        pts = [(x - s, y - s * .2), (x + s, y - s * .2), (x, y - s * 1.9)] if up else [(x - s, y - s * 1.9), (x + s, y - s * 1.9), (x, y - s * .2)]
        self.d.polygon(pts, fill=fill)

    def rule(self, x, y, up_price, up_oi, size, fill=MUTED):
        """'Price ▲  OI ▲' with drawn arrows, left-aligned at x."""
        for label, up in (("Price", up_price), ("OI", up_oi)):
            self.text((x, y), label, size, fill, "medium", "ls")
            x += self.width(label, size, "medium") + size * .45
            self.arrow(x, y, up, size, fill)
            x += size * 1.1

    def wrap(self, s, size, max_w, weight="medium"):
        lines, line = [], ""
        for word in s.split():
            trial = f"{line} {word}".strip()
            if line and self.width(trial, size, weight) > max_w:
                lines.append(line); line = word
            else:
                line = trial
        return lines + ([line] if line else [])


def crore(v):
    return f"₹{abs(v):,.0f} Cr"


def signed(v):
    return ("+" if v > 0 else "−" if v < 0 else "") + crore(v)


def pct(v, dp=2):
    return "—" if v is None else ("+" if v > 0 else "−" if v < 0 else "") + f"{abs(v):.{dp}f}%"


def tone(v):
    return GREEN if (v or 0) > 0 else RED if (v or 0) < 0 else CREAM


def header(c, D):
    c.text((W / 2, 190), f"Market Data  •  {D['dateEn']}", 40, GOLD)
    c.text((W / 2, 250), "FII / DII  •  F&O Open Interest", 34, MUTED, "medium")


def footer(c):
    c.box(W / 2 - 330, 1712, 660, 132, 28, (0, 0, 0, 90))
    c.text((W / 2, 1772), "letmoneyearn.in", 48, GOLD)
    c.text((W / 2, 1822), "Information only • Not investment advice • Source: NSE", 28, CREAM, "medium")


def pill(c, label, y=470):
    w = c.width(label, 46) + 80
    c.box(W / 2 - w / 2, y - 50, w, 76, 38, GOLD + (255,))
    c.text((W / 2, y + 2), label, 46, (42, 29, 0))


def bar(c, x, y, w, h, frac, color):
    c.box(x, y, w, h, h // 2, CREAM + (56,))
    c.box(x, y, max(h, w * max(0, min(1, frac))), h, h // 2, color + (255,))


def card(c, x, y, w, h):
    c.box(x, y, w, h, 28, (255, 255, 255, 18), outline=(245, 192, 74, 90))


def scene_intro(c, D):
    c.text((W / 2, 210), "Daily Market Data", 54, CREAM)
    c.text((W / 2, 300), D["dateEn"], 62, GOLD)
    label = "FII  •  DII  •  OI Change"
    w = c.width(label, 62) + 100
    c.box(W / 2 - w / 2, 1270, w, 100, 50, (6, 48, 22, 230))
    c.text((W / 2, 1342), label, 62, GOLD)


def scene_fiidii(c, D):
    header(c, D); pill(c, "Cash Market: FII vs DII")
    rows = [("FII / FPI", "Foreign investors", D["fiidii"]["FII"]), ("DII", "Domestic institutions", D["fiidii"]["DII"])]
    top = max(v for r in rows for v in (r[2]["buy"], r[2]["sell"]))
    for i, (name, sub, v) in enumerate(rows):
        y0 = 590 + i * 520
        card(c, 90, y0, 900, 470)
        c.text((140, y0 + 80), name, 52, CREAM, "bold", "ls")
        c.text((140, y0 + 130), sub, 34, MUTED, "medium", "ls")
        c.text((940, y0 + 72), "Net", 30, MUTED, "medium", "rs")
        c.text((940, y0 + 136), signed(v["net"]), 64, tone(v["net"]), "bold", "rs")
        for j, (lbl, val, col) in enumerate((("Buy", v["buy"], GREEN), ("Sell", v["sell"], RED))):
            y = y0 + 230 + j * 110
            c.text((140, y), lbl, 36, CREAM, "medium", "ls")
            c.text((940, y), crore(val), 38, col, "bold", "rs")
            bar(c, 140, y + 22, 800, 22, val / top, col)


def scene_trend(c, D):
    hist = D["history"]
    header(c, D); pill(c, f"Last {len(hist)} sessions: Net (₹ Cr)")
    top = max(max(abs(h["FII"]), abs(h["DII"])) for h in hist) or 1
    x0, w, mid, hmax = 120, 840, 1100, 380
    col_w = w / len(hist)
    c.d.line((x0, mid, x0 + w, mid), fill=MUTED, width=2)
    for i, h in enumerate(hist):
        cx = x0 + col_w * i + col_w / 2
        for key, off, col in (("FII", -.2, RED), ("DII", .2, GREEN)):
            bh, bw = abs(h[key]) / top * hmax, col_w * .3
            y = mid - bh if h[key] >= 0 else mid
            c.box(cx + off * col_w - bw / 2, y, bw, max(bh, 3), 8, col + (240,))
        c.text((cx, mid + hmax + 80), h["label"], 30, MUTED, "medium")
    c.text((300, 1620), "FII", 38, RED); c.text((780, 1620), "DII", 38, GREEN)
    total = lambda k: sum(h[k] for h in hist)
    c.text((W / 2, 1680), f"Total: FII {signed(total('FII'))}   •   DII {signed(total('DII'))}", 34, CREAM, "medium")


def scene_participants(c, D):
    header(c, D); pill(c, "Index Futures: Who Is Long, Who Is Short")
    c.text((W / 2, 580), "Share of long positions in each group (contracts)", 34, MUTED, "medium")
    for i, p in enumerate(D["participants"]):
        y = 700 + i * 230
        long_pct = p["long"] / (p["long"] + p["short"]) * 100
        c.text((120, y), p["name"], 50, CREAM, "bold", "ls")
        c.text((960, y), f"Long {long_pct:.0f}%  •  Short {100 - long_pct:.0f}%", 38, CREAM, "medium", "rs")
        c.box(120, y + 30, 840, 40, 20, RED + (255,))
        c.box(120, y + 30, max(40, 840 * long_pct / 100), 40, 20, GREEN + (255,))
        if p["netChg"] is not None:
            chg = p["netChg"]
            c.text((120, y + 120), f"Net position change: {'+' if chg > 0 else '−' if chg < 0 else ''}{abs(chg):,.0f} contracts",
                   32, tone(chg), "medium", "ls")


def scene_indices(c, D):
    header(c, D); pill(c, "NIFTY & BANKNIFTY: F&O")
    for i, x in enumerate(D["indices"]):
        y0 = 580 + i * 540
        card(c, 90, y0, 900, 500)
        c.text((140, y0 + 85), x["symbol"], 56, CREAM, "bold", "ls")
        c.text((940, y0 + 85), f"{x['price']:,.0f}" if x.get("price") else "—", 50, CREAM, "bold", "rs")
        c.text((940, y0 + 140), pct(x["priceChgPct"]), 40, tone(x["priceChgPct"]), "bold", "rs")
        kind = next((k for k in KINDS if k[0] == x.get("buildup")), None)
        if kind:
            tag, col = kind[1], kind[3]
            tw = c.width(tag, 40) + 50
            c.box(140, y0 + 120, tw, 64, 32, col + (46,))
            c.text((140 + tw / 2, y0 + 166), tag, 40, col)
        for j, (label, val, col) in enumerate((("Futures OI change", pct(x.get("futOiChgPct")), tone(x.get("futOiChgPct"))),
                                               ("Put-Call Ratio (PCR)", "—" if x.get("pcr") is None else f"{x['pcr']:.2f}", GOLD))):
            y = y0 + 270 + j * 70
            c.text((140, y), label, 36, MUTED, "medium", "ls"); c.text((940, y), val, 42, col, "bold", "rs")
        lakh = lambda v: f"{'+' if (v or 0) >= 0 else '−'}{abs(v or 0) / 1e5:.1f} lakh"
        c.text((W / 2, y0 + 450), f"Call OI {lakh(x.get('ceOiChg'))}  •  Put OI {lakh(x.get('peOiChg'))}", 32, CREAM, "medium")


def stock_row(c, x0, y, s, right, right_col):
    c.box(x0, y - 60, 440, 100, 18, (255, 248, 230, 24))
    c.text((x0 + 24, y), s["symbol"], 36, CREAM, "bold", "ls")
    c.text((x0 + 416, y), right, 34, right_col, "bold", "rs")
    c.text((x0 + 24, y + 30), f"Price {pct(s['priceChgPct'])}", 26, tone(s["priceChgPct"]), "medium", "ls")


def scene_oisummary(c, D):
    header(c, D); pill(c, "OI Change: The Whole F&O Market")
    total = sum(D["counts"].values()) or 1
    c.text((W / 2, 580), f"Futures OI trend across {total} F&O stocks", 34, MUTED, "medium")
    for i, (key, name, (pu, ou), col) in enumerate(KINDS):
        x, y = 90 + (i % 2) * 460, 620 + (i // 2) * 230
        card(c, x, y, 440, 200)
        c.text((x + 30, y + 60), name, 38, col, "bold", "ls")
        c.rule(x + 30, y + 105, pu, ou, 30)
        n = D["counts"][key]
        c.text((x + 410, y + 170), str(n), 64, CREAM, "bold", "rs")
        c.text((x + 30, y + 170), f"{round(n / total * 100)}%", 34, col, "bold", "ls")
    for g, (title, lst, col) in enumerate((("Biggest OI addition", D["gainers"], GOLD), ("Biggest OI reduction", D["losers"], (159, 211, 255)))):
        x0 = 90 + g * 460
        c.text((x0 + 220, 1150), title, 36, col)
        for i, s in enumerate(lst):
            stock_row(c, x0, 1240 + i * 120, s, pct(s["futOiChgPct"], 1), col)
    c.text((W / 2, 1640), "OI = open futures contracts • Ranked by ₹ value of OI added/cut", 28, MUTED, "medium")


def scene_buildup(c, D):
    header(c, D); pill(c, "Stock Futures: All Four Buildups")
    for g, (key, name, (pu, ou), col) in enumerate(KINDS):
        x0, y0 = 90 + (g % 2) * 460, 560 + (g // 2) * 540
        c.text((x0 + 10, y0 + 40), name, 38, col, "bold", "ls")
        c.rule(x0 + 10, y0 + 82, pu, ou, 28)
        lst = D["buildups"].get(key) or []
        if not lst:
            c.text((x0 + 220, y0 + 200), "—", 36, MUTED, "medium")
        for i, s in enumerate(lst):
            stock_row(c, x0, y0 + 170 + i * 120, s, f"OI {pct(s['futOiChgPct'], 1)}", GOLD)
    c.text((W / 2, 1660), "Data only — not a recommendation on any stock", 32, MUTED, "medium")


def scene_outro(c, D):
    c.text((W / 2, 230), "Daily Market Data", 50, CREAM)
    c.text((W / 2, 320), "letmoneyearn.in", 76, GOLD)
    paras = [c.wrap(p, 33, W - 220) for p in DISCLAIMER]
    h = 130 + sum(len(ls) * 46 + 16 for ls in paras) + 20
    y0 = 1840 - h
    c.box(70, y0, W - 140, h, 28, (255, 253, 246, 242))
    c.text((W / 2, y0 + 70), "Disclaimer", 46, (155, 28, 28))
    y = y0 + 140
    for ls in paras:
        for line in ls:
            c.text((W / 2, y), line, 33, (31, 51, 38), "medium"); y += 46
        y += 16


SCENES = {"intro": scene_intro, "fiidii": scene_fiidii, "trend": scene_trend, "participants": scene_participants,
          "indices": scene_indices, "oisummary": scene_oisummary, "buildup": scene_buildup, "outro": scene_outro}


def render(D, workdir):
    """Writes one PNG per scene and returns [(path, seconds)]."""
    from PIL import Image
    src = Image.open(asset_dir() / "brand_bg.png").convert("RGBA")
    scale = max(W / src.width, H / src.height) * 1.03
    src = src.resize((round(src.width * scale), round(src.height * scale)), Image.LANCZOS)
    bg = src.crop(((src.width - W) // 2, (src.height - H) // 2, (src.width - W) // 2 + W, (src.height - H) // 2 + H))
    ids = ["intro", "fiidii"] + (["trend"] if D["history"] else []) + ["participants", "indices", "oisummary", "buildup", "outro"]
    durs = [MIN_D[s] for s in ids]
    data_ix = [i for i, s in enumerate(ids) if s not in ("intro", "outro")]
    extra = TARGET + XFADE * (len(ids) - 1) - sum(durs)          # crossfades overlap, so pad for them too
    weight = sum(durs[i] for i in data_ix)
    for i in data_ix:
        durs[i] += max(extra, 0) * durs[i] / weight
    frames = []
    for k, sid in enumerate(ids):
        c = Canvas(bg, 0 if sid == "intro" else .6 if sid == "outro" else 1)
        SCENES[sid](c, D)
        if sid != "outro":
            footer(c)
        path = Path(workdir) / f"scene_{k}_{sid}.png"
        c.img.convert("RGB").save(path)
        frames.append((path, durs[k]))
    return frames


def make_video(frames, out):
    ff = ffmpeg_exe()
    args = [ff, "-y", "-loglevel", "error"]
    for path, d in frames:
        args += ["-loop", "1", "-framerate", "30", "-t", f"{d:.2f}", "-i", str(path)]
    args += ["-stream_loop", "-1", "-i", str(asset_dir() / "bgm.mp3")]
    chains, prev, length = [], "[0:v]", frames[0][1]
    for k in range(1, len(frames)):
        tag = f"[x{k}]"
        chains.append(f"{prev}[{k}:v]xfade=transition=fade:duration={XFADE}:offset={length - XFADE:.2f}{tag}")
        prev, length = tag, length + frames[k][1] - XFADE
    chains.append(f"{prev}fade=t=in:st=0:d=0.6,fade=t=out:st={length - 0.6:.2f}:d=0.6,format=yuv420p[v]")
    chains.append(f"[{len(frames)}:a]aresample=48000,volume=0.5,afade=t=in:d=1.5,afade=t=out:st={length - 2:.2f}:d=2[a]")
    args += ["-filter_complex", ";".join(chains), "-map", "[v]", "-map", "[a]", "-r", "30",
             "-c:v", "libx264", "-preset", "veryfast", "-tune", "stillimage", "-crf", "22",
             "-c:a", "aac", "-b:a", "128k", "-t", f"{length:.2f}", "-movflags", "+faststart", str(out)]
    subprocess.run(args, check=True, timeout=900, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    return length


def caption(D):
    f, d = D["fiidii"]["FII"]["net"], D["fiidii"]["DII"]["net"]
    sign = lambda v: "+" if v >= 0 else "−"
    return "\n".join([
        f"📊 Daily Market Data | {D['dateEn']}",
        f"FII: {sign(f)}₹{abs(f):,.0f} Cr  •  DII: {sign(d)}₹{abs(d):,.0f} Cr (provisional)",
        "NIFTY/BANKNIFTY OI, participant-wise positions, OI change and all four buildups — full data in the reel 👆",
        "",
        "🌐 letmoneyearn.in",
        f"💬 Get the daily market data on WhatsApp: {WHATSAPP}",
        "",
        "Disclaimer: For educational and information purposes only; not investment or trading advice. Data: NSE (provisional). "
        "Ratnesh Kumar Singh — NISM certified MFD (AMFI ARN-132137), not a SEBI-registered RA.",
        "",
        HASHTAGS,
    ])


# ---- Instagram ------------------------------------------------------------
def instagram_config(root):
    path = Path(root) / "instagram.env"
    if not path.is_file():
        return None
    env = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip().strip('"').strip("'")
    user, token = env.get("INSTAGRAM_USER_ID"), env.get("INSTAGRAM_TOKEN")
    return {"user": user, "token": token} if user and token else None


def _upload(mp4):
    """Instagram takes only a public video URL, so the MP4 goes to uguu.se (temporary, ~3 h) first."""
    boundary = uuid.uuid4().hex
    head = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"files[]\"; filename=\"{mp4.name}\"\r\n"
            f"Content-Type: video/mp4\r\n\r\n").encode()
    body = head + mp4.read_bytes() + f"\r\n--{boundary}--\r\n".encode()
    req = urllib.request.Request(UPLOAD_URL, data=body, headers=dict(UA, **{"Content-Type": f"multipart/form-data; boundary={boundary}"}))
    reply = json.loads(urllib.request.urlopen(req, timeout=300).read())
    if not reply.get("success"):
        raise RuntimeError(f"uguu.se upload failed: {str(reply)[:200]}")
    return reply["files"][0]["url"]


def _graph(cfg, path, params=None, post=True):
    params = dict(params or {}, access_token=cfg["token"])
    url = f"{GRAPH}/{path}"
    try:
        if post:
            raw = urllib.request.urlopen(urllib.request.Request(url, data=urllib.parse.urlencode(params).encode()), timeout=60).read()
        else:
            raw = urllib.request.urlopen(f"{url}?{urllib.parse.urlencode(params)}", timeout=60).read()
    except urllib.error.HTTPError as error:
        raise RuntimeError(f"Graph API {path} -> HTTP {error.code}: {error.read()[:500].decode(errors='replace')}") from None
    return json.loads(raw)


def post_reel(cfg, mp4, text):
    """Publishes mp4 as a Reel that also shows in the feed. Returns (media id, permalink)."""
    container = _graph(cfg, f"{cfg['user']}/media", {"media_type": "REELS", "video_url": _upload(mp4),
                                                      "share_to_feed": "true", "caption": text[:2200]})["id"]
    for _ in range(60):                       # video processing usually takes a minute or two
        status = _graph(cfg, container, {"fields": "status_code,status"}, post=False)
        if status.get("status_code") == "FINISHED":
            break
        if status.get("status_code") in ("ERROR", "EXPIRED"):
            raise RuntimeError(f"Instagram could not process the video: {status.get('status')}")
        time.sleep(5)
    else:
        raise RuntimeError("Instagram was still processing the video after 5 minutes.")
    media_id = _graph(cfg, f"{cfg['user']}/media_publish", {"creation_id": container})["id"]
    link = _graph(cfg, media_id, {"fields": "permalink"}, post=False).get("permalink")
    return media_id, link


# ---- daily run --------------------------------------------------------------
def run(root, fetch_oi_change, force=False, post=True, keep=None):
    """Build today's reel and post it. Returns a one-line status. Safe to call repeatedly: it does
    nothing on holidays, before NSE has published, or once the day is posted."""
    root = Path(root)
    state_path = root / "market_reel_state.json"
    state = json.loads(state_path.read_text(encoding="utf-8")) if state_path.exists() else {"history": {}, "posted": {}}
    cfg = instagram_config(root)
    if post and not cfg:
        return "Instagram not set up (instagram.env missing or incomplete); reel not built."
    fd = fetch_fiidii()
    day = fd["date"]
    if day != datetime.now(IST).date() and not force:
        return f"FII/DII data is for {day}, not today; nothing to do."
    if post and day.isoformat() in state["posted"]:
        return f"{day} already posted."
    parts = participant_oi(day)
    oi = fetch_oi_change()
    if not parts or (oi.get("date") != day.isoformat() and not force):
        return f"Participant OI or F&O bhavcopy for {day} not published yet."
    prev = next((p for back in range(1, 8) if (d := day - timedelta(days=back)).weekday() < 5 and (p := participant_oi(d))), None)
    state["history"][day.isoformat()] = {"FII": fd["FII"]["net"], "DII": fd["DII"]["net"]}
    state["history"] = dict(sorted(state["history"].items())[-30:])
    state_path.write_text(json.dumps(state, indent=1), encoding="utf-8")

    D = collect(fd, parts, prev, oi, state["history"])
    with tempfile.TemporaryDirectory(prefix="market_reel_") as work:
        out = Path(work) / f"market-reel-{D['date']}.mp4"
        seconds = make_video(render(D, work), out)
        if keep:
            Path(keep).write_bytes(out.read_bytes())
        if not post:
            return f"Built {seconds:.0f}s reel for {day}" + (f" -> {keep}" if keep else "") + " (not posted)."
        media_id, link = post_reel(cfg, out, caption(D))
    state["posted"][day.isoformat()] = {"media_id": media_id, "permalink": link, "at": datetime.now(IST).isoformat(timespec="seconds")}
    state["posted"] = dict(sorted(state["posted"].items())[-30:])
    state_path.write_text(json.dumps(state, indent=1), encoding="utf-8")
    return f"Posted reel for {day}: {link}"


if __name__ == "__main__":
    import app
    keep = sys.argv[sys.argv.index("--out") + 1] if "--out" in sys.argv else None
    print(run(app.ROOT, app.fetch_oi_change, force="--force" in sys.argv, post="--no-post" not in sys.argv, keep=keep))
