"""Renders a quick MP4 of the planned edit with ffmpeg, so an edit can be
checked (or even shipped) without opening Premiere. Mirrors the XML: cuts,
punch-ins, b-roll, title card, burned captions, music bed, -14 LUFS."""
import subprocess
from pathlib import Path


def _ass_time(t):
    cs = int(round(max(0, t) * 100))
    h, cs = divmod(cs, 360000)
    m, cs = divmod(cs, 6000)
    s, cs = divmod(cs, 100)
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def write_ass(cues, look, W, H, path):
    size = look["size_px_at_1080w"] * W / 1080
    sh = look.get("shadow") or {"opacity": 0, "distance_px": 0}
    alpha = format(int(255 * (1 - sh["opacity"])), "02X")
    y = H * look["center_y_pct"] / 100
    font = look.get("font_fallback", "Inter SemiBold")
    head = (
        "[Script Info]\nScriptType: v4.00+\n"
        f"PlayResX: {W}\nPlayResY: {H}\nWrapStyle: 2\nScaledBorderAndShadow: yes\n\n"
        "[V4+ Styles]\nFormat: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, "
        "Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, "
        "Alignment, MarginL, MarginR, MarginV, Encoding\n"
        f"Style: Cap,{font},{size:.0f},&H00FFFFFF,&H00FFFFFF,&H00000000,&H{alpha}000000,0,0,0,0,100,100,0,0,1,0,"
        f"{sh.get('distance_px', 1)},5,0,0,0,1\n\n"
        "[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
    )
    lines = [f"Dialogue: 0,{_ass_time(s)},{_ass_time(e)},Cap,,0,0,0,,{{\\pos({W / 2:.0f},{y:.0f})\\blur{sh.get('blur_px', 0) / 3:.1f}}}"
             + t.replace("\n", "\\N") for s, e, t in cues]
    Path(path).write_text(head + "\n".join(lines) + "\n", encoding="utf-8")


def _fill(W, H, z=1.0):
    return (f"scale={int(W * z)}:{int(H * z)}:force_original_aspect_ratio=increase,"
            f"crop={W}:{H},setsar=1")


def render(out, plan, src_info, style, cues=None, broll=None, title_card=None, music=None, workdir=None, fast=False):
    if fast:  # half-resolution draft: ~4x fewer pixels, fastest x264 preset
        style = dict(style, sequence={"width": style["sequence"]["width"] // 2,
                                      "height": style["sequence"]["height"] // 2})
    W, H = style["sequence"]["width"], style["sequence"]["height"]
    fps = float(src_info.fps) or 24
    # one seeked input per shot: each decodes only its own seconds (a single input
    # split into N trims would push every frame through every branch)
    inputs, fc, vlabels = [], [], []
    for k, c in enumerate(plan.clips):
        inputs += ["-ss", f"{c.src_in:.4f}", "-t", f"{c.src_out - c.src_in:.4f}", "-i", str(src_info.path)]
        fc.append(f"[{k}:v]setpts=PTS-STARTPTS,fps={fps},{_fill(W, H, c.scale / 100)}[v{k}]")
        vlabels.append(f"[v{k}]")
        if src_info.has_audio:
            fc.append(f"[{k}:a]asetpts=PTS-STARTPTS[a{k}]")
            vlabels.append(f"[a{k}]")
    n = len(plan.clips)
    fc.append(f"{''.join(vlabels)}concat=n={n}:v=1:a={1 if src_info.has_audio else 0}[base]"
              + ("[aud]" if src_info.has_audio else ""))
    cur = "[base]"
    idx = n
    for j, p in enumerate(broll or []):
        a, d = p["start"], p["duration"]
        if p["still"]:
            inputs += ["-loop", "1", "-t", f"{d:.3f}", "-i", p["file"]]
            src = f"[{idx}:v]fps={fps},"
        else:
            inputs += ["-i", p["file"]]
            src = f"[{idx}:v]trim=start={p.get('src_in', 0):.3f}:duration={d:.3f},fps={fps},"
        fc.append(f"{src}setpts=PTS-STARTPTS+{a:.3f}/TB,{_fill(W, H)}[b{j}]")
        fc.append(f"{cur}[b{j}]overlay=enable='between(t,{a:.3f},{a + d:.3f})':eof_action=pass[o{j}]")
        cur = f"[o{j}]"
        idx += 1
    if title_card:
        tc_info, tc_in, tc_out = title_card
        fd = style["title_card"].get("fade_duration", 0.25)
        inputs += ["-loop", "1", "-t", f"{tc_out:.3f}", "-i", str(tc_info.path)]
        fc.append(f"[{idx}:v]fps={fps},format=rgba,{_fill(W, H)},fade=in:st={tc_in:.3f}:d={fd}:alpha=1,"
                  f"fade=out:st={tc_out - fd:.3f}:d={fd}:alpha=1[tc]")
        fc.append(f"{cur}[tc]overlay=eof_action=pass[otc]")
        cur = "[otc]"
        idx += 1
    if cues:
        ass = Path(workdir or Path(out).parent) / (Path(out).stem + ".ass")
        write_ass(cues, style["caption_look"], W, H, ass)
        esc = str(ass).replace("\\", "/").replace(":", "\\:").replace("'", "\\'")
        fc.append(f"{cur}ass='{esc}'[vout]")
        cur = "[vout]"
    alab = "[aud]" if src_info.has_audio else None
    if music:
        m_info, mcfg = music
        inputs += ["-i", str(m_info.path)]
        end = min(plan.duration, m_info.duration)
        fc.append(f"[{idx}:a]atrim=0:{end:.3f},asetpts=PTS-STARTPTS,volume={mcfg['level_db']}dB,"
                  f"afade=in:d={mcfg.get('fade_in', 0.3)},afade=out:st={end - mcfg.get('fade_out', 1.0):.3f}:d={mcfg.get('fade_out', 1.0)}[mus]")
        if alab:
            fc.append("[aud][mus]amix=inputs=2:duration=first:normalize=0[mix]")
            alab = "[mix]"
        else:
            alab = "[mus]"
    if alab:
        lufs = style.get("deliver", {}).get("loudness_lufs", -14)
        fc.append(f"{alab}loudnorm=I={lufs}:TP=-1:LRA=11,aresample=48000[afinal]")
    cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", *inputs, "-filter_complex", ";".join(fc),
           "-map", cur] + (["-map", "[afinal]"] if alab else []) + [
           "-r", f"{fps}", "-c:v", "libx264", "-preset", "ultrafast" if fast else "veryfast", "-crf", "28" if fast else "20", "-pix_fmt", "yuv420p",
           "-c:a", "aac", "-b:a", "192k", "-t", f"{plan.duration:.3f}", str(out)]
    subprocess.run(cmd, check=True)
