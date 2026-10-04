"""Render doha-001-reel.html to MP4 with hi-IN-SwaraNeural narration over the Let Money Earn music.

Needs: pip install edge-tts imageio-ffmpeg playwright (drives the installed Microsoft Edge;
no browser download) and an internet connection for the voice and the Google Fonts.
Pass --stills to save one PNG per scene instead of the video (quick layout check).
"""
import asyncio, base64, pathlib, re, subprocess, sys
import edge_tts, imageio_ffmpeg
from playwright.sync_api import sync_playwright

HERE = pathlib.Path(__file__).resolve().parent
HTML = HERE / "doha-001-reel.html"
OUT = HERE / "doha-001-reel.mp4"
MUSIC = HERE / "assets" / "bgm.mp3"
WORK = HERE / "build"          # voice clips and intermediates (git-ignored)
FF = imageio_ffmpeg.get_ffmpeg_exe()
FPS = 30
VOICE = "hi-IN-SwaraNeural"
LEAD, TAIL = 0.7, 0.9           # silence before and after each scene's narration

# One clip per scene, in the page's SCENES order: (text, speaking rate, minimum scene length)
# Commas rather than "।" inside a clip: the voice pauses about a second at every full stop.
CLIPS = [
    (None, "", 5),              # title card: music only
    ("धीरे-धीरे रे मना, धीरे सब कुछ होय, माली सींचे सौ घड़ा, ऋतु आए फल होय।", "-12%", 8),
    ("अर्थ, मन को समझाओ, धीरे-धीरे सब कुछ होता है, माली सैकड़ों घड़े पानी डालता है, "
     "पर फल तभी आता है जब ऋतु आती है।", "+8%", 8),
    ("अब निवेशक के लिए, धीरे-धीरे रे निवेशक, धीरे सब कुछ होय, एस आई पी करे सौ मास, ब्याज बढ़त होय।", "-12%", 8),
    ("जैसे माली रोज़ पानी देता है पर फल समय पर आता है, वैसे ही एस आई पी में हर महीने छोटी राशि डालने से "
     "बड़ा कॉर्पस बनता है, पाँच हज़ार रुपये महीने की एस आई पी, बारह प्रतिशत सालाना पर, "
     "दस साल में लगभग साढ़े ग्यारह लाख, बीस साल में लगभग पचास लाख, और तीस साल में एक करोड़ छिहत्तर लाख रुपये बनती है, "
     "कंपाउंडिंग का जादू तभी दिखता है, जब निवेशक धैर्य रखे।", "+10%", 16),
    (None, "", 5),              # outro: logo, URL and disclaimer, music only
]


def clip_seconds(path):
    err = subprocess.run([FF, "-i", str(path)], capture_output=True, text=True).stderr
    h, m, s = re.search(r"Duration: (\d+):(\d+):([\d.]+)", err).groups()
    return int(h) * 3600 + int(m) * 60 + float(s)


async def make_voice():
    for k, (text, rate, _) in enumerate(CLIPS):
        if text:
            await edge_tts.Communicate(text, VOICE, rate=rate).save(str(WORK / f"voice{k}.mp3"))


FRAME_JS = "t => { render(t); return cv.toDataURL('image/jpeg', 0.93).split(',')[1]; }"

WORK.mkdir(exist_ok=True)
stills = "--stills" in sys.argv
if not stills:
    asyncio.run(make_voice())
    lens = [clip_seconds(WORK / f"voice{k}.mp3") if c[0] else -LEAD - TAIL for k, c in enumerate(CLIPS)]
    durs = [round(max(LEAD + n + TAIL, c[2]), 2) for n, c in zip(lens, CLIPS)]
else:
    durs = [c[2] for c in CLIPS]
starts = [sum(durs[:k]) for k in range(len(durs))]

silent = WORK / "doha001_silent.mp4"
with sync_playwright() as p:
    # without the flag the file:// background would taint the canvas and block toDataURL
    browser = p.chromium.launch(channel="msedge", args=["--allow-file-access-from-files"])
    page = browser.new_page(viewport={"width": 1400, "height": 2000})
    page.goto(HTML.as_uri(), wait_until="networkidle")
    page.evaluate("""() => Promise.all([
      setBackground('assets/brand_bg.png'),
      document.fonts.load(`84px ${F_DOHA}`, 'धीरे'),
      document.fonts.load(`500 60px ${F_BODY}`, 'धीरे'),
      document.fonts.load(`700 48px ${F_BODY}`, 'धीरे')])""")
    DUR = page.evaluate("d => setDurations(d)", durs)
    print("scenes", durs, "total", round(DUR, 2))

    if stills:
        for k, s in enumerate(starts):
            t = s + durs[k] * (0.92 if k < len(durs) - 1 else 0.6)
            (WORK / f"still{k}.jpg").write_bytes(base64.b64decode(page.evaluate(FRAME_JS, t)))
        browser.close()
        print("stills in", WORK)
        sys.exit()

    enc = subprocess.Popen([FF, "-y", "-loglevel", "error", "-f", "image2pipe", "-framerate", str(FPS),
                            "-c:v", "mjpeg", "-i", "-", "-vf", "scale=in_range=pc:out_range=tv,format=yuv420p",
                            "-c:v", "libx264", "-preset", "medium", "-crf", "19", "-color_range", "tv",
                            str(silent)], stdin=subprocess.PIPE)
    n = round(DUR * FPS)
    for i in range(n):
        enc.stdin.write(base64.b64decode(page.evaluate(FRAME_JS, i / FPS)))
        if i % 300 == 0:
            print(f"frame {i}/{n}", flush=True)
    enc.stdin.close(); enc.wait()
    browser.close()

inputs = ["-i", str(silent), "-stream_loop", "-1", "-i", str(MUSIC)]
fade = max(DUR - 2, 0)
filters = [f"[1:a]aresample=48000,volume=0.18,afade=t=in:d=1.5,afade=t=out:st={fade:.2f}:d=2[bg]"]
voiced = [k for k, c in enumerate(CLIPS) if c[0]]
for j, k in enumerate(voiced):
    inputs += ["-i", str(WORK / f"voice{k}.mp3")]
    ms = int((starts[k] + LEAD) * 1000)
    filters.append(f"[{j + 2}:a]aresample=48000,volume=1.5,adelay={ms}|{ms}[v{j}]")
mix = "".join(f"[v{j}]" for j in range(len(voiced)))
filters.append(f"[bg]{mix}amix=inputs={len(voiced) + 1}:normalize=0,alimiter=limit=0.95[a]")
subprocess.run([FF, "-y", "-loglevel", "error", *inputs, "-filter_complex", ";".join(filters),
                "-map", "0:v", "-map", "[a]", "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
                "-t", f"{DUR:.2f}", "-movflags", "+faststart", str(OUT)], check=True)
print("saved", OUT)
