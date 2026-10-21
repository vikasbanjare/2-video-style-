# Style 02 — "B-Roll Story"

Fast, visual podcast clip. The guest's story is illustrated on the exact
words: client b-roll, count-up number graphics, a split-screen hook, small
1-3 word captions with bold key phrases, and constant re-framing.

Learned from reference sample #2 (`0001.mp4`, 720×1280, 30 fps, 32.5 s), then
checked against 3 more podcast clips (refs batch 1: sample7, 9, 10; sample8 is
the original reference).

## 0. Across 4 videos

| Rule | Range |
|---|---|
| Cuts per 10 s | 2.2 – 5.6 (median ~3.7) |
| Median shot | 1.1 – 2.8 s |
| Opening | guest/host intro shot with a name tag ("Alex Hormozi / Acquisition.com") or a b-roll cold open, in 4/4 |
| Split screen with b-roll | 2/4 |
| Loudness | −14.2 to −14.9 LUFS |
| Caption treatment | **per client** — three variants below |

**Caption variants** (`--caption-variant`, defined in style.json):

| Variant | Seen in | Look |
|---|---|---|
| `white-bold` (default) | sample8, sample9 | small white medium + big white bold key phrases (2 tracks) |
| `blue-accent` | sample7 | white semibold, the key word of key phrases in house blue **#0EB2EE**, ~61 % down |
| `blue-all` | sample10 | every caption bold house blue with a dark soft shadow, ~61 % down |

The blue measured #0BB5ED and #10AEF0 in two different clients' clips → one
house accent, ≈ **#0EB2EE**. In SRT the accent is written as
`<font color="#0EB2EE">word</font>`.
Measured with `python -m autoedit analyze` (report: `docs/reference/style02_analysis.md`)
plus frame checks. Reference images: `docs/reference/style02_one_frame_per_shot.png`,
`style02_contact_*.jpg`, `style02_captions_closeup.png`.

---

## 1. How this editor thinks

1. **Open on the host's question, illustrated.** "You were the brains behind the
   Alex Hormozi book launch that broke the internet" plays over a **split
   screen**: host on top, the thing he is talking about (the live launch) at the
   bottom. Promise and proof in the first 3 s.
2. **Introduce the guest once.** On the guest's first shot, a name tag
   ("Tobias Allen / CMO, Simon Squibb / Ex-Acquisition.com & Fanfive" + arrow)
   for ~1 s. Never again.
3. **Show every concrete noun.** "About 560,000 people for a live event" → we
   *see* the live event. "Affiliate program" → whiteboard footage. B-roll lands
   on the noun phrase, not on a timer.
4. **Numbers become graphics.** Big numbers **count up** on screen
   (0 → 29,000 "affiliates"; → 100,000 "in a single day"). The clip **ends on
   the biggest number**: the payoff is visual, no outro.
5. **Never sit still.** Between b-roll, the talking head is re-cut every
   1.3–3.8 s with a different framing, so something changes every ~1.5 s.
6. **Captions read along, key phrases hook.** Small 1-3 word captions follow
   the voice; important phrases ("broke the internet", "tech collapsed",
   "the top ten", "bonus chapter", "for free") jump out big and bold.

## 2. Structure (sample)

| Time | Shot | Purpose |
|---|---|---|
| 0.0 – 0.9 | host close-up | question starts |
| 0.9 – 3.3 | **split**: host top / launch b-roll bottom | hook + proof |
| 3.3 – 4.5 | wide two-shot | "Tell us about where that started?" |
| 4.5 – 5.5 | guest CU + **name tag** | who is talking |
| 5.5 – 8.6 | full-screen b-roll (vertical live event) | "560,000 people for a live event" |
| 8.6 – 13.7 | guest CU, re-cut 3× | story |
| 13.7 – 15.1 | wide b-roll **fitted over blurred copy** | "affiliate program" |
| 16.0 – 18.6 | **count-up** 0 → 29,000 "affiliates" | number |
| 18.6 – 20.1 | wide b-roll fit/blur | "all promoting for free" |
| 20.1 – 30.0 | guest CU, re-cut 5× | competition story |
| 30.0 – end | **count-up** → 100,000 "in a single day" over the book | payoff, ends here |

## 3. Pacing & cuts

- 15–16 cuts in 32.5 s → **~4.8 cuts / 10 s**, median shot **1.5 s** (0.9 – 5.0).
- Talking-head re-cuts alternate framing (modelled as 100 % ↔ 115 % scale),
  each held 1.2–3.8 s.
- Hard cuts; the only soft move is a counter blurring out.

## 4. B-roll

- On the noun phrase being said (lead ~0.05 s), **1.4–3.1 s**, ends on a word.
- ~**42 %** of runtime is b-roll or graphics.
- Layouts: **split** (hook: speaker top, b-roll bottom) · **full** (vertical
  footage) · **fit_blur** (horizontal footage fitted to width over a blurred,
  filled copy — never cropped to a sliver).
- Captions keep running over b-roll.
- Footage is the client's own (stream, whiteboard, book) — never stock.

## 5. Number graphics

- A number ≥ 1,000 said after the hook → count-up card: #F7F7F7 background with
  a soft vignette, bold near-black number ~16 % of frame width, small grey label
  = the words after it ("affiliates", "in a single day").
- Ease-out count over ~60 % of the card (max 1.6 s), then hold; 1.8–3 s.
- A number in the last ~3 s runs to the end.
- Captions are hidden while the card is up (the number *is* the caption).

## 6. Captions

| | Normal | Emphasis |
|---|---|---|
| Font | SF Pro Display Medium (Inter) | SF Pro Display Bold (Inter Bold) |
| Size @1080 w | **~60 px** | **~93 px** (1.55×) |
| Tracking | tight (≈ −2) | tight (≈ −3) |
| Colour | white, no stroke, faint shadow | same |
| Position | centred, ~57 % from top; at the seam during split screen | same |

- **1–3 words**, one caption at a time, median **0.55 s** on screen (38 changes in 32 s).
- Phrases stay whole ("the top ten", "for free", "competition where").
- ~25–30 % of captions are emphasis: numbers and dense content phrases, never two in a row.
- Question marks kept ("where that started?"), other punctuation dropped.
- Delivered as **two SRTs / two caption tracks** (`_captions.srt` +
  `_captions_emphasis.srt`), each with its own Premiere Track Style. On jobs
  that arrive with a client SRT + Track Style, the client SRT is used untouched
  (`prefer_client_srt`; `--restyle-captions` builds these instead).

## 7. Audio

- −14.2 LUFS integrated (LRA 5.0). Music bed more present than Style 01
  (~8 dB under the voice by the quiet-floor estimate) → `level_db: -18`.
- No SFX measured.

## Job brief (from the client, for podcast-clip work)

- Clips arrive **pre-cut**, with an **SRT and a caption Track Style** already
  made — no transcribing or re-timing needed (`--mode none`, SRT passed through).
- The editor's job: **relevant b-roll** (client library, or real-looking
  reference footage the team saved — never stock), **trending music**,
  **zoom in / zoom out** for energy, a clean look, export.
- Audience: founders / top-1% business and entrepreneur podcasts; the look
  should feel current (2026), real, not stock.
- Volume: 500+ clips/month, 5–7 clips per editor per day → the batch command.
