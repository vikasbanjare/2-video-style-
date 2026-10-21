"""Optional AI help for b-roll, built to spend as few tokens as possible.

describe – each library file is looked at ONCE (a tiny 3-frame strip, ~160 px
           per frame), up to 12 files per request; the result is cached in
           catalog.json and never re-sent.
pick     – per clip, TEXT ONLY: the open slots (phrase + keywords) and a
           pre-filtered shortlist of library entries ("id | tags | desc"),
           answered with a small JSON map. No video, no images.

Everything works without this module (keyword matching); it only improves
the choices. Needs `pip install anthropic` and an API key / `ant auth login`.
"""
import base64
import json
import re
from pathlib import Path

from .broll import STOP, content_words, stem

DEFAULT_MODEL = "claude-opus-5-5"

DESCRIBE_SYSTEM = (
    "You catalog b-roll footage for short-form video editors. For each image strip "
    "(3 frames from one clip), give a plain, literal description of what is visible "
    "(subject, action, setting) in at most 12 words, and 3-6 lowercase search tags. "
    'Reply with JSON only: {"<id>": {"desc": "...", "tags": ["..."]}, ...}'
)

PICK_SYSTEM = (
    "You place b-roll in podcast/talking-head clips for social media. For each slot, "
    "choose the library item that most literally shows what is being said at that "
    "moment, or null if nothing fits well — a wrong cutaway is worse than none. "
    "Use each item at most once. "
    'Reply with JSON only: {"<slot id>": "<item id or null>", ...}'
)


def _client():
    import anthropic
    return anthropic.Anthropic()


def _ask(client, model, system, content, max_tokens=2000):
    resp = client.beta.messages.create(
        model=model, max_tokens=max_tokens, system=system,
        output_config={"effort": "low"},
        betas=["server-side-fallback-2026-07-01"], fallbacks="default",
        messages=[{"role": "user", "content": content}],
    )
    if resp.stop_reason == "refusal":
        return {}
    text = "".join(b.text for b in resp.content if b.type == "text")
    m = re.search(r"\{.*\}", text, re.S)
    try:
        return json.loads(m.group(0)) if m else {}
    except json.JSONDecodeError:
        return {}


def describe_library(folder, model=DEFAULT_MODEL, batch=12, log=print):
    from .catalog import build_catalog, save_descriptions
    folder = Path(folder).resolve()
    cat = build_catalog(folder, thumbs=True, log=log)
    todo = [(rel, i) for rel, i in cat["items"].items() if not i.get("desc") and i.get("thumb")]
    if not todo:
        log("describe: nothing new to describe")
        return 0
    client = _client()
    done = 0
    for k in range(0, len(todo), batch):
        chunk = todo[k:k + batch]
        content = []
        for rel, item in chunk:
            data = base64.standard_b64encode((folder / item["thumb"]).read_bytes()).decode()
            content += [{"type": "text", "text": f"id {item['id']} (file: {Path(rel).name})"},
                        {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": data}}]
        content.append({"type": "text", "text": "Describe each id."})
        out = _ask(client, model, DESCRIBE_SYSTEM, content)
        by_id = {item["id"]: rel for rel, item in chunk}
        save_descriptions(folder, {by_id[i]: v for i, v in out.items() if i in by_id and isinstance(v, dict)})
        done += len(out)
        log(f"describe: {done}/{len(todo)}")
    return done


def shortlist(slots, library, limit=40):
    """Cheap pre-filter so the prompt only carries plausible candidates."""
    if len(library) <= limit:
        return library
    terms = {stem(k) for s in slots for k in s["keywords"] + content_words([{"w": x} for x in s["phrase"].split()])}
    terms -= STOP

    def score(item):
        have = set(item["tags"]) | {stem(w) for w in re.findall(r"[A-Za-z]+", item.get("desc", ""))}
        return len(have & terms)
    return sorted(library, key=score, reverse=True)[:limit]


def make_picker(model=DEFAULT_MODEL, limit=40):
    client = _client()

    def pick(slots, library):
        cands = shortlist(slots, library, limit)
        if not cands:
            return {}
        lib_lines = "\n".join(f"{i['id']} | {' '.join(sorted(i['tags']))} | {i.get('desc', '')}" for i in cands)
        slot_lines = "\n".join(f"{s['id']} ({s['duration']:.1f}s): \"{s['phrase']}\"" for s in slots)
        out = _ask(client, model, PICK_SYSTEM,
                   f"LIBRARY (id | tags | description)\n{lib_lines}\n\nSLOTS\n{slot_lines}", max_tokens=1000)
        by_id = {i["id"]: i["file"] for i in cands}
        return {sid: by_id[iid] for sid, iid in out.items() if isinstance(iid, str) and iid in by_id}
    return pick
