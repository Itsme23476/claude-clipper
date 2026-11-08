#!/usr/bin/env python3
"""Turn one long video into vertical Shorts. Stdlib, plus ffmpeg, whisper-cli and Swift.

  clipper.py prep VIDEO_OR_LINK [--out DIR]   transcribe it, write words.json and transcript.txt
  clipper.py render DIR [--only 1,3]          cut the clips listed in DIR/picks.json
  clipper.py test                             self-check
"""
# ponytail: macOS only (Vision and AppKit through vision.swift, because this ffmpeg has no
# caption filters). Swap vision.swift for OpenCV and Pillow to support Windows and Linux.
import argparse
import json
import os
import re
import shutil
import statistics
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
STYLE = {"font": "Arial Black", "size": 76, "color": "#FFFFFF", "highlight": "#FFD400", "stroke": "#000000",
         "stroke_width": 16, "y": 0.66, "max_words": 3, "upper": True, "zoom": 1.12}
W, H, CAP_H = 1080, 1920, 360


def run(*cmd, **kw):
    r = subprocess.run([str(c) for c in cmd], text=True, capture_output=True, **kw)
    if r.returncode:
        sys.exit(f"{cmd[0]} failed: {r.stderr.strip()[-800:]}")
    return r.stdout


def slug(text):
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:50] or "clip"


def even(n):
    return int(n) // 2 * 2


def find_model():
    for p in [os.environ.get("WHISPER_MODEL"), "~/.cache/whisper/ggml-base.en.bin",
              "/opt/homebrew/share/whisper-cpp/ggml-base.en.bin"]:
        if p and Path(p).expanduser().exists():
            return Path(p).expanduser()
    sys.exit("No Whisper model found. Set WHISPER_MODEL to a ggml-*.bin file.")


def sentences(words):
    """[(start, text)] so the picker can see where each line begins."""
    out, cur, start = [], [], 0.0
    for i, w in enumerate(words):
        if not cur:
            start = w["s"]
        cur.append(w["w"])
        gap = words[i + 1]["s"] - w["e"] if i + 1 < len(words) else 9
        if w["w"][-1] in ".?!" or gap > 1.0:
            out.append((start, " ".join(cur)))
            cur = []
    return out


def prep(src, out):
    is_link = re.match(r"https?://", src)
    name = "video" if is_link else Path(src).stem
    out = Path(out or f"~/Desktop/Clips/{slug(name)}").expanduser()
    out.mkdir(parents=True, exist_ok=True)
    if is_link:
        if not shutil.which("yt-dlp"):
            sys.exit("Missing yt-dlp, which is needed for links. Ask the user before installing it.")
        run("yt-dlp", "-q", "-f", "bv*[height<=1080]+ba/b[height<=1080]", "--merge-output-format", "mp4",
            "-o", out / "source.mp4", src)
        video = out / "source.mp4"
    else:
        video = Path(src).expanduser().resolve()
    wav = out / "audio.wav"
    run("ffmpeg", "-y", "-v", "error", "-i", video, "-vn", "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", wav)
    run("whisper-cli", "-m", find_model(), "-f", wav, "-ml", "1", "-sow", "-oj", "-of", out / "whisper", "-np")
    wav.unlink()
    raw = json.loads((out / "whisper.json").read_text())["transcription"]
    words = [{"w": t, "s": r["offsets"]["from"] / 1000, "e": r["offsets"]["to"] / 1000}
             for r in raw if (t := r["text"].strip()) and not t.startswith(("[", "("))]
    (out / "words.json").write_text(json.dumps(words))
    (out / "meta.json").write_text(json.dumps({"source": str(video)}))
    (out / "transcript.txt").write_text("".join(f"[{s:.1f}] {t}\n" for s, t in sentences(words)))
    print(f"{len(words)} words. Transcript: {out / 'transcript.txt'}")


def clean(word):
    return re.sub(r"[^\w$%']", "", word.lower())


def apply_fixes(words, fix):
    """Correct misheard names. A key of several words, like "open out there", merges into one."""
    keys = {tuple(clean(x) for x in k.split()): v for k, v in fix.items()}
    out, i = [], 0
    while i < len(words):
        for key, value in keys.items():
            part = words[i : i + len(key)]
            if tuple(clean(w["w"]) for w in part) == key:
                tail = re.search(r"[.,?!]*$", part[-1]["w"]).group()
                out.append({"w": value + tail, "s": part[0]["s"], "e": part[-1]["e"]})
                i += len(key)
                break
        else:
            out.append(words[i])
            i += 1
    return out


def chunk_words(words, highlights, max_words):
    """Caption groups: [{"a": start, "b": end, "words": [{"t", "hl"}]}]."""
    keys = {clean(k) for h in highlights for k in h.split()}
    chunks, cur = [], []
    for i, w in enumerate(words):
        cur.append(w)
        gap = words[i + 1]["s"] - w["e"] if i + 1 < len(words) else 9
        if len(cur) == max_words or w["w"][-1] in ".?!," or gap > 0.4:
            chunks.append({"a": cur[0]["s"], "b": cur[-1]["e"],
                           "words": [{"t": x["w"].strip(".,"), "hl": clean(x["w"]) in keys} for x in cur]})
            cur = []
    for c, nxt in zip(chunks, chunks[1:]):  # hold each caption until the next, across short pauses
        c["b"] = min(nxt["a"], c["b"] + 0.25)
    return chunks


def timeline(chunks, duration):
    """[(chunk index or None for blank, seconds)] covering the clip with no overlaps."""
    out, t = [], 0.0
    for i, c in enumerate(chunks):
        if c["a"] > t:
            out.append((None, c["a"] - t))
        out.append((i, max(c["b"] - max(c["a"], t), 0.04)))
        t = c["b"]
    if duration > t:
        out.append((None, duration - t))
    return out


def zoom_windows(words, highlights, hold=2.0, spacing=4.0):
    """Punch in on the first time each highlighted word is spoken."""
    keys, out = {clean(k) for h in highlights for k in h.split()}, []
    for w in words:
        if clean(w["w"]) in keys and (not out or w["s"] >= out[-1][0] + spacing):
            out.append((w["s"], w["s"] + hold))
    return out


def x_expr(shots, xs):
    """ffmpeg expression: hold one crop position per shot, jump on each camera cut."""
    expr = str(xs[-1])
    for (_, end), x in zip(reversed(shots[:-1]), reversed(xs[:-1])):
        expr = f"if(lt(t,{end:.3f}),{x},{expr})"
    return expr


def fill_gaps(values, default=0.5):
    """Shots with no face borrow the nearest earlier one, then the next one found."""
    out, last = [], None
    for v in values:
        last = v if v is not None else last
        out.append(last)
    nxt = next((v for v in out if v is not None), default)
    return [v if v is not None else nxt for v in out]


def vision():
    if sys.platform != "darwin":
        sys.exit("clipper currently needs macOS. See the note at the top of clipper.py.")
    exe, src = Path("~/.cache/clipper/vision").expanduser(), HERE / "vision.swift"
    if not exe.exists() or exe.stat().st_mtime < src.stat().st_mtime:
        exe.parent.mkdir(parents=True, exist_ok=True)
        run("swiftc", "-O", src, "-o", exe)
    return exe


def size(video):
    w, h = run("ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height",
               "-of", "csv=p=0", video).split(",")[:2]
    return int(w), int(h)


def shots_of(video, start, length):
    log = run("ffmpeg", "-v", "error", "-ss", start, "-t", length, "-i", video, "-an", "-vf",
              "scale=320:-2,select='gt(scene,0.32)',metadata=print:file=-", "-f", "null", "-")
    edges = [0.0] + [t for t in map(float, re.findall(r"pts_time:([\d.]+)", log)) if 0.4 < t < length - 0.4] + [length]
    keep = [edges[0]]
    for t in edges[1:-1]:
        if t - keep[-1] >= 0.4:
            keep.append(t)
    return list(zip(keep, keep[1:] + [length]))


def find_faces(video, start, shots, tmp):
    frames, owner = [], []
    for i, (a, b) in enumerate(shots):
        for frac in (0.2, 0.5, 0.8):
            p = tmp / f"f{len(frames):04d}.jpg"
            run("ffmpeg", "-y", "-v", "error", "-ss", start + a + (b - a) * frac, "-i", video,
                "-frames:v", 1, "-vf", "scale=640:-2", p)
            frames.append(p)
            owner.append(i)
    lines = run(vision(), "faces", *frames).strip().splitlines()
    found = [[] for _ in shots]
    for i, line in zip(owner, lines):
        if line != "null":
            found[i].append(tuple(map(float, line.split())))
    return [tuple(statistics.median(p[i] for p in f) for i in range(3)) if f else None for f in found]


def clip_name(clip):
    return f"{clip['rank']:02d}-{slug(clip['title'])}.mp4"


def choose_layout(faces, forced=None):
    """crop: a talking head. split: a screen recording with a corner face bubble. fit: no face."""
    seen = [f for f in faces if f]
    if forced and (seen or forced == "fit"):
        return forced
    if len(seen) <= len(faces) * 0.4:
        return "fit"
    x, y = (statistics.median(f[i] for f in seen) for i in (0, 1))
    return "split" if abs(x - 0.5) > 0.25 and abs(y - 0.5) > 0.15 else "crop"


def zoomed(src, dst, w, h, windows, zoom, anchor):
    """Punch in by overlaying a slightly enlarged copy during each window."""
    if not windows:
        return f"[{src}]null[{dst}]"
    z_w, z_h = even(w * zoom), even(h * zoom)
    on = "+".join(f"between(t,{a:.2f},{b:.2f})" for a, b in windows)
    return (f"[{src}]split[{dst}a][{dst}b];[{dst}b]scale={z_w}:{z_h}:flags=lanczos,"
            f"crop={w}:{h}:{(z_w - w) // 2}:{int((z_h - h) * anchor)}[{dst}z];"
            f"[{dst}a][{dst}z]overlay=0:0:enable='{on}'[{dst}]")


def split_boxes(src_w, src_h, fx, fy, fw):
    """Screen panel (x, w), its height on the Short, and the face crop (x, y, w, h)."""
    # ponytail: assumes the face bubble stays in one corner for the whole clip
    screen_w = even(src_w * (1 - min(fw * 2.7, 0.35)))  # leave the bubble out of the screen panel
    top_h = even(W * src_h / screen_w)
    face_w = even(min(fw * 2.3 * src_w, src_w))  # stays inside the bubble's rounded corners
    face_h = even(min(face_w * (H - top_h) / W, src_h))
    x = min(max(even(fx * src_w - face_w / 2), 0), src_w - face_w)
    y = min(max(even(fy * src_h - 0.11 * face_h - face_h / 2), 0), src_h - face_h)
    return (0 if fx > 0.5 else src_w - screen_w, screen_w), top_h, (x, y, face_w, face_h)


def render_clip(video, words, clip, style, out_dir):
    start, length = clip["start"], clip["end"] - clip["start"]
    inside = [{**w, "s": w["s"] - start, "e": w["e"] - start} for w in words
              if start <= w["s"] and w["e"] <= clip["end"]]
    highlights = clip.get("highlights", [])
    src_w, src_h = size(video)
    with tempfile.TemporaryDirectory() as t:
        tmp = Path(t)
        shots = shots_of(video, start, length)
        faces = find_faces(video, start, shots, tmp)
        windows = [(a, min(b, length)) for a, b in zoom_windows(inside, highlights)] if clip.get("zoom", True) else []
        layout = choose_layout(faces, clip.get("layout") or style.get("layout"))
        seen = [f for f in faces if f]
        caption_y = int(H * style["y"])
        if layout == "split":
            fx, fy, fw = (statistics.median(f[i] for f in seen) for i in range(3))
            (sx, sw), top_h, (x, y, cw, ch) = split_boxes(src_w, src_h, fx, fy, fw)
            caption_y = top_h  # on the seam between screen and face
            graph = (f"[0:v]split[s][f];[s]crop={sw}:{src_h}:{sx}:0,scale={W}:{top_h}:flags=lanczos,setsar=1[top];"
                     f"[f]crop={cw}:{ch}:{x}:{y},scale={W}:{H - top_h}:flags=lanczos,setsar=1[f0];"
                     + zoomed("f0", "bot", W, H - top_h, windows, style["zoom"], 0.4) + ";[top][bot]vstack[v0]")
        elif layout == "crop":
            crop_w = even(src_h * 9 / 16)
            fx = fill_gaps([f and f[0] for f in faces])
            face_y = statistics.median(f[1] for f in seen)
            xs = [min(max(even(x * src_w - crop_w / 2), 0), src_w - crop_w) for x in fx]
            graph = (f"[0:v]crop={crop_w}:{src_h}:'{x_expr(shots, xs)}':0,scale={W}:{H}:flags=lanczos,setsar=1[p0];"
                     + zoomed("p0", "v0", W, H, windows, style["zoom"], face_y))
        else:
            graph = (f"[0:v]scale={W}:-2:flags=lanczos,pad={W}:{H}:(ow-iw)/2:(oh-ih)/2:color=black,setsar=1[p0];"
                     + zoomed("p0", "v0", W, H, windows, style["zoom"], 0.5))
        chunks = chunk_words(inside, highlights, style["max_words"]) if inside else []
        for c in chunks:
            for w in c["words"]:
                w["t"] = w["t"].upper() if style["upper"] else w["t"]
        items = [{"path": str(tmp / "blank.png"), "words": []}]
        items += [{"path": str(tmp / f"c{i:04d}.png"), "words": c["words"]} for i, c in enumerate(chunks)]
        spec = tmp / "spec.json"
        spec.write_text(json.dumps({**{k: style[k] for k in ("font", "size", "color", "highlight", "stroke",
                                                             "stroke_width")},
                                    "width": W, "height": CAP_H, "items": items}))
        run(vision(), "captions", spec)
        lines = ["ffconcat version 1.0"]
        for i, secs in timeline(chunks, length):
            lines += [f"file {items[0]['path'] if i is None else items[i + 1]['path']}", f"duration {secs:.3f}"]
        lines.append(f"file {items[0]['path']}")  # ffconcat ignores the last entry's duration
        (tmp / "captions.ffconcat").write_text("\n".join(lines) + "\n")
        y = caption_y - CAP_H // 2
        graph += f";[v0][1:v]overlay=0:{y}:eof_action=pass:format=auto[out]"
        name = clip_name(clip)
        out_dir.mkdir(exist_ok=True)
        run("ffmpeg", "-y", "-v", "error", "-ss", start, "-t", length, "-i", video,
            "-f", "concat", "-safe", 0, "-i", tmp / "captions.ffconcat", "-filter_complex", graph,
            "-map", "[out]", "-map", "0:a?", "-c:v", "libx264", "-preset", "veryfast", "-crf", 20,
            "-pix_fmt", "yuv420p", "-r", 30, "-c:a", "aac", "-b:a", "160k", "-movflags", "+faststart",
            out_dir / name)
    print(f"{name}  {length:.0f}s, {layout} layout, {len(shots)} shots, {len(windows)} zooms, {len(chunks)} captions")


def render(folder, only):
    folder = Path(folder).expanduser()
    picks = json.loads((folder / "picks.json").read_text())
    video = json.loads((folder / "meta.json").read_text())["source"]
    words = json.loads((folder / "words.json").read_text())
    base = {**STYLE}
    if (HERE / "style.json").exists():
        base.update(json.loads((HERE / "style.json").read_text()))
    base.update(picks.get("style", {}))
    out = folder / "clips"
    clips = sorted(picks["clips"], key=lambda c: c["rank"])
    for clip in clips:
        if not only or clip["rank"] in only:
            fixed = apply_fixes(words, {**picks.get("fix", {}), **clip.get("fix", {})})
            render_clip(video, fixed, clip, {**base, **clip.get("style", {})}, out)
    (out / "post-copy.md").write_text("\n".join(
        f"## {clip_name(c)}\nScore: {c.get('score', '?')}/10\nTitle: {c['title']}\nCaption: {c.get('caption', '')}\n"
        for c in clips), encoding="utf-8")


def test():
    ws = [{"w": w, "s": i * 0.5, "e": i * 0.5 + 0.4} for i, w in enumerate("This is free. Really free money now".split())]
    ch = chunk_words(ws, ["free"], 3)
    assert [len(c["words"]) for c in ch] == [3, 3, 1], ch
    assert ch[0]["words"][2] == {"t": "free", "hl": True}
    assert zoom_windows(ws, ["free"]) == [(1.0, 3.0)]
    assert sum(s for _, s in timeline(ch, 5)) == 5
    assert x_expr([(0, 2), (2, 5)], [10, 20]) == "if(lt(t,2.000),10,20)"
    assert x_expr([(0, 5)], [10]) == "10"
    assert fill_gaps([None, 0.2, None, 0.8]) == [0.2, 0.2, 0.2, 0.8]
    assert fill_gaps([None, None]) == [0.5, 0.5]
    assert [s for s, _ in sentences(ws)] == [0.0, 1.5]
    said = [{"w": w, "s": i, "e": i + 1} for i, w in enumerate("use Cloud and open out there, today".split())]
    fixed = apply_fixes(said, {"Cloud": "Claude", "open out there": "OpenRouter"})
    assert [w["w"] for w in fixed] == ["use", "Claude", "and", "OpenRouter,", "today"]
    assert (fixed[3]["s"], fixed[3]["e"]) == (3, 6)
    assert choose_layout([(0.89, 0.82, 0.07)]) == "split"
    assert choose_layout([(0.5, 0.4, 0.2)]) == "crop"
    assert choose_layout([None, None, (0.5, 0.4, 0.2)]) == "fit"
    (sx, sw), top, (x, y, cw, ch) = split_boxes(1920, 1080, 0.889, 0.824, 0.075)
    assert sx == 0 and sw < 1920 and 0 < top < H and x + cw <= 1920 and y + ch <= 1080
    assert split_boxes(1920, 1080, 0.13, 0.8, 0.08)[0][0] > 0  # bubble on the left keeps the right side
    assert zoomed("a", "b", 100, 100, [], 1.1, 0.5) == "[a]null[b]"
    print("ok")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=["prep", "render", "test"])
    ap.add_argument("target", nargs="?")
    ap.add_argument("--out")
    ap.add_argument("--only", help="comma-separated ranks to re-render")
    a = ap.parse_args()
    for tool in ("ffmpeg", "ffprobe", "whisper-cli"):
        if a.cmd != "test" and not shutil.which(tool):
            sys.exit(f"Missing {tool}. Ask the user before installing it.")
    if a.cmd == "prep":
        prep(a.target, a.out)
    elif a.cmd == "render":
        render(a.target, {int(x) for x in a.only.split(",")} if a.only else None)
    else:
        test()
