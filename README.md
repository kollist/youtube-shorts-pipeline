# YouTube Shorts Pipeline (Local AI + Whisper + ffmpeg)

Long video in -> transcript -> a local AI model picks the best moments ->
ffmpeg cuts vertical Shorts with burned-in captions -> uploaded to your
channel via the YouTube Data API v3.

**Fully free.** Clip selection runs on a local open-weight model via Ollama
(no API key, no per-call cost, runs entirely on your Mac). Transcription
(Whisper) and video cutting (ffmpeg) were already free and local.

**Important:** this runs on YOUR computer, not in this chat. The scripts need
your video files and your YouTube OAuth login — neither of which Claude.ai
has access to.

## 1. Install

```bash
python3 -m venv venv
source venv/bin/activate      # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

You also need `ffmpeg` installed and on your PATH:
- Mac: `brew install ffmpeg`
- Ubuntu/Debian: `sudo apt install ffmpeg`
- Windows: download from ffmpeg.org and add to PATH

## 2. Ollama (local AI for clip selection — free, no account needed)

```bash
brew install ollama
ollama pull qwen2.5:7b-instruct
```

Ollama runs as a background service after install. If a script says it
can't connect to `localhost:11434`, run `ollama serve` in a separate
terminal tab, or restart your Mac once after installing.

This model runs comfortably on Apple Silicon (M1 and up). If you want
higher-quality clip picks and have the RAM to spare, you can swap to a
bigger model (e.g. `ollama pull qwen2.5:14b-instruct`) and pass
`--model qwen2.5:14b-instruct` to `select_clips.py` / `pipeline.py`.

## 3. YouTube OAuth (one-time setup)

1. https://console.cloud.google.com/ -> create a project.
2. **APIs & Services -> Library** -> enable "YouTube Data API v3".
3. **APIs & Services -> OAuth consent screen** -> External -> add your own
   Google account under "Test users" (this avoids needing Google's app
   review for personal/private use).
4. **APIs & Services -> Credentials -> Create Credentials -> OAuth client ID**
   -> Application type: **Desktop app** -> Download JSON.
5. Save it as `client_secret.json` in this folder.

First time you run an upload, a browser window opens for you to log in and
approve. After that, `token.json` is cached and you won't be asked again.

## 4. Run it

Drop a long video in `input/`, then:

```bash
# Generate clips only (review before posting)
python pipeline.py input/myvideo.mp4 --max-clips 8

# Generate AND upload immediately as public Shorts
python pipeline.py input/myvideo.mp4 --max-clips 8 --upload --privacy public

# Upload everything sitting in output/ that hasn't been posted yet
python pipeline.py --upload-only
```

### Hitting ~20 shorts/day

One long video rarely has 20 genuinely strong standalone moments — quality
falls off a cliff if you force it. The realistic way to hit volume is
multiple source videos per day:

```bash
# Drop 3-4 long videos into input/, then:
python queue_daily.py --target 20 --upload --spacing-minutes 20
```

This splits the daily target across however many videos are in `input/`,
caps the model's clip count per video accordingly, and spaces uploads out
across the day instead of dumping 20 videos in one burst.

## 5. Quota math (why this is safe on the free tier)

- Default free YouTube API quota: 10,000 units/day.
- A `videos.insert` call now costs ~100 units (down from the old 1,600).
- 20 uploads/day = ~2,000 units. Plenty of headroom left.
- Clip selection costs $0 since it runs locally via Ollama.

## Pipeline files

| File | Role |
|---|---|
| `transcribe.py` | Whisper transcription -> timestamped JSON |
| `select_clips.py` | Sends transcript to a local Ollama model, gets back clip timestamps + titles/descriptions |
| `cut_clips.py` | ffmpeg: crops to 9:16, burns captions, exports clips |
| `upload_youtube.py` | OAuth + `videos.insert` upload |
| `pipeline.py` | Runs all of the above on one video |
| `queue_daily.py` | Runs the pipeline across every video in `input/` to hit a daily clip target |

## Notes / things worth knowing

- **Whisper model size**: `small` is the default (fast). Use `medium` or
  `large-v3` for cleaner captions if your machine can handle it — pass via
  `--whisper-model`.
- **Local model quality**: Qwen2.5 7B is solid but not as sharp as a
  frontier model at judging "is this moment actually good." Expect to
  occasionally need to manually skip a weak pick — review `clips/*_plan.json`
  before uploading if quality matters more than speed.
- **Privacy default is "public"** — change `--privacy unlisted` if you'd
  rather review on YouTube Studio before making clips public.
- **The model returns fewer clips than asked if the material is weak.**
  That's intentional — the prompt explicitly asks it to prioritize quality
  over hitting a number, though local models follow this instruction less
  reliably than a frontier model would.
- **YouTube's own automated systems still apply** (spam/abuse detection,
  Shorts eligibility heuristics). High-volume identical-sounding titles or
  very repetitive content style can still get flagged independent of API
  quota — that's a YouTube policy layer, not something this pipeline
  controls.

## Switching back to the Anthropic API later

If you ever want sharper clip-picking judgment, you can switch `select_clips.py`
back to calling Claude via the Anthropic API instead of Ollama — the function
signatures (`select_clips(segments, max_clips)`) are the same either way, so
`pipeline.py` and `queue_daily.py` wouldn't need any changes. Just ask and I
can restore that version.

