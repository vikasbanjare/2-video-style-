"""Placeholder slates for empty b-roll slots: a translucent full-frame PNG
showing the slot id, suggested search words and the spoken phrase, so the gap
is obvious on the timeline and the editor knows what to find."""
import subprocess
import textwrap
from pathlib import Path


def make_slate(slot, out_png, W, H):
    out_png = Path(out_png)
    if out_png.exists():
        return out_png
    out_png.parent.mkdir(parents=True, exist_ok=True)
    txt = out_png.with_suffix(".txt")
    phrase = textwrap.fill(f"\"{slot['phrase']}\"", 30) if slot.get("phrase") else ""
    txt.write_text(f"B-ROLL {slot['id']}\n{slot.get('label', '')}\n\n{phrase}", encoding="utf-8")
    size = int(W * 0.05)
    base = (f"color=c=black@0.55:s={W}x{H},format=rgba,"
            f"drawbox=x=0:y=0:w={W}:h={H}:c=yellow@0.9:t={max(4, W // 120)}")
    text = (f",drawtext=textfile='{txt.as_posix()}':fontcolor=white:fontsize={size}:line_spacing={size // 3}:"
            f"x=(w-text_w)/2:y=(h-text_h)/2")
    for vf in (base + text, base):  # without drawtext if this ffmpeg lacks fonts
        r = subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", vf, "-frames:v", "1", str(out_png)],
                           capture_output=True)
        if r.returncode == 0:
            break
    txt.unlink(missing_ok=True)
    return out_png
