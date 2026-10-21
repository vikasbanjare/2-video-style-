import json
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
                   "3\n00:00:10,000 --> 00:00:12,000\nBut I'm telling you it's possible.\n")
    return d


def _check_xml(path, expect_tracks):
    root = ET.parse(path).getroot()
    seq = root.find("sequence")
    assert seq.find("rate/timebase").text == "24" and seq.find("rate/ntsc").text == "TRUE"
    assert len(seq.findall("media/video/track")) == 3
    for kind, n in expect_tracks.items():
        assert sum(1 for t in seq.findall(f"media/{kind}/track") if t.find("clipitem") is not None) == n
    for ci in seq.iter("clipitem"):
        assert int(ci.find("end").text) > int(ci.find("start").text)
    return seq


def test_style01_end_to_end(media, tmp_path):
    main(["edit", str(media / "clip.mp4"), "--style", "style-01-raw-captions", "--mode", "tight",
          "--hook", "9.0-11.6", "--title-card", str(media / "title.png"), "--music", str(media / "music.mp3"),
          "--out", str(tmp_path), "--preview"])
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


def test_style02_precut_srt_broll_zoom(media, tmp_path):
    main(["edit", str(media / "clip.mp4"), "--style", "style-02-broll-story", "--srt", str(media / "precut.srt"),
          "--broll-dir", str(media / "broll"), "--music", str(media / "music.mp3"), "--out", str(tmp_path), "--preview"])
    out = tmp_path / "clip"
    plan = json.loads((out / "clip_plan.json").read_text())
    assert plan["mode"] == "none"
    assert len(plan["clips"]) >= 2 and {c["scale"] for c in plan["clips"]} == {100, 112}
    assert [Path(b["file"]).name for b in plan["broll"]] == ["six-figure-mistakes-money.mp4", "telling-crowd.png"]
    seq = _check_xml(out / "clip.xml", {"video": 2, "audio": 4})
    assert (out / "clip_captions.srt").read_text() == (media / "precut.srt").read_text()  # client SRT untouched
    assert probe(out / "clip_preview.mp4").duration > 14
