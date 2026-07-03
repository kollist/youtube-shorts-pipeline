# YouTube Shorts Pipeline (Groq + Whisper + ffmpeg)

Long video in -> transcript -> a free hosted AI model picks the best moments ->
ffmpeg cuts vertical Shorts with burned-in captions -> uploaded to your
channel via the YouTube Data API v3.

**Free.** Clip selection runs on Groq's free API tier (Llama 3.3 70B) - no
payment, just a free API key and an internet connection. Transcription
(Whisper) and video cutting (ffmpeg) are free and fully local.

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

## 2. Groq API key (free tier, used for clip selection)

1. Go to https://console.groq.com/keys and create a free account.
2. Create an API key.
3. Add it to `.env` (copy `.env.example` -> `.env` first if you haven't):

```
GROQ_API_KEY=gsk_xxxxxxxx
```

That's it — no local model download, no GPU/RAM requirements. Clip selection
runs as an API call to Llama 3.3 70B on Groq's infrastructure, which is far
stronger at judging "is this moment actually good" than any model that fits
on a 16GB Mac. The free tier has generous rate limits for this use case
(a handful of transcripts a day).

If you want to try a different Groq-hosted model, pass
`--model <groq-model-name>` to `select_clips.py` / `pipeline.py`.

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

Paste a YouTube URL directly — the video is downloaded automatically:

```bash
# Download + generate clips (review before posting)
python pipeline.py https://www.youtube.com/watch?v=XXXX --max-clips 8

# Download + generate + upload immediately
python pipeline.py https://www.youtube.com/watch?v=XXXX --max-clips 8 --upload

# Target longer clips (default is 30-45s)
python pipeline.py https://www.youtube.com/watch?v=XXXX --max-clips 8 --min-duration 45 --max-duration 60

# Local file still works too
python pipeline.py input/myvideo.mp4 --max-clips 8 --upload --privacy public

# Upload everything sitting in output/ that hasn't been posted yet
python pipeline.py --upload-only
```

Downloaded videos are saved to `input/` (gitignored) and reused on subsequent
runs — if you run the same URL twice the download is skipped if the file is
already there (transcript caching also kicks in).

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
- Clip selection costs $0 on Groq's free tier.

## Pipeline files

| File | Role |
|---|---|
| `transcribe.py` | Whisper transcription -> timestamped JSON |
| `select_clips.py` | Sends transcript to Groq (Llama 3.3 70B), gets back clip timestamps + titles/descriptions/hashtags, snapped to clean sentence boundaries |
| `cut_clips.py` | ffmpeg: crops to 9:16, burns captions, exports clips |
| `upload_youtube.py` | OAuth + `videos.insert` upload |
| `pipeline.py` | Runs all of the above on one video |
| `queue_daily.py` | Runs the pipeline across every video in `input/` to hit a daily clip target |

## Notes / things worth knowing

- **Whisper model size**: `small` is the default (fast). Use `medium` or
  `large-v3` for cleaner captions if your machine can handle it — pass via
  `--whisper-model`.
- **Long videos get chunked**: Groq's free tier caps `llama-3.3-70b-versatile`
  at 12,000 tokens/minute per request. For long source videos, `select_clips.py`
  automatically splits the transcript into ~7000-token chunks and pauses ~65s
  between Groq calls to stay under that limit - so a multi-hour video will take
  several extra minutes on this step alone. This is automatic, no flag needed.
- **Clip length**: `--min-duration` / `--max-duration` (default 30-45s) control
  the target window. The model is instructed to only pick clips whose start/end
  land exactly on a transcript segment boundary, and `select_clips.py` snaps
  near-miss timestamps onto the nearest segment edge — so cuts land on a clean
  sentence break instead of mid-word.
- **Model quality**: Llama 3.3 70B on Groq is noticeably sharper than a small
  local model at judging "is this moment actually good," but it's still not a
  frontier model — review `clips/*_plan.json` before uploading if quality
  matters more than speed.
- **Privacy default is "public"** — change `--privacy unlisted` if you'd
  rather review on YouTube Studio before making clips public.
- **The model returns fewer clips than asked if the material is weak.**
  That's intentional — the prompt explicitly asks it to prioritize quality
  over hitting a number.
- **YouTube's own automated systems still apply** (spam/abuse detection,
  Shorts eligibility heuristics). High-volume identical-sounding titles or
  very repetitive content style can still get flagged independent of API
  quota — that's a YouTube policy layer, not something this pipeline
  controls.

## Switching to a different model later

If you ever want sharper clip-picking judgment than Groq's free tier, you can
swap `select_clips.py` to call Claude via the Anthropic API (paid, per-call
cost) or back to a local Ollama model — the function signature
(`select_clips(segments, max_clips, min_duration, max_duration)`) can stay the
same either way, so `pipeline.py` and `queue_daily.py` wouldn't need any
changes. Just ask and I can wire that up.

