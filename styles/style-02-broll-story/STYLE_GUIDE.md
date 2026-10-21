# Style 02 — "B-Roll Story" (waiting for reference sample)

Known so far (from the brief):

- **B-roll driven, no captions.**
- B-roll is **supplied by the client per project** (their own footage), not
  downloaded stock. The pipeline must never fetch stock footage.

Not learned yet — needs the second reference video:

- How often b-roll replaces the talking head (cut rate, shot length).
- Whether b-roll is full-screen cutaway, picture-in-picture or split.
- Whether b-roll cuts land on words, on beats of the music, or on sentence ends.
- Audio: music type, level, SFX/whooshes, ducking behaviour.
- Hook structure, opening/ending, title cards, transitions, zooms, grade.

The pipeline already supports this style mechanically: put the client's clips
in a folder and give a b-roll plan (`broll_plan.json`, see `README.md`); they
are placed on V2 over the edited talking head. Once the reference video
arrives, the rules above get measured the same way Style 01 was, and the
automatic placement rules get written into `style.json`.

## Job brief (from the client, for podcast-clip work)

- Clips arrive **pre-cut**, with an **SRT and a caption Track Style** already
  made — no transcribing or re-timing needed (`--mode none`, SRT passed through).
- The editor's job: **relevant b-roll** (client library, or real-looking
  reference footage the team saved — never stock), **trending music**,
  **zoom in / zoom out** for energy, a clean look, export.
- Audience: founders / top-1% business and entrepreneur podcasts; the look
  should feel current (2026), real, not stock.
- Volume: 500+ clips/month, 5–7 clips per editor per day → the batch command.
