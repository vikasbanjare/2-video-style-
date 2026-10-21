"""B-roll library catalog: one cached entry per file, built once and updated
incrementally (only new/changed files are probed). Lives at
<library>/catalog.json so the whole team shares it.

Entry: {"id", "file", "duration", "w", "h", "tags": [...], "desc": "", "thumb"}
  tags  – filename words + folder names + tags.json + AI/human tags
  desc  – one-line description, written by a person or `autoedit describe`
  thumb – tiny 3-frame strip used for AI description (seen once, never again)
"""
import json
import re
import subprocess
from pathlib import Path

from .media import probe

MEDIA_EXT = {".mp4", ".mov", ".m4v", ".mxf", ".avi", ".webm", ".png", ".jpg", ".jpeg"}
STILL_EXT = {".png", ".jpg", ".jpeg"}


def _stem(w):
    from .broll import stem
    return stem(w)


def _name_tags(path, root):
    from .broll import STOP
    parts = re.split(r"[^A-Za-z0-9]+", path.stem)
    for parent in path.relative_to(root).parents:
        if str(parent) != ".":
            parts += re.split(r"[^A-Za-z0-9]+", parent.name)
    camera = re.compile(r"^(img|dsc|mvi|vid|clip|gopr|pxl|c\d+|\d+)$", re.I)
    return sorted({_stem(p) for p in parts if p and not camera.match(p) and _stem(p) not in STOP and len(p) > 2})


def _thumb(path, out, duration, still):
    out.parent.mkdir(parents=True, exist_ok=True)
    if still:
        vf = "scale=160:-2"
        cmd = ["ffmpeg", "-v", "error", "-y", "-i", str(path), "-vf", vf, "-frames:v", "1", str(out)]
    else:
        # three frames at 20/50/80 % side by side, 160 px wide each
        step = max(duration, 0.3) * 0.3
        vf = f"select='isnan(prev_selected_t)+gte(t-prev_selected_t\\,{step:.3f})',scale=160:-2,tile=3x1"
        cmd = ["ffmpeg", "-v", "error", "-y", "-ss", f"{duration * 0.2:.2f}", "-i", str(path), "-vf", vf,
               "-frames:v", "1", "-q:v", "6", str(out)]
    return subprocess.run(cmd, capture_output=True).returncode == 0


def build_catalog(folder, thumbs=True, log=print):
    folder = Path(folder).resolve()
    cat_path = folder / "catalog.json"
    cat = json.loads(cat_path.read_text()) if cat_path.exists() else {"version": 1, "items": {}}
    extra = json.loads((folder / "tags.json").read_text()) if (folder / "tags.json").exists() else {}
    seen, added = set(), 0
    for f in sorted(folder.rglob("*")):
        if f.suffix.lower() not in MEDIA_EXT or ".thumbs" in f.parts:
            continue
        rel = f.relative_to(folder).as_posix()
        seen.add(rel)
        st = f.stat()
        item = cat["items"].get(rel)
        if item and item.get("size") == st.st_size and int(item.get("mtime", 0)) == int(st.st_mtime):
            item["tags"] = sorted(set(item["tags"]) | {_stem(t) for t in extra.get(f.name, [])})
            continue
        info = probe(f)
        still = f.suffix.lower() in STILL_EXT
        item = {"id": f"L{len(cat['items']) + 1:04d}", "size": st.st_size, "mtime": int(st.st_mtime),
                "duration": round(info.duration, 2) if not still else 0, "w": info.width, "h": info.height,
                "tags": sorted(set(_name_tags(f, folder)) | {_stem(t) for t in extra.get(f.name, [])}),
                "desc": (cat["items"].get(rel) or {}).get("desc", "")}
        if thumbs:
            t = folder / ".thumbs" / (rel.replace("/", "__") + ".jpg")
            if _thumb(f, t, info.duration, still):
                item["thumb"] = t.relative_to(folder).as_posix()
        cat["items"][rel] = item
        added += 1
    for rel in list(cat["items"]):
        if rel not in seen:
            del cat["items"][rel]
    ids = [i["id"] for i in cat["items"].values()]
    if len(ids) != len(set(ids)):  # re-number after deletions so ids stay unique
        for n, i in enumerate(cat["items"].values(), 1):
            i["id"] = f"L{n:04d}"
    cat_path.write_text(json.dumps(cat, indent=1))
    log(f"catalog: {len(cat['items'])} files ({added} new/changed) -> {cat_path}")
    return cat


def load_catalog(folder):
    folder = Path(folder).resolve()
    cat = build_catalog(folder, thumbs=False, log=lambda *_: None) if not (folder / "catalog.json").exists() \
        else json.loads((folder / "catalog.json").read_text())
    return [{"id": i["id"], "file": str(folder / rel), "tags": set(i["tags"]), "desc": i.get("desc", ""),
             "thumb": str(folder / i["thumb"]) if i.get("thumb") else None, "rel": rel}
            for rel, i in cat["items"].items() if (folder / rel).exists()]


def save_descriptions(folder, updates):
    """updates: {rel_path: {"desc": str, "tags": [..]}} merged into catalog.json."""
    folder = Path(folder).resolve()
    cat = json.loads((folder / "catalog.json").read_text())
    for rel, u in updates.items():
        if rel in cat["items"]:
            cat["items"][rel]["desc"] = u.get("desc", "")[:200]
            cat["items"][rel]["tags"] = sorted(set(cat["items"][rel]["tags"]) | {_stem(t) for t in u.get("tags", [])})
    (folder / "catalog.json").write_text(json.dumps(cat, indent=1))
