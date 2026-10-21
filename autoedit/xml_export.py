"""Writes the edit as Final Cut Pro 7 XML (xmeml v4), which Premiere Pro imports
natively via File > Import. Track layout:

  V1  talking head (cuts + punch-in scale)    A1/A2  talking-head audio (L/R)
  V2  b-roll                                  A3/A4  music bed (L/R, fixed gain)
  V3  title card (hook only, dissolves)
Captions travel separately as an .srt (Premiere caption track).
"""
from pathlib import Path
from urllib.parse import quote
from xml.sax.saxutils import escape

from .media import snap_fps


def pathurl(p):
    p = Path(p).resolve().as_posix()
    if not p.startswith("/"):          # Windows drive path C:/...
        p = "/" + p
    return "file://localhost" + quote(p)


class XmlWriter:
    def __init__(self, fps):
        self.timebase, self.ntsc, self.fps = snap_fps(fps)
        self.files = {}
        self.n = 0

    def f(self, t):
        return int(round(t * self.fps))

    def rate(self):
        return f"<rate><timebase>{self.timebase}</timebase><ntsc>{'TRUE' if self.ntsc else 'FALSE'}</ntsc></rate>"

    def file_el(self, info, still=False):
        key = str(info.path)
        if key in self.files:
            return f'<file id="{self.files[key]}"/>'
        fid = f"file-{len(self.files) + 1}"
        self.files[key] = fid
        dur = self.f(info.duration) if not still else self.f(3600)
        media = ""
        if info.width:
            media += (f"<video><samplecharacteristics>{self.rate()}<width>{info.width}</width>"
                      f"<height>{info.height}</height></samplecharacteristics></video>")
        if info.has_audio:
            media += (f"<audio><samplecharacteristics><depth>16</depth><samplerate>{info.sample_rate}"
                      f"</samplerate></samplecharacteristics><channelcount>{info.audio_channels}</channelcount></audio>")
        return (f'<file id="{fid}"><name>{escape(info.path.name)}</name><pathurl>{pathurl(info.path)}</pathurl>'
                f"{self.rate()}<duration>{dur}</duration><media>{media}</media></file>")

    def clip(self, info, rec_in, rec_out, src_in, kind="video", src_track=1, filters="", still=False, cid=None, links=""):
        self.n += 1
        cid = cid or f"clipitem-{self.n}"
        start, end = self.f(rec_in), self.f(rec_out)
        i = self.f(src_in)
        o = i + (end - start)
        dur = self.f(info.duration) if not still else self.f(3600)
        st = (f"<sourcetrack><mediatype>audio</mediatype><trackindex>{src_track}</trackindex></sourcetrack>"
              if kind == "audio" else "")
        return (f'<clipitem id="{cid}"><name>{escape(info.path.name)}</name><enabled>TRUE</enabled>'
                f"<duration>{dur}</duration>{self.rate()}<start>{start}</start><end>{end}</end>"
                f"<in>{i}</in><out>{o}</out>{self.file_el(info, still)}{st}{filters}{links}</clipitem>")

    @staticmethod
    def motion(scale):
        return ("<filter><effect><name>Basic Motion</name><effectid>basic</effectid><effectcategory>motion</effectcategory>"
                "<effecttype>motion</effecttype><mediatype>video</mediatype><parameter authoringApp=\"PremierePro\">"
                f"<parameterid>scale</parameterid><name>Scale</name><valuemin>0</valuemin><valuemax>1000</valuemax>"
                f"<value>{scale:.2f}</value></parameter></effect></filter>")

    @staticmethod
    def level(db):
        return ("<filter><effect><name>Audio Levels</name><effectid>audiolevels</effectid><effectcategory>audiolevels"
                "</effectcategory><effecttype>audiolevels</effecttype><mediatype>audio</mediatype><parameter>"
                f"<parameterid>level</parameterid><name>Level</name><valuemin>0</valuemin><valuemax>3.98109</valuemax>"
                f"<value>{10 ** (db / 20):.5f}</value></parameter></effect></filter>")

    def transition(self, a, b, align, media="video"):
        name, eid = (("Cross Dissolve", "Cross Dissolve") if media == "video"
                     else ("Cross Fade (+3dB)", "KGAudioTransCrossFade3dB"))
        return (f"<transitionitem>{self.rate()}<start>{self.f(a)}</start><end>{self.f(b)}</end>"
                f"<alignment>{align}</alignment><effect><name>{name}</name><effectid>{eid}</effectid>"
                f"<effectcategory>Dissolve</effectcategory><effecttype>transition</effecttype>"
                f"<mediatype>{media}</mediatype></effect></transitionitem>")


def fill_scale(info, w, h):
    if not info.width:
        return 100.0
    return max(w / info.width, h / info.height) * 100


def write_xml(path, name, plan, src_info, style, broll=None, title_card=None, music=None):
    W, H = style["sequence"]["width"], style["sequence"]["height"]
    x = XmlWriter(src_info.fps)
    base = fill_scale(src_info, W, H)

    v1, a1, a2 = [], [], []
    for k, c in enumerate(plan.clips):
        ids = [f"v1-{k}", f"a1-{k}", f"a2-{k}"]
        links = "".join(
            f"<link><linkclipref>{cid}</linkclipref><mediatype>{mt}</mediatype><trackindex>{ti}</trackindex>"
            f"<clipindex>{k + 1}</clipindex></link>"
            for cid, mt, ti in zip(ids, ["video", "audio", "audio"], [1, 1, 2]))
        v1.append(x.clip(src_info, c.rec_in, c.rec_out, c.src_in, filters=x.motion(base * c.scale / 100),
                         cid=ids[0], links=links))
        if src_info.has_audio:
            a1.append(x.clip(src_info, c.rec_in, c.rec_out, c.src_in, "audio", 1, cid=ids[1], links=links))
            a2.append(x.clip(src_info, c.rec_in, c.rec_out, c.src_in, "audio", min(2, src_info.audio_channels),
                             cid=ids[2], links=links))

    v2 = []
    for p in broll or []:
        info = p["info"]
        v2.append(x.clip(info, p["start"], p["start"] + p["duration"], p.get("src_in", 0.0),
                         filters=x.motion(fill_scale(info, W, H)), still=p["still"]))

    v3 = []
    if title_card:
        tc_info, tc_in, tc_out = title_card
        fd = style["title_card"].get("fade_duration", 0.25)
        v3 = [x.transition(tc_in, tc_in + fd, "start"),
              x.clip(tc_info, tc_in, tc_out, 0.0, filters=x.motion(fill_scale(tc_info, W, H)), still=True),
              x.transition(tc_out - fd, tc_out, "end")]

    m1, m2 = [], []
    if music:
        m_info, mcfg = music
        m_end = min(plan.duration, m_info.duration)
        for track, ch in ((m1, 1), (m2, min(2, m_info.audio_channels))):
            track.append(x.transition(0, mcfg.get("fade_in", 0.3), "start", "audio"))
            track.append(x.clip(m_info, 0.0, m_end, 0.0, "audio", ch, filters=x.level(mcfg["level_db"])))
            track.append(x.transition(m_end - mcfg.get("fade_out", 1.0), m_end, "end", "audio"))

    def track(items):
        return f"<track>{''.join(items)}</track>"

    video = "".join(track(t) for t in (v1, v2, v3))
    audio = "".join(track(t) for t in (a1, a2, m1, m2) if t) or track([])
    xml = (
        '<?xml version="1.0" encoding="UTF-8"?>\n<!DOCTYPE xmeml>\n<xmeml version="4">'
        f'<sequence id="sequence-1"><name>{escape(name)}</name><duration>{x.f(plan.duration)}</duration>{x.rate()}'
        f"<media><video><format><samplecharacteristics>{x.rate()}<width>{W}</width><height>{H}</height>"
        "<pixelaspectratio>square</pixelaspectratio><fielddominance>none</fielddominance></samplecharacteristics>"
        f"</format>{video}</video><audio><numOutputChannels>2</numOutputChannels><format><samplecharacteristics>"
        f"<depth>16</depth><samplerate>48000</samplerate></samplecharacteristics></format>{audio}</audio></media>"
        "</sequence></xmeml>\n"
    )
    Path(path).write_text(xml, encoding="utf-8")
