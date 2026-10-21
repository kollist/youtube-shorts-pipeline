"""
public_tunnel.py
Gives one local video file a temporary public https address, so APIs that only accept a video URL
(Instagram Reels) can fetch it. Uses ngrok, which must be installed and logged in once
(`brew install ngrok` + `ngrok config add-authtoken ...`). Only that one file is served, at a random
path, for as long as the `with` block lasts.

    with public_file_url("clip.mp4") as url:
        ...hand `url` to the API and wait until it has downloaded the file...
"""

import contextlib
import json
import re
import secrets
import shutil
import subprocess
import threading
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from social_common import SocialError


def available() -> bool:
    return shutil.which("ngrok") is not None


def _handler(path: Path, token: str):
    size = path.stat().st_size

    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _send(self, head_only: bool):
            if self.path.split("?")[0] != f"/{token}.mp4":
                self.send_error(404)
                return
            start, end, code = 0, size - 1, 200
            m = re.match(r"bytes=(\d*)-(\d*)", self.headers.get("Range", ""))
            if m and (m.group(1) or m.group(2)):
                if m.group(1):
                    start = int(m.group(1))
                    end = int(m.group(2)) if m.group(2) else size - 1
                else:
                    start = max(0, size - int(m.group(2)))
                end, code = min(end, size - 1), 206
            self.send_response(code)
            self.send_header("Content-Type", "video/mp4")
            self.send_header("Accept-Ranges", "bytes")
            self.send_header("Content-Length", str(end - start + 1))
            if code == 206:
                self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
            self.end_headers()
            if head_only:
                return
            with path.open("rb") as f:
                f.seek(start)
                left = end - start + 1
                while left > 0:
                    chunk = f.read(min(1 << 20, left))
                    if not chunk:
                        break
                    try:
                        self.wfile.write(chunk)
                    except (BrokenPipeError, ConnectionResetError):
                        return
                    left -= len(chunk)

        def do_GET(self):
            self._send(False)

        def do_HEAD(self):
            self._send(True)

    return H


@contextlib.contextmanager
def public_file_url(video_path: str):
    if not available():
        raise SocialError("ngrok isn't installed - needed to give Instagram a public link to the video (brew install ngrok).")
    path = Path(video_path).resolve()
    token = secrets.token_urlsafe(24)
    server = ThreadingHTTPServer(("127.0.0.1", 0), _handler(path, token))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    proc = subprocess.Popen(["ngrok", "http", str(server.server_address[1]), "--log=stdout"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        base = None
        for _ in range(40):
            time.sleep(0.5)
            if proc.poll() is not None:
                raise SocialError("ngrok exited right away - is it logged in? Run `ngrok config add-authtoken <token>` once.")
            try:
                tunnels = json.load(urllib.request.urlopen("http://127.0.0.1:4040/api/tunnels", timeout=2)).get("tunnels", [])
                base = next((t["public_url"] for t in tunnels if t["public_url"].startswith("https")), None)
            except Exception:
                base = None
            if base:
                break
        if not base:
            raise SocialError("ngrok didn't start a tunnel in time.")
        yield f"{base}/{token}.mp4"
    finally:
        proc.terminate()
        server.shutdown()
