"""Learn a style from several reference videos at once.

  python -m autoedit learn https://www.instagram.com/<profile>/ --count 5 --name style-02
  python -m autoedit learn ref1.mp4 ref2.mp4 ...

URLs are downloaded with yt-dlp (profile = latest --count posts; Instagram
usually needs `--cookies cookies.txt` from a logged-in browser). Every video
goes through `analyze` (frame-by-frame measurements + contact sheets), then
summary.md lists each video and the median / range of every rule, which is
what goes into styles/<id>/style.json. Reading summary.md + a few sheets is a
few thousand tokens for a whole account.
"""
import json
import statistics
import subprocess
import sys
from pathlib import Path

from .analyze import analyze

VIDEO_EXT = {".mp4", ".mov", ".m4v", ".webm", ".mkv"}


def download(url, dest, count, cookies=None):
    dest.mkdir(parents=True, exist_ok=True)
    cmd = [sys.executable, "-m", "yt_dlp", "--no-progress", "-q", "--playlist-items", f"1:{count}",
           "-f", "mp4/best", "-o", str(dest / "%(uploader_id)s_%(id)s.%(ext)s"), url]
    if cookies:
        cmd[3:3] = ["--cookies", str(cookies)]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode:
        raise RuntimeError(f"download failed for {url}: {(r.stderr or r.stdout).strip()[-400:]}")
    return sorted(p for p in dest.iterdir() if p.suffix.lower() in VIDEO_EXT)


def _stat(values):
    v = [x for x in values if x is not None]
    if not v:
        return None
    v = [float(x) for x in v]
    return {"median": round(statistics.median(v), 2), "min": round(min(v), 2), "max": round(max(v), 2)}


def summarize(reports):
    caps = [r["captions"] for r in reports if r.get("captions")]
    return {
        "videos": len(reports),
        "duration_s": _stat([r["duration"] for r in reports]),
        "cuts_per_10s": _stat([r["cuts_per_10s"] for r in reports]),
        "shot_len_median_s": _stat([r["shot_len"]["median"] for r in reports]),
        "videos_with_captions": len(caps),
        "caption_on_screen_s": _stat([c["dur_median"] for c in caps]),
        "caption_max_lines": _stat([c["max_lines"] for c in caps]),
        "caption_width_pct": _stat([c["max_width_pct"] for c in caps]),
        "caption_band_top_pct": _stat([c["band_y_pct"][0] for c in caps]),
        "caption_positions": sorted({c.get("position", "fixed band") for c in caps}),
        "loudness_lufs": _stat([r["audio"].get("lufs") for r in reports]),
        "music_floor_below_speech_db": _stat([r["audio"].get("bed_below_speech_db") for r in reports]),
    }


def learn(sources, out, count=5, cookies=None, log=print):
    out = Path(out)
    videos = []
    for s in sources:
        if "://" in s:
            got = download(s, out / "videos", count, cookies)
            log(f"downloaded {len(got)} from {s}")
            videos += got
        elif Path(s).is_dir():
            videos += sorted(p for p in Path(s).iterdir() if p.suffix.lower() in VIDEO_EXT)
        else:
            videos.append(Path(s))
    videos = list(dict.fromkeys(videos))
    reports = []
    for n, v in enumerate(videos, 1):
        rep = analyze(v, out / f"{n:02d}_{v.stem}")
        reports.append(rep)
        log(f"[{n}/{len(videos)}] analysed {v.name}")
    summ = summarize(reports)
    (out / "summary.json").write_text(json.dumps({"summary": summ, "reports": reports}, indent=1))
    rows = ["| # | video | s | cuts/10s | shot med | caption s | lines | width % | LUFS |",
            "|---|---|---|---|---|---|---|---|---|"]
    for n, (v, r) in enumerate(zip(videos, reports), 1):
        c = r.get("captions") or {}
        rows.append(f"| {n} | {v.name} | {r['duration']} | {r['cuts_per_10s']} | {r['shot_len']['median']} | "
                    f"{c.get('dur_median', '-')} | {c.get('max_lines', '-')} | {c.get('max_width_pct', '-')} | "
                    f"{r['audio'].get('lufs')} |")
    agg = [f"- **{k}**: {v}" for k, v in summ.items()]
    (out / "summary.md").write_text("# Style learning summary\n\n" + "\n".join(rows) + "\n\n## Across all videos\n\n"
                                    + "\n".join(agg) + "\n\nPer-video folders hold report.md and contact sheets.\n")
    return summ
