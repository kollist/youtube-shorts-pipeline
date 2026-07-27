"""
run_control.py
Shared "stop this run" primitive. A live Python thread can't be safely killed
outright, so stopping a run is cooperative: the worker thread's cancel_event
gets set when the user hits Stop, and every slower step (Groq chunk calls +
cooldowns, ffmpeg cuts, uploads + spacing, whisper segments, yt-dlp downloads)
checks it at a safe point in between and raises RunCancelled rather than
starting the next unit of work. A step already in flight (a single Groq call,
a single ffmpeg cut) still runs to completion - only the gaps between steps
are actually interruptible.

Usage:
    from run_control import RunCancelled, check_cancelled, interruptible_sleep
"""

import threading


class RunCancelled(Exception):
    """Raised when a user stops an in-progress run via the Stop button."""


def check_cancelled(cancel_event: threading.Event | None) -> None:
    if cancel_event is not None and cancel_event.is_set():
        raise RunCancelled("Run stopped by user.")


def interruptible_sleep(seconds: float, cancel_event: threading.Event | None) -> None:
    """time.sleep() that wakes up immediately and raises RunCancelled if the
    run gets stopped mid-wait, instead of blocking out the full duration -
    matters most for the long cooldowns between Groq calls and the spacing
    gaps between daily-queue uploads."""
    if cancel_event is None:
        import time
        time.sleep(seconds)
        return
    if cancel_event.wait(seconds):
        raise RunCancelled("Run stopped by user.")
