"""
auto_daily.py - one new Foundation Tapes episode a day, built ahead of the evening and posted to every platform.

How a day goes (all times US Eastern, whatever your Mac's clock says):
  from 10:00  - if no finished, unposted episode is waiting, take the next SCP number from data/scp_queue.json, write it, make the pictures,
                render the normal cut and the YouTube-quality cut
  20:00-23:30 - run safety checks, then post: YouTube (YouTube-quality file), Facebook, Instagram, and TikTok as a DRAFT in your inbox (normal file).
  Then a Mac notification. A failed platform is retried on later runs (up to 3 attempts). TikTok drafts: until TikTok approves the app, direct posts are
  private-only, so open TikTok, paste the caption (python auto_daily.py caption copies it) and press Post. A TikTok failure is not retried.
Nothing is deleted after posting. Media older than 10 days is cleaned up.

Run by launchd every 20 minutes (see launchd/com.shorts.foundation-tapes-daily.plist); safe to run by hand:
    python auto_daily.py status                 what is queued, ready, posted; the last post's links
    python auto_daily.py run [--now] [--dry-run] [--episode N]
                                                --now ignores the clock windows; --dry-run does every check and writes the captions but posts nothing
    python auto_daily.py pause | resume         stop / start the daily job
    python auto_daily.py queue 049 106 ...      add SCP numbers to the end of the queue
    python auto_daily.py remake N               after you take episode N down: wipe it and put its SCP back at the front of the queue
"""

import argparse
import datetime as dt
import fcntl
import json
import os
import re
import shutil
import subprocess
import sys
import time
import traceback
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).parent
os.environ.setdefault("USER", Path.home().name); os.environ.setdefault("LOGNAME", Path.home().name)       # launchd gives a bare environment; Claude Code needs these
os.environ["PATH"] = os.environ.get("PATH", "") + ":/opt/homebrew/bin:/usr/local/bin"
DATA = ROOT / "data"
SLUG = "foundation-tapes"
TZ = ZoneInfo("America/New_York")
BUILD_FROM, POST_FROM, POST_UNTIL = dt.time(10, 0), dt.time(20, 0), dt.time(23, 30)
PLATFORMS = ["youtube", "facebook", "instagram", "tiktok"]
MAX_ATTEMPTS = 3
KEEP_DAYS = 10

QUEUE, STATE, LOG, PAUSE, LOCK, HOLD = (DATA / n for n in ("scp_queue.json", "auto_state.json", "auto_log.jsonl", "auto_pause", "auto.lock", "auto_hold.json"))


# ---------------------------------------------------------------- small helpers
def now_et() -> dt.datetime:
    return dt.datetime.now(TZ)


def log(kind: str, **kw) -> None:
    DATA.mkdir(exist_ok=True)
    row = {"at": now_et().isoformat(timespec="seconds"), "kind": kind, **kw}
    with LOG.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")
    print(f"[auto] {kind} {kw if kw else ''}")


def notify(title: str, message: str) -> None:
    log("notify", title=title, message=message)
    try:
        subprocess.run(["osascript", "-e", f'display notification {json.dumps(message)} with title {json.dumps(title)} sound name "Glass"'], timeout=15)
    except Exception:
        pass


def _read(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def _write(path: Path, obj) -> None:
    DATA.mkdir(exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, ensure_ascii=False), encoding="utf-8")


def queue() -> list[str]:
    return [str(n).zfill(3) for n in _read(QUEUE, {"queue": []}).get("queue", [])]


def save_queue(q: list[str]) -> None:
    _write(QUEUE, {"queue": q})


# ---------------------------------------------------------------- episodes
def _series_mod():
    import series
    return series


def ep_dir(n: int) -> Path:
    return _series_mod().episode_dir(SLUG, n)


def episodes() -> list[int]:
    s = _series_mod(); sj = _read(s.STORIES_DIR / SLUG / "series.json", {"arc": []})
    return list(range(1, len(sj["arc"]) + 1))


def held(n: int) -> bool:
    """data/auto_hold.json = {"3": "2026-10-31"}: episode 3 is finished but must not post before that US-Eastern date (e.g. a Halloween episode built early)."""
    until = _read(HOLD, {}).get(str(n))
    return bool(until) and now_et().date().isoformat() < until


def ready_episode() -> int | None:
    """The lowest-numbered episode that has a finished video, is not held, and has not been posted."""
    for n in episodes():
        d = ep_dir(n)
        if held(n):
            continue
        if (d / "story.json").exists() and not (d / "posted.json").exists() and (d / f"{d.name}-HORROR.mp4").exists():
            return n
    return None


def build_next() -> int:
    s = _series_mod(); q = queue()
    have = {str(e.get("scp", "")).zfill(3) for e in _read(s.STORIES_DIR / SLUG / "series.json", {"arc": []})["arc"]}
    q = [n for n in q if n not in have]
    if not q:
        save_queue([])
        raise RuntimeError("the SCP queue is empty")
    number = q[0]
    s.add_episode(SLUG, number)
    save_queue(q[1:])
    n = len(episodes())
    log("build_start", episode=n, scp=number)
    s.make_episode(SLUG, n, log=lambda m: print(m, flush=True))                       # script, pictures, normal cut
    from horror_video import build_horror_video
    build_horror_video(str(ep_dir(n)), log=lambda m: print(m, flush=True), yt=True)    # the YouTube-quality cut
    log("build_done", episode=n, scp=number)
    return n


# ---------------------------------------------------------------- safety checks
def _probe_seconds(p: Path) -> float:
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(p)], capture_output=True, text=True).stdout.strip()
    try:
        return float(out)
    except ValueError:
        return 0.0


def check(n: int) -> list[str]:
    """Returns the reasons NOT to post (empty list = fine)."""
    d = ep_dir(n); bad = []
    try:
        story = json.loads((d / "story.json").read_text(encoding="utf-8"))
    except Exception:
        return ["story.json is missing or broken"]
    normal, yt = d / f"{d.name}-HORROR.mp4", d / f"{d.name}-HORROR-YT.mp4"
    for f in (normal, yt):
        if not f.exists():
            bad.append(f"{f.name} is missing")
        elif not 25 <= _probe_seconds(f) <= 90:
            bad.append(f"{f.name} has an odd length ({_probe_seconds(f):.0f}s)")
    credit = (story.get("credit") or {}).get("line", "")
    m = re.search(r"by (.+?) - ", credit)
    if not m or m.group(1).strip().lower() in ("", "author", "unknown", "?", "none"):
        bad.append(f"the SCP credit looks wrong: {credit!r}")
    if not (d / "credit.txt").exists():
        bad.append("credit.txt is missing")
    if not story.get("title", "").strip():
        bad.append("the title is empty")
    return bad


# ---------------------------------------------------------------- captions + posting
def captions_for(n: int, remember: bool = True) -> dict:
    from export_posts import episode_captions
    return episode_captions(SLUG, n, remember=remember)


def post(n: int, platforms: list[str], dry: bool) -> dict:
    from social_post import post_video
    d = ep_dir(n); c = captions_for(n, remember=not dry)
    normal, yt = d / f"{d.name}-HORROR.mp4", d / f"{d.name}-HORROR-YT.mp4"
    if dry:
        (DATA / "tiktok_caption.txt").write_text(c["caps"]["tiktok"], encoding="utf-8")      # so `auto_daily.py caption` can be tried before the first real post
        print("\n=== DRY RUN: would post to", platforms)
        for k in ("youtube_title", "youtube", "instagram", "facebook", "tiktok"):
            print(f"--- {k}\n{c['caps'].get(k, '')}")
        return {}
    results = {}
    for plat in platforms:
        video = yt if plat == "youtube" else normal
        if plat == "tiktok":                                              # unaudited app: a draft in your TikTok inbox, which you publish with one tap
            try:
                import social_tiktok
                (DATA / "tiktok_caption.txt").write_text(c["caps"]["tiktok"], encoding="utf-8")
                results["tiktok"] = {"ok": True, **social_tiktok.post_draft(str(video), c["caps"]["tiktok"])}
            except Exception as e:
                results["tiktok"] = {"ok": False, "error": str(e)}
            continue
        out = post_video(str(video), c["title"], c["summary"], [plat], "public", aigc=True, captions=c["caps"], category=c["category"],
                         youtube_license="creativeCommon")
        results.update(out["results"])
    return results


def writer_ready() -> str | None:
    """None if SOME model answers (Claude Code first, then the free Groq / OpenRouter models); otherwise the reason. We never post the bland template captions."""
    try:
        from series import _llm_json
        _llm_json('Respond with ONLY a JSON object {"ok": true}', "ping")
        return None
    except Exception as e:
        return str(e)[:120]


def run_post(n: int, state: dict, dry: bool) -> None:
    why = writer_ready()
    if why:
        if state.get("writer_notified") != now_et().date().isoformat():
            state["writer_notified"] = now_et().date().isoformat(); _write(STATE, state)
            notify(f"Episode {n} NOT posted", f"No model could write the captions (Claude Code and the free models all failed): {why}")
        log("writer_unavailable", episode=n, reason=why); return
    today = state.setdefault("posting", {"episode": n, "results": {}, "attempts": 0})
    if today.get("episode") != n:
        today.clear(); today.update({"episode": n, "results": {}, "attempts": 0})
    todo = [p for p in PLATFORMS if not today["results"].get(p, {}).get("ok") and not today["results"].get(p, {}).get("final")]
    if dry:
        post(n, todo or PLATFORMS, True)
        notify("Foundation Tapes (dry run)", f"Episode {n} passed every check. Nothing was posted.")
        return
    today["attempts"] += 1
    res = post(n, todo, False)
    for plat, r in res.items():
        if plat == "tiktok" and not r.get("ok"):
            r = {**r, "final": True}
        today["results"][plat] = r
    _write(STATE, state)
    failed = [p for p in PLATFORMS if not today["results"].get(p, {}).get("ok")]
    retryable = [p for p in failed if not today["results"].get(p, {}).get("final")]
    if retryable and today["attempts"] < MAX_ATTEMPTS:
        log("post_partial", episode=n, failed=retryable)
        return                                                    # the next run (20 minutes later) tries the failed ones again
    story = json.loads((ep_dir(n) / "story.json").read_text(encoding="utf-8"))
    ok = [p for p in PLATFORMS if today["results"].get(p, {}).get("ok")]
    (ep_dir(n) / "posted.json").write_text(json.dumps({"at": now_et().isoformat(timespec="seconds"), "results": {
        p: {"url": r.get("url"), "id": r.get("id")} for p, r in today["results"].items() if r.get("ok")}}, indent=2), encoding="utf-8")
    state["posted_date"] = now_et().date().isoformat(); state.pop("posting", None); state.pop("ready", None)
    _write(STATE, state)
    marks = " ".join(f"{p.capitalize()} {('draft' if p == 'tiktok' else 'OK') if p in ok else 'FAILED'}" for p in PLATFORMS)
    errors = {p: str(today["results"].get(p, {}).get("error", ""))[:300] for p in PLATFORMS if p not in ok}
    extra = ("  TikTok: draft is in your inbox - open the app, paste the caption (auto_daily.py caption), press Post." if "tiktok" in ok
             else f"  TikTok failed ({errors.get('tiktok', '')[:90]}): upload by hand.")
    urls = {p: today["results"][p].get("url") for p in ok if today["results"][p].get("url")}
    log("posted", episode=n, title=story["title"], urls=urls, failed=[p for p in PLATFORMS if p not in ok], errors=errors)
    notify(f"Episode {n} posted: {story['title'][:40]}", marks + extra + "  Review it; run 'auto_daily.py remake' to redo it.")


# ---------------------------------------------------------------- housekeeping
def cleanup_old() -> None:
    cutoff = time.time() - KEEP_DAYS * 86400
    for n in episodes():
        d = ep_dir(n); pj = d / "posted.json"
        if pj.exists() and pj.stat().st_mtime < cutoff:
            for p in list(d.glob("*.mp4")) + [d / x for x in ("images", "build", "build_horror")]:
                shutil.rmtree(p, ignore_errors=True) if p.is_dir() else p.unlink(missing_ok=True)


# ---------------------------------------------------------------- main
def run(now: bool = False, dry: bool = False, episode: int | None = None) -> None:
    DATA.mkdir(exist_ok=True)
    if PAUSE.exists() and not dry:
        print("[auto] paused (python auto_daily.py resume)"); return
    lock = LOCK.open("w")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        print("[auto] another run is in progress"); return
    subprocess.Popen(["caffeinate", "-i", "-w", str(os.getpid())])         # don't let the Mac sleep mid-render
    t = now_et(); today = t.date().isoformat(); state = _read(STATE, {})
    try:
        if dry:
            n = episode or ready_episode()
            if not n:
                print("[auto] dry run: no ready episode - pass --episode N"); return
            bad = check(n)
            print(f"[auto] checks for episode {n}:", bad or "all fine")
            if bad:
                notify("Foundation Tapes (dry run)", f"Episode {n} would NOT post: {bad[0]}"); return
            run_post(n, state, True); return
        if state.get("posted_date") == today and not now:
            cleanup_old(); return
        n = ready_episode()
        if n is None:
            if not (now or t.time() >= BUILD_FROM):
                return
            if not queue():
                if state.get("empty_notified") != today:
                    state["empty_notified"] = today; _write(STATE, state)
                    notify("Foundation Tapes: queue is empty", "Add SCP numbers: python auto_daily.py queue 049 106 ...")
                return
            try:
                n = build_next()
            except Exception as e:
                log("build_failed", error=str(e), trace=traceback.format_exc()[-800:])
                notify("Foundation Tapes: build failed", str(e)[:150]); return
        in_window = POST_FROM <= t.time() <= POST_UNTIL
        if not (now or in_window):
            return
        bad = check(n)
        if bad:
            if state.get("blocked") != f"{n}:{bad[0]}":
                state["blocked"] = f"{n}:{bad[0]}"; _write(STATE, state)
                log("blocked", episode=n, reasons=bad)
                notify(f"Episode {n} NOT posted", bad[0][:150])
            return
        run_post(n, state, False)
    finally:
        fcntl.flock(lock, fcntl.LOCK_UN)


def status() -> None:
    state = _read(STATE, {}); print("paused:", PAUSE.exists()); print("queue :", queue() or "(empty)")
    print("ready :", ready_episode() or "(none)"); print("held  :", _read(HOLD, {}) or "(none)"); print("state :", {k: v for k, v in state.items() if k != "posting"})
    for line in LOG.read_text(encoding="utf-8").splitlines()[-30:][::-1] if LOG.exists() else []:
        row = json.loads(line)
        if row["kind"] == "posted":
            print("last posted:", row["at"], row["title"]); [print("  ", p, u) for p, u in row.get("urls", {}).items()]; break
    print("now (US Eastern):", now_et().strftime("%a %H:%M"), "| builds from 10:00, posts 20:00-23:30")


def remake(n: int) -> None:
    s = _series_mod(); d = ep_dir(n)
    if n != len(episodes()):
        sys.exit("Only the newest episode can be remade (the numbers of later ones would shift).")
    sj = _read(s.STORIES_DIR / SLUG / "series.json", {"arc": []}); scp = str(sj["arc"][n - 1].get("scp", "")).zfill(3)
    for p in list(d.glob("*.mp4")) + [d / x for x in ("images", "build", "build_horror", "posted.json", "story.json", "credit.txt")]:
        shutil.rmtree(p, ignore_errors=True) if p.is_dir() else p.unlink(missing_ok=True)
    sj["arc"].pop(n - 1)
    _write(s.STORIES_DIR / SLUG / "series.json", sj)
    save_queue([scp] + [x for x in queue() if x != scp])
    print(f"Episode {n} wiped. SCP-{scp} is back at the front of the queue (the next daily run rebuilds it).")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(); sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run"); r.add_argument("--now", action="store_true"); r.add_argument("--dry-run", action="store_true"); r.add_argument("--episode", type=int)
    sub.add_parser("caption"); sub.add_parser("status"); sub.add_parser("pause"); sub.add_parser("resume")
    q = sub.add_parser("queue"); q.add_argument("numbers", nargs="+")
    m = sub.add_parser("remake"); m.add_argument("episode", type=int)
    a = ap.parse_args()
    if a.cmd == "run":
        run(a.now, a.dry_run, a.episode)
    elif a.cmd == "status":
        status()
    elif a.cmd == "caption":
        txt = (DATA / "tiktok_caption.txt").read_text(encoding="utf-8") if (DATA / "tiktok_caption.txt").exists() else ""
        if not txt.strip():
            sys.exit("No TikTok caption saved yet - it is written when the job posts an episode.")
        subprocess.run(["pbcopy"], input=txt.encode()); print("Copied the latest TikTok caption to your clipboard:\n\n" + txt)
    elif a.cmd == "pause":
        DATA.mkdir(exist_ok=True); PAUSE.write_text("paused"); print("Paused. The daily job does nothing until: python auto_daily.py resume")
    elif a.cmd == "resume":
        PAUSE.unlink(missing_ok=True); print("Resumed.")
    elif a.cmd == "queue":
        save_queue(queue() + [re.sub(r"\D", "", n).zfill(3) for n in a.numbers]); print("Queue:", queue())
    elif a.cmd == "remake":
        remake(a.episode)
