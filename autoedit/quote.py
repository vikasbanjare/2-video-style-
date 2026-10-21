"""Style 01 quote format: one sentence over lifestyle footage.

  python -m autoedit quote gym1.mp4 gym2.mp4 --text "right now is not the time to rest." --music bed.mp3

Measured from the reference quote videos (sample1, sample4): 8.8-10 s, 0-1
cuts (shots >= 4.5 s), the sentence lowercase with its full stop, white serif
~50 px centred, on screen from first to last frame, music only.
"""
import json
from pathlib import Path

from .edit_plan import Clip, Plan
from .media import probe
from .srt import write_srt


def build_quote_plan(clips, qcfg):
    infos = [probe(c) for c in clips]
    total = qcfg.get("target_duration", 10.0)
    n = max(1, min(len(infos), int(total // qcfg.get("min_shot", 4.5)) or 1))
    per = total / n
    out, t = [], 0.0
    for info in infos[:n]:
        a = min(qcfg.get("skip_start", 0.3), max(0.0, info.duration - per))
        d = min(per, info.duration - a)
        out.append(Clip(a, a + d, t, src=info))
        t += d
    return Plan(out, [], t, 0.0, [f"quote: {len(out)} shots, {t:.1f}s"]), infos[0]


def make_quote(clips, text, style, out_dir, music=None, preview=None, log=print):
    from .xml_export import write_xml
    plan, main_info = build_quote_plan(clips, style.get("quote", {}))
    stem = Path(clips[0]).stem
    out = Path(out_dir).resolve() / f"{stem}_quote"
    out.mkdir(parents=True, exist_ok=True)
    cues = [(0.0, plan.duration, text.strip())]
    write_srt(cues, out / f"{stem}_captions.srt")
    m = (probe(music), style["music"]) if music else None
    write_xml(out / f"{stem}.xml", f"{stem} - {style['name']}", plan, main_info, style, [], None, m, [])
    (out / f"{stem}_plan.json").write_text(json.dumps(
        {"style": style["id"], "text": text, "duration": round(plan.duration, 3),
         "clips": [dict(src=str(c.src.path), src_in=c.src_in, src_out=c.src_out, rec_in=c.rec_in) for c in plan.clips]},
        indent=1))
    if preview:
        from .preview import render
        render(out / f"{stem}_preview.mp4", plan, main_info, style, [(cues, style["caption_look"])], [], None, m, out,
               fast=preview == "fast")
    log(f"[ok] quote: {plan.duration:.1f}s, {len(plan.clips)} shots -> {out}")
    return out
