"""Command line entry point.

  python -m autoedit edit  CLIP.mp4 --style ID [options]      one clip
  python -m autoedit batch INBOX/   --style ID [options]      a folder, in parallel, skips finished clips
  python -m autoedit fill  output/CLIP/ [--preview]          rebuild after filling b-roll slots by hand
  python -m autoedit catalog BROLL_DIR                        index the b-roll library (cached)
  python -m autoedit describe BROLL_DIR                       AI-describe new library files once (optional)
  python -m autoedit analyze REF.mp4                          measure a reference edit (style learning)
  python -m autoedit learn URL|FILE... --name ID              download + analyse many references, one summary
  python -m autoedit quote CLIP... --text "..."               Style 01 quote video (one sentence over footage)
  python -m autoedit transcript CLIP.mp4                      numbered sentences, for picking a hook
"""
import argparse
import itertools
import json
import shutil
import sys
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

from . import broll as broll_mod
from .captions import build_chunks, build_cues
from .edit_plan import Clip
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


def _srt_for(video, args):
    p = args.srt or Path(video).with_suffix(".srt")
    return Path(p) if p and Path(p).exists() else None


def hide_during(cues, spans):
    """Drop caption cues mostly inside the spans, trim the ones that overlap an edge."""
    out = []
    for s, e, t in cues:
        for a, b in spans:
            if s < b and e > a:
                if min(e, b) - max(s, a) > 0.5 * (e - s):
                    s = e  # mostly covered: drop
                elif s < a:
                    e = min(e, a)
                else:
                    s = max(s, b)
        if e - s > 0.05:
            out.append((s, e, t))
    return out


def apply_split_screen(plan, splits):
    """Cut V1 at split-screen b-roll edges and move those pieces to the top half."""
    for p in splits:
        a, b = p["start"], p["start"] + p["duration"]
        out = []
        for c in plan.clips:
            edges = sorted({c.rec_in, c.rec_out} | {t for t in (a, b) if c.rec_in < t < c.rec_out})
            for x, y in zip(edges, edges[1:]):
                piece = Clip(c.src_in + x - c.rec_in, c.src_in + y - c.rec_in, x, c.scale, c.pos_y)
                if a - 1e-6 <= x and y <= b + 1e-6:
                    piece.pos_y = -0.25
                out.append(piece)
        plan.clips = out


def edit_one(video, style, args, music_file=None, slots_override=None, log=print):
    video = Path(video).resolve()
    src = probe(video)
    srt = _srt_for(video, args)
    words = get_words(video, srt, args.words, args.model)
    mode = args.mode or ("tight" if style["id"].startswith("style-01") and not srt else "none")
    plan = build_plan(words, src.duration, style, mode=mode, hook=parse_range(args.hook) if args.hook else None)
    if mode == "none":
        plan.hook_end = args.hook_end if args.hook_end is not None else first_sentence_end(plan.words)
        for w in plan.words:
            w["hook"] = w["e"] <= plan.hook_end + 0.01
    plan = apply_zooms(plan, style.get("zoom"))

    out = Path(args.out).resolve() / video.stem
    out.mkdir(parents=True, exist_ok=True)
    W, H = style["sequence"]["width"], style["sequence"]["height"]

    ccfg = style["captions"]
    caption_tracks = []        # [(cues, look)] -> one SRT + one Premiere caption track each
    if ccfg.get("enabled") and not args.no_captions and not (
            srt and mode == "none" and ccfg.get("prefer_client_srt") and not args.restyle_captions):
        if ccfg.get("reveal") == "chunk":
            variant = (style.get("caption_variants") or {}).get(args.caption_variant or style.get("caption_variant"), {})
            look = dict(style["caption_look"], **variant.get("look", {}))
            normal, strong = build_chunks(plan.words, ccfg, variant.get("emphasis", "track"),
                                          variant.get("accent", "#0EB2EE"))
            caption_tracks = [(normal, look)]
            write_srt(normal, out / f"{video.stem}_captions.srt")
            if strong:
                caption_tracks.append((strong, style.get("caption_look_emphasis")))
                write_srt(strong, out / f"{video.stem}_captions_emphasis.srt")
        else:
            cues = build_cues(plan.words, ccfg, plan.hook_end,
                              style["hook"].get("caption_mode", "static"), style["hook"].get("gap_after", 0.2))
            caption_tracks = [(cues, style["caption_look"])]
            write_srt(cues, out / f"{video.stem}_captions.srt")
    elif mode == "none" and srt:
        shutil.copy(srt, out / f"{video.stem}_captions.srt")   # client's SRT, untouched

    # ---- b-roll: where (slots), then what (manual > dropped files > AI > keywords)
    gcfg = style.get("graphics", {})
    if slots_override is not None:
        slots = slots_override
    elif args.broll_plan:
        slots = broll_mod.load_plan(args.broll_plan)
    else:
        counters = broll_mod.plan_counters(plan.words, plan.duration, gcfg, plan.hook_end) if gcfg.get("counters") else []
        slots = counters
        if style["broll"].get("enabled"):
            slots = sorted(counters + broll_mod.plan_slots(plan.words, plan.duration, style["broll"], plan.hook_end,
                                                           reserved=counters), key=lambda s: s["start"])
        hook_layout = style["broll"].get("hook_layout")
        for s in slots:
            if hook_layout and s.get("type") == "broll" and s["start"] < plan.hook_end:
                s["layout"] = hook_layout
    fps = int(round(float(src.fps) or 30))
    for s in slots:   # number graphics are generated, not searched for
        if s.get("type") == "counter" and not s.get("file"):
            from .graphics import make_counter
            s["file"] = str(make_counter(s["number"], s["label"], s["duration"], out / "graphics" / f"{s['id']}.mp4",
                                         W, H, fps, gcfg))
    library = broll_mod.load_library(args.broll_dir) if args.broll_dir else []
    picker = None
    if args.ai and library:
        from .ai import make_picker
        picker = make_picker(args.ai_model)
    (out / "broll").mkdir(exist_ok=True)
    slots = broll_mod.fill_slots(slots, library, out / "broll", picker)
    placements = broll_mod.to_placements(slots, style["broll"].get("fit_wide", True))
    if not args.no_placeholders:
        from .slate import make_slate
        for s in slots:
            if not s.get("file"):
                png = make_slate(s, out / "placeholders" / f"{s['id']}.png", W, H)
                placements.append(dict(s, file=str(png), info=probe(png), still=True, placeholder=True,
                                       layout=s.get("layout") if s.get("layout") == "split" else "full"))
        placements.sort(key=lambda p: p["start"])
    apply_split_screen(plan, [p for p in placements if p.get("layout") == "split"])
    counters = [(s["start"], s["start"] + s["duration"]) for s in slots if s.get("type") == "counter"]
    if counters and caption_tracks:   # the number graphic is the caption: no white text on the light card
        caption_tracks = [(hide_during(cues, counters), look) for cues, look in caption_tracks]
        names = ["_captions.srt", "_captions_emphasis.srt"]
        for (cues, _), name in zip(caption_tracks, names):
            write_srt(cues, out / f"{video.stem}{name}")
    (out / "slots.json").write_text(json.dumps(slots, indent=1))
    (out / ".slots_auto.json").write_text(json.dumps(slots, indent=1))  # lets `fill` spot hand edits

    title = None
    if args.title_card:
        tc = style["title_card"]
        if args.title_at:
            title = (probe(args.title_card), *parse_range(args.title_at))
        elif tc.get("at") == "after_hook":   # name tag on the guest's first shot
            a = plan.hook_end
            title = (probe(args.title_card), a, min(plan.duration, a + tc.get("duration", 1.5)))
        elif plan.hook_end:
            title = (probe(args.title_card), min(tc["fade_in_start"], plan.hook_end / 2), plan.hook_end)

    music = None
    if music_file and style["music"].get("enabled"):
        music = (probe(music_file), style["music"])

    from .xml_export import write_xml
    write_xml(out / f"{video.stem}.xml", f"{video.stem} - {style['name']}", plan, src, style,
              placements, title, music, slots)
    cues = [c for track, _ in caption_tracks for c in track]

    filled = sum(1 for s in slots if s.get("file"))
    saved_args = {k: v for k, v in vars(args).items() if k not in ("func",)}
    saved_args.update(style=style["id"], music=str(music_file) if music_file else None, video=str(video))
    report = {
        "source": str(video), "style": style["id"], "mode": mode, "duration": round(plan.duration, 3),
        "hook_end": round(plan.hook_end, 3), "notes": plan.notes,
        "clips": [vars(c) for c in plan.clips],
        "broll": {"slots": len(slots), "filled": filled, "empty": len(slots) - filled},
        "music": str(music_file) if music else None, "captions": len(cues or []), "args": saved_args,
    }
    (out / f"{video.stem}_plan.json").write_text(json.dumps(report, indent=1))

    if args.preview:
        from .preview import render
        render(out / f"{video.stem}_preview.mp4", plan, src, style, caption_tracks, placements, title, music, out,
               fast=args.preview == "fast")
    log(f"[ok] {video.name}: {plan.duration:.1f}s, {len(plan.clips)} shots, b-roll {filled}/{len(slots)} slots filled, "
        f"{len(cues or [])} caption cues -> {out}")
    return report


def cmd_fill(args):
    """Re-run a finished job after the editor filled slots: by editing "file" in
    slots.json (a path, a library file name, or plain words) or by dropping
    B01.mp4, B02.mov ... into output/<clip>/broll/. Hand edits are kept; every
    other slot is matched again (new drops, new library files, --ai)."""
    out = Path(args.job).resolve()
    plan = json.loads(next(out.glob("*_plan.json")).read_text())
    saved = argparse.Namespace(**plan["args"])
    saved.preview = args.preview
    saved.out = str(out.parent)
    saved.broll_plan = None
    if args.broll_dir:
        saved.broll_dir = args.broll_dir
    saved.ai = args.ai
    slots = json.loads((out / "slots.json").read_text())
    auto = {a["id"]: a for a in json.loads((out / ".slots_auto.json").read_text())}
    for s in slots:
        a = auto.get(s["id"], {})
        if s.get("file") != a.get("file"):
            s["source"] = "manual" if s.get("file") and Path(s["file"]).exists() else None
        elif s.get("source") != "plan":
            s["file"], s["source"] = None, None
    edit_one(saved.video, load_style(saved.style), saved, saved.music, slots_override=slots)


def _job(video, style_id, args_dict, music):
    args = argparse.Namespace(**args_dict)
    edit_one(video, load_style(style_id), args, music, log=lambda *_: None)
    return Path(video).name


def _is_done(video, out_dir):
    xml = Path(out_dir) / video.stem / f"{video.stem}.xml"
    if not xml.exists():
        return False
    newest = max(p.stat().st_mtime for p in [video, video.with_suffix(".srt")] if p.exists())
    return xml.stat().st_mtime >= newest


def cmd_batch(args, style):
    videos = sorted(f for f in Path(args.folder).iterdir() if f.suffix.lower() in VIDEO_EXT)
    todo = [v for v in videos if args.force or not _is_done(v, args.out)]
    if len(todo) < len(videos):
        print(f"skipping {len(videos) - len(todo)} already-finished clips (use --force to redo)")
    tracks = sorted(f for f in Path(args.music_dir).iterdir() if f.suffix.lower() in AUDIO_EXT) if args.music_dir else []
    rotation = itertools.cycle(tracks) if tracks else itertools.repeat(args.music)
    if args.broll_dir:  # index once up front instead of in every worker
        from .catalog import build_catalog
        build_catalog(args.broll_dir, thumbs=False)
    failed = 0
    with ProcessPoolExecutor(max_workers=args.jobs) as pool:
        futs = {pool.submit(_job, v, style["id"], vars(args), next(rotation)): v for v in todo}
        for f in as_completed(futs):
            try:
                print(f"[ok] {f.result()}")
            except Exception as e:  # keep the batch going; report at the end
                failed += 1
                print(f"[FAILED] {futs[f].name}: {e}", file=sys.stderr)
    print(f"done: {len(todo) - failed}/{len(todo)} clips")
    sys.exit(1 if failed else 0)


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
        p.add_argument("--ai", action="store_true", help="let Claude pick b-roll for the slots (text only, cheap)")
        p.add_argument("--ai-model", default="claude-opus-5-5")
        p.add_argument("--no-placeholders", action="store_true", help="leave empty slots blank instead of slates")
        p.add_argument("--no-captions", action="store_true")
        p.add_argument("--restyle-captions", action="store_true",
                       help="build the style's captions even when the client sent an SRT")
        p.add_argument("--title-at", help="show the title card / name tag at A-B seconds")
        p.add_argument("--caption-variant", help="style caption variant, e.g. white-bold | blue-accent | blue-all")
        p.add_argument("--preview", nargs="?", const="fast", choices=["fast", "full"],
                       help="render an MP4 preview: fast = 540x960 draft (default), full = 1080x1920")
        p.add_argument("--out", default="output")

    p = sub.add_parser("edit"); p.add_argument("video"); common(p)
    p = sub.add_parser("batch"); p.add_argument("folder"); common(p)
    p.add_argument("--music-dir", help="music folder; tracks are rotated across clips")
    p.add_argument("--jobs", type=int, default=3, help="clips processed in parallel")
    p.add_argument("--force", action="store_true", help="redo clips that are already finished")
    p = sub.add_parser("fill"); p.add_argument("job", help="output/<clip> folder")
    p.add_argument("--broll-dir"); p.add_argument("--ai", action="store_true")
    p.add_argument("--preview", nargs="?", const="fast", choices=["fast", "full"])
    p = sub.add_parser("catalog"); p.add_argument("folder"); p.add_argument("--no-thumbs", action="store_true")
    p = sub.add_parser("describe"); p.add_argument("folder"); p.add_argument("--ai-model", default="claude-opus-5-5")
    p = sub.add_parser("analyze"); p.add_argument("video"); p.add_argument("--out")
    p = sub.add_parser("learn", help="download (optional) + analyse several reference videos, one summary")
    p.add_argument("sources", nargs="+", help="profile/reel URLs, video files or folders")
    p.add_argument("--count", type=int, default=5, help="latest N posts per profile URL")
    p.add_argument("--cookies", help="cookies.txt from a logged-in browser (Instagram needs it)")
    p.add_argument("--name", default="new-style", help="output folder name under analysis/")
    p = sub.add_parser("quote", help="Style 01 quote format: one sentence over lifestyle footage")
    p.add_argument("clips", nargs="+"); p.add_argument("--text", required=True)
    p.add_argument("--style", default="style-01-quote"); p.add_argument("--music"); p.add_argument("--out", default="output")
    p.add_argument("--preview", nargs="?", const="fast", choices=["fast", "full"])
    p = sub.add_parser("transcript"); p.add_argument("video")
    p.add_argument("--srt"); p.add_argument("--words"); p.add_argument("--model", default="small")
    args = ap.parse_args(argv)

    if args.cmd == "transcript":
        return cmd_transcript(args)
    if args.cmd == "fill":
        return cmd_fill(args)
    if args.cmd == "catalog":
        from .catalog import build_catalog
        return build_catalog(args.folder, thumbs=not args.no_thumbs)
    if args.cmd == "describe":
        from .ai import describe_library
        return describe_library(args.folder, args.ai_model)
    if args.cmd == "quote":
        from .quote import make_quote
        return make_quote(args.clips, args.text, load_style(args.style), args.out, args.music, args.preview)
    if args.cmd == "learn":
        from .learn import learn
        out = Path("analysis") / args.name
        learn(args.sources, out, args.count, args.cookies)
        print((out / "summary.md").read_text())
        return
    if args.cmd == "analyze":
        from .analyze import analyze
        out = args.out or f"analysis/{Path(args.video).stem}"
        analyze(args.video, out)
        print((Path(out) / "report.md").read_text())
        return
    style = load_style(args.style)
    if args.cmd == "edit":
        edit_one(args.video, style, args, args.music)
        return
    cmd_batch(args, style)


if __name__ == "__main__":
    main()
