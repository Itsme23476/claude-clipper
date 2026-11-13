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
         "stroke_width": 16, "y": 0.66, "max_words": 3, "upper": True, "zoom": 1.12,
         "highlight_font": "", "highlight_scale": 1.0, "shadow": 0, "line_words": 0, "stagger": 0, "reveal": False,
         "wide_zoom": 1.6, "hook_font": "AvenirNext-Heavy", "hook_highlight": "#D64045", "hook_box": "#000000",
         "highlight_upper": False, "emphasis_font": "", "emphasis_scale": 0, "emphasis_color": "", "frame": ""}
LOOK = ("font", "size", "color", "highlight", "highlight_font", "highlight_scale", "stroke", "stroke_width", "shadow",
        "stagger")
W, H, CAP_H, HOOK_SECS = 1080, 1920, 480, 2.0
BAND = (H - W) // 2  # black bar above and below a square frame


def run(*cmd, **kw):
    r = subprocess.run([str(c) for c in cmd], text=True, capture_output=True, **kw)
    if r.returncode:
        sys.exit(f"{cmd[0]} failed: {r.stderr.strip()[-800:]}")
    return r.stdout


def slug(text):
    return re.sub(r"[^a-z0-9]+", "-", re.sub(r"['’,]", "", text.lower())).strip("-")[:50].strip("-") or "clip"


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
    if is_link and not shutil.which("yt-dlp"):
        sys.exit("Missing yt-dlp, which is needed for links. Ask the user before installing it.")
    name = run("yt-dlp", "--no-warnings", "--print", "title", src).splitlines()[0] if is_link else Path(src).stem
    out = Path(out or f"~/Desktop/Clips/{slug(name)}").expanduser()
    out.mkdir(parents=True, exist_ok=True)
    if is_link:
        video = out / "source.mp4"
        if not video.exists():  # yt-dlp only writes it once the download is complete
            run("yt-dlp", "-q", "-f", "bv*[height<=1080]+ba/b[height<=1080]", "--merge-output-format", "mp4",
                "-o", video, src)
    else:
        video = Path(src).expanduser().resolve()
    wav = out / "audio.wav"
    run("ffmpeg", "-y", "-v", "error", "-i", video, "-vn", "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", wav)
    run("whisper-cli", "-m", find_model(), "-f", wav, "-ml", "1", "-sow", "-oj", "-of", out / "whisper", "-np")
    wav.unlink()
    raw = json.loads((out / "whisper.json").read_text())["transcription"]
    words = [{"w": t, "s": r["offsets"]["from"] / 1000, "e": r["offsets"]["to"] / 1000}
             for r in raw if (t := r["text"].strip()) and not t.startswith(("[", "(")) and not t.endswith(("]", ")"))]
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
                new = (value + tail).split()  # "TED Talk" stays two words, sharing the time it took to say
                step = (part[-1]["e"] - part[0]["s"]) / len(new)
                out += [{"w": t, "s": part[0]["s"] + k * step, "e": part[0]["s"] + (k + 1) * step}
                        for k, t in enumerate(new)]
                i += len(key)
                break
        else:
            out.append(words[i])
            i += 1
    return out


def mark(words, phrases):
    """{word index: colour} for every place one of the phrases is said, matched as a whole phrase."""
    said = [clean(w["w"]) for w in words]
    out = {}
    for phrase, colour in phrases.items():
        key = [clean(x) for x in phrase.split()]
        for i in range(len(said) - len(key) + 1):
            if said[i : i + len(key)] == key:
                out.update({j: colour for j in range(i, i + len(key))})
    return out


def chunk_words(words, marks, max_words):
    """Caption groups: [{"a": start, "b": end, "words": [{"t", "hl", "s", ...}]}]. marks: {word index: {"c", "f", "z"}}.
    Whisper's "-" marks a new speaker: it is never shown, and the group ends there."""
    chunks, cur = [], []
    for i, w in enumerate(words):
        nxt = words[i + 1] if i + 1 < len(words) else None
        if clean(w["w"]):
            cur.append(i)
        if cur and (not nxt or not clean(nxt["w"]) or len(cur) == max_words or w["w"][-1] in ".?!,"
                    or nxt["s"] - w["e"] > 0.4):
            chunks.append({"a": words[cur[0]]["s"], "b": words[cur[-1]]["e"],
                           "words": [{"t": words[j]["w"].strip(".,-"), "hl": j in marks, "s": words[j]["s"],
                                      **marks.get(j, {})} for j in cur]})
            cur = []
    for c, nxt in zip(chunks, chunks[1:]):  # hold each caption until the next, across short pauses
        c["b"] = min(nxt["a"], c["b"] + 0.25)
    return chunks


def cards(chunks, reveal):
    """What the caption shows over time. With reveal, each group builds up one word at a time as it is said."""
    if not reveal:
        return [{**c, "on": len(c["words"])} for c in chunks]
    out = []
    for c in chunks:
        ws = c["words"]
        for k in range(len(ws)):
            out.append({**c, "a": max(ws[k]["s"], c["a"]), "b": ws[k + 1]["s"] if k + 1 < len(ws) else c["b"],
                        "on": k + 1})
    return out


def lines_of(words, per_line):
    """Short lines of up to per_line words. Highlighted words get a line of their own, one per font. 0 means one line."""
    if not per_line:
        return [words]
    out = []
    for w in words:
        prev = out[-1][-1] if out else {}
        if not out or len(out[-1]) == per_line or (prev["hl"], prev.get("f")) != (w["hl"], w.get("f")):
            out.append([w])
        else:
            out[-1].append(w)
    return out


def hook_lines(text, upper=True):
    """'HE LOST *TENS OF MILLIONS*...' -> two lines, the starred words marked to colour."""
    ws = []
    for i, part in enumerate((text.upper() if upper else text).split("*")):
        for t in part.split():
            if ws and not clean(t):  # keep "..." on the word before it
                ws[-1]["t"] += t
            else:
                ws.append({"t": t, "hl": i % 2 == 1, "on": True})
    half = (len(ws) + 1) // 2 if len(ws) > 2 else len(ws)
    return [ws[:half], ws[half:]] if ws[half:] else [ws]


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
    """Punch in each time a highlighted word or phrase is spoken, at least `spacing` seconds apart."""
    out = []
    for i in sorted(mark(words, {h: 1 for h in highlights})):
        if not out or words[i]["s"] >= out[-1][0] + spacing:
            out.append((words[i]["s"], words[i]["s"] + hold))
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
        square = style["frame"] == "square" and layout == "crop"
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
            # "square": a 1:1 frame between black bars, like a Hormozi Short. Otherwise full 9:16.
            crop_w, crop_h = (even(min(src_w, src_h)),) * 2 if square else (even(src_h * 9 / 16), src_h)
            out_h = W if square else H
            fx = fill_gaps([f and f[0] for f in faces])
            face_y = statistics.median(f[1] for f in seen)
            xs = [min(max(even(x * src_w - crop_w / 2), 0), src_w - crop_w) for x in fx]
            # ponytail: a face narrower than 17% of the frame height means a wide shot. Punch in for the whole shot.
            wide = [(shot, f) for shot, f in zip(shots, faces) if f and f[2] * src_w / src_h < 0.17]
            wide_y = statistics.median(f[1] for _, f in wide) if wide else 0.5
            graph = (f"[0:v]crop={crop_w}:{crop_h}:'{x_expr(shots, xs)}':{(src_h - crop_h) // 2},"
                     f"scale={W}:{out_h}:flags=lanczos,setsar=1[p0];"
                     + zoomed("p0", "p1", W, out_h, [s for s, _ in wide], style["wide_zoom"], wide_y) + ";"
                     + zoomed("p1", "v1" if square else "v0", W, out_h, windows, style["zoom"], face_y))
            if square:
                graph += f";[v1]pad={W}:{H}:0:{BAND}:black[v0]"
        else:
            graph = (f"[0:v]scale={W}:-2:flags=lanczos,pad={W}:{H}:(ow-iw)/2:(oh-ih)/2:color=black,setsar=1[p0];"
                     + zoomed("p0", "v0", W, H, windows, style["zoom"], 0.5))
        # highlights: zoom words in the highlight font. emphasis: more key words, in the emphasis font if set.
        big = {"f": style["highlight_font"] or None, "z": style["highlight_scale"], "up": style["highlight_upper"]}
        accent = {"f": style["emphasis_font"] or big["f"], "z": style["emphasis_scale"] or big["z"], "up": False}
        marks = {i: {**big, "c": c} for i, c in mark(inside, {h: style["highlight"] for h in highlights}).items()}
        colours = {}
        for e in clip.get("emphasis", []):  # "word", or {"word": "#hex"} for its own colour
            colours.update(e if isinstance(e, dict) else {e: style["emphasis_color"] or style["highlight"]})
        marks.update({i: {**accent, "c": c} for i, c in mark(inside, colours).items()})
        chunks = chunk_words(inside, marks, style["max_words"]) if inside else []
        for c in chunks:
            for w in c["words"]:
                w["t"] = w["t"].upper() if style["upper"] or w.get("up") else w["t"]
        shown = cards(chunks, style["reveal"])
        look = {**{k: style[k] for k in LOOK}, "box": "", "align": "center"}
        hook = clip.get("hook")
        if hook:  # square frame: a title in the top bar all along. Otherwise a title box for the first seconds.
            hook_look = {**look, "font": style["hook_font"], "highlight_font": style["hook_font"], "size": 72,
                         "highlight_scale": 1, "highlight": style["hook_highlight"], "box": style["hook_box"],
                         "stroke_width": 0, "shadow": 0, "stagger": 0}
            if square:
                hook_look.update(size=54, box="", align="left")
            else:
                shown = [{"a": 0.0, "b": HOOK_SECS, "hook": True}] + [
                    {**c, "a": max(c["a"], HOOK_SECS)} for c in shown if c["b"] > HOOK_SECS + 0.1]
        items = [{"path": str(tmp / "blank.png"), "lines": [], "look": look}]
        for i, c in enumerate(shown):
            ws = [{**w, "on": j < c.get("on", 0)} for j, w in enumerate(c.get("words", []))]
            items.append({"path": str(tmp / f"c{i:04d}.png"), "lines": hook_lines(hook) if c.get("hook") else
                          lines_of(ws, style["line_words"]), "look": hook_look if c.get("hook") else look})
        bar = bool(hook and square)
        if bar:  # not in the timeline: overlaid on its own for the whole clip
            items.append({"path": str(tmp / "title.png"), "lines": hook_lines(hook, upper=False), "look": hook_look})
        spec = tmp / "spec.json"
        spec.write_text(json.dumps({"width": W, "height": CAP_H, "items": items}))
        run(vision(), "captions", spec)
        lines = ["ffconcat version 1.0"]
        for i, secs in timeline(shown, length):
            lines += [f"file {items[0]['path'] if i is None else items[i + 1]['path']}", f"duration {secs:.3f}"]
        lines.append(f"file {items[0]['path']}")  # ffconcat ignores the last entry's duration
        (tmp / "captions.ffconcat").write_text("\n".join(lines) + "\n")
        y = caption_y - CAP_H // 2
        graph += f";[v0][1:v]overlay=0:{y}:eof_action=pass:format=auto"
        graph += f"[c0];[c0][2:v]overlay=0:{int(BAND * 0.7) - CAP_H // 2}:format=auto[out]" if bar else "[out]"
        name = clip_name(clip)
        out_dir.mkdir(exist_ok=True)
        run("ffmpeg", "-y", "-v", "error", "-ss", start, "-t", length, "-i", video,
            "-f", "concat", "-safe", 0, "-i", tmp / "captions.ffconcat",
            *(["-loop", 1, "-t", length, "-i", tmp / "title.png"] if bar else []), "-filter_complex", graph,
            "-map", "[out]", "-map", "0:a?", "-af", f"afade=t=out:st={length - 0.1:.3f}:d=0.1",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", 20,
            "-pix_fmt", "yuv420p", "-r", 30, "-c:a", "aac", "-b:a", "160k", "-movflags", "+faststart",
            out_dir / name)
    wides = len(wide) if layout == "crop" else 0
    print(f"{name}  {length:.0f}s, {layout} layout, {len(shots)} shots ({wides} wide), {len(windows)} zooms, "
          f"{len(chunks)} captions")


def render(folder, only):
    folder = Path(folder).expanduser()
    picks = json.loads((folder / "picks.json").read_text())
    video = json.loads((folder / "meta.json").read_text())["source"]
    words = json.loads((folder / "words.json").read_text())
    preset = HERE / "styles" / f"{picks.get('preset', 'classic')}.json"
    if not preset.exists():
        sys.exit(f"No style called {preset.stem}. Pick one of: {', '.join(p.stem for p in (HERE / 'styles').glob('*.json'))}")
    base = {**STYLE, **json.loads(preset.read_text()), **picks.get("style", {})}
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
    ch = chunk_words(ws, {i: {"c": c} for i, c in mark(ws, {"free": "#F00"}).items()}, 3)
    assert [len(c["words"]) for c in ch] == [3, 3, 1], ch
    assert ch[0]["words"][2] == {"t": "free", "hl": True, "c": "#F00", "s": 1.0}
    assert ch[0]["words"][0] == {"t": "This", "hl": False, "s": 0.0}
    turns = [{"w": w, "s": i, "e": i + 0.9} for i, w in enumerate("No way. - How much? -".split())]
    assert [[w["t"] for w in c["words"]] for c in chunk_words(turns, {}, 6)] == [["No", "way"], ["How", "much?"]]
    money = [{"w": w} for w in "tens of millions of dollars, $5 million".split()]
    assert mark(money, {"tens of millions": "a", "$5": "b"}) == {0: "a", 1: "a", 2: "a", 5: "b"}
    built = cards(ch, reveal=True)
    assert [c["on"] for c in built] == [1, 2, 3, 1, 2, 3, 1] and built[1]["a"] == 0.5
    assert sum(s for _, s in timeline(built, 5)) == 5
    hl = [{"t": t, "hl": t == "free"} for t in "this is free money now".split()]
    assert [[w["t"] for w in l] for l in lines_of(hl, 3)] == [["this", "is"], ["free"], ["money", "now"]]
    assert lines_of(hl, 0) == [hl]
    mixed = [{"t": "what", "hl": True, "f": "Script"}, {"t": "NOTES", "hl": True, "f": "Black"}]
    assert len(lines_of(mixed, 3)) == 2  # a script word and a big word never share a line
    assert [w["t"] for l in hook_lines("Nobody knows *CliffNotes*.", upper=False) for w in l][-1] == "CliffNotes."
    hook = hook_lines("He lost *tens of millions*...")
    assert [[w["t"] for w in l] for l in hook] == [["HE", "LOST", "TENS"], ["OF", "MILLIONS..."]]
    assert [w["hl"] for l in hook for w in l] == [False, False, True, True, True]
    assert slug("You're Gonna Suck, 1,100 Times") == "youre-gonna-suck-1100-times"
    assert not slug("a" * 49 + " b").endswith("-")
    assert zoom_windows(ws, ["free"]) == [(1.0, 3.0)]
    assert zoom_windows(ws, ["free money"]) == [(2.0, 4.0)]  # the phrase, not every "free"
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
    ted = apply_fixes(said[:3], {"Cloud and": "TED Talk"})
    assert [(w["w"], w["s"]) for w in ted] == [("use", 0), ("TED", 1), ("Talk", 2)]
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
