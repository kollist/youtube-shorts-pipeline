"""Runs inside venv-habibi. Job JSON: {ref_audio, ref_text, nfe_step, items:[{text, out}]}. Loads the Moroccan (MAR) model once, writes one wav per item, skips items already on disk."""
import json
import sys
import time
from importlib.resources import files
from pathlib import Path

import gc

import soundfile as sf
import torch
from f5_tts.infer.utils_infer import load_model, load_vocoder, preprocess_ref_audio_text
from habibi_tts.infer.utils_infer import device, infer_process
from hydra.utils import get_class
from omegaconf import OmegaConf

job = json.load(open(sys.argv[1], encoding="utf-8"))
base = Path(__file__).parent / "models" / "habibi" / "MAR"
cfg = OmegaConf.load(str(files("f5_tts").joinpath("configs/F5TTS_v1_Base.yaml")))
cls, arch, voc = get_class(f"f5_tts.model.{cfg.model.backbone}"), cfg.model.arch, cfg.model.mel_spec.mel_spec_type
model = load_model(cls, arch, str(base / "model_100000.safetensors"), mel_spec_type=voc, vocab_file=str(base / "vocab.txt"), device=device)
vocoder = load_vocoder(vocoder_name=voc, is_local=False, local_path="", device=device)
ref_audio, ref_text = preprocess_ref_audio_text(job["ref_audio"], job["ref_text"])
for it in job["items"]:
    if Path(it["out"]).exists():
        continue
    t0 = time.time()
    audio, sr, _ = infer_process(ref_audio, ref_text, it["text"], model, vocoder, mel_spec_type=voc, nfe_step=job.get("nfe_step", 32), speed=job.get("speed", 1.0), device=device, dialect_id=None)
    sf.write(it["out"], audio, sr)
    gc.collect()
    if hasattr(torch, "mps") and torch.backends.mps.is_available():
        torch.mps.empty_cache()                                          # the cache grows with every sentence and ran out at about sentence 30
    print(f"done {time.time() - t0:.0f}s for {len(audio) / sr:.1f}s of audio: {it['text'][:40]}", flush=True)
print("HABIBI WORKER DONE", flush=True)
