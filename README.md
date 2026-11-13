# Claude Clipper

A free Claude Code skill that turns one long video into vertical Shorts with captions and zooms. It picks the best moments, shows you a ranked list, and only cuts what you approve.

Everything runs on your own computer except picking the moments, which uses your Claude plan.

## What you need

- A Mac. Face detection and captions use frameworks built into macOS.
- Claude Code, which needs a paid Claude plan.
- FFmpeg and whisper.cpp: `brew install ffmpeg whisper-cpp`
- Swift, from the Xcode Command Line Tools: `xcode-select --install`
- A Whisper model, about 150 MB. The skill offers to download one if you don't have it.
- yt-dlp, only if you want to give it a link instead of a file.

## Install

Paste this repo's link into Claude Code and say: "Install this skill and set it up for me."

Or do it by hand:

```bash
git clone https://github.com/Itsme23476/claude-clipper ~/.claude/skills/clipper
```

The skill must live in `~/.claude/skills/clipper`. Restart Claude Code after installing.

## Use

In Claude Code, type `/clipper` and drag in a long video or paste a YouTube link. You get a ranked list of moments with a score and opening line for each, and it asks which style you want. Tell it which clips to keep, and it renders them to `~/Desktop/Clips/<video name>/clips/`, with titles and post captions in `post-copy.md`.

To change anything, just ask: a different highlight colour, no zooms on one clip, a shorter cut.

## Styles

- **Hormozi** (default): a square picture between black bars, with a headline in the top bar for the whole clip. Bold white captions build word by word, punch words land in giant capitals and key words in red script.
- **Elegant**: full-height video with lower-case captions that build word by word in stepped lines, key words in gold serif, and a title box for the first two seconds.
- **Classic**: bold outlined capitals with yellow highlight words.

Each style is a small file in `styles/`. Show it a Short whose captions you like and ask it to learn that style, and it saves a new one there that you can pick next time.

It picks a layout for each clip:

- **Screen recording with your face in a corner:** the screen on top and your face underneath.
- **Talking head:** a crop that finds the speaker's face again on each camera change and punches in on wide shots.
- **No face:** the full frame, with bars above and below.

## Limits

- Mac only for now.
- It's set up for English. Whisper mishears names, so read the captions and tell it what to fix.

Only clip videos you own or have permission to use.

## License

MIT
