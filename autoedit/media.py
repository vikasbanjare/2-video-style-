"""ffprobe helpers."""
import json
import subprocess
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path


@dataclass
class MediaInfo:
    path: Path
    duration: float
    width: int = 0
    height: int = 0
    fps: Fraction = Fraction(0)
    has_audio: bool = False
    audio_channels: int = 0
    sample_rate: int = 48000


def probe(path) -> MediaInfo:
    path = Path(path).resolve()
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_format", "-show_streams", "-of", "json", str(path)],
        check=True, capture_output=True, text=True,
    ).stdout
    data = json.loads(out)
    info = MediaInfo(path=path, duration=float(data["format"].get("duration", 0) or 0))
    for s in data["streams"]:
        if s["codec_type"] == "video" and not info.width:
            info.width, info.height = int(s["width"]), int(s["height"])
            rate = s.get("avg_frame_rate") or s.get("r_frame_rate") or "0/1"
            if rate in ("0/0", "0/1"):
                rate = s.get("r_frame_rate", "0/1")
            info.fps = Fraction(rate) if rate not in ("0/0",) else Fraction(0)
            # PNG/JPG stills report a bogus rate; callers treat fps==0 or 25 as "still"
        elif s["codec_type"] == "audio" and not info.has_audio:
            info.has_audio = True
            info.audio_channels = int(s.get("channels", 2))
            info.sample_rate = int(s.get("sample_rate", 48000))
    return info


def snap_fps(fps: Fraction) -> tuple[int, bool, Fraction]:
    """Return (timebase, ntsc, exact fps) for an XML <rate>, snapping 23.976/29.97/59.94."""
    f = float(fps) or 24.0
    for base in (24, 25, 30, 50, 60):
        if abs(f - base * 1000 / 1001) < 0.01:
            return base, True, Fraction(base * 1000, 1001)
        if abs(f - base) < 0.01:
            return base, False, Fraction(base)
    return round(f), False, Fraction(round(f))
