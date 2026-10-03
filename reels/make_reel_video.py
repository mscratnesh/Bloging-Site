"""Render madhur-vani-reel.html to MP4 with hi-IN-SwaraNeural narration over the tanpura.

Needs: pip install edge-tts imageio-ffmpeg playwright (drives the installed Microsoft Edge;
no browser download) and an internet connection for the voice and the Google Fonts.
"""
import asyncio, base64, pathlib, subprocess, sys
import edge_tts, imageio_ffmpeg
from playwright.sync_api import sync_playwright

HERE = pathlib.Path(__file__).resolve().parent
HTML = HERE / "madhur-vani-reel.html"
OUT = pathlib.Path(sys.argv[1]) if len(sys.argv) > 1 else HERE / "madhur-vani-reel.mp4"
WORK = HERE / "build"          # voice clips and intermediates (git-ignored)
FF = imageio_ffmpeg.get_ffmpeg_exe()
FPS = 30
VOICE = "hi-IN-SwaraNeural"

# (file, text, speaking rate, start in real seconds)
CLIPS = [
    ("title.mp3", "संत कबीर के दोहे। मधुर वाणी।", "-5%", 0.5),
    ("doha.mp3", "ऐसी वाणी बोलिए, मन का आपा खोय। औरन को शीतल करे, आपहुं शीतल होय।", "-15%", 6.2),
    ("meaning.mp3", "अर्थ। मनुष्य को हमेशा ऐसी मीठी और नम्र भाषा बोलनी चाहिए जो सुनने वाले के मन को शांति दे "
                    "और साथ ही बोलने वाले को भी अंदर से प्रसन्नता और शीतलता का अनुभव हो।", "+0%", 16.9),
]
# Piecewise map: real seconds -> the page's 25 s timeline, so each section lasts as long as its narration
# (title 0-3.6, doha 3.6-12, meaning 12-21, recap 21-25). Change these if the narration changes length.
KNOTS = [(0, 0), (5.6, 3.6), (16.4, 12), (31.8, 21), (36.8, 25)]
DUR = KNOTS[-1][0]


def warp(t):
    for (r0, o0), (r1, o1) in zip(KNOTS, KNOTS[1:]):
        if t <= r1:
            return o0 + (t - r0) / (r1 - r0) * (o1 - o0)
    return KNOTS[-1][1]


async def make_voice():
    for name, text, rate, _ in CLIPS:
        await edge_tts.Communicate(text, VOICE, rate=rate).save(str(WORK / name))


# Renders the page's own tanpura (pluck()) offline for the full length and returns a 16-bit WAV as base64.
TANPURA_JS = """async (D) => {
  const sr = 48000;
  ac = new OfflineAudioContext(2, Math.ceil(sr * D), sr);
  const master = ac.createGain(); master.connect(ac.destination);
  const now = 0.05;
  master.gain.setValueAtTime(0, now);
  master.gain.linearRampToValueAtTime(.55, now + 2);
  master.gain.setValueAtTime(.55, D - 1.5);
  master.gain.linearRampToValueAtTime(0, D);
  const SA = 130.81, strings = [SA * .75, SA, SA, SA / 2];
  for (let i = 0, time = now; time < D; i++, time += .75) pluck(strings[i % 4], time, master);
  const buf = await ac.startRendering(); ac = null;
  const n = buf.length, L = buf.getChannelData(0), R = buf.getChannelData(1);
  const out = new DataView(new ArrayBuffer(44 + n * 4));
  const str = (o, s) => [...s].forEach((c, i) => out.setUint8(o + i, c.charCodeAt(0)));
  str(0, 'RIFF'); out.setUint32(4, 36 + n * 4, true); str(8, 'WAVEfmt ');
  out.setUint32(16, 16, true); out.setUint16(20, 1, true); out.setUint16(22, 2, true);
  out.setUint32(24, sr, true); out.setUint32(28, sr * 4, true); out.setUint16(32, 4, true); out.setUint16(34, 16, true);
  str(36, 'data'); out.setUint32(40, n * 4, true);
  for (let i = 0; i < n; i++) {
    out.setInt16(44 + i * 4, Math.max(-1, Math.min(1, L[i])) * 32767, true);
    out.setInt16(46 + i * 4, Math.max(-1, Math.min(1, R[i])) * 32767, true);
  }
  let s = ''; const b = new Uint8Array(out.buffer);
  for (let i = 0; i < b.length; i += 0x8000) s += String.fromCharCode.apply(null, b.subarray(i, i + 0x8000));
  return btoa(s);
}"""

FRAME_JS = """([real, orig]) => {
  window.__real = real;
  render(orig);
  return cv.toDataURL('image/jpeg', 0.95).split(',')[1];
}"""

WORK.mkdir(exist_ok=True)
asyncio.run(make_voice())

silent = WORK / "video_silent.mp4"
with sync_playwright() as p:
    browser = p.chromium.launch(channel="msedge")
    page = browser.new_page(viewport={"width": 1400, "height": 2000})
    page.goto(HTML.as_uri(), wait_until="networkidle")
    page.evaluate("""() => Promise.all([
      document.fonts.load(`92px ${F_DOHA}`, 'मधुर वाणी'),
      document.fonts.load(`500 58px ${F_BODY}`, 'मधुर वाणी'),
      document.fonts.load(`600 54px ${F_BODY}`, 'मधुर वाणी')])""")
    # Background drift and particles follow real time, not the stretched timeline.
    page.evaluate("() => { const bg = background; background = () => bg(window.__real); }")

    (WORK / "tanpura.wav").write_bytes(base64.b64decode(page.evaluate(TANPURA_JS, DUR)))

    enc = subprocess.Popen([FF, "-y", "-loglevel", "error", "-f", "image2pipe", "-framerate", str(FPS),
                            "-c:v", "mjpeg", "-i", "-", "-vf", "scale=in_range=pc:out_range=tv,format=yuv420p",
                            "-c:v", "libx264", "-preset", "medium", "-crf", "18", "-color_range", "tv",
                            str(silent)], stdin=subprocess.PIPE)
    n = round(DUR * FPS)
    for i in range(n):
        t = i / FPS
        enc.stdin.write(base64.b64decode(page.evaluate(FRAME_JS, [t, warp(t)])))
        if i % 150 == 0:
            print(f"frame {i}/{n}", flush=True)
    enc.stdin.close(); enc.wait()
    browser.close()

inputs = ["-i", str(silent), "-i", str(WORK / "tanpura.wav")]
filters = ["[1:a]volume=0.45[bg]"]
for k, (name, _, _, start) in enumerate(CLIPS):
    inputs += ["-i", str(WORK / name)]
    ms = int(start * 1000)
    filters.append(f"[{k + 2}:a]aresample=48000,volume=1.6,adelay={ms}|{ms}[v{k}]")
mix = "".join(f"[v{k}]" for k in range(len(CLIPS)))
filters.append(f"[bg]{mix}amix=inputs={len(CLIPS) + 1}:normalize=0,alimiter=limit=0.95[a]")
subprocess.run([FF, "-y", "-loglevel", "error", *inputs, "-filter_complex", ";".join(filters),
                "-map", "0:v", "-map", "[a]", "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
                "-t", str(DUR), "-movflags", "+faststart", str(OUT)], check=True)
print("saved", OUT)
