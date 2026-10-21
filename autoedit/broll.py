"""B-roll placement from a client library folder (never downloads stock).

Library = a folder of clips/images. Each file is tagged by its filename words
("smash-piggy-bank.mp4" -> smash, piggy, bank) plus optional extra tags in
`tags.json` next to them: {"IMG_0412.mov": ["office", "team", "laptop"]}.

Auto mode matches caption phrases to tags and places b-roll on the matched
word, following the style's spacing rules. A manual `broll_plan.json`
([{"file": ..., "start": sec, "duration": sec, "src_in": sec}]) overrides it.
"""
import json
import re
from pathlib import Path

from .media import probe

MEDIA_EXT = {".mp4", ".mov", ".m4v", ".mxf", ".avi", ".webm", ".png", ".jpg", ".jpeg"}
STOP = set("""a an the and or but so then to of in on at for with from by is are was were be been
i you he she it we they me my your our their this that these those just like really very not
do did does have has had will would can could get got gonna going go one some what when where
which who how there here its it's i'm you're we've don't okay yeah""".split())


def stem(w):
    w = re.sub(r"[^a-z0-9]", "", w.lower())
    for suf in ("ing", "ed", "es", "s"):
        if len(w) > len(suf) + 2 and w.endswith(suf):
            return w[: -len(suf)]
    return w


def load_library(folder):
    folder = Path(folder)
    extra = {}
    if (folder / "tags.json").exists():
        extra = json.loads((folder / "tags.json").read_text())
    lib = []
    for f in sorted(folder.rglob("*")):
        if f.suffix.lower() not in MEDIA_EXT:
            continue
        words = re.split(r"[^A-Za-z0-9]+", f.stem) + list(extra.get(f.name, []))
        words += re.split(r"[^A-Za-z0-9]+", f.parent.name) if f.parent != folder else []
        tags = {stem(w) for w in words if w and stem(w) not in STOP and not w.isdigit()}
        lib.append({"file": str(f.resolve()), "tags": tags})
    return lib


def auto_place(words, duration, library, bcfg, hook_end=0.0):
    start_after = max(bcfg.get("start_after", 1.5), hook_end if bcfg.get("skip_hook", True) else 0.0)
    end_before = duration - bcfg.get("end_before", 1.5)
    used, placed, last_end = set(), [], -1e9
    for i, w in enumerate(words):
        if w["s"] < start_after or w["s"] > end_before - bcfg["min_len"]:
            continue
        if w["s"] - last_end < bcfg["min_gap"]:
            continue
        key = stem(w["w"])
        if not key or key in STOP:
            continue
        # look at the phrase around the word for multi-tag matches
        ctx = {stem(x["w"]) for x in words[max(0, i - 2): i + 3]} - STOP
        best, best_score = None, 0
        for item in library:
            if item["file"] in used or key not in item["tags"]:
                continue
            score = len(item["tags"] & ctx)
            if score > best_score:
                best, best_score = item, score
        if not best:
            continue
        start = max(start_after, w["s"] - bcfg.get("lead", 0.08))
        # end on a word boundary between min_len and max_len
        ends = [x["e"] for x in words if start + bcfg["min_len"] <= x["e"] <= start + bcfg["max_len"]]
        end = min(end_before, ends[-1] if ends else start + bcfg["min_len"])
        if end - start < bcfg["min_len"] * 0.8:
            continue
        placed.append({"file": best["file"], "start": round(start, 3), "duration": round(end - start, 3),
                       "src_in": 0.0, "score": best_score, "reason": f"'{w['w']}' matched {sorted(best['tags'] & ctx)}"})
        used.add(best["file"])
        last_end = end
    cover = sum(p["duration"] for p in placed) / max(duration, 0.01)
    while placed and cover > bcfg.get("max_coverage", 0.45):
        placed.remove(min(placed, key=lambda p: p["score"]))
        cover = sum(p["duration"] for p in placed) / duration
    return sorted(placed, key=lambda p: p["start"])


def load_plan(path):
    return json.loads(Path(path).read_text())


def with_media_info(placements):
    for p in placements:
        info = probe(p["file"])
        p["info"] = info
        is_still = Path(p["file"]).suffix.lower() in {".png", ".jpg", ".jpeg"}
        p["still"] = is_still
        if not is_still and info.duration:
            p["duration"] = min(p["duration"], info.duration - p.get("src_in", 0.0))
    return placements
