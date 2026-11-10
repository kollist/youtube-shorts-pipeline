"""Runs inside venv-clone (Chatterbox). Reads a job JSON {ref, items:[{text, out, exaggeration, cfg}]} and writes one wav per item. Items whose file exists are skipped, so a crash resumes."""
import json
import sys
from pathlib import Path

import soundfile as sf
import torch
from chatterbox.mtl_tts import ChatterboxMultilingualTTS

job = json.load(open(sys.argv[1], encoding="utf-8"))
dev = "mps" if torch.backends.mps.is_available() else "cpu"
model = ChatterboxMultilingualTTS.from_local(Path(__file__).parent / "models" / "chatterbox", dev)
for it in job["items"]:
    if Path(it["out"]).exists():
        continue
    w = model.generate(it["text"], language_id="ar", audio_prompt_path=job["ref"], exaggeration=it.get("exaggeration", 0.5), cfg_weight=it.get("cfg", 0.5))
    sf.write(it["out"], w.squeeze().cpu().numpy(), model.sr)
    print("done", it["out"], flush=True)
print("WORKER DONE", flush=True)
