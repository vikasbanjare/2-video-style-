"""Turns a word list (source time) into a list of timeline clips.

Two modes:
  * "tight"  – raw footage: remove pauses, fillers and retakes (Style 01 rules).
  * "none"   – footage arrives pre-cut: keep the whole clip as one piece.
Either way the result is a list of Clip objects plus the words remapped to
timeline time, which the captions / zoom / b-roll stages build on.
"""
import re
from dataclasses import dataclass, field


@dataclass
class Clip:
    src_in: float
    src_out: float
    rec_in: float
    scale: float = 100.0  # Basic Motion scale %, used for punch-in zooms

    @property
    def rec_out(self):
        return self.rec_in + (self.src_out - self.src_in)


@dataclass
class Plan:
    clips: list
    words: list               # timeline words: {"w","s","e","gap_src","hook"}
    duration: float
    hook_end: float = 0.0     # timeline time the hook finishes (0 = no hook)
    notes: list = field(default_factory=list)


def norm(w):
    return re.sub(r"[^a-z0-9']", "", w.lower())


def remove_retakes(words, max_back=6, min_match=2):
    """Drop a false start when the speaker restarts the same phrase within a
    few words ("I made some, I made some six figure mistakes" -> keep last)."""
    keep = list(words)
    i = 0
    while i < len(keep):
        removed = False
        for j in range(i + min_match, min(i + max_back + 1, len(keep))):
            k = 0
            while j + k < len(keep) and i + k < j and norm(keep[i + k]["w"]) == norm(keep[j + k]["w"]):
                k += 1
            # only a real stumble: the attempt is broken off ("some," / "some-") or the
            # speaker pauses before restarting; rhetorical repeats flow straight on
            stumble = re.search(r"[,\-\u2014\u2026]$|\.\.\.$", keep[j - 1]["w"]) or \
                keep[j]["s"] - keep[j - 1]["e"] >= 0.25
            if k >= min_match and norm(keep[i]["w"]) and stumble:
                del keep[i:j]
                removed = True
                break
        if not removed:
            i += 1
    return keep


def _spans(words, cfg, src_duration):
    """Group consecutive kept words into source spans, cutting long pauses."""
    spans = []
    for w in words:
        s = max(0.0, w["s"] - cfg["pad_before"])
        e = min(src_duration, w["e"] + cfg["pad_after"])
        if spans and (w["s"] - spans[-1]["last_e"] <= cfg["max_pause"]) and w["idx"] == spans[-1]["last_idx"] + 1:
            spans[-1]["e"] = e
        else:
            if spans:
                s = max(s, spans[-1]["e"])
            spans.append({"s": s, "e": e, "words": []})
        spans[-1]["words"].append(w)
        spans[-1]["last_e"] = w["e"]
        spans[-1]["last_idx"] = w["idx"]
    for sp in spans:
        if sp["e"] - sp["s"] < cfg["min_clip"]:
            sp["e"] = min(src_duration, sp["s"] + cfg["min_clip"])
    return spans


def build_plan(words, src_duration, style, mode="none", hook=None):
    cfg = style["cuts"]
    words = [dict(w, idx=i, gap_src=(w["s"] - words[i - 1]["e"]) if i else 9.0) for i, w in enumerate(words)]
    notes = []

    if mode == "none":
        clips = [Clip(0.0, src_duration, 0.0)]
        tl = [dict(w, hook=False) for w in words]
        return Plan(clips, tl, src_duration, 0.0, notes)

    fillers = set(cfg.get("fillers", []))
    kept = [w for w in words if norm(w["w"]) not in fillers]
    if len(kept) != len(words):
        notes.append(f"removed {len(words) - len(kept)} filler words")
    if cfg.get("remove_retakes"):
        before = len(kept)
        kept = remove_retakes(kept)
        if len(kept) != before:
            notes.append(f"removed {before - len(kept)} words of false starts/retakes")

    hook_words, body_words = [], kept
    if hook:
        hs, he = hook
        hook_words = [w for w in kept if w["s"] >= hs - 0.05 and w["e"] <= he + 0.05]
        if style["hook"].get("remove_from_body", True):
            ids = {w["idx"] for w in hook_words}
            body_words = [w for w in kept if w["idx"] not in ids]

    spans = _spans(hook_words, cfg, src_duration) + _spans(body_words, cfg, src_duration)
    if spans:
        spans[-1]["e"] = min(src_duration, spans[-1]["e"] - cfg["pad_after"] + cfg["tail_after_last_word"])

    clips, tl, t = [], [], 0.0
    hook_end = 0.0
    n_hook_spans = len(_spans(hook_words, cfg, src_duration)) if hook_words else 0
    for k, sp in enumerate(spans):
        clip = Clip(sp["s"], sp["e"], t)
        clips.append(clip)
        for w in sp["words"]:
            tl.append(dict(w, s=t + w["s"] - sp["s"], e=t + w["e"] - sp["s"], hook=k < n_hook_spans))
        t = clip.rec_out
        if k == n_hook_spans - 1:
            hook_end = t
    notes.append(f"{len(clips)} clips, {src_duration:.1f}s -> {t:.1f}s")
    return Plan(clips, tl, t, hook_end, notes)
