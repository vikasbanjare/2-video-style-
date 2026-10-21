# Style 01 — "Raw Captions"

Caption-only, talking-head short. No b-roll, no zooms, no sound effects. The
speaker, the words on screen, and a quiet music bed carry the whole video.

Learned from reference sample `0001.mp4` (720×1280, 23.976 fps, 34.4 s), then
checked against 5 more videos from the same creator (refs batch 1: sample1-5,
`analysis/refs-batch1/summary.md`). All numbers are measured, not guessed.

## 0. Across 6 videos (what is constant, what varies)

| Rule | Range | Holds in |
|---|---|---|
| Cuts per 10 s | 1.0 – 1.9 (median ~1.2) | all talking videos |
| Median shot | 4.2 – 5.5 s | all talking videos |
| "Co-Founder and CEO of Bloom" card + arrow at the start | top-left, first ~5 s | 4/4 talking videos |
| Caption block centre | 47 – 57 % from top (on the chest; depends on framing) | all |
| Loudness | −14.1 to −14.4 LUFS | all |
| Locations | gym, trade-show walk-and-talk, kitchen table, car | — |
| Occasional emphasis | quotes + ALL-CAPS word ("“It will NEVER work...”") | 1/4 |

**Second format — quote video** (sample1, sample4): 8.8–10 s of the creator
training, 0–1 cuts, one lowercase sentence *with* its full stop in a white
serif (Times-like, ~50 px @1080) centred at ~50 % for the whole video, music
only. Built by `python -m autoedit quote` with style `style-01-quote`.

Reference frames: `docs/reference/style01_contact_0-18s.png`,
`docs/reference/style01_contact_18-34s.png`, `docs/reference/style01_caption_closeup.png`.

---

## 1. How this editor thinks

1. **Lead with the punchline.** The video opens on the single most quotable line
   ("If you're not failing you're not trying hard enough"), shown as a full
   two-line caption for the whole hook. It is not repeated later.
2. **Establish authority instantly.** During the hook only, a title card names the
   speaker ("Co-Founder and CEO of Bloom" + brand logo + hand-drawn arrow pointing
   at their face). It disappears the moment the hook ends.
3. **Then drop straight into the story, mid-thought.** The body starts with
   "where you're filling up the piggy bank…" — no intro, no "hey guys". The
   viewer is pulled into a story that is already moving.
4. **Story arc:** setup (saving up) → action (smash the piggy bank, place the
   order, start the business) → failure (first one might not work, six-figure
   mistakes) → reassurance (it won't be smooth) → payoff ("but I'm telling you
   it's possible"). It **ends on the payoff line** — no outro, no CTA card.
5. **Don't over-edit.** Only ~4 jump cuts in 34 s. The handheld camera and the
   speaker's energy provide the movement. Cuts exist only to remove dead air,
   stumbles and retakes, never for "visual rhythm".
6. **Words are the visual.** Captions sit dead-centre on the chest, big and
   clean, revealed in speech rhythm so the viewer reads along with the voice.

## 2. Structure / timing template

| Section | Time in sample | Rule |
|---|---|---|
| Hook | 0.00 – 4.75 s | Best one-liner, cold open. Full sentence caption, static. Title card on. |
| Breath | 4.75 – 4.96 s | ~0.2 s with no caption = a reset between hook and story. |
| Story | 4.96 – 34.3 s | Continuous speech, pauses trimmed to ≤ ~0.3 s. |
| End | last word | Cut ~0.5–1 s after the final word. Music fades. No end card. |

Target length: 30–45 s.

## 3. Cuts & pacing

- Hard jump cuts only (no transitions, no crossfades, no zoom punch-ins).
- Measured cuts at 1.33 s, 12.55 s, 15.93 s, 30.20 s → **~1 cut per 8 s**.
- Remove every pause longer than **~0.3 s** (measured: 22 pauses ≥ 0.1 s, all but a
  handful < 0.3 s; the longest kept beat is ~0.8 s for emphasis).
- Remove fillers ("um", "uh"), false starts and retakes — keep the **last** take.
- No speed ramps, no reframing; keep the native handheld frame.

## 4. Captions (the core of the style)

**Look**
- Font: bold geometric/neo-grotesk sans — SF Pro Display **Semibold** (closest
  free match: Inter SemiBold).
- Size: ~36 px at 720 w → **57 px on a 1080×1920 sequence** (verified by rendering against the reference: same width and centre). Line spacing ~1.15.
- Colour: pure white `#FFFFFF`. No box, no stroke, at most a very soft shadow
  (shadow ~30 % opacity, 2–4 px blur) for legibility on bright skin.
- Position: centred horizontally, block centred at **~49 % from the top** (chest).
- Max width ~67 % of frame (≈ 28 characters per line). Max **2 lines**.

**Text rules**
- Sentence case as spoken: capital only where a new sentence starts
  ("And that's okay too"), lowercase for continuations ("you smash the f*cking…").
- No periods, commas, question or exclamation marks.
- Keep apostrophes. Use an **em dash (—)** where the speaker cuts themselves off
  ("Like—", "Some of them—").
- **Censor swear words with an asterisk on the first vowel**: f*cking, sh*t.
- Spell numbers as spoken ("six figure mistakes").

**Reveal / timing**
- Captions are grouped into *pages* of ≤ 2 lines. A page is revealed **line by
  line**: line 1 appears on its first word, line 2 is added under it when its
  first word is spoken; the page clears when the next phrase starts.
  (Occasionally word-by-word on repeated words: "we've / failed failed failed".)
- Measured chunk durations: 0.33 – 2.0 s, median ≈ 0.8 s.
- New page on: sentence end, a pause, or when 2 lines are full.
- No gaps between pages during continuous speech.
- Hook caption is the exception: the whole sentence is shown at once, static.

## 5. Title card (hook only)

- Top-left, roughly x 8–37 %, y 10–18 % of frame.
- Small two-line role text ("Co-Founder / and CEO of") above a large brand
  wordmark, plus a white hand-drawn arrow pointing to the speaker's face.
- Fades in 0.5 → 0.7 s, holds, fades out 4.6 → 4.9 s (ends with the hook).
- Supplied as a transparent PNG per client (`--title-card`).

## 6. Audio

- Voice-forward. Final integrated loudness **-14 LUFS** (LRA 3.9 LU).
- Soft, sustained music bed (pads/held chords around 250–400 Hz, chord changes
  every few seconds), effectively mono, sitting **~20 dB under the voice**
  (≈ -22 dB clip gain on a normalised track). It runs under the whole video,
  including the hook. No risers, hits, whooshes or SFX.
- Fade music in over the first ~0.3 s, out over the last ~1 s.

## 7. Picture

- 9:16 vertical, 23.976 fps, deliver 1080×1920.
- Natural warm dusk look, no heavy grade, no vignette, no overlays besides
  captions + title card.
