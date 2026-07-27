"""
clip_log.py
Records a permanent, append-only log of every clip actually uploaded to
YouTube - title, hook mechanic, video id, duration, timestamp - since
cut_clips.py's meta JSON in output/ gets deleted right after a successful
upload (see upload_youtube.py's delete_uploaded_clip). This is the data
needed later to correlate hook mechanics with real YouTube retention
performance once you're pulling numbers from the YouTube Analytics API.

Usage:
    from clip_log import log_upload, read_log
"""

import json
from datetime import datetime, timezone
from pathlib import Path

LOG_FILE = Path("upload_log.jsonl")


def log_upload(record: dict) -> None:
    record = dict(record)
    record.setdefault("uploaded_at", datetime.now(timezone.utc).isoformat())
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def read_log() -> list[dict]:
    if not LOG_FILE.exists():
        return []
    records = []
    with open(LOG_FILE, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return records
