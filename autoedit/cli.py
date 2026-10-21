"""Command line entry point.

  python -m autoedit edit  CLIP.mp4 --style style-01-raw-captions [options]
  python -m autoedit batch INBOX/   --style style-02-broll-story  [options]
  python -m autoedit transcript CLIP.mp4      (numbered sentences, for picking a hook)
"""
import argparse
import itertools
import json
import sys
from pathlib import Path

from . import broll as broll_mod
from .captions import build_cues
from .edit_plan import build_plan
from .media import probe
from .srt import srt_to_words, write_srt
from .zoom import apply_zooms

ROOT = Path(__file__).resolve().parent.parent
VIDEO_EXT = {".mp4", ".mov", ".m4v", ".mxf"}
AUDIO_EXT = {".mp3", ".wav", ".m4a", ".aac", ".aif", ".aiff", ".flac"}


def load_style(name):
    p = Path(name)
    if not p.exists():
        p = ROOT / "styles" / name / "style.json"
    return json.loads(p.read_text())


def get_words(video, srt=None, words=None, model="small"):
    if words:
        return json.loads(Path(words).read_text())
    if srt:
        return srt_to_words(srt)
    sib = Path(video).with_suffix(".srt")
    if sib.exists():
        return srt_to_words(sib)
    from .transcribe import load_or_transcribe
    return load_or_transcribe(video, model_size=model)


def first_sentence_end(words, cap=6.0):
    for w in words:
        if w["w"][-1:] in ".?!" and w["e"] <= cap:
            return w["e"]
    return 0.0


def parse_range(s):
    a, b = s.split("-")
    return float(a), float(b)


def edit_one(video, style, args, music_file=None, log=print):
    video = Path(video)
    src = probe(video)
    words = get_words(video, args.srt, args.words, args.model)
    mode = args.mode or ("tight" if style["id"].startswith("style-01") and not (args.srt or video.with_suffix(".srt").exists()) else "none")
    plan = build_plan(words, src.duration, style, mode=mode, hook=parse_range(args.hook) if args.hook else None)
    if mode == "none":
        plan.hook_end = args.hook_end if args.hook_end is not None else first_sentence_end(plan.words)
        for w in plan.words:
            w["hook"] = w["e"] <= plan.hook_end + 0.01
    plan = apply_zooms(plan, style.get("zoom"))

    out = Path(args.out) / video.stem
    out.mkdir(parents=True, exist_ok=True)

    cues = None
    if style["captions"].get("enabled") and not args.no_captions:
        cues = build_cues(plan.words, style["captions"], plan.hook_end,
                          style["hook"].get("caption_mode", "static"), style["hook"].get("gap_after", 0.2))
        write_srt(cues, out / f"{video.stem}_captions.srt")
    elif mode == "none" and (args.srt or video.with_suffix(".srt").exists()):
        # pre-cut job with the client's own SRT: pass it through untouched
        import shutil
        shutil.copy(args.srt or video.with_suffix(".srt"), out / f"{video.stem}_captions.srt")

    placements = []
    if args.broll_plan:
        placements = broll_mod.load_plan(args.broll_plan)
    elif style["broll"].get("enabled") and args.broll_dir:
        lib = broll_mod.load_library(args.broll_dir)
        placements = broll_mod.auto_place(plan.words, plan.duration, lib, style["broll"], plan.hook_end)
    placements = broll_mod.with_media_info(placements)

    title = None
    if args.title_card and plan.hook_end:
        tc = style["title_card"]
        title = (probe(args.title_card), min(tc["fade_in_start"], plan.hook_end / 2), plan.hook_end)

    music = None
    if music_file and style["music"].get("enabled"):
        music = (probe(music_file), style["music"])

    from .xml_export import write_xml
    write_xml(out / f"{video.stem}.xml", f"{video.stem} - {style['name']}", plan, src, style,
              placements, title, music)

    report = {
        "source": str(video.resolve()), "style": style["id"], "mode": mode, "duration": round(plan.duration, 3),
        "hook_end": round(plan.hook_end, 3), "notes": plan.notes,
        "clips": [vars(c) for c in plan.clips],
        "broll": [{k: v for k, v in p.items() if k != "info"} for p in placements],
        "music": str(music_file) if music else None,
        "captions": len(cues or []),
    }
    (out / f"{video.stem}_plan.json").write_text(json.dumps(report, indent=1))

    if args.preview:
        from .preview import render
        render(out / f"{video.stem}_preview.mp4", plan, src, style, cues, placements, title, music, out)
    log(f"[ok] {video.name}: {plan.duration:.1f}s, {len(plan.clips)} clips, {len(placements)} b-roll, "
        f"{len(cues or [])} caption cues -> {out}")
    return report


def cmd_transcript(args):
    words = get_words(args.video, args.srt, args.words, args.model)
    sent, n = [], 1
    for w in words:
        sent.append(w)
        if w["w"][-1:] in ".?!" or w is words[-1]:
            print(f"{n:3d}  {sent[0]['s']:7.2f}-{sent[-1]['e']:7.2f}  {' '.join(x['w'] for x in sent)}")
            sent, n = [], n + 1


def main(argv=None):
    ap = argparse.ArgumentParser(prog="autoedit")
    sub = ap.add_subparsers(dest="cmd", required=True)

    def common(p):
        p.add_argument("--style", default="style-01-raw-captions")
        p.add_argument("--mode", choices=["none", "tight"], help="none = clip is pre-cut, tight = cut pauses/retakes")
        p.add_argument("--srt"), p.add_argument("--words"), p.add_argument("--model", default="small")
        p.add_argument("--hook", help="source range moved to the front, e.g. 41.2-45.9 (tight mode)")
        p.add_argument("--hook-end", type=float, help="pre-cut mode: where the hook ends (default: first sentence)")
        p.add_argument("--title-card", help="transparent full-frame PNG shown during the hook")
        p.add_argument("--music", help="music file (or use --music-dir in batch)")
        p.add_argument("--broll-dir", help="client b-roll library folder")
        p.add_argument("--broll-plan", help="manual b-roll plan JSON")
        p.add_argument("--no-captions", action="store_true")
        p.add_argument("--preview", action="store_true", help="also render an MP4 preview with ffmpeg")
        p.add_argument("--out", default="output")

    p = sub.add_parser("edit"); p.add_argument("video"); common(p)
    p = sub.add_parser("batch"); p.add_argument("folder"); common(p)
    p.add_argument("--music-dir", help="music folder; tracks are rotated across clips")
    p = sub.add_parser("transcript"); p.add_argument("video")
    p.add_argument("--srt"); p.add_argument("--words"); p.add_argument("--model", default="small")
    args = ap.parse_args(argv)

    if args.cmd == "transcript":
        return cmd_transcript(args)
    style = load_style(args.style)
    if args.cmd == "edit":
        edit_one(args.video, style, args, args.music)
        return
    videos = sorted(f for f in Path(args.folder).iterdir() if f.suffix.lower() in VIDEO_EXT)
    tracks = sorted(f for f in Path(args.music_dir).iterdir() if f.suffix.lower() in AUDIO_EXT) if args.music_dir else []
    rotation = itertools.cycle(tracks) if tracks else itertools.repeat(args.music)
    failed = 0
    for v in videos:
        try:
            edit_one(v, style, args, next(rotation))
        except Exception as e:  # keep the batch going; report at the end
            failed += 1
            print(f"[FAILED] {v.name}: {e}", file=sys.stderr)
    print(f"done: {len(videos) - failed}/{len(videos)} clips")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
