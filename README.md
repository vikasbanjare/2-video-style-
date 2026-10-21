# AutoEdit — style-driven short-form editing for Premiere Pro

Turns a podcast/talking-head clip into a ready-to-review Premiere Pro sequence
in a learned editing style: cuts, punch-in zooms, captions, b-roll slots
(auto-filled from the client library or left as labelled gaps), title card and
music bed. Built for volume (500+ clips/month): a whole day's inbox is one
command, ~2 s per clip, no AI tokens needed.

```
inbox/clip.mp4 + clip.srt ─┐
client b-roll library ─────┼─► autoedit batch ─► output/clip/clip.xml           → Premiere: File > Import
music folder ──────────────┘                     output/clip/clip_captions.srt  → caption track (your Track Style)
                                                 output/clip/slots.json         → b-roll slots (what goes where)
                                                 output/clip/broll/             → drop B01.mp4, B02.mov … here
                                                 output/clip/clip_preview.mp4   → optional draft render
```

## Styles

| ID | Name | What it is | Status |
|---|---|---|---|
| `style-01-raw-captions` | **Raw Captions** | Caption-only talking head. Punchline cold-open + title card, tight jump cuts, big centred line-by-line captions, censored swears, quiet music bed, no b-roll, no zooms. | Learned from sample `0001.mp4` — [`STYLE_GUIDE.md`](styles/style-01-raw-captions/STYLE_GUIDE.md) |
| `style-02-broll-story` | **B-Roll Story** | Fast podcast clip: split-screen hook, guest name tag, re-cut/punch-in every ~1.5 s, client b-roll on the spoken noun (wide footage fitted over a blurred copy), count-up number graphics, 1-3 word captions with bold key phrases. | Learned from sample #2 — [`STYLE_GUIDE.md`](styles/style-02-broll-story/STYLE_GUIDE.md) |

| `style-01-quote` | **Raw Captions – Quote** | Style 01's short format: 8–10 s of lifestyle footage, one lowercase serif sentence the whole time, music. `python -m autoedit quote clip.mp4 --text "..."` | Learned from refs sample1 + sample4 |

Style 02 caption looks differ per client: `--caption-variant white-bold | blue-accent | blue-all`
(house blue #0EB2EE). Both styles were checked against 8 more reference videos
(`analysis/refs-batch1/summary.md`); ranges are in each STYLE_GUIDE.

Each style is a `style.json` (every number the pipeline uses) plus a
`STYLE_GUIDE.md` (how that editor thinks). New styles are new folders.

## Install

```bash
pip install -r requirements.txt   # faster-whisper only if a clip has no SRT; anthropic only for --ai
# ffmpeg + ffprobe on PATH
```

## Daily workflow

```bash
# 1. once per client, and again whenever new b-roll is added (only new files are processed)
python -m autoedit catalog "Clients/Acme/BRoll"
python -m autoedit describe "Clients/Acme/BRoll"     # optional: AI looks at each NEW file once

# 2. the day's clips (parallel, skips anything already finished)
python -m autoedit batch inbox/ --style style-02-broll-story \
    --broll-dir "Clients/Acme/BRoll" --music-dir music/ --out output/ --jobs 4 [--ai] [--preview]

# 3. for clips with empty slots: drop files named B01…, or edit slots.json, then
python -m autoedit fill output/clip_017/ --preview

# 4. Premiere: run premiere/AutoEdit_Import.jsx (or File > Import the .xml + drag the .srt),
#    apply the caption Track Style, review, export.
```

## Long recording → many shorts

```bash
python -m autoedit clips episode.mp4 --style style-02-broll-story --count 10 \
    [--srt episode.srt] [--min-len 25 --max-len 60] [--ai] [--broll-dir ...] [--music ...] [--preview]
```

1. Transcript: the episode's SRT if given, else local Whisper (cached as
   `episode.mp4.words.json`, so it runs once per episode; a 2 h episode on CPU
   with `--model small` takes a while — use a GPU or `--model base` to speed up).
2. Every run of whole sentences that fits the style's length (`clips` in
   style.json: Style 01 30–45 s, Style 02 25–60 s) is scored **without AI**:
   strong / quotable opening line, numbers, story and contrast markers, clean
   ending, speaking pace, few fillers, not starting mid-thought. Weak filler
   sentences are trimmed off the ends. The top non-overlapping clips win.
3. `--ai` (optional): Claude re-ranks 3× the shortlist and titles them, from
   those clips' text only (~150 tokens each). No video, no full transcript.
4. Each clip is cut and edited in the style straight from the master file
   (pauses/fillers/retakes removed; Style 01 moves the clip's most quotable
   line to the front as the hook, Style 02 keeps the natural opening), with
   b-roll slots, captions, music — `output/episode_clips/clip_01/ … clip_10/`.
5. `clips.md` lists every clip with time range, score, why it was picked and
   its hook, for a 1-minute human check before Premiere.

## B-roll: slots first, footage second

B-roll is decided in two separate steps, so the computer, an editor or AI can
each do the part they are good at:

1. **Where** — from what is said and the style rules (style.json `broll`):
   start after the hook, 1.5–3.5 s, ending on a word, ≥ 2 s apart, nothing in
   the last 1.5 s, ≤ 45 % coverage. Each slot gets an id, the phrase and
   suggested search words:
   ```json
   {"id": "B03", "start": 12.4, "duration": 2.6, "phrase": "you smash the piggy bank",
    "keywords": ["piggy", "smash", "bank"], "label": "piggy smash", "file": null}
   ```
2. **What** — first match wins:

   | Priority | Source | How |
   |---|---|---|
   | 1 | **you, by hand** | set `"file"` in `slots.json` to a path, a library file name, or plain words ("gym squat") |
   | 2 | **dropped file** | put `B03.mp4` (or `B03_anything.mov`) in `output/<clip>/broll/` |
   | 3 | **AI pick** (`--ai`) | Claude picks from the library catalog (text only, see below) |
   | 4 | **keyword match** | slot words vs. library tags and descriptions (free, offline) |

   A slot nothing fills stays a **labelled gap**: a translucent yellow-bordered
   slate on V2 reading "B-ROLL B03 / piggy smash / *you smash the piggy bank*",
   plus a sequence marker "B03 EMPTY - piggy smash". The editor sees exactly
   where b-roll is needed and what to search for (Pinterest, client drive…).
   `--no-placeholders` leaves the gap blank instead.

`fill` keeps every hand edit and re-matches everything else, so re-running
after adding library footage or dropping files is safe.

### Library naming (makes matching work without AI)

Name files by what they show: `smash-piggy-bank.mp4`, `office/team-meeting-laptop.mov`
(folder names count). Camera names like `IMG_0412.MOV` carry no tags: add them in
`tags.json` (`{"IMG_0412.MOV": ["gym", "squat"]}`), type a `"desc"` in
`catalog.json`, or run `describe`.

### Number graphics (Style 02)

Numbers ≥ 1,000 in the transcript ("29,000 affiliates") become `G01`, `G02`…
slots with a generated count-up clip (`output/<clip>/graphics/G01.mp4`, rendered
by ffmpeg, no plugins). B-roll slots are planned around them, captions are
hidden while they are on screen, and one near the end runs to the end.

## Keeping AI tokens low

Everything except `describe` and `--ai` is plain code with no tokens. When AI
is used, it is set up to cost as little as possible:

| Step | What is sent | How often |
|---|---|---|
| `describe` | one tiny 3-frame strip per library file (160 px frames), 12 files per request | **once per file, ever** (cached in `catalog.json`) |
| `--ai` pick | text only: the clip's open slots + a shortlist of ≤ 40 library lines `id \| tags \| desc` | once per clip, only for slots still empty |
| style learning | `autoedit analyze ref.mp4` → `report.md` + small contact sheets | once per new style |

No video is ever uploaded. Model: `--ai-model` (default `claude-opus-5-5` at low
effort; any Claude model id works).

## Learning a new style

From many references at once (local files, folders, or profile/reel URLs):

```bash
python -m autoedit learn https://www.instagram.com/<profile>/ --count 5 --name style-02 --cookies cookies.txt
python -m autoedit learn refs/*.mp4 --name style-02
```
downloads with yt-dlp (Instagram needs a logged-in `cookies.txt`, and the
environment must allow `instagram.com`, `cdninstagram.com`, `fbcdn.net`), runs
`analyze` on each video, and writes `analysis/<name>/summary.md`: one row per
video plus median / min / max for every rule.

A single video:

```bash
python -m autoedit analyze reference.mp4
```
writes `analysis/reference/report.md` (cuts and shot lengths, caption band /
timing / lines / width, pauses, loudness, music-bed level) and 2 fps contact
sheets. On the Style 01 sample it reproduces the hand measurements: cuts at
1.33 / 12.55 / 15.93 / 30.2 s, 2-line captions ~66 % wide centred at ~49 %,
-14.4 LUFS. Those numbers go into a new `styles/<id>/style.json`.

## Commands

| Command | Does |
|---|---|
| `edit CLIP` | one clip |
| `batch FOLDER` | every `.mp4/.mov` (matching `.srt` by name), `--jobs N` in parallel, skips finished clips (`--force` redoes) |
| `fill JOB_DIR` | rebuild a clip after filling slots |
| `catalog DIR` / `describe DIR` | index / AI-describe the b-roll library |
| `analyze VIDEO` | measure a reference edit |
| `learn SRC...` | download (optional) + analyse many references, combined summary |
| `quote CLIP... --text` | Style 01 quote video |
| `clips LONG --count N` | find the best N clips in a long recording and edit each |
| `transcript CLIP` | numbered sentences with times (pick a hook) |

Common options: `--style`, `--mode none|tight` (pre-cut vs. cut pauses/fillers/retakes),
`--hook A-B` (tight: move a line to the front), `--hook-end S` (pre-cut: where the hook ends),
`--title-card PNG` (transparent full-frame PNG during the hook), `--music` / `--music-dir`,
`--title-at A-B` (name tag timing), `--broll-dir`, `--broll-plan JSON`, `--ai`, `--no-placeholders`,
`--no-captions`, `--restyle-captions` (build the style's captions even when a client SRT exists),
`--preview [fast|full]` (fast = 540×960 draft).

## The Premiere sequence

| Track | Content |
|---|---|
| V1 | talking head, cut, Scale per segment (punch-ins), moved to the top half during split screen |
| V2 | blurred, filled copies under fitted wide b-roll |
| V3 | b-roll, count-up number graphics, placeholder slates for empty slots |
| V4 | title card / name tag (Cross Dissolve in/out) |
| A1/A2 | talking-head audio |
| A3/A4 | music at the style's gain, Cross Fade in/out |
| markers | one per b-roll slot (filled file or EMPTY + search words) |
| captions | `_captions.srt` (+ `_captions_emphasis.srt` for Style 02, one Track Style each); a client SRT is passed through untouched |

## Speed (measured, 4-core container, 60 s 1080×1920 clip)

| Step | Time |
|---|---|
| plan + XML + SRT + slots | ~2 s |
| `--preview` draft (540×960) | ~16 s without placeholders, ~26 s with |
| `--preview full` | ~40 s |

Previews are optional; the Premiere XML is the deliverable. With `--jobs 4`
a 30-clip inbox builds in about a minute without previews.

## Tests

```bash
python -m pytest -q
```
Synthetic footage, b-roll, music and title card; both styles end to end, slots
/ placeholders / markers / `fill` (dropped files and hand labels), batch
parallel + skip, `analyze`, caption rules, retake / filler / pause cutting,
zooms, title-card visibility, and the AI picker's prompt size and validation
(mocked, no tokens).

## Not verified yet

- XML/JSX checked structurally and via ffmpeg renders, not yet opened in
  Premiere here: confirm on the first real clip that Scale, transitions,
  markers and the stereo audio pair import as expected.
- Split screen uses Basic Motion "center" (assumed ±1 = frame edge,
  `XmlWriter.CENTER_EDGE`), Crop and Gaussian Blur filters from the FCP7 XML
  vocabulary. If the speaker lands in the wrong place or the blur is missing
  after import, that constant / filter name is the one thing to change.
- `describe` / `--ai` are tested with a mocked client only; the first real run
  will show whether the descriptions are useful enough.
- `blue-accent` writes the accent as `<font color>` in the SRT; check that
  Premiere's SRT import keeps it (otherwise colour that word in the caption track).
- `analyze` misses coloured captions on bright backgrounds (blue text on a white
  shirt, sample10); their colour/position were measured by hand.
- ExtendScript is being replaced by UXP in newer Premiere versions; if the JSX
  doesn't run, use the manual import.
