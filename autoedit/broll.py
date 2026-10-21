"""B-roll in two steps, so humans, rules and AI can share the same work:

1. plan_slots()  – decide WHERE b-roll goes (style spacing rules + what is
   being said). Needs no footage. Each slot gets an id (B01, B02...), the
   phrase, and suggested search keywords.
2. fill_slots()  – decide WHAT goes in each slot, in priority order:
     a. a file the editor set by hand in slots.json ("file": path or label)
     b. a file named after the slot dropped in the clip's broll/ folder (B03.mp4)
     c. AI pick (optional, see ai.py) or keyword match against the library
   Slots left empty become labelled placeholders on V2 plus a sequence marker.

Never downloads anything: the library is whatever footage you put in it.
"""
import json
import re
from pathlib import Path

from .media import probe

MEDIA_EXT = {".mp4", ".mov", ".m4v", ".mxf", ".avi", ".webm", ".png", ".jpg", ".jpeg"}
STILL_EXT = {".png", ".jpg", ".jpeg"}
STOP = set("""a an the and or but so then to of in on at for with from by is are was were be been being
i you he she it we they me my your our their this that these those just like really very not no yes
do did does doing done have has had will would can could should get got gonna going go goes went one some
what when where which who how why there here its it's i'm you're we're they're we've i've don't didn't
okay yeah um uh also even still about into out up down over all any every much many more most thing things
know think say said tell telling make made want need see look come take put let mean actually literally
right now then time way lot kind sort pretty guy guys people someone something everything anything back""".split())


def stem(w):
    w = re.sub(r"[^a-z0-9]", "", w.lower())
    for suf in ("ing", "ed", "es", "s"):
        if len(w) > len(suf) + 2 and w.endswith(suf):
            return w[: -len(suf)]
    return w


def content_words(words):
    """Phrase words worth showing on screen, most specific (longest) first."""
    seen, out = set(), []
    for w in words:
        clean = re.sub(r"[^A-Za-z0-9']", "", w["w"])
        k = stem(clean)
        if len(k) >= 3 and clean.lower() not in STOP and k not in STOP and k not in seen and not k.isdigit():
            seen.add(k)
            out.append(clean.lower())
    return sorted(out, key=len, reverse=True)


# ---------------------------------------------------------------- 1. where
def plan_counters(words, duration, gcfg, hook_end=0.0):
    """Slots for count-up number graphics: big numbers said after the hook.
    The words after the number (up to the sentence end) become the label."""
    from .graphics import parse_number
    out = []
    for i, w in enumerate(words):
        p = parse_number(w["w"])
        if not p or p[0] < gcfg.get("min_value", 1000) or w["s"] < hook_end:
            continue
        if out and w["s"] < out[-1]["start"] + out[-1]["duration"]:
            continue
        label = []
        for x in words[i + 1:i + 5]:
            label.append(re.sub(r"[.,!?;:]", "", x["w"]))
            if x["w"][-1:] in ".,!?;:":
                break
        start = max(0.0, w["s"] - gcfg.get("lead", 0.05))
        dur = min(max(gcfg.get("min_len", 1.8), (words[min(i + len(label), len(words) - 1)]["e"] - start) + 0.6),
                  gcfg.get("max_len", 3.0))
        if duration - (start + dur) < gcfg.get("run_to_end_within", 3.0):
            dur = duration - start            # a number near the end becomes the closing shot
        dur = min(dur, duration - start)
        out.append({"id": f"G{len(out) + 1:02d}", "type": "counter", "start": round(start, 3), "duration": round(dur, 3),
                    "phrase": " ".join([w["w"]] + label), "keywords": [], "label": " ".join(label),
                    "number": w["w"].strip(".,!?;:"), "file": None, "src_in": 0.0, "source": "graphic",
                    "layout": "full"})
    return out


def plan_slots(words, duration, bcfg, hook_end=0.0, reserved=()):
    start_after = max(bcfg.get("start_after", 1.5), hook_end if bcfg.get("skip_hook", True) else 0.0)
    end_before = duration - bcfg.get("end_before", 1.5)
    look = bcfg.get("lookahead", 2.5)
    slots, t, covered = [], start_after, 0.0
    for i, w in enumerate(words):
        w["_i"] = i
    while t < end_before - bcfg["min_len"]:
        lead = bcfg.get("lead", 0.08)
        cands = [w for w in words if t + lead <= w["s"] <= min(t + look, end_before - bcfg["min_len"])]
        if not cands:
            t += 0.5
            continue

        def score(w):
            i = w["_i"]
            phrase_start = i == 0 or words[i - 1]["w"][-1:] in ".?!," or w.get("gap_src", 0) >= 0.2
            return len(content_words(words[i:i + 5])) + (1.0 if phrase_start else 0.0)

        best = max(cands, key=score)
        if score(best) < 1.0:
            t = best["s"] + 0.5
            continue
        start = max(start_after, best["s"] - lead)
        ends = [x["e"] for x in words if start + bcfg["min_len"] <= x["e"] <= start + bcfg["max_len"]]
        end = min(end_before, ends[-1] if ends else start + bcfg["min_len"])
        clash = next((r for r in reserved if start < r["start"] + r["duration"] + bcfg["min_gap"] * 0.5
                      and end > r["start"] - bcfg["min_gap"] * 0.5), None)
        if clash and clash["start"] > start:       # shorten to end before the number graphic
            ends = [x["e"] for x in words if start + bcfg["min_len"] * 0.8 <= x["e"] <= clash["start"] - 0.3]
            end = ends[-1] if ends else start
        if clash and (clash["start"] <= start or end - start < bcfg["min_len"] * 0.8):
            t = clash["start"] + clash["duration"] + bcfg["min_gap"] * 0.5
            continue
        if end - start >= bcfg["min_len"] * 0.8:
            inside = [x for x in words if start - 0.01 <= x["s"] < end]
            kw = content_words(inside)[:3]
            slots.append({"id": f"B{len(slots) + 1:02d}", "start": round(start, 3), "duration": round(end - start, 3),
                          "phrase": " ".join(x["w"] for x in inside), "keywords": kw,
                          "label": " ".join(kw[:2]) or "b-roll", "file": None, "src_in": 0.0, "source": None,
                          "type": "broll", "layout": None})
            covered += end - start
            if (covered + sum(r["duration"] for r in reserved)) / max(duration, 0.01) >= bcfg.get("max_coverage", 0.45):
                break
        t = end + bcfg["min_gap"]
    for w in words:
        w.pop("_i", None)
    return slots


# ---------------------------------------------------------------- library
def load_library(folder):
    """Library items: {"id", "file", "tags": set, "desc": str}. Uses catalog.json
    (descriptions, AI/human tags) when present, filenames + tags.json otherwise."""
    from .catalog import load_catalog
    return load_catalog(folder)


def _item_terms(item):
    return set(item["tags"]) | {stem(w) for w in re.findall(r"[A-Za-z]+", item.get("desc", ""))} - STOP


def keyword_match(slot, library, used):
    terms = [stem(k) for k in slot["keywords"]] + [stem(w) for w in content_words(
        [{"w": x} for x in slot["phrase"].split()])]
    best, best_score = None, 0.0
    for item in library:
        if item["file"] in used:
            continue
        have = _item_terms(item)
        score = sum((1.5 if k in item["tags"] else 1.0) / (1 + 0.3 * n) for n, k in enumerate(dict.fromkeys(terms)) if k in have)
        if score > best_score:
            best, best_score = item, score
    return (best, best_score) if best_score >= 1.0 else (None, 0.0)


def resolve_label(value, library):
    """slots.json "file" may be a path, a library file name, or free words."""
    p = Path(value)
    if p.exists():
        return str(p.resolve())
    for item in library:
        if Path(item["file"]).name == value or Path(item["file"]).stem == value:
            return item["file"]
    best, _ = keyword_match({"keywords": value.split(), "phrase": value}, library, set())
    return best["file"] if best else None


# ---------------------------------------------------------------- 2. what
def fill_slots(slots, library, clip_broll_dir=None, ai_picker=None):
    used = {s["file"] for s in slots if s.get("file") and Path(s["file"]).exists()}
    dropped = {}
    if clip_broll_dir and Path(clip_broll_dir).is_dir():
        for f in Path(clip_broll_dir).iterdir():
            m = re.match(r"(B\d{2})", f.name, re.I)
            if m and f.suffix.lower() in MEDIA_EXT:
                dropped[m.group(1).upper()] = str(f.resolve())
    for s in slots:
        if s["id"] in dropped:
            s.update(file=dropped[s["id"]], source="dropped")
        elif s.get("file") and not Path(s["file"]).exists():
            s.update(file=resolve_label(s["file"], library), source="label")
        elif s.get("file"):
            s["source"] = s.get("source") or "manual"
        if s.get("file"):
            used.add(s["file"])
    open_slots = [s for s in slots if not s.get("file") and s.get("type") != "counter"]
    if open_slots and library and ai_picker:
        picks = ai_picker(open_slots, [i for i in library if i["file"] not in used])
        for s in open_slots:
            f = picks.get(s["id"])
            if f and f not in used:
                s.update(file=f, source="ai")
                used.add(f)
    for s in slots:
        if not s.get("file") and library and s.get("type") != "counter":
            item, score = keyword_match(s, library, used)
            if item:
                s.update(file=item["file"], source=f"keywords({score:.1f})")
                used.add(item["file"])
    return slots


def to_placements(slots, fit_wide=True):
    """Filled slots -> placements with media info (duration clipped to the source)."""
    out = []
    for s in slots:
        if not s.get("file"):
            continue
        p = dict(s)
        p["info"] = probe(p["file"])
        p["still"] = Path(p["file"]).suffix.lower() in STILL_EXT
        if not p.get("layout"):   # horizontal footage: fit width over a blurred copy (never crop it to bits)
            wide = p["info"].width > p["info"].height * 1.1
            p["layout"] = "fit_blur" if wide and fit_wide else "full"
        if not p["still"] and p["info"].duration:
            p["duration"] = min(p["duration"], p["info"].duration - p.get("src_in", 0.0))
        out.append(p)
    return out


def load_plan(path):
    """Manual plan [{"file", "start", "duration", "src_in"}] -> pre-filled slots."""
    return [dict({"id": f"B{i + 1:02d}", "phrase": "", "keywords": [], "label": Path(p["file"]).stem,
                  "src_in": 0.0, "source": "plan"}, **p) for i, p in enumerate(json.loads(Path(path).read_text()))]
