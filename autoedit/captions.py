"""Caption pages in the Style 01 manner.

Words are grouped into pages of <= max_lines lines. Each page is revealed line
by line (line 1 on its first word, line 2 added when its first word is spoken),
or all at once ("static", used for the hook), or word by word ("word").
Output cues are (start, end, text) on the timeline, text lines joined by "\n".
"""
import re

CONJ = {"and", "but", "so", "then", "which", "that", "because", "or", "if", "when", "where", "like"}
VOWELS = "aeiouAEIOU"
# words a new caption line naturally starts with (measured from the Style 01 sample)
BREAK_BEFORE = CONJ | {"the", "a", "an", "into", "in", "on", "to", "would", "could", "not", "really",
                       "i", "i'm", "it's", "my", "your", "our", "we", "you", "might"}


def censor(word, bad):
    core = re.sub(r"[^A-Za-z']", "", word).lower().replace("'", "")
    if core not in bad and core.rstrip("s") not in bad:
        return word
    for i, ch in enumerate(word):
        if i and ch in VOWELS:
            return word[:i] + "*" + word[i + 1:]
    return word


def clean(word, ccfg):
    """Returns (display_text, ends_sentence, cut_off)."""
    w = word.strip()
    cut_off = bool(re.search(r"(-|\.\.\.|…)$", w)) and len(w) > 1
    ends = bool(re.search(r"[.?!]$", w)) and not cut_off
    w = re.sub(r"(-|\.\.\.|…)+$", "", w) if cut_off else w
    w = w.strip(ccfg.get("strip_punctuation", ".,!?;:\""))
    w = w.replace("’", "'")
    w = censor(w, set(ccfg.get("censor", [])))
    if cut_off:
        w += ccfg.get("cutoff_dash", "—")
    return w, ends, cut_off


def _text(ws):
    return " ".join(w["t"] for w in ws)


def _splits_number(ws, i):
    """Penalty for breaking between a number and the word it counts ("30 | days")."""
    return 2.0 if NUMBER.match(ws[i - 1]["t"]) and ws[i]["t"].lower() not in BREAK_BEFORE else 0.0


def _best_split(ws, max_chars):
    """Split index for two lines: prefer a speech pause / conjunction, keep both lines
    within max_chars, mildly prefer balance. Returns None if no valid split."""
    best, best_score = None, None
    for i in range(1, len(ws)):
        a, b = _text(ws[:i]), _text(ws[i:])
        if len(a) > max_chars or len(b) > max_chars:
            continue
        if ws[i - 1]["cut"]:
            return i
        score = ws[i].get("gap_src", 0) * 10
        score += 0.6 if ws[i]["t"].lower() in CONJ else 0
        score += 0.4 if ws[i]["t"].lower() in BREAK_BEFORE else 0
        score -= _splits_number(ws, i)
        score -= abs(len(a) - len(b)) / max_chars
        if best_score is None or score > best_score:
            best, best_score = i, score
    return best


def _pages(ws, ccfg):
    """Recursively split a run of words into pages that fit max_lines x max_chars."""
    mc = ccfg["max_chars_per_line"]
    if len(ws) == 1 or (len(_text(ws)) <= mc and len(ws) <= 6):
        return [[ws]]
    if len(ws) <= 9 and ccfg["max_lines"] >= 2:
        i = _best_split(ws, mc)
        if i is not None:
            return [[ws[:i], ws[i:]]]
    # too long for one page: split at the strongest pause / conjunction near the middle
    best, best_score = 1, None
    for i in range(1, len(ws)):
        score = ws[i].get("gap_src", 0) * 10 + (0.6 if ws[i]["t"].lower() in CONJ else 0)
        score -= _splits_number(ws, i)
        score -= abs(i - len(ws) / 2) / len(ws)
        if best_score is None or score > best_score:
            best, best_score = i, score
    return _pages(ws[:best], ccfg) + _pages(ws[best:], ccfg)


def _runs(words, ccfg):
    runs, cur = [], []
    for w in words:
        if cur and (cur[-1]["end"] or w.get("gap_src", 0) >= ccfg["page_break_pause"] or w["hook"] != cur[-1]["hook"]):
            runs.append(cur)
            cur = []
        cur.append(w)
    if cur:
        runs.append(cur)
    return runs


def build_cues(plan_words, ccfg, hook_end=0.0, hook_mode="static", gap_after_hook=0.2):
    words = []
    for w in plan_words:
        t, end, cut = clean(w["w"], ccfg)
        if t:
            words.append(dict(w, t=t, end=end, cut=cut))
    pages = []  # (lines, is_hook)
    for run in _runs(words, ccfg):
        for p in _pages(run, ccfg):
            pages.append(p)

    cues = []
    for n, lines in enumerate(pages):
        first = lines[0][0]
        last = lines[-1][-1]
        start = first["s"]
        nxt = pages[n + 1][0][0]["s"] if n + 1 < len(pages) else None
        if first["hook"] and hook_end:
            end = (hook_end - gap_after_hook) if (nxt is None or not pages[n + 1][0][0]["hook"]) else nxt
            mode = hook_mode
        else:
            end = nxt if (nxt is not None and nxt - last["e"] < 0.8) else last["e"] + ccfg.get("hold_after_last_word", 0.3)
            mode = ccfg.get("reveal", "line")
        end = max(end, start + 0.1)
        if mode == "static" or len(lines) == 1 and mode != "word":
            cues.append((start, end, "\n".join(_text(l) for l in lines)))
        elif mode == "line":
            for k in range(len(lines)):
                s = lines[k][0]["s"]
                e = lines[k + 1][0]["s"] if k + 1 < len(lines) else end
                cues.append((s, e, "\n".join(_text(l) for l in lines[:k + 1])))
        else:  # word by word, accumulating
            flat = [(li, w) for li, l in enumerate(lines) for w in l]
            for k, (li, w) in enumerate(flat):
                e = flat[k + 1][1]["s"] if k + 1 < len(flat) else end
                shown = [[x["t"] for (lj, x) in flat[:k + 1] if lj == j] for j in range(li + 1)]
                cues.append((w["s"], e, "\n".join(" ".join(s) for s in shown)))
    return [(round(s, 3), round(e, 3), t) for s, e, t in cues if e - s > 0.04]


# ---------------------------------------------------------------- Style 02: chunks
NUMBER = re.compile(r"^\$?\d[\d,.]*[kKmMbB%]?$")
NUM_WORDS = {"ten", "hundred", "thousand", "million", "billion", "first", "top", "zero"}


def _content(t):
    from .broll import STOP
    k = re.sub(r"[^a-z0-9']", "", t.lower())
    return len(k) >= 3 and k not in STOP


def emphasis_score(chunk):
    """How much a 1-3 word chunk deserves the big bold treatment: numbers and
    dense content phrases ("broke the internet", "the top ten", "bonus chapter")."""
    texts = [w["t"] for w in chunk]
    score = 2.0 * sum(1 for t in texts if NUMBER.match(t) or t.lower() in NUM_WORDS)
    score += sum(1.0 for t in texts if _content(t))
    if len(texts) >= 2 and _content(texts[-1]):
        score += 0.5                      # phrases that end on the key word read as a punch
    return score


def build_chunks(plan_words, ccfg, emphasis="track", accent="#0EB2EE"):
    """1-3 word captions that replace each other (Style 02). Returns
    (normal_cues, emphasis_cues):
      emphasis="track" – key chunks go to the second list (own caption track/style)
      emphasis="word"  – one list; the key word of each key chunk is wrapped in
                         <font color="accent"> (accent-colour word, e.g. house blue)
      emphasis="none"  – one list, no emphasis"""
    words = []
    for w in plan_words:
        t, end, cut = clean(w["w"], ccfg)
        if t:
            words.append(dict(w, t=t, end=end, cut=cut))
    max_w, max_c = ccfg.get("chunk_max_words", 3), ccfg.get("chunk_max_chars", 18)
    # hard breaks at sentence ends, cut-offs and pauses; inside a run, split into
    # 1-3 word phrases with the lowest cost (never end on "the/a/for/that...")
    runs, cur = [], []
    for w in words:
        if cur and (cur[-1]["end"] or cur[-1]["cut"] or w.get("gap_src", 0) >= ccfg.get("page_break_pause", 0.35)):
            runs.append(cur)
            cur = []
        cur.append(w)
    if cur:
        runs.append(cur)

    def cost(run, a, b):
        c = run[a:b]
        if len(_text(c)) > max_c and len(c) > 1:
            return 1e9
        k = 1.0
        if not _content(c[-1]["t"]) and not NUMBER.match(c[-1]["t"]):
            k += 1.2                                  # dangling "the", "a", "for"...
        if len(c) == 1 and not (_content(c[0]["t"]) or NUMBER.match(c[0]["t"])):
            k += 1.0
        if c[0]["t"].lower() in BREAK_BEFORE:
            k -= 0.3                                  # phrases naturally start here
        if b < len(run) and _content(run[b]["t"]) and run[b]["t"].lower() not in BREAK_BEFORE \
                and (_content(c[-1]["t"]) or c[-1]["t"].lower() in NUM_WORDS):
            k += 1.5                                  # splitting "top | ten", "Hormozi | book"
        return k

    chunks = []
    for run in runs:
        best = [0.0] + [1e18] * len(run)
        back = [0] * (len(run) + 1)
        for j in range(1, len(run) + 1):
            for n in range(1, min(max_w, j) + 1):
                c = best[j - n] + cost(run, j - n, j)
                if c < best[j]:
                    best[j], back[j] = c, j - n
        cuts, j = [], len(run)
        while j > 0:
            cuts.append((back[j], j))
            j = back[j]
        chunks += [run[a:b] for a, b in reversed(cuts)]
    # emphasis: best-scoring chunks, never two in a row, at most `emphasis_share` of all chunks
    scores = [emphasis_score(c) for c in chunks]
    budget = int(round(len(chunks) * ccfg.get("emphasis_share", 0.3)))
    emph = set()
    for i in sorted(range(len(chunks)), key=lambda i: -scores[i]):
        if len(emph) >= budget or scores[i] < ccfg.get("emphasis_min_score", 2.0):
            break
        if i - 1 not in emph and i + 1 not in emph:
            emph.add(i)
    normal, strong = [], []
    for i, c in enumerate(chunks):
        s = c[0]["s"]
        nxt = chunks[i + 1][0]["s"] if i + 1 < len(chunks) else None
        e = nxt if nxt is not None and nxt - c[-1]["e"] < 0.6 else c[-1]["e"] + ccfg.get("hold_after_last_word", 0.2)
        text = _text(c)
        if i in emph and emphasis == "word":
            key = max(c, key=lambda w: (bool(NUMBER.match(w["t"])), _content(w["t"]), len(w["t"])))
            text = " ".join(f'<font color="{accent}">{w["t"]}</font>' if w is key else w["t"] for w in c)
        cue = (round(s, 3), round(max(e, s + 0.1), 3), text)
        (strong if i in emph and emphasis == "track" else normal).append(cue)
    return normal, strong
