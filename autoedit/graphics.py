"""Count-up number graphics (Style 02): when a big number is said, cut to a
clean light frame where the number counts up from 0 with an ease-out, with the
words that follow it as a small label ("29,000" / "affiliates").

Rendered by ffmpeg + libass into an .mp4 that sits on the b-roll track like
any other clip, so it imports into Premiere with no plugins.
"""
import re
import subprocess
from pathlib import Path

NUM = re.compile(r"^(\$?)(\d[\d,]*(?:\.\d+)?)([kKmMbB%]?)$")
SCALE = {"k": 1e3, "m": 1e6, "b": 1e9}


def parse_number(token):
    """'29,000' -> (29000, '', '', True); '$100k' -> (100000, '$', 'k', False)."""
    m = NUM.match(token.strip(".,!?;:\"'"))
    if not m:
        return None
    pre, digits, suf = m.groups()
    value = float(digits.replace(",", ""))
    return value * SCALE.get(suf.lower(), 1), pre, suf, "," in digits


def fmt(v, pre, suf, commas):
    if suf.lower() in SCALE:
        v = v / SCALE[suf.lower()]
        body = f"{v:,.0f}" if commas else f"{v:.0f}"
    else:
        body = f"{v:,.0f}" if (commas or v >= 10000) else f"{v:.0f}"
    return f"{pre}{body}{suf}"


def _t(t):
    cs = int(round(t * 100))
    return f"{cs // 360000}:{cs // 6000 % 60:02d}:{cs // 100 % 60:02d}.{cs % 100:02d}"


def make_counter(token, label, duration, out, W=1080, H=1920, fps=30, gcfg=None):
    gcfg = gcfg or {}
    out = Path(out)
    if out.exists():
        return out
    out.parent.mkdir(parents=True, exist_ok=True)
    value, pre, suf, commas = parse_number(token)
    count = min(duration * gcfg.get("count_share", 0.6), gcfg.get("count_max", 1.6))
    num_size = int(W * gcfg.get("number_size_pct", 16) / 100)
    lab_size = int(num_size * 0.3)
    y = H * gcfg.get("number_y_pct", 50) / 100
    font = gcfg.get("font", "Inter")
    head = (f"[Script Info]\nPlayResX: {W}\nPlayResY: {H}\n\n[V4+ Styles]\n"
            "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, "
            "Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, "
            "MarginR, MarginV, Encoding\n"
            f"Style: N,{font},{num_size},&H001A1A1A,&H0,&H0,&H0,-1,0,0,0,100,100,-2,0,1,0,0,5,0,0,0,1\n"
            f"Style: L,{font},{lab_size},&H00555555,&H0,&H0,&H0,0,0,0,0,100,100,-1,0,1,0,0,8,0,0,0,1\n\n"
            "[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n")
    ev, n = [], int(round(duration * fps))
    for f in range(n):
        t = f / fps
        p = min(1.0, t / count) if count else 1.0
        v = value * (1 - (1 - p) ** 3)                 # ease-out cubic
        ev.append(f"Dialogue: 0,{_t(t)},{_t(t + 1 / fps)},N,,0,0,0,,{{\\pos({W / 2:.0f},{y:.0f})}}{fmt(v, pre, suf, commas)}")
    if label:
        ev.append(f"Dialogue: 0,{_t(count * 0.7)},{_t(duration)},L,,0,0,0,,"
                  f"{{\\pos({W / 2:.0f},{y + num_size * 0.62:.0f})\\fad(150,0)}}{label}")
    ass = out.with_suffix(".ass")
    ass.write_text(head + "\n".join(ev) + "\n", encoding="utf-8")
    bg = gcfg.get("background", "0xF7F7F7")
    esc = ass.as_posix().replace(":", "\\:").replace("'", "\\'")
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", f"color=c={bg}:s={W}x{H}:r={fps}:d={duration:.3f}",
                    "-vf", f"vignette=PI/12,ass='{esc}'", "-c:v", "libx264", "-preset", "veryfast", "-crf", "18",
                    "-pix_fmt", "yuv420p", str(out)], check=True)
    ass.unlink(missing_ok=True)
    return out
