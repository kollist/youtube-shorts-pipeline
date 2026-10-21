# Third-party material

Everything the app depends on or adapts, and under what terms.

| Item | Used for | Licence / terms |
|---|---|---|
| [SCP Foundation wiki](https://scp-wiki.wikidot.com) articles | The source text of the "Foundation tapes" episodes (adapted by `scp_story.py`) | **CC BY-SA 3.0.** Every episode credits the item, author and link (end card, captions, `credit.txt`) and is released under the same licence. See https://scp-wiki.wikidot.com/licensing-guide |
| [FLUX.2 klein 4B](https://huggingface.co/black-forest-labs) (via [mflux](https://github.com/filipstrand/mflux)) | Local picture generation | Apache-2.0 |
| [Depth Anything V2 Small](https://github.com/DepthAnything/Depth-Anything-V2) | Depth map for the parallax camera move in narrated stories | Apache-2.0 |
| [faster-whisper](https://github.com/SYSTRAN/faster-whisper) | Local transcription | MIT |
| [edge-tts](https://github.com/rany2/edge-tts) | Free narrator voices (Microsoft's online voices) | LGPL-3.0; the voice service itself is Microsoft's |
| [yt-dlp](https://github.com/yt-dlp/yt-dlp) | Downloading source videos you point it at | Unlicense |
| [ngrok](https://ngrok.com) | A temporary public link so Instagram can fetch a Reel (free tier) | Service terms |
| Claude Code (`claude -p`) | Optional script writer using your own Claude plan | Anthropic terms |

## Retired experiments

`archive/studio_tools/` keeps the retired Studio tools (MoneyPrinterTurbo bridge, stickman explainer, Seedance prompt library, Wan2GP bridge,
physics simulations, Blender 3D explainers, motion graphics). Their licence notices are in `archive/studio_tools/third_party_notices/`. Nothing in the app imports from `archive/`.
