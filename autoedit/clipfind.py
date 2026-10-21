"""Find the best short clips in a long recording (1-2 h podcast, interview, vlog).

  python -m autoedit clips episode.mp4 --style style-02-broll-story --count 10 [--srt episode.srt] [--ai]

1. transcript: client SRT > cached Whisper words (episode.mp4.words.json) > transcribe
2. candidates: every run of whole sentences that fits the style's clip length
3. free scoring (no tokens): hook strength of the opening line, quotable
   punchline, numbers, story / contrast markers, clean ending, speaking pace,
   few fillers, self-contained start (not "and so that..."); picks the top
   non-overlapping clips
4. optional --ai: Claude re-ranks a shortlist using only those clips' text
   (~150 tokens each), never the full transcript or any video
5. each clip is edited in the chosen style straight from the long file (XML
   points into the master, nothing re-encoded); clips.md lists them for review
"""
import json
import re
import subprocess
from pathlib import Path

from .broll import STOP

HOOK_WORDS = {"never", "always", "nobody", "everyone", "secret", "mistake", "mistakes", "truth", "biggest",
              "worst", "best", "most", "only", "stop", "why", "how", "what", "if", "nobody", "wrong", "money",
              "million", "billion", "failed", "failing", "fail", "broke", "rich", "free", "first", "real"}
STORY = {"when i", "i remember", "the day", "one day", "years ago", "i was", "we were", "i started", "we started",
         "the first time", "back then", "i realized", "turned out"}
CONTRAST = {"but", "instead", "actually", "except", "however", "until"}
BAD_START = {"and", "so", "but", "because", "that", "which", "it", "this", "they", "he", "she", "or", "then",
             "also", "yeah", "um", "uh", "like", "right"}
FILLERS = {"um", "uh", "uhh", "umm", "erm", "like", "basically", "literally", "kinda", "sorta"}
NUM = re.compile(r"^\$?\d[\d,.]*[kKmMbB%]?$")
ENDS = re.compile(r"[.?!]$")


def norm(w):
    return re.sub(r"[^a-z0-9']", "", w.lower())


def sentences(words):
    out, cur = [], []
    for i, w in enumerate(words):
        cur.append(i)
        nxt_gap = words[i + 1]["s"] - w["e"] if i + 1 < len(words) else 9
        if ENDS.search(w["w"]) or nxt_gap > 1.2 or len(cur) > 45:
            out.append({"i0": cur[0], "i1": cur[-1], "s": words[cur[0]]["s"], "e": w["e"],
                        "text": " ".join(words[k]["w"] for k in cur),
                        # cut only by the length cap: mid-sentence, so never a clip boundary
                        "forced": not ENDS.search(w["w"]) and nxt_gap <= 1.2})
            cur = []
    return out


def quotable(sent):
    """How well a sentence works as a stand-alone punchline / cold-open hook."""
    toks = [norm(t) for t in sent["text"].split()]
    n = len(toks)
    if n < 5 or n > 18:
        return 0.0
    score = 1.0 + 0.6 * sum(t in HOOK_WORDS for t in toks) + 0.8 * any(NUM.match(t) for t in sent["text"].split())
    score += 0.8 if sent["text"].rstrip().endswith("?") else 0
    score += 0.6 if toks[0] in ("if", "you", "the", "most", "nobody", "everyone", "never", "stop") else 0
    score -= 1.0 if toks[0] in BAD_START else 0
    return round(score, 2)


def scene_cuts(video):
    """Hard picture cuts (seconds) in the source, cached next to it as <video>.cuts.txt.
    A montage cuts every 1-2 s; one person telling a story holds a shot for many seconds."""
    cache = Path(str(video) + ".cuts.txt")
    if not cache.exists():
        out = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-hwaccel", "auto", "-i", str(video), "-an",
                              "-vf", "scale=192:-2,scdet=threshold=12:sc_pass=1,metadata=print:file=-",
                              "-f", "null", "-"], capture_output=True, text=True, check=True).stdout
        cache.write_text("\n".join(re.findall(r"lavfi\.scd\.time=([\d.]+)", out)) + "\n")
    return [float(t) for t in cache.read_text().split()]


THUMB_FPS, THUMB_W, THUMB_H = 2, 16, 9


def scene_thumbs(video):
    """16x9 px RGB frames at 2 fps over the whole source, cached as <video>.thumbs.npy (~1.6 MB / 30 min)."""
    import numpy as np
    cache = Path(str(video) + ".thumbs.npy")
    if not cache.exists():
        raw = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-loglevel", "error", "-hwaccel", "auto",
                              "-i", str(video), "-an", "-vf", f"fps={THUMB_FPS},scale={THUMB_W}:{THUMB_H}",
                              "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], capture_output=True, check=True).stdout
        np.save(cache, np.frombuffer(raw, np.uint8).reshape(-1, THUMB_H, THUMB_W, 3))
    return np.load(cache)


def new_places(video, back=20.0, same=0.5):
    """Start times of shots that show a place not seen in the previous `back` seconds.
    A story cuts between a few places (speaker, host, back again); a montage shows a new
    place every shot. Place = shot colour histogram (4x4x4 bins); L1 < `same` is a match."""
    import numpy as np
    th, cuts = scene_thumbs(video), scene_cuts(video)
    edges = [0.0, *cuts, len(th) / THUMB_FPS]
    shots = []
    for a, b in zip(edges, edges[1:]):
        f = th[int(a * THUMB_FPS):max(int(a * THUMB_FPS) + 1, int(b * THUMB_FPS))].reshape(-1, 3) // 64
        h = np.bincount(f[:, 0] * 16 + f[:, 1] * 4 + f[:, 2], minlength=64).astype(float)
        shots.append((a, h / max(h.sum(), 1)))
    return [t for i, (t, h) in enumerate(shots)
            if not any(np.abs(h - h2).sum() < same for t2, h2 in shots[:i] if t2 >= t - back)]


def montage_penalty(places):
    """Score penalty from the most new places shown within any 20 s of the window."""
    # ponytail: tuned on one documentary (stories 0-2 new places / 20 s, montage 6-10); retune on more episodes
    return max(0, places - 2) * 2.0


def score_window(words, sents, a, b, places=()):
    """Score sentences a..b (inclusive) as one clip. Returns (score, reasons)."""
    s0, s1 = sents[a], sents[b]
    toks = [norm(words[k]["w"]) for k in range(s0["i0"], s1["i1"] + 1)]
    raw = [words[k]["w"] for k in range(s0["i0"], s1["i1"] + 1)]
    dur = s1["e"] - s0["s"]
    text = " ".join(toks)
    reasons, score = [], 0.0
    first = quotable(s0)
    if first:
        score += first
        reasons.append(f"opening line {first}")
    best_q = max(quotable(sents[k]) for k in range(a, b + 1))
    if best_q >= 2.0:
        score += 0.6 * best_q
        reasons.append(f"quotable line {best_q}")
    nums = sum(1 for t in raw if NUM.match(t.strip(".,!?")) and t[0].isdigit() or t.startswith("$"))
    if nums:
        score += min(2.0, 0.7 * nums)
        reasons.append(f"{nums} number" + ("s" if nums > 1 else ""))
    story = sum(1 for m in STORY if m in text)
    if story:
        score += min(1.5, 0.6 * story)
        reasons.append("story")
    contrast = sum(1 for t in toks if t in CONTRAST)
    if contrast:
        score += min(1.0, 0.4 * contrast)
        reasons.append("contrast")
    wps = len(toks) / max(dur, 1)
    score += 0.8 if 2.3 <= wps <= 4.2 else -0.5          # energetic but understandable
    fill = sum(1 for t in toks if t in FILLERS) / max(len(toks), 1)
    score -= 8 * fill
    if toks and toks[0] in BAD_START:
        score -= 1.5
        reasons.append("starts mid-thought")
    if s1["text"].rstrip()[-1:] not in ".!?":
        score -= 0.5
    content = sum(1 for t in toks if len(t) > 3 and t not in STOP) / max(len(toks), 1)
    score += 2 * content
    k = [t for t in places if s0["s"] - 1 <= t < s1["e"]]     # edges count: a montage tail is the worst place for one
    pen = montage_penalty(max((sum(1 for u in k if t <= u < t + 20) for t in k), default=0))
    if pen:
        score -= pen
        reasons.append(f"montage -{pen:.1f}")
    return round(score, 2), reasons


def find_clips(words, count=10, min_len=25.0, max_len=60.0, gap=5.0, places=()):
    sents = sentences(words)
    cands = []
    for a in range(len(sents)):
        for b in range(a, len(sents)):
            dur = sents[b]["e"] - sents[a]["s"]
            if dur > max_len:
                break
            if dur >= min_len and not sents[b]["forced"] and not (a and sents[a - 1]["forced"]):
                sc, why = score_window(words, sents, a, b, places)
                cands.append({"start": sents[a]["s"], "end": sents[b]["e"], "a": a, "b": b, "score": sc,
                              "why": why, "text": " ".join(s["text"] for s in sents[a:b + 1])})
    cands.sort(key=lambda c: -c["score"])
    chosen = []
    for c in cands:
        if all(c["end"] + gap <= d["start"] or c["start"] >= d["end"] + gap for d in chosen):
            chosen.append(c)
        if len(chosen) >= count:
            break
    for c in chosen:   # trim weak filler sentences off both ends (may go to 80 % of min_len)
        def weak(k):
            toks = [norm(t) for t in sents[k]["text"].split()]
            return sum(t in FILLERS for t in toks) / max(len(toks), 1) > 0.12 or (toks and toks[0] in BAD_START
                                                                                 and quotable(sents[k]) < 1.5)
        while c["b"] > c["a"] and not sents[c["b"] - 1]["forced"] and weak(c["b"]) and sents[c["b"] - 1]["e"] - sents[c["a"]]["s"] >= 0.8 * min_len:
            c["b"] -= 1
        while c["a"] < c["b"] and not sents[c["a"]]["forced"] and weak(c["a"]) and sents[c["b"]]["e"] - sents[c["a"] + 1]["s"] >= 0.8 * min_len:
            c["a"] += 1
        # then drop a host reaction ("Nice.", "Yeah.") at either end; done last so it never unlocks more trimming
        short = lambda k: len(sents[k]["text"].split()) <= 2
        # last sentence starts on a cut to a new place: it belongs to the next scene ("We're Mara Goodman.")
        new_scene = lambda k: any(sents[k - 1]["e"] - 0.3 <= t <= sents[k]["s"] + 0.5 for t in places)
        while c["b"] > c["a"] and not sents[c["b"] - 1]["forced"] and (short(c["b"]) or new_scene(c["b"])):
            c["b"] -= 1
        while c["a"] < c["b"] and not sents[c["a"]]["forced"] and short(c["a"]):
            c["a"] += 1
        c["start"], c["end"] = sents[c["a"]]["s"], sents[c["b"]]["e"]
        c["text"] = " ".join(x["text"] for x in sents[c["a"]:c["b"] + 1])
    for c in chosen:   # cold-open hook candidate: the most quotable sentence inside the clip
        best = max(range(c["a"], c["b"] + 1), key=lambda k: quotable(sents[k]))
        c["hook"] = {"start": sents[best]["s"], "end": sents[best]["e"], "text": sents[best]["text"],
                     "score": quotable(sents[best])}
    return chosen, cands


AI_SYSTEM = ("You pick short-form clips (Reels/TikTok/Shorts) from long podcast transcripts for founder and "
             "business audiences. Rank the candidates by how likely they are to hold attention and get shared: "
             "a strong first line, a clear self-contained point or story, and a payoff ending. "
             'Reply with JSON only: {"order": ["<id>", ...best first], "titles": {"<id>": "<5-8 word title>"}}')


def ai_rerank(cands, model, keep):
    """Text-only re-rank of a shortlist; ~150 tokens per candidate."""
    from .ai import _ask, _client
    lines = "\n\n".join(f"{i}: [{c['end'] - c['start']:.0f}s] {c['text'][:900]}" for i, c in enumerate(cands))
    out = _ask(_client(), model, AI_SYSTEM, f"CANDIDATES\n\n{lines}", max_tokens=800)
    order = [int(i) for i in out.get("order", []) if str(i).isdigit() and int(i) < len(cands)]
    order += [i for i in range(len(cands)) if i not in order]
    for i, t in (out.get("titles") or {}).items():
        if str(i).isdigit() and int(i) < len(cands):
            cands[int(i)]["title"] = t
    return [cands[i] for i in order[:keep]]


def write_report(chosen, path):
    md = ["# Clips found", "", "| # | time | length | score | why | hook |", "|---|---|---|---|---|---|"]
    fmt = lambda t: f"{int(t // 3600)}:{int(t // 60 % 60):02d}:{t % 60:04.1f}"
    for n, c in enumerate(chosen, 1):
        md.append(f"| {n} | {fmt(c['start'])}–{fmt(c['end'])} | {c['end'] - c['start']:.0f}s | {c['score']} | "
                  f"{', '.join(c['why'])} | {c['hook']['text'][:60]} |")
    md += ["", *[f"## {n}. {c.get('title', '')}\n\n{c['text']}\n" for n, c in enumerate(chosen, 1)]]
    path.write_text("\n".join(md))
    path.with_suffix(".json").write_text(json.dumps(chosen, indent=1))
