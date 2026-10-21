"""Punch-in zooms for talking-head / podcast footage.

Splits the timeline clips at sentence starts and alternates the scale
(e.g. 100% wide -> 112% punch-in -> 100% ...), holding each framing between
`min_hold` and `max_hold` seconds. Static scale per clip, so Premiere imports
it as plain Motion > Scale values with no keyframes to break.
"""
from .edit_plan import Clip


def _cut_points(words, duration, zcfg):
    starts = [w["s"] for i, w in enumerate(words)
              if i and (words[i - 1]["w"][-1:] in ".?!" or w.get("gap_src", 0) > 0.35)]
    cuts, last = [], 0.0
    word_starts = [w["s"] for w in words]
    for t in starts:
        if t - last >= zcfg["min_hold"] and duration - t >= zcfg["min_hold"]:
            cuts.append(t)
            last = t
    # force a change when a framing would hold too long
    forced, prev = [], 0.0
    for t in cuts + [duration]:
        while t - prev > zcfg["max_hold"]:
            target = prev + zcfg["max_hold"] * 0.75
            cand = [s for s in word_starts if prev + zcfg["min_hold"] <= s <= t - zcfg["min_hold"]]
            if not cand:
                break
            prev = min(cand, key=lambda s: abs(s - target))
            forced.append(prev)
        prev = t
    return sorted(set(cuts + forced))


def apply_zooms(plan, zcfg):
    if not zcfg or not zcfg.get("enabled"):
        return plan
    hook_end = plan.hook_end if zcfg.get("skip_hook") else 0.0
    points = [t for t in _cut_points(plan.words, plan.duration, zcfg) if t > hook_end + 0.01]
    if hook_end:
        points = sorted(set(points + [hook_end]))
    levels = zcfg["levels"]
    # every framing change: chosen zoom points, plus existing jump cuts
    changes = set(points)
    if zcfg.get("change_on_cut", True):
        changes |= {c.rec_in for c in plan.clips if c.rec_in > 0}
    changes = sorted(changes)
    out = []
    for c in plan.clips:
        inside = [p for p in points if c.rec_in + 0.05 < p < c.rec_out - 0.05]
        edges = [c.rec_in] + inside + [c.rec_out]
        for a, b in zip(edges, edges[1:]):
            level = levels[sum(1 for p in changes if p <= a + 1e-6) % len(levels)]
            out.append(Clip(c.src_in + (a - c.rec_in), c.src_in + (b - c.rec_in), a, level))
    plan.clips = out
    plan.notes.append(f"zoom: {len(out)} framings")
    return plan
