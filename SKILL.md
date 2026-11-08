---
name: clipper
description: Turns one long video the user has the rights to into ready-to-post vertical Shorts with captions and zooms. It picks the best moments, shows a ranked list for approval, then cuts them. Use when the user runs /clipper or asks to clip a long video into Shorts, Reels or TikToks.
---

# Clipper

Everything runs on this computer except picking the moments, which is your own reading of the transcript.

## Rules

- Only clip videos the user owns or has permission to use. If it looks like someone else's video, ask first.
- Never cut anything until the user approves the ranked list.
- Ask before installing or downloading anything.

## Steps

**1. Prepare.** Run this with the video file or link:

```bash
python3 ~/.claude/skills/clipper/clipper.py prep "<VIDEO OR LINK>"
```

If it says no Whisper model was found, search for an existing `ggml-*.bin` file and pass it as `WHISPER_MODEL=<path>`. Only offer to download one if none exists. It is about 150 MB: `mkdir -p ~/.cache/whisper && curl -L -o ~/.cache/whisper/ggml-base.en.bin https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-base.en.bin`. Add `--out <folder>` to choose where it works. The default is `~/Desktop/Clips/<video name>/`.

**2. Pick the moments.** Read all of `transcript.txt`. Each line starts with its time in seconds. Choose the best moments, 30 to 60 seconds each unless the user says otherwise:

- It makes sense to someone who never saw the video, with no missing context.
- It starts on a strong first line, never in the middle of a thought.
- It ends on a payoff, not trailing off.
- Start and end on sentence boundaries from the transcript.

Score each out of 10, and be strict. A long video might have five good moments, not fifteen.

**3. Show the ranked list and stop.** A table with rank, score, length, title, and the opening line. Wait for the user's OK. They may drop or change some.

**4. Save the picks** to `picks.json` in the same folder:

```json
{"clips": [{"rank": 1, "score": 9, "title": "Short title", "caption": "Post caption with hashtags",
            "start": 123.4, "end": 171.2, "highlights": ["free", "minute"]}]}
```

`highlights` is one to three words spoken in that clip. They are coloured in the captions and trigger the zooms.

Whisper mishears names, so read for that and add a top-level `"fix": {"Cloud": "Claude", "open out there": "OpenRouter"}`. Put it on a single clip instead if a word is only wrong there, such as a real mention of cloud storage.

**5. Render:**

```bash
python3 ~/.claude/skills/clipper/clipper.py render "<FOLDER>"
```

Clips land in `<FOLDER>/clips/`, with titles and captions in `post-copy.md`. Open at least one clip's frames to check the result before saying it's done.

## Changes

Edit `picks.json` and re-render only what changed with `--only 2`. For one clip, set `"zoom": false`, change `start` or `end`, or add `"style": {"highlight": "#00AAFF"}`. To change the whole batch, add a top-level `"style"`.

The layout is chosen for you: `split` puts the screen on top and the face below for a screen recording with a corner face bubble, `crop` follows a talking head and re-centres on each camera change, and `fit` is for footage with no face. Set `"layout"` on a clip to override it.

Style keys: `font`, `size`, `color`, `highlight`, `stroke`, `stroke_width`, `y` (caption height, 0 to 1), `max_words`, `upper`, `zoom`.

## Teach it a style

When the user shows a Short they like, look at a frame of it and write the closest matching keys to `~/.claude/skills/clipper/style.json`. Every future clip then uses that look. Copy the caption style only, never the video.
