import json
import shutil
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from autoedit.captions import build_cues, censor, clean
from autoedit.cli import load_style, main
from autoedit.edit_plan import build_plan, remove_retakes
from autoedit.media import probe

STYLE1 = load_style("style-01-raw-captions")
STYLE2 = load_style("style-02-broll-story")


def W(text, start, step=0.3, gap=0.05):
    out, t = [], start
    for tok in text.split():
        out.append({"w": tok, "s": round(t, 3), "e": round(t + step - gap, 3)})
        t += step
    return out


# a hook line, a long pause, a filler, a false start, then the story
WORDS = (W("If you're not failing you're not trying hard enough.", 0.5)
         + W("Um,", 4.2)
         + W("I made some, I made some six figure mistakes.", 5.5)
         + W("Which at the time really fucking set us back.", 9.0)
         + W("But I'm telling you it's possible.", 12.5))


def test_censor_and_clean():
    assert censor("fucking", {"fucking"}) == "f*cking"
    assert censor("Shit's", {"shit"}) == "Sh*t's"
    assert clean("Like-", STYLE1["captions"])[0] == "Like—"
    assert clean("enough.", STYLE1["captions"]) == ("enough", True, False)


def test_retake_keeps_last_take():
    ws = W("I made some, I made some six figure mistakes", 0)
    assert " ".join(w["w"] for w in remove_retakes(ws)) == "I made some six figure mistakes"
    rhet = W("we've failed failed failed", 0)
    assert len(remove_retakes(rhet)) == 4
    parallel = W("If you're not failing you're not trying hard enough", 0)
    assert len(remove_retakes(parallel)) == 9


def test_tight_plan_cuts_pauses_fillers_and_moves_hook():
    plan = build_plan(WORDS, 15.0, STYLE1, mode="tight", hook=(9.0, 11.6))
    text = " ".join(w["w"] for w in plan.words)
    assert text.startswith("Which at the time")          # hook moved to front
    assert "Um," not in text
    assert text.count("I made some") == 1
    assert plan.duration < 15.0 - 2.0                   # dead air removed
    assert 2.0 < plan.hook_end < 3.2
    for a, b in zip(plan.clips, plan.clips[1:]):
        assert abs(a.rec_out - b.rec_in) < 1e-6           # gapless timeline


def test_caption_rules():
    plan = build_plan(WORDS, 15.0, STYLE1, mode="tight", hook=(9.0, 11.6))
    cues = build_cues(plan.words, STYLE1["captions"], plan.hook_end)
    hook = cues[0]
    assert hook[2] == "Which at the time\nreally f*cking set us back"   # static, full sentence
    assert "If you're not failing you're\nnot trying hard enough" in [c[2] for c in cues]
    assert hook[1] == pytest.approx(plan.hook_end - 0.2, abs=1e-3)
    for s, e, t in cues:
        assert t.count("\n") <= 1
        assert all(len(line) <= 28 for line in t.split("\n"))
        assert not any(c in t for c in ".,!?")
    # line-by-line reveal: some cue is line 1 alone followed by line 1 + line 2
    pairs = [(a[2], b[2]) for a, b in zip(cues, cues[1:])]
    assert any("\n" not in a and b.startswith(a + "\n") for a, b in pairs)


@pytest.fixture(scope="module")
def media(tmp_path_factory):
    d = tmp_path_factory.mktemp("media")
    ff = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error"]
    subprocess.run(ff + ["-f", "lavfi", "-i", "testsrc2=s=1080x1920:r=24000/1001:d=15", "-f", "lavfi",
                         "-i", "sine=f=220:d=15", "-ac", "2", "-shortest", str(d / "clip.mp4")], check=True)
    (d / "clip.mp4.words.json").write_text(json.dumps(WORDS))
    lib = d / "broll"; lib.mkdir()
    subprocess.run(ff + ["-f", "lavfi", "-i", "testsrc=s=1920x1080:r=30:d=5", str(lib / "six-figure-mistakes-money.mp4")], check=True)
    subprocess.run(ff + ["-f", "lavfi", "-i", "color=c=red:s=800x800:d=1", "-frames:v", "1", str(lib / "telling-crowd.png")], check=True)
    subprocess.run(ff + ["-f", "lavfi", "-i", "sine=f=440:d=30", "-ac", "2", str(d / "music.mp3")], check=True)
    subprocess.run(ff + ["-f", "lavfi", "-i", "color=c=black@0.0:s=1080x1920,format=rgba", "-f", "lavfi",
                         "-i", "color=c=white:s=300x120,format=rgba", "-filter_complex", "[0][1]overlay=80:200",
                         "-frames:v", "1", str(d / "title.png")], check=True)
    srt = d / "precut.srt"
    srt.write_text("1\n00:00:00,500 --> 00:00:03,000\nIf you're not failing you're not trying.\n\n"
                   "2\n00:00:05,000 --> 00:00:08,000\nI made some six figure mistakes\n\n"
                   "3\n00:00:08,100 --> 00:00:09,600\nWe got 29,000 affiliates.\n\n"
                   "4\n00:00:10,000 --> 00:00:12,000\nBut I'm telling you it's possible.\n")
    return d


def _check_xml(path, expect_tracks):
    root = ET.parse(path).getroot()
    seq = root.find("sequence")
    assert seq.find("rate/timebase").text == "24" and seq.find("rate/ntsc").text == "TRUE"
    assert len(seq.findall("media/video/track")) == 4
    for kind, n in expect_tracks.items():
        assert sum(1 for t in seq.findall(f"media/{kind}/track") if t.find("clipitem") is not None) == n
    for ci in seq.iter("clipitem"):
        assert int(ci.find("end").text) > int(ci.find("start").text)
    return seq


def test_style01_end_to_end(media, tmp_path):
    main(["edit", str(media / "clip.mp4"), "--style", "style-01-raw-captions", "--mode", "tight",
          "--hook", "9.0-11.6", "--title-card", str(media / "title.png"), "--music", str(media / "music.mp3"),
          "--out", str(tmp_path), "--preview", "full"])
    out = tmp_path / "clip"
    _check_xml(out / "clip.xml", {"video": 2, "audio": 4})   # V1 + title card; A1/A2 + music L/R
    assert (out / "clip_captions.srt").read_text().count("-->") >= 6
    prev = probe(out / "clip_preview.mp4")
    plan = json.loads((out / "clip_plan.json").read_text())
    assert prev.width == 1080 and prev.height == 1920
    assert abs(prev.duration - plan["duration"]) < 0.3

    def title_luma(t):
        raw = subprocess.run(["ffmpeg", "-v", "error", "-ss", str(t), "-i", str(out / "clip_preview.mp4"), "-frames:v", "1",
                              "-vf", "crop=200:60:130:230,format=gray", "-f", "rawvideo", "-"], capture_output=True).stdout
        return sum(raw) / len(raw)
    assert title_luma(1.5) > 240                        # title card visible during the hook
    assert title_luma(plan["hook_end"] + 1.0) < 240     # and gone after it


def test_style02_slots_layouts_counters_and_fill(media, tmp_path):
    main(["edit", str(media / "clip.mp4"), "--style", "style-02-broll-story", "--srt", str(media / "precut.srt"),
          "--broll-dir", str(media / "broll"), "--music", str(media / "music.mp3"), "--title-card", str(media / "title.png"),
          "--out", str(tmp_path), "--preview"])
    out = tmp_path / "clip"
    plan = json.loads((out / "clip_plan.json").read_text())
    assert plan["mode"] == "none"
    assert {c["scale"] for c in plan["clips"]} == {100, 115}                               # punch-ins
    assert (out / "clip_captions.srt").read_text() == (media / "precut.srt").read_text()  # client SRT untouched
    assert probe(out / "clip_preview.mp4").width == 540                                    # fast draft

    slots = {s["id"]: s for s in json.loads((out / "slots.json").read_text())}
    assert set(slots) == {"B01", "B02", "G01"}
    b1, b2, g1 = slots["B01"], slots["B02"], slots["G01"]
    assert b1["start"] < plan["hook_end"] and b1["layout"] == "split" and b1["file"] is None
    assert Path(b2["file"]).name == "six-figure-mistakes-money.mp4" and "mistakes" in b2["keywords"]
    assert g1["type"] == "counter" and g1["number"] == "29,000" and g1["label"] == "affiliates"
    assert Path(g1["file"]).exists() and b2["start"] + b2["duration"] <= g1["start"]
    assert (out / "placeholders" / "B01.png").exists()

    seq = _check_xml(out / "clip.xml", {"video": 4, "audio": 4})
    v1, v2, v3, v4 = seq.findall("media/video/track")
    # speaker moved to the top half only while the split-screen slot is on
    moved = [c for c in v1.findall("clipitem") if c.find(".//parameter[parameterid='center']") is not None]
    assert moved and all(int(c.find("start").text) >= round(b1["start"] * 23.976) - 1 for c in moved)
    assert [c.find("name").text for c in v2.findall("clipitem")] == ["six-figure-mistakes-money.mp4"]  # blurred bg
    assert v2.find(".//effect[name='Gaussian Blur']") is not None
    assert [c.find("name").text for c in v3.findall("clipitem")] == ["B01.png", "six-figure-mistakes-money.mp4", "G01.mp4"]
    assert v4.find("clipitem") is not None                                                # name tag after the hook
    assert int(v4.find("clipitem/start").text) == round(plan["hook_end"] * 23.976)
    names = [m.find("name").text for m in seq.findall("marker")]
    assert any(n.startswith("B01 EMPTY") for n in names) and len(names) == 3

    # editor drops a file named after the slot, then runs `fill`
    shutil.copy(media / "broll" / "telling-crowd.png", out / "broll" / "B01.png")
    main(["fill", str(out)])
    slots = {s["id"]: s for s in json.loads((out / "slots.json").read_text())}
    assert slots["B01"]["source"] == "dropped" and slots["B02"]["file"].endswith("six-figure-mistakes-money.mp4")
    seq = ET.parse(out / "clip.xml").getroot().find("sequence")
    assert all("EMPTY" not in m.find("name").text for m in seq.findall("marker"))

    # editor overrides a slot by typing a library name into slots.json
    lst = json.loads((out / "slots.json").read_text())
    next(s for s in lst if s["id"] == "B02")["file"] = "telling-crowd"
    (out / "slots.json").write_text(json.dumps(lst))
    (out / "broll" / "B01.png").unlink()
    main(["fill", str(out)])
    slots = {s["id"]: s for s in json.loads((out / "slots.json").read_text())}
    assert Path(slots["B02"]["file"]).name == "telling-crowd.png" and slots["B02"]["source"] == "label"


def test_chunk_captions_keep_phrases_and_emphasise_key_ones():
    from autoedit.captions import build_chunks
    ws = W("We had a competition where the top ten could win a session with Alex and then anyone who "
           "referred ten people got a bonus chapter for free. 29,000 affiliates in six weeks.", 0, 0.3)
    normal, strong = build_chunks(ws, STYLE2["captions"])
    chunks = [c[2] for c in sorted(normal + strong)]
    assert "the top ten" in chunks and "for free" in chunks and "29,000 affiliates" in [c[2] for c in strong]
    assert all(1 <= len(c.split()) <= 3 for c in chunks)
    assert 0 < len(strong) <= round(0.3 * len(chunks))
    em = sorted(strong)
    assert all(b[0] >= a[1] for a, b in zip(em, em[1:]))     # never two emphasis chunks back to back
    allc = sorted(normal + strong)
    assert all(b[0] >= a[1] - 1e-6 for a, b in zip(allc, allc[1:]))   # one chunk on screen at a time


def test_style02_restyled_captions_two_tracks(media, tmp_path):
    main(["edit", str(media / "clip.mp4"), "--style", "style-02-broll-story", "--srt", str(media / "precut.srt"),
          "--restyle-captions", "--no-placeholders", "--out", str(tmp_path)])
    out = tmp_path / "clip"
    assert (out / "clip_captions.srt").exists() and (out / "clip_captions_emphasis.srt").exists()
    from autoedit.srt import read_srt
    cues = read_srt(out / "clip_captions.srt") + read_srt(out / "clip_captions_emphasis.srt")
    g1 = next(s for s in json.loads((out / "slots.json").read_text()) if s["type"] == "counter")
    assert cues and not any(s < g1["start"] + g1["duration"] - 0.01 and e > g1["start"] + 0.01 for s, e, _ in cues)


def test_counter_graphic_counts_up(tmp_path):
    from autoedit.graphics import fmt, make_counter, parse_number
    assert parse_number("29,000") == (29000, "", "", True) and parse_number("$100k")[0] == 100000
    assert fmt(5142.4, "", "", True) == "5,142" and fmt(100000, "$", "k", False) == "$100k"
    f = make_counter("29,000", "affiliates", 2.0, tmp_path / "c.mp4", 540, 960, 30)
    info = probe(f)
    assert info.width == 540 and abs(info.duration - 2.0) < 0.1


def test_plan_slots_without_library():
    from autoedit.broll import plan_slots
    words = W("So we started the company in a tiny garage with two laptops and a dog. "
              "Then investors flew in from London to see the prototype.", 0.0, step=0.4)
    slots = plan_slots(words, 25.0, STYLE2["broll"], hook_end=2.0)
    assert slots and all(s["file"] is None for s in slots)
    for a, b in zip(slots, slots[1:]):
        assert b["start"] - (a["start"] + a["duration"]) >= STYLE2["broll"]["min_gap"] - 1e-6
    assert all(STYLE2["broll"]["min_len"] * 0.8 <= s["duration"] <= STYLE2["broll"]["max_len"] for s in slots)
    assert any(k in ("garage", "laptops", "investors", "prototype", "company", "london") for s in slots for k in s["keywords"])


def test_analyze_reference(media, tmp_path):
    from autoedit.analyze import analyze
    main(["edit", str(media / "clip.mp4"), "--style", "style-01-raw-captions", "--mode", "tight",
          "--hook", "9.0-11.6", "--out", str(tmp_path), "--preview", "full"])
    rep = analyze(tmp_path / "clip" / "clip_preview.mp4", tmp_path / "an")
    assert rep["captions"] and 40 < rep["captions"]["band_y_pct"][0] < 52 and rep["captions"]["max_lines"] == 2
    assert (tmp_path / "an" / "report.md").exists() and (tmp_path / "an" / "sheet_01.jpg").exists()


def test_batch_parallel_and_skip(media, tmp_path, capsys):
    inbox = tmp_path / "inbox"; inbox.mkdir()
    for n in ("a", "b"):
        shutil.copy(media / "clip.mp4", inbox / f"{n}.mp4")
        shutil.copy(media / "precut.srt", inbox / f"{n}.srt")
    args = ["batch", str(inbox), "--style", "style-02-broll-story", "--out", str(tmp_path / "out"), "--jobs", "2"]
    with pytest.raises(SystemExit) as e:
        main(args)
    assert e.value.code == 0 and (tmp_path / "out" / "a" / "a.xml").exists() and (tmp_path / "out" / "b" / "b.xml").exists()
    with pytest.raises(SystemExit):
        main(args)
    assert "skipping 2 already-finished" in capsys.readouterr().out


def test_ai_picker_prompt_is_small_and_validated(monkeypatch):
    from types import SimpleNamespace
    from autoedit import ai
    sent = {}

    class FakeMessages:
        def create(self, **kw):
            sent.update(kw)
            text = '{"B01": "L0002", "B02": "L9999", "B03": null}'   # one valid, one hallucinated id, one null
            return SimpleNamespace(stop_reason="end_turn", content=[SimpleNamespace(type="text", text=text)])

    monkeypatch.setattr(ai, "_client", lambda: SimpleNamespace(beta=SimpleNamespace(messages=FakeMessages())))
    lib = [{"id": f"L{n:04d}", "file": f"/lib/{n}.mp4", "tags": {t}, "desc": ""}
           for n, t in enumerate(["dog", "garage", "laptop"] + [f"misc{k}" for k in range(100)], 1)]
    slots = [{"id": f"B0{k}", "duration": 2.0, "phrase": p, "keywords": p.split()}
             for k, p in enumerate(["tiny garage", "two laptops", "the dog"], 1)]
    picks = ai.make_picker(limit=40)(slots, lib)
    assert picks == {"B01": "/lib/2.mp4"}                       # invalid / null ids dropped
    prompt = sent["messages"][0]["content"]
    assert isinstance(prompt, str) and prompt.count("\nL") <= 40   # text only, shortlisted library
    assert "garage" in prompt and len(prompt) < 4000
