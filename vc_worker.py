"""Runs inside venv-clone. Job JSON: {ref, items:[{in, out}]}: converts each speech file to the reference voice (Chatterbox voice conversion), keeping the words and the accent."""
import json
import sys
from pathlib import Path

import soundfile as sf
import torch
from chatterbox.models.s3gen import S3Gen
from chatterbox.vc import ChatterboxVC

job = json.load(open(sys.argv[1], encoding="utf-8"))
d = Path(__file__).parent / "models" / "chatterbox"
dev = "mps" if torch.backends.mps.is_available() else "cpu"
s3 = S3Gen(); s3.load_state_dict(torch.load(d / "s3gen.pt", map_location="cpu", weights_only=True)); s3.to(dev).eval()
vc = ChatterboxVC(s3, dev, ref_dict=None)
for it in job["items"]:
    if Path(it["out"]).exists():
        continue
    w = vc.generate(it["in"], target_voice_path=job["ref"])
    sf.write(it["out"], w.squeeze().cpu().numpy(), vc.sr)
    print("done", it["out"], flush=True)
print("VC WORKER DONE", flush=True)
