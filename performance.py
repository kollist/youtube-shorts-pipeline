"""
performance.py
Groups uploaded clips (the upload log joined with real YouTube stats) by the
things you can actually change - which streamer, what format, how long, when
it was posted - so the Analytics tab can show which choices earn views and
subscribers instead of leaving that to a guess.

Median views is the headline number, not the average: one clip that blows up
would otherwise make a streamer or format look better than it typically is.
Groups with fewer than MIN_CONFIDENT_N clips are flagged as too small to trust.
"""

from datetime import datetime
from statistics import median

MIN_CONFIDENT_N = 5


def _length_bucket(r: dict) -> str:
    sec = r.get("duration_sec") or 0
    if sec < 20:
        return "under 20s"
    if sec < 30:
        return "20-30s"
    if sec < 45:
        return "30-45s"
    if sec < 60:
        return "45-60s"
    return "60s+"


def _posting_time(r: dict) -> str:
    try:
        hour = datetime.fromisoformat(r["uploaded_at"]).astimezone().hour  # viewer-agnostic: your local clock
    except (KeyError, ValueError):
        return "unknown"
    if hour < 6:
        return "00:00-06:00"
    if hour < 12:
        return "06:00-12:00"
    if hour < 18:
        return "12:00-18:00"
    return "18:00-24:00"


def _loudness(r: dict) -> str:
    score = r.get("peak_score")
    if score is None:
        return "not measured"
    if score < 8:
        return "quiet (under 8 dB over normal)"
    if score < 15:
        return "loud (8-15 dB)"
    return "very loud (15+ dB)"


def _yes_no(key: str):
    def label(r: dict) -> str:
        value = r.get(key)
        return "unknown" if value is None else ("on" if value else "off")
    return label


# (key, title, label function) - what the Analytics tab groups clips by.
DIMENSIONS = [
    ("streamer", "Streamer / source channel", lambda r: r.get("streamer") or "(untagged)"),
    ("format", "Layout", lambda r: {"split_screen": "split-screen"}.get(r.get("format", "normal"), "normal")),
    ("length", "Clip length", _length_bucket),
    ("posting_time", "Time posted (your local time)", _posting_time),
    ("loudness", "Detector loudness (stream mode)", _loudness),
    ("captions", "Captions", _yes_no("captions")),
    ("voiceover", "AI voiceover intro", _yes_no("voiceover")),
]


def _summarize(label: str, rows: list[dict]) -> dict:
    return {
        "label": label,
        "n": len(rows),
        "median_views": round(median(r["views"] for r in rows)),
        "avg_views": round(sum(r["views"] for r in rows) / len(rows)),
        "avg_retention": round(sum(r["avg_view_percentage"] for r in rows) / len(rows), 1),
        "subs_gained": sum(r.get("subscribers_gained", 0) for r in rows),
        "low_confidence": len(rows) < MIN_CONFIDENT_N,
    }


def compute_breakdowns(records_with_stats: list[dict]) -> list[dict]:
    """[{key, title, rows}] with rows sorted best-first by median views. A
    dimension with only one group is dropped - there's nothing to compare."""
    result = []
    for key, title, label_of in DIMENSIONS:
        groups: dict = {}
        for r in records_with_stats:
            groups.setdefault(label_of(r), []).append(r)
        if len(groups) < 2:
            continue
        rows = sorted(
            (_summarize(label, rs) for label, rs in groups.items()),
            key=lambda row: row["median_views"],
            reverse=True,
        )
        result.append({"key": key, "title": title, "rows": rows})
    return result
