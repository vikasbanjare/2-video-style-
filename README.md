# AutoEdit — style-driven short-form editing for Premiere Pro

Turns a podcast/talking-head clip into a ready-to-review Premiere Pro sequence
in a learned editing style: cuts, punch-in zooms, captions, client b-roll,
title card and music bed. Built for volume (500+ clips/month): one command per
clip, or a whole inbox folder at once.

```
clip.mp4 (+ clip.srt)  ──►  autoedit  ──►  clip.xml            → Premiere: File > Import (sequence)
client b-roll folder                       clip_captions.srt   → caption track (apply your Track Style)
music file / folder                        clip_preview.mp4    → quick check without opening Premiere
title-card PNG                             clip_plan.json      → what was cut/placed and why
```

## Styles

| ID | Name | What it is | Status |
|---|---|---|---|
| `style-01-raw-captions` | **Raw Captions** | Caption-only talking head. Punchline cold-open + title card, tight jump cuts, big centred line-by-line captions, censored swears, quiet music bed, no b-roll, no zooms. | Learned from sample `0001.mp4` — see [`styles/style-01-raw-captions/STYLE_GUIDE.md`](styles/style-01-raw-captions/STYLE_GUIDE.md) |
| `style-02-broll-story` | **B-Roll Story** | B-roll driven, client footage only (no stock), punch-in zooms, music. | Mechanics built; rules are placeholders until its reference video is analysed — see [`styles/style-02-broll-story/STYLE_GUIDE.md`](styles/style-02-broll-story/STYLE_GUIDE.md) |

Each style is a `style.json` (every number the pipeline uses) plus a
`STYLE_GUIDE.md` (how that editor thinks, with the measurements). New styles
are new folders.

## Install

```bash
pip install -r requirements.txt      # faster-whisper only needed when there is no SRT
# ffmpeg + ffprobe on PATH
```

## Use

Pre-cut clip with the client's SRT (the normal job): the SRT is used for timing
and copied through unchanged for the caption track.

```bash
python -m autoedit edit clip.mp4 --style style-02-broll-story \
    --srt clip.srt --broll-dir "Client/BRoll" --music track.mp3 --preview
```

Raw footage in Style 01 (transcribes locally, cuts pauses/fillers/retakes,
moves a chosen line to the front as the hook):

```bash
python -m autoedit transcript raw.mp4            # numbered sentences + times, pick the hook
python -m autoedit edit raw.mp4 --style style-01-raw-captions --mode tight \
    --hook 41.2-45.9 --title-card bloom_title.png --music bed.mp3 --preview
```

A day's inbox (every `.mp4/.mov` in the folder, matching `.srt` picked up by
name, music rotated through a folder):

```bash
python -m autoedit batch inbox/ --style style-02-broll-story \
    --broll-dir "Client/BRoll" --music-dir music/ --out output/ --preview
```

Then in Premiere: run `premiere/AutoEdit_Import.jsx` (imports every sequence and
puts each SRT on a caption track), or File > Import the `.xml` and drag the
`_captions.srt` onto it. Apply the saved caption **Track Style**, review, export.

### Options

| Flag | Meaning |
|---|---|
| `--mode none\|tight` | `none` = clip already cut (default when an SRT is present); `tight` = remove pauses > 0.3 s, fillers and false starts |
| `--hook A-B` | (tight) source range to move to the front as the cold-open hook |
| `--hook-end S` | (pre-cut) where the hook ends; default = end of the first sentence |
| `--title-card PNG` | transparent **full-frame** (1080×1920) PNG shown during the hook, dissolves in/out |
| `--broll-dir DIR` | client b-roll library, matched to what is being said |
| `--broll-plan JSON` | manual placements instead: `[{"file": "...", "start": 3.2, "duration": 2.5, "src_in": 0}]` |
| `--music FILE` / `--music-dir DIR` | music bed, set to the style's level with fades |
| `--no-captions` | skip caption generation |
| `--preview` | also render an MP4 with ffmpeg (captions burned in) |

### B-roll library

Name files by what they show — the filename words are the tags:
`smash-piggy-bank.mp4`, `office/team-meeting-laptop.mov` (folder names count
too). Extra tags for camera-named files go in `tags.json` in the library root:

```json
{ "IMG_0412.mov": ["gym", "workout", "training"] }
```

The matcher places a clip on the word that triggers it, 1.5–3.5 s long, ending
on a word boundary, ≥ 2 s apart, never over the hook or the last 1.5 s, each
clip used once, ≤ 45 % coverage, horizontal footage scaled to fill 9:16. Every
decision is written to `_plan.json` with the matched words. The tool never
downloads anything — Pinterest/other references and music have to be saved
into the folders by you with the right to use them.

## What the Premiere sequence contains

| Track | Content |
|---|---|
| V1 | talking head, cut, with Scale set per segment (punch-ins) |
| V2 | b-roll |
| V3 | title card (Cross Dissolve in/out) |
| A1/A2 | talking-head audio |
| A3/A4 | music at the style's gain with Cross Fade in/out |
| captions | from `_captions.srt` |

Captions styling (font, size, position) lives in Premiere as a caption Track
Style. For Style 01 create it once from the values in its `STYLE_GUIDE.md`
(SF Pro Display / Inter SemiBold, 57 px, white, soft shadow, centre ~49 % down,
max 2 lines). The `--preview` render already uses that look.

## Tests

```bash
python -m pytest -q
```

Generates synthetic footage, b-roll, music and title card, runs both styles end
to end (XML structure, caption rules, retake/filler/pause cutting, zooms, b-roll
matching, title-card visibility, preview duration).

## Not verified yet

- The XML and JSX were checked structurally and through ffmpeg renders, but not
  opened in Premiere from this environment. Confirm on the first real clip that
  the scale values, transitions and the stereo audio pair import as expected.
- ExtendScript is being replaced by UXP in newer Premiere versions; if the JSX
  doesn't run, use the manual import (two drags).
