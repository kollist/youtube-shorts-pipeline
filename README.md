# YouTube Shorts Pipeline (Claude + Whisper + ffmpeg)

Long video in -> transcript -> Claude picks the best moments -> ffmpeg cuts
vertical Shorts with burned-in captions -> uploaded to your channel via the
YouTube Data API v3.

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

## 2. Anthropic API key

Copy `.env.example` to `.env` and add your key from
https://console.anthropic.com:

```
ANTHROPIC_API_KEY=sk-ant-...
```

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
caps Claude's clip count per video accordingly, and spaces uploads out
across the day instead of dumping 20 videos in one burst.

## 5. Quota math (why this is safe on the free tier)

- Default free quota: 10,000 units/day.
- A `videos.insert` call now costs ~100 units (down from the old 1,600).
- 20 uploads/day = ~2,000 units. Plenty of headroom left.

## Pipeline files

| File | Role |
|---|---|
| `transcribe.py` | Whisper transcription -> timestamped JSON |
| `select_clips.py` | Sends transcript to Claude, gets back clip timestamps + titles/descriptions |
| `cut_clips.py` | ffmpeg: crops to 9:16, burns captions, exports clips |
| `upload_youtube.py` | OAuth + `videos.insert` upload |
| `pipeline.py` | Runs all of the above on one video |
| `queue_daily.py` | Runs the pipeline across every video in `input/` to hit a daily clip target |

## Notes / things worth knowing

- **Whisper model size**: `small` is the default (fast). Use `medium` or
  `large-v3` for cleaner captions if your machine can handle it — pass via
  `--whisper-model`.
- **Privacy default is "public"** — change `--privacy unlisted` if you'd
  rather review on YouTube Studio before making clips public.
- **Claude returns fewer clips than asked if the material is weak.** That's
  intentional — `select_clips.py`'s prompt explicitly tells it to prioritize
  quality over hitting a number.
- **YouTube's own automated systems still apply** (spam/abuse detection,
  Shorts eligibility heuristics). High-volume identical-sounding titles or
  very repetitive content style can still get flagged independent of API
  quota — that's a YouTube policy layer, not something this pipeline
  controls.
