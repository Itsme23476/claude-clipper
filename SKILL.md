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

If it says no Whisper model was found, search for an existing `ggml-*.bin` file and pass it as `WHISPER_MODEL=<path>`. Only offer to download one if none exists. It is about 150 MB: `mkdir -p ~/.cache/whisper && curl -L -o ~/.cache/whisper/ggml-base.en.bin https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-base.en.bin`. Add `--out <folder>` to choose where it works. The default is `~/Desktop/Clips/<video name>/`, using the YouTube title for a link. Running it again on the same link reuses the video it already downloaded.

**2. Pick the moments.** Read all of `transcript.txt`. Each line starts with its time in seconds, and a `-` marks a new speaker. Choose the best moments, 30 to 60 seconds each unless the user says otherwise:

- It makes sense to someone who never saw the video, with no missing context.
- It starts on a strong first line, never in the middle of a thought.
- It ends on a payoff, not trailing off.
- Start and end on sentence boundaries from the transcript.

Score each out of 10, and be strict. A long video might have five good moments, not fifteen.

**3. Show the ranked list, ask for a style, and stop.** A table with rank, score, length, title, and the opening line. In the same message, ask which style to use. Each file in `~/.claude/skills/clipper/styles/` is one style:

- `hormozi` (the default): a square picture between black bars, a title in the top bar for the whole clip, bold white captions, punch words in giant capitals and key words in red script.
- `elegant`: full-height video, lower-case captions that build word by word in stepped lines, key words in gold serif, and a title box for the first two seconds.
- `classic`: bold outlined capitals with yellow highlight words.
- Any other file there is a style the user taught it. Describe it from its keys.

Wait for the user's OK on both. They may drop or change some clips.

**4. Save the picks** to `picks.json` in the same folder, with the chosen style as `preset`:

```json
{"preset": "hormozi",
 "clips": [{"rank": 1, "score": 9, "title": "Short title", "caption": "Post caption with hashtags",
            "start": 123.4, "end": 171.2, "highlights": ["free", "minute"], "hook": "Why it's *free* now.",
            "emphasis": ["no limits", "every model", {"cancelled": "#F0484E"}]}]}
```

`highlights` is one to four words or short phrases spoken in that clip. They trigger the zooms. In `hormozi` they are the punch words in giant capitals, so prefer numbers and one-word payoffs, and don't pick a word that is said many times.

`emphasis` is the key word or short phrase in most sentences, about one per caption. Each one gets the accent colour and font, without a zoom: red script in `hormozi`, gold serif in `elegant`. Write `{"word": "#hex"}` to give a word its own colour, such as red for a loss or a warning in `elegant`. Phrases match only as a whole, so "tens of millions" never colours every "of".

`hook` is the title. In `hormozi` it is a sentence-case headline of up to eight words that stays in the top bar, such as `Why most creators *quit* before they get good.`. In `elegant` and `classic` it is a teaser of up to six words in capitals, shown in a box for the first two seconds, such as `HE LOST *TENS OF MILLIONS*...`. Make it a cliffhanger, not a summary, and wrap the word to colour in `*asterisks*`.

Whisper mishears names, so read for that and add a top-level `"fix": {"Cloud": "Claude", "open out there": "OpenRouter"}`. Put it on a single clip instead if a word is only wrong there, such as a real mention of cloud storage.

**5. Render:**

```bash
python3 ~/.claude/skills/clipper/clipper.py render "<FOLDER>"
```

Clips land in `<FOLDER>/clips/`, with titles and captions in `post-copy.md`. Open at least one clip's frames to check the result before saying it's done.

## Changes

Edit `picks.json` and re-render only what changed with `--only 2`. For one clip, set `"zoom": false`, change `start` or `end`, or add `"style": {"highlight": "#00AAFF"}`. To change the whole batch, switch `preset` or add a top-level `"style"` with the keys to change. When switching between `hormozi` and the others, rewrite the hooks to match the new style.

The layout is chosen for you: `split` puts the screen on top and the face below for a screen recording with a corner face bubble, `crop` follows a talking head, re-centres on each camera change and punches in on wide shots, and `fit` is for footage with no face. Set `"layout"` on a clip to override it.

Style keys: `font`, `size`, `color`, `highlight`, `stroke`, `stroke_width` (0 for no outline), `shadow` (blur in pixels, 0 for none), `y` (caption height, 0 to 1), `max_words` (words per caption), `upper`, `zoom`, `wide_zoom` (punch-in on wide shots, 1 to turn it off).
- Key words: `highlight_font` and `highlight_scale` set highlights in a second font, larger, and `highlight_upper` puts them in capitals. `emphasis_font`, `emphasis_scale` and `emphasis_color` do the same for emphasis words, and default to the highlight ones.
- Layout: `line_words` breaks a caption into lines of that many words, and a key word gets its own line. `stagger` steps each line right by that many pixels. `reveal: true` shows each word as it is spoken. `frame: "square"` puts a 1:1 picture between black bars, for the crop layout.
- Hook: `hook_font`, `hook_highlight` (the starred word), `hook_box` (box colour).

Fonts are macOS font names such as `HelveticaNeue-Medium`, `Didot-Bold` or `AvenirNext-Heavy`.

## Teach it a style

When the user shows a Short they like, look at several frames of it and write the closest matching keys to `~/.claude/skills/clipper/styles/<name>.json`, with a short name the user picks. From then on it is one of the styles offered in step 3. Start from the existing style closest to it and change only what differs. Check for an outline or a shadow, capitals or lower case, words appearing one at a time, stepped lines, one or two accent fonts for key words, a title box at the start, and a square frame with a title bar. Copy the caption style only, never the video.
