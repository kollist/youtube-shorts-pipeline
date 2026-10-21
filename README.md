# T-Minus - short-video studio

A local dashboard (FastAPI + plain JavaScript) that makes and posts vertical short videos. Everything runs on your own computer and
is free to run: Groq's free tier, local Whisper and ffmpeg, a local image model, free edge-tts voices, and (optionally) your own
Claude plan as the script writer.

| Tab | What it does |
|---|---|
| **Run** | Clip a long video (YouTube link or file) into Shorts: transcript -> a model picks the moments -> ffmpeg cuts 9:16 clips with burned-in captions. Livestream mode finds the loud moments first. A live **Activity** card shows progress; the raw log is under "Technical log". |
| **Discover** | Recent long streams from IShowSpeed and Kai Cenat, one click to load into Run. |
| **Input / Filler** | Your source videos, and the gameplay footage used for the split-screen layout. |
| **Clips** | Review, split-screen, caption, and post the clips. |
| **Series** | AI story series and **SCP Foundation tapes**: one click makes the next episode, then you review it and press Post. |
| **Analytics** | What actually performed, by format / streamer / hook. |

## 1. Install

```bash
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env          # then fill in the keys you need (see below)
python server.py              # -> http://localhost:8000  (the login is printed / saved in .env on first start)
```

You also need `ffmpeg` on your PATH (`brew install ffmpeg`).

### Keys (all in `.env`, never in chat or git)

- **Groq (free)** - `GROQ_API_KEY` from https://console.groq.com/keys. Used for clip selection and as a script-writer fallback.
- **YouTube** - one-time OAuth: create a project at https://console.cloud.google.com/, enable "YouTube Data API v3", add yourself as a test user,
  create a **Desktop app** OAuth client, save it as `client_secret.json`. The first upload opens a browser to approve; then `token.json` is cached.
- **Script writer: your Claude plan** - `USE_CLAUDE_CODE=1` uses Claude Code's headless mode (`claude -p`, no API key). Order: Claude Code ->
  Groq -> OpenRouter free models (last resort).
- **Facebook / Instagram / TikTok** - optional, see `SOCIAL_SETUP.md`.

## 2. Clipping (Run, Discover, Input, Clips)

```bash
python pipeline.py "https://www.youtube.com/watch?v=..."        # download + clip, review before posting
python pipeline.py "https://..." --mode stream --streamer speed  # livestream mode: loudness peaks first
python queue_daily.py --clips 20                                 # spread a daily target across every video in input/
```

- Clips are written to `output/` with a `.json` per clip (title, description, hashtags); nothing is uploaded until you ask.
- **Heads-up (Oct 2026):** YouTube now reduces Shorts reach for channels that mainly re-upload other creators' clips (crop + captions + music
  don't count as original). See `research/FORMAT_STUDY.md` before relying on clips for YouTube growth.
- Long videos are chunked to stay under Groq's free per-minute token limit; `select_clips.py` falls back across models automatically.
- Whisper model size: `--whisper-model small` (default) or `medium` / `large-v3` for cleaner captions.

## 3. Series

**Create a series** from the Series tab. Two kinds:

- **AI story series** - the AI writes the cast, the look and a planned arc; each episode is a narrated, animated story.
- **SCP Foundation tapes** - type SCP numbers (e.g. `173, 096, 049`). Each episode fetches the article from the SCP wiki and adapts it into a
  "Foundation orientation tape": the containment procedures become the rules, the entity creeps closer in every picture, and the picture
  degrades like a failing VHS tape.

**One click per episode** - *Make episode N*: writes it (or fetches/adapts the SCP), makes the pictures (skips ones that exist), renders the
video. Then you watch it and press **Post**. **＋ Add episode** on a series adds an SCP (type its number) or has the AI plan the next chapter.

**Posting** opens a dialog: nothing is ticked by default, the captions and hashtags are written per platform (and editable), and the episode's
video + pictures are deleted after it posts everywhere you ticked (the script stays).

### SCP licence (important)

SCP Foundation content is **CC BY-SA 3.0**. Every SCP episode carries the credit (item, author, link) on its end card, in the captions and in
`credit.txt`, and the YouTube upload uses YouTube's Creative Commons setting (YouTube only offers plain CC BY, so the description also states the CC BY-SA 3.0 terms). Your video is released under the same licence. Details: https://scp-wiki.wikidot.com/licensing-guide

### How the tape format is built

| File | Role |
|---|---|
| `scp_story.py` | Fetches an SCP article and adapts it (Claude) into scenes; keeps the credit |
| `rules_story.py` / `rules_video.py` | The original "Night shift as X - 6 rules" story + plain assembler (poster frame, RULE badges, word-highlighted captions) |
| `horror_video.py` | Builds the scary version: tension curve, tape damage, keyword-timed foley, silence before the last line, tape-death end card |
| `horror_fx.py` | VHS degradation per frame (grain, tracking tears, chroma smear, static/roll/freeze/flash events) |
| `horror_sfx.py` | Synthesized foley and beds (phone, elevator, wet steps, keys, creak, snap, scream, drone, heartbeat, sting) |
| `captions.py` | Per-platform captions + rotating hashtag pools |
| `series.py` | Series/episodes: bible, SCP series, add-episode, one-click make, cleanup after posting |
| `story_images.py` / `story_video.py` / `story_motion.py` | Local pictures (FLUX.2 klein), voices, captions, parallax motion for the narrated story series |
| `shots.py` | "Animate with free web tools": motion prompts per scene; drop in clips from Kling / Google Flow free credits |

### Fast local pictures (Apple silicon)

```bash
python3.11 -m venv venv-mlx
./venv-mlx/bin/pip install "mflux==0.23.0" && ./venv-mlx/bin/pip install "pillow<12"
python fetch_model.py mflux-community/flux2-klein-4b-mflux-q4 models/klein-q4      # ~4.6 GB, resumes if the connection drops
```

About 40-60 s per picture. Without it the slower PyTorch build (`models/flux2klein`, `pip install -r requirements-story.txt`) is used.

## 4. Posting beyond YouTube

Facebook Reels, Instagram Reels and TikTok: `SOCIAL_SETUP.md`. `python social_post.py status` shows what's connected; `python social_auth.py instagram`
re-checks the Instagram link. Instagram uploads go through a temporary public link (ngrok, free) because direct upload is rejected for this app type.
New accounts: post a couple a day, not dozens - Facebook rate-limits bursts.

## 5. Project layout

- Root `*.py` - the app (categories above); `web_static/` - the dashboard (`app.js`, `series.js`, `activity.js`, styles).
- `stories/` - series and episode scripts (`story.json` is tracked; pictures and videos are generated and ignored).
- `research/` - format studies (what performs, with the data behind it).
- `archive/` - retired experiments kept for reference (Studio tools, physics simulations, 3D explainers, a paid cloud route, X posting). Nothing imports from it.
- Not in git: `.env`, tokens, `models/`, `input/`, `output/`, `transcripts/`, generated episode media.

Third-party licences: `THIRD_PARTY.md`.
