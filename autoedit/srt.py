"""SRT reading/writing. Incoming jobs ship as pre-cut clip + SRT, so the SRT is
turned into approximate word timings (spread across each cue by character
length) and fed through the same pipeline as a Whisper transcript."""
import re
from pathlib import Path

_TS = re.compile(r"(\d+):(\d+):(\d+)[,.](\d+)\s*-->\s*(\d+):(\d+):(\d+)[,.](\d+)")


def _sec(h, m, s, ms):
    return int(h) * 3600 + int(m) * 60 + int(s) + int(ms.ljust(3, "0")[:3]) / 1000


def read_srt(path):
    text = Path(path).read_text(encoding="utf-8-sig")
    cues = []
    for block in re.split(r"\n\s*\n", text.replace("\r\n", "\n").strip()):
        lines = block.strip().split("\n")
        for i, line in enumerate(lines):
            m = _TS.search(line)
            if m:
                g = m.groups()
                body = " ".join(l.strip() for l in lines[i + 1:] if l.strip())
                body = re.sub(r"<[^>]+>", "", body)
                if body:
                    cues.append((_sec(*g[:4]), _sec(*g[4:]), body))
                break
    return cues


def srt_to_words(path):
    words = []
    for start, end, body in read_srt(path):
        toks = body.split()
        total = sum(len(t) + 1 for t in toks)
        t = start
        for tok in toks:
            d = (end - start) * (len(tok) + 1) / total
            words.append({"w": tok, "s": round(t, 3), "e": round(t + d * 0.92, 3)})
            t += d
    return words


def fmt_ts(t):
    t = max(0.0, t)
    ms = int(round(t * 1000))
    h, ms = divmod(ms, 3600000)
    m, ms = divmod(ms, 60000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def write_srt(cues, path):
    out = []
    for i, (s, e, text) in enumerate(cues, 1):
        out.append(f"{i}\n{fmt_ts(s)} --> {fmt_ts(e)}\n{text}\n")
    Path(path).write_text("\n".join(out), encoding="utf-8")
