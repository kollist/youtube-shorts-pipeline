"""
variety_report.py
Which creative choices actually get watched? Every episode records its shape, ending, scare profile and picture look in story.json; this lines those up with real views.

    python variety_report.py                 collect the numbers now, print the report, save data/variety_report.md
    python variety_report.py --no-fetch      report from the saved history only (no API calls)
    python variety_report.py set tiktok ep06 17    enter a number the APIs can't give us (TikTok); also instagram / facebook / youtube if their API refuses

Numbers come from: YouTube (Data API), Instagram and Facebook (Graph API with your Page token - may be refused if the token lacks insights permission, then it says so),
and data/manual_metrics.json for anything you type in. Each collection is also appended to data/metrics_history.jsonl, so episodes can be compared at the same age
(views ~48 hours after posting) instead of whichever happens to be oldest.

How to read it: with only a handful of episodes per choice the averages are noise. Anything with fewer than 3 episodes is flagged. Judge after ~20 episodes, and
treat small gaps as nothing.
"""

import datetime as dt
import json
import statistics
import sys
import time
from pathlib import Path

import requests

BASE = Path(__file__).parent
DATA = BASE / "data"
HISTORY, MANUAL, REPORT = DATA / "metrics_history.jsonl", DATA / "manual_metrics.json", DATA / "variety_report.md"
SLUG = "foundation-tapes"
GRAPH = "https://graph.facebook.com/v25.0"
PLATFORMS = ["youtube", "instagram", "tiktok", "facebook"]
DIMENSIONS = [("shape", "story shape"), ("finale_type", "ending"), ("scare_profile", "scare"), ("picture_style", "picture look")]


def _episodes() -> list[dict]:
    out = []
    for d in sorted((BASE / "stories" / SLUG / "episodes").glob("ep*")):
        pj, sj = d / "posted.json", d / "story.json"
        if not (pj.exists() and sj.exists()):
            continue
        try:
            posted, story = json.loads(pj.read_text(encoding="utf-8")), json.loads(sj.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        res = posted.get("results", {})
        yt = (res.get("youtube_reupload_private") or res.get("youtube") or {}).get("id")      # ep01: the better-quality re-upload
        out.append({"ep": d.name, "title": story.get("title", ""), "scp": (story.get("credit") or {}).get("item", ""), "at": posted.get("at", ""),
                    "ids": {"youtube": yt, "instagram": (res.get("instagram") or {}).get("id"), "facebook": (res.get("facebook") or {}).get("id")},
                    "variety": {k: story.get(k) or "legacy" for k, _ in DIMENSIONS}, "tape_no": story.get("tape_no") or int(d.name[2:] or 0)})
    return out


# ---------------------------------------------------------------- collectors (each returns None when it cannot get a number)
def _youtube(ids: list[str]) -> dict:
    try:
        from upload_youtube import get_authenticated_service
        yt, out = get_authenticated_service(), {}
        for i in range(0, len(ids), 50):
            for v in yt.videos().list(part="statistics", id=",".join(ids[i:i + 50])).execute().get("items", []):
                out[v["id"]] = int(v["statistics"].get("viewCount", 0))
        return out
    except Exception as e:
        print(f"[report] YouTube numbers unavailable: {str(e)[:100]}")
        return {}


def _graph(path: str, params: dict) -> dict | None:
    from social_common import env
    token = env("FACEBOOK_PAGE_ACCESS_TOKEN")
    if not token:
        return None
    try:
        r = requests.get(f"{GRAPH}/{path}", params={**params, "access_token": token}, timeout=20)
        return r.json() if r.status_code == 200 else None
    except requests.RequestException:
        return None


def _instagram(media_id: str) -> int | None:
    for metric in ("views", "plays", "ig_reels_aggregated_all_plays_count"):
        j = _graph(f"{media_id}/insights", {"metric": metric})
        if j and j.get("data"):
            try:
                return int(j["data"][0]["values"][0]["value"])
            except (KeyError, IndexError, ValueError):
                pass
    return None


def _facebook(video_id: str) -> int | None:
    j = _graph(video_id, {"fields": "views"})
    if j and j.get("views") is not None:
        return int(j["views"])
    j = _graph(f"{video_id}/video_insights", {"metric": "blue_reels_play_count"})
    if j and j.get("data"):
        try:
            return int(j["data"][0]["values"][0]["value"])
        except (KeyError, IndexError, ValueError):
            pass
    return None


def _manual() -> dict:
    try:
        return json.loads(MANUAL.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def collect() -> list[dict]:
    """Fetch the latest views for every posted episode. Returns one record per episode: {"ep", "views": {platform: n}, ...}."""
    eps, man = _episodes(), _manual()
    yt = _youtube([e["ids"]["youtube"] for e in eps if e["ids"]["youtube"]])
    rows = []
    for e in eps:
        v = {}
        if e["ids"]["youtube"] in yt:
            v["youtube"] = yt[e["ids"]["youtube"]]
        for plat, fn in (("instagram", _instagram), ("facebook", _facebook)):
            if e["ids"][plat]:
                n = fn(e["ids"][plat])
                if n is not None:
                    v[plat] = n
        for plat in PLATFORMS:                                    # typed-in numbers fill what the APIs refuse (and win if larger: they were read later)
            m = (man.get(plat) or {}).get(e["ep"])
            if m is not None and m >= v.get(plat, -1):
                v[plat] = int(m)
        rows.append({**e, "views": v})
    return rows


def snapshot() -> int:
    """Append today's numbers to the history (at most once every 20 hours). Returns how many episodes were recorded."""
    DATA.mkdir(exist_ok=True)
    try:
        last = json.loads(HISTORY.read_text(encoding="utf-8").strip().splitlines()[-1])["at"]
        if time.time() - dt.datetime.fromisoformat(last).timestamp() < 20 * 3600:
            return 0
    except (OSError, IndexError, KeyError, ValueError):
        pass
    rows, now = collect(), dt.datetime.now().astimezone().isoformat(timespec="seconds")
    with HISTORY.open("a", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps({"at": now, "ep": r["ep"], "views": r["views"]}) + "\n")
    return len(rows)


def _history() -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {}
    try:
        for line in HISTORY.read_text(encoding="utf-8").splitlines():
            row = json.loads(line)
            out.setdefault(row["ep"], []).append(row)
    except (OSError, json.JSONDecodeError):
        pass
    return out


def _total(v: dict) -> int:
    return sum(v.get(p, 0) for p in PLATFORMS)


def report(rows: list[dict]) -> str:
    now, hist = dt.datetime.now().astimezone(), _history()
    for r in rows:
        try:
            posted = dt.datetime.fromisoformat(r["at"])
            posted = posted if posted.tzinfo else posted.astimezone()
        except ValueError:
            posted = now
        r["age"] = max(0.3, (now - posted).total_seconds() / 86400)
        r["total"] = _total(r["views"])
        r["per_day"] = r["total"] / r["age"]
        near = [h for h in hist.get(r["ep"], []) if 40 <= (dt.datetime.fromisoformat(h["at"]) - posted).total_seconds() / 3600 <= 80]
        r["at48"] = _total(near[0]["views"]) if near else None
    lines = ["# Variety report", f"_{now.strftime('%Y-%m-%d %H:%M')} - {len(rows)} posted episodes_", "",
             "## Episodes", "", "| tape | SCP | age (days) | YouTube | Instagram | TikTok | Facebook | total | per day | shape / ending / scare / look |", "|---|---|---|---|---|---|---|---|---|---|"]
    for r in sorted(rows, key=lambda x: x["tape_no"]):
        v, var = r["views"], r["variety"]
        cell = lambda p: str(v[p]) if p in v else "-"
        lines.append(f"| {r['tape_no']} | {r['scp']} | {r['age']:.1f} | {cell('youtube')} | {cell('instagram')} | {cell('tiktok')} | {cell('facebook')} | {r['total']} | {r['per_day']:.0f} | "
                     f"{var['shape']} / {var['finale_type']} / {var['scare_profile']} / {var['picture_style']} |")
    base = statistics.mean([r["per_day"] for r in rows]) if rows else 0
    lines += ["", f"Average across all episodes: **{base:.0f} views per day**. Missing numbers (a dash) count as zero in the totals, so TikTok and Facebook are undercounted until you enter them.", ""]
    for key, label in DIMENSIONS:
        groups: dict[str, list[dict]] = {}
        for r in rows:
            groups.setdefault(r["variety"][key], []).append(r)
        lines += [f"## By {label}", "", "| choice | episodes | avg views/day | vs average |", "|---|---|---|---|"]
        for name, g in sorted(groups.items(), key=lambda kv: -statistics.mean(x["per_day"] for x in kv[1])):
            m = statistics.mean(x["per_day"] for x in g)
            flag = "  (too few to trust)" if len(g) < 3 else ""
            lines.append(f"| {name} | {len(g)} | {m:.0f} | {(m / base - 1) * 100:+.0f}%{flag} |" if base else f"| {name} | {len(g)} | {m:.0f} | - |")
        lines.append("")
    lines += ["_Views per day divides by how long the episode has been live, which still favours older episodes a little (most views come early). The 48-hour column in the history, once it fills in, is the fairer comparison._"]
    return "\n".join(lines)


def main() -> None:
    args = sys.argv[1:]
    if args[:1] == ["set"]:
        if len(args) != 4 or args[1] not in PLATFORMS:
            sys.exit("usage: python variety_report.py set <youtube|instagram|tiktok|facebook> <epNN> <views>")
        m = _manual(); m.setdefault(args[1], {})[args[2]] = int(args[3])
        DATA.mkdir(exist_ok=True); MANUAL.write_text(json.dumps(m, indent=1), encoding="utf-8")
        print(f"saved: {args[1]} {args[2]} = {args[3]}"); return
    if "--no-fetch" in args:
        rows = []
        latest = {ep: h[-1] for ep, h in _history().items()}
        for e in _episodes():
            v = dict((latest.get(e["ep"]) or {}).get("views", {}))
            for plat in PLATFORMS:                                      # typed-in numbers count here too
                m = (_manual().get(plat) or {}).get(e["ep"])
                if m is not None and m >= v.get(plat, -1):
                    v[plat] = int(m)
            rows.append({**e, "views": v})
    else:
        snapshot()
        rows = collect()
    text = report(rows)
    DATA.mkdir(exist_ok=True); REPORT.write_text(text, encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
