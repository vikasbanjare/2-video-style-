"""Measure a finished reference edit, to learn (or check) a style cheaply.

Produces, in <out>/:
  report.md / report.json – cuts & shot lengths, caption timing & position,
                            pauses, loudness, music-bed level
  sheet_NN.jpg            – contact sheets (2 fps, small) to look at
A human or Claude then only needs the short report + 2-3 sheets instead of
watching the whole video, which keeps style learning to a few thousand tokens.
"""
import json
import re
import subprocess
from pathlib import Path

import numpy as np

from .media import probe

GW, GH = 180, 320  # analysis resolution (9:16)


def _gray_frames(path):
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-vf", f"scale={GW}:{GH},format=gray",
                          "-f", "rawvideo", "-"], capture_output=True, check=True).stdout
    return np.frombuffer(raw, np.uint8).reshape(-1, GH, GW).astype(np.int16)


def _text_mask(frames):
    """Bright pixels with a sharp horizontal edge next to them: caption strokes,
    not bright skies, skin or lights."""
    bright = frames > 225
    edge = np.zeros_like(bright)
    edge[:, :, 1:] = np.abs(np.diff(frames, axis=2)) > 70
    edge[:, :, :-1] |= edge[:, :, 1:]
    return bright & edge


def _caption_band(frames):
    """Rows where captions sit: text-like pixels present most of the time AND
    changing often (captions swap every second or so). None if no captions."""
    text = _text_mask(frames)
    row_frac = text.mean(axis=2)
    active = ((row_frac > 0.01) & (row_frac < 0.5)).mean(axis=0)
    rows = np.where(active > 0.3)[0]
    if len(rows) < 3:
        return None
    runs = [r for r in np.split(rows, np.where(np.diff(rows) > 8)[0] + 1) if len(r) >= 3]  # keep 2-line blocks together
    if not runs:
        return None
    change = lambda r: (text[1:, r[0]:r[-1] + 1] ^ text[:-1, r[0]:r[-1] + 1]).mean()
    r = max(runs, key=change)
    if len(r) > GH * 0.35:  # a "band" covering a third of the frame is background, not captions
        return None
    return int(r[0]), int(r[-1]) + 1


def _cuts(frames, fps, band):
    m = np.ones((GH, GW), bool)
    if band:
        m[max(0, band[0] - 4):band[1] + 4, :] = False
    if len(frames) < 8:
        return []
    d = np.array([np.abs(frames[i] - frames[i - 1])[m].mean() for i in range(1, len(frames))])
    cuts = []
    for i in range(3, len(d) - 3):
        local = np.median(np.r_[d[i - 3:i], d[i + 1:i + 4]])
        if d[i] > 3 * max(local, 0.5) and d[i] > 4 and (not cuts or (i + 1) / fps - cuts[-1] > 0.3):
            cuts.append(round((i + 1) / fps, 2))
    return cuts


def _caption_events(frames, fps, band):
    if not band:
        return []
    w = _text_mask(frames[:, band[0]:band[1], :])
    ev = [0]
    for i in range(1, len(w)):
        if (w[i] ^ w[i - 1]).sum() > max(40, w[i].sum() * 0.25) and i - ev[-1] > 2:
            ev.append(i)
    ev.append(len(w))
    out = []
    for a, b in zip(ev, ev[1:]):
        f = w[min(a + 2, len(w) - 1)]
        rows = np.where(f.sum(1) > 1)[0]
        lines = 0 if len(rows) == 0 else 1 + int((np.diff(rows) > 2).sum())
        out.append({"t": round(a / fps, 2), "dur": round((b - a) / fps, 2), "lines": lines,
                    "width_pct": round(100 * (np.ptp(np.where(f.any(0))[0]) if f.any() else 0) / GW, 1)})
    return out


def _audio(path):
    r = subprocess.run(["ffmpeg", "-hide_banner", "-i", str(path), "-af", "ebur128", "-f", "null", "-"],
                       capture_output=True, text=True).stderr
    lufs = re.findall(r"I:\s+(-?[\d.]+) LUFS", r)
    lra = re.findall(r"LRA:\s+([\d.]+) LU", r)
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-ac", "1", "-ar", "16000", "-f", "f32le", "-"],
                         capture_output=True).stdout
    x = np.frombuffer(raw, np.float32)
    if not len(x):
        return {}
    win = 320
    n = len(x) // win
    e = 20 * np.log10(np.sqrt((x[:n * win].reshape(n, win) ** 2).mean(1)) + 1e-9)
    quiet = e < np.percentile(e, 50) - 15
    runs, c = [], 0
    for q in quiet:
        if q:
            c += 1
        elif c:
            runs.append(c * 0.02)
            c = 0
    runs = np.array(runs or [0])
    return {"lufs": float(lufs[-1]) if lufs else None, "lra": float(lra[-1]) if lra else None,
            "speech_db_p50": round(float(np.percentile(e, 50)), 1),
            "floor_db_p5": round(float(np.percentile(e, 5)), 1),
            "bed_below_speech_db": round(float(np.percentile(e, 50) - np.percentile(e, 5)), 1),
            "pauses_over_0.3s": int((runs > 0.3).sum()), "longest_pause": round(float(runs.max()), 2)}


def analyze(video, out):
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    info = probe(video)
    fps = float(info.fps) or 24
    frames = _gray_frames(video)
    band = _caption_band(frames)
    cuts = _cuts(frames, fps, band)
    caps = _caption_events(frames, fps, band)
    shots = np.diff([0] + cuts + [info.duration]) if info.duration else np.array([])
    shown = [c for c in caps if c["lines"]]
    rep = {
        "file": str(video), "duration": round(info.duration, 2), "size": f"{info.width}x{info.height}",
        "fps": round(fps, 3),
        "cuts": cuts, "cuts_per_10s": round(10 * len(cuts) / max(info.duration, 1), 2),
        "shot_len": {"median": round(float(np.median(shots)), 2) if len(shots) else None,
                     "min": round(float(shots.min()), 2) if len(shots) else None,
                     "max": round(float(shots.max()), 2) if len(shots) else None},
        "captions": None if not band else {
            "band_y_pct": [round(100 * band[0] / GH, 1), round(100 * band[1] / GH, 1)],
            "changes": len(shown),
            "dur_median": round(float(np.median([c["dur"] for c in shown])), 2) if shown else None,
            "max_lines": max((c["lines"] for c in shown), default=0),
            "max_width_pct": max((c["width_pct"] for c in shown), default=0),
            "events": caps},
        "audio": _audio(video),
    }
    (out / "report.json").write_text(json.dumps(rep, indent=1))
    c = rep["captions"]
    md = [f"# Analysis: {Path(video).name}", "",
          f"- {rep['size']} @ {rep['fps']} fps, {rep['duration']} s",
          f"- cuts: {len(cuts)} ({rep['cuts_per_10s']}/10 s), shot length median {rep['shot_len']['median']} s "
          f"(min {rep['shot_len']['min']}, max {rep['shot_len']['max']})",
          f"- cut times: {', '.join(map(str, cuts)) or 'none'}",
          (f"- captions: band {c['band_y_pct'][0]}–{c['band_y_pct'][1]} % from top, {c['changes']} changes, "
           f"median {c['dur_median']} s on screen, up to {c['max_lines']} lines, {c['max_width_pct']} % wide")
          if c else "- captions: none detected",
          f"- audio: {rep['audio'].get('lufs')} LUFS (LRA {rep['audio'].get('lra')}), floor "
          f"{rep['audio'].get('bed_below_speech_db')} dB under speech, "
          f"{rep['audio'].get('pauses_over_0.3s')} pauses > 0.3 s (longest {rep['audio'].get('longest_pause')} s)",
          "", "Contact sheets: sheet_01.jpg ... (2 fps, left→right, top→bottom)"]
    (out / "report.md").write_text("\n".join(md) + "\n")
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(video), "-vf", "fps=2,scale=180:-2,tile=6x6",
                    "-q:v", "5", str(out / "sheet_%02d.jpg")], check=True)
    return rep
