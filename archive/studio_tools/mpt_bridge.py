"""
mpt_bridge.py
Drives MoneyPrinterTurbo (https://github.com/harry0703/MoneyPrinterTurbo, MIT license) as a helper service:
it finds/downloads matching stock footage, speaks the script, adds subtitles and background music,
and assembles the video. We don't copy its code into this project - it's cloned into third_party/ and runs
in its own environment (venv-mpt) on 127.0.0.1:8081, and this module starts it, stops it, and sends it jobs.

The script and search keywords are written by THIS app's own model chain and passed in, so MoneyPrinterTurbo
needs no language-model key. Footage comes from Pexels (free key: PEXELS_API_KEY in .env) or from your own
clips (video_source="local").

Usage:
    python mpt_bridge.py setup        # one time: clone + install (several minutes, a few hundred MB)
    python mpt_bridge.py status
"""

import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import requests
from dotenv import load_dotenv

load_dotenv()

BASE = Path(__file__).parent
MPT_DIR = BASE / "third_party" / "MoneyPrinterTurbo"
MPT_VENV = BASE / "venv-mpt"
MPT_PORT = 8081
MPT_URL = f"http://127.0.0.1:{MPT_PORT}"
MPT_REPO = "https://github.com/harry0703/MoneyPrinterTurbo.git"
_proc: subprocess.Popen | None = None


def installed() -> bool:
    return (MPT_DIR / "main.py").exists() and (MPT_VENV / "bin" / "python").exists() and (MPT_DIR / "config.toml").exists()


def _run(cmd: list[str], log, cwd: Path | None = None) -> None:
    log(f"$ {' '.join(str(c) for c in cmd)}")
    proc = subprocess.Popen(cmd, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    for line in proc.stdout:
        line = line.rstrip()
        if line and not line.startswith(("Collecting", "  Using cached", "Requirement already")):
            log("  " + line[:200])
    if proc.wait() != 0:
        raise RuntimeError(f"command failed: {' '.join(str(c) for c in cmd)}")


def write_config() -> None:
    """config.toml for the helper: loopback only, our port, footage keys from our .env."""
    src = (MPT_DIR / "config.example.toml").read_text(encoding="utf-8")
    pexels = [k.strip() for k in os.environ.get("PEXELS_API_KEY", "").split(",") if k.strip()]
    pixabay = [k.strip() for k in os.environ.get("PIXABAY_API_KEY", "").split(",") if k.strip()]
    out = []
    for line in src.splitlines():
        key = line.split("=")[0].strip()
        if key == "listen_host":
            line = 'listen_host = "127.0.0.1"'
        elif key == "listen_port":
            line = f"listen_port = {MPT_PORT}"
        elif key == "pexels_api_keys":
            line = f"pexels_api_keys = {json.dumps(pexels)}"
        elif key == "pixabay_api_keys":
            line = f"pixabay_api_keys = {json.dumps(pixabay)}"
        out.append(line)
    (MPT_DIR / "config.toml").write_text("\n".join(out) + "\n", encoding="utf-8")


def setup(log=print) -> None:
    (BASE / "third_party").mkdir(exist_ok=True)
    if not (MPT_DIR / "main.py").exists():
        _run(["git", "clone", "--depth", "1", MPT_REPO, str(MPT_DIR)], log)
    if not (MPT_VENV / "bin" / "python").exists():
        py = shutil.which("python3.11") or shutil.which("python3.12") or shutil.which("python3.13") or sys.executable
        _run([py, "-m", "venv", str(MPT_VENV)], log)
    for attempt in range(4):   # downloads drop on a flaky connection; pip resumes from its cache
        try:
            _run([str(MPT_VENV / "bin" / "pip"), "install", "--retries", "10", "--timeout", "120",
                  "-r", str(MPT_DIR / "requirements.txt")], log)
            break
        except RuntimeError:
            if attempt == 3:
                raise
            log("install hit a snag, retrying...")
            time.sleep(5)
    write_config()
    commit = subprocess.run(["git", "-C", str(MPT_DIR), "rev-parse", "--short", "HEAD"], capture_output=True, text=True).stdout.strip()
    log(f"MoneyPrinterTurbo ready (commit {commit}). Footage keys come from PEXELS_API_KEY / PIXABAY_API_KEY in .env.")


def is_running() -> bool:
    try:
        return requests.get(f"{MPT_URL}/ping", timeout=2).status_code == 200
    except requests.RequestException:
        return False


def start(log=print) -> None:
    global _proc
    if is_running():
        return
    if not installed():
        raise RuntimeError("MoneyPrinterTurbo isn't set up yet - run setup first.")
    write_config()    # pick up a Pexels key added to .env since the last start
    _proc = subprocess.Popen([str(MPT_VENV / "bin" / "python"), "main.py"], cwd=MPT_DIR,
                             stdout=open(MPT_DIR / "helper.log", "a"), stderr=subprocess.STDOUT)
    for _ in range(90):
        if is_running():
            log("MoneyPrinterTurbo helper is up.")
            return
        if _proc.poll() is not None:
            raise RuntimeError(f"The helper exited at start-up - see {MPT_DIR / 'helper.log'}")
        time.sleep(1)
    raise RuntimeError("The helper didn't start within 90 seconds.")


def stop() -> None:
    global _proc
    if _proc and _proc.poll() is None:
        _proc.terminate()
        try:
            _proc.wait(10)
        except subprocess.TimeoutExpired:
            _proc.kill()
    _proc = None


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "status"
    if cmd == "setup":
        setup()
    else:
        print({"installed": installed(), "running": is_running()})
