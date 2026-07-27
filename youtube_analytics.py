"""
youtube_analytics.py
Pulls real view/retention numbers for uploaded clips from the YouTube
Analytics API, and joins them with the local hook_mechanic log (clip_log.py)
so you can see which hook mechanics actually hold viewers, not just which
ones got uploaded most.

ONE-TIME SETUP:
    1. Google Cloud Console -> APIs & Services -> Library -> enable
       "YouTube Analytics API" (same project as the upload OAuth client).
    2. That's it - the next call to get_credentials() (shared with
       upload_youtube.py via google_auth.py) will notice the cached token is
       missing the yt-analytics.readonly scope and automatically reopen the
       consent screen to grant it.

Usage:
    python youtube_analytics.py
"""

from datetime import date

from googleapiclient.discovery import build

from clip_log import read_log
from google_auth import get_credentials

ANALYTICS_START_DATE = "2020-01-01"  # broad enough to cover any upload date


def get_analytics_service():
    return build("youtubeAnalytics", "v2", credentials=get_credentials())


def get_channel_stats() -> dict:
    """Real channel-wide stats straight from YouTube (total video count, view
    count, subscriber count) - NOT derived from upload_log.jsonl, which only
    knows about clips uploaded through this pipeline since local logging was
    added, not your channel's actual full history."""
    service = build("youtube", "v3", credentials=get_credentials())
    response = service.channels().list(part="statistics", mine=True).execute()
    stats = response["items"][0]["statistics"]
    return {
        "video_count": int(stats.get("videoCount", 0)),
        "view_count": int(stats.get("viewCount", 0)),
        "subscriber_count": int(stats.get("subscriberCount", 0)),
    }


def fetch_video_stats(video_ids: list[str]) -> dict:
    """{video_id: {"views", "avg_view_duration_sec", "avg_view_percentage"}} -
    real retention numbers straight from YouTube, not our own upload log."""
    if not video_ids:
        return {}

    service = get_analytics_service()
    response = service.reports().query(
        ids="channel==MINE",
        startDate=ANALYTICS_START_DATE,
        endDate=str(date.today()),
        metrics="views,estimatedMinutesWatched,averageViewDuration,averageViewPercentage",
        dimensions="video",
        filters=f"video=={','.join(video_ids)}",
        maxResults=len(video_ids),
    ).execute()

    stats = {}
    for row in response.get("rows", []):
        video_id, views, _watched_min, avg_dur, avg_pct = row
        stats[video_id] = {
            "views": int(views),
            "avg_view_duration_sec": round(avg_dur, 1),
            "avg_view_percentage": round(avg_pct, 1),
        }
    return stats


def hook_mechanic_performance() -> list[dict]:
    """Real retention numbers averaged per hook_mechanic, joining
    upload_log.jsonl's local records with the YouTube Analytics API."""
    records = read_log()
    video_ids = [r["video_id"] for r in records if r.get("video_id")]
    stats = fetch_video_stats(video_ids)

    by_mechanic: dict = {}
    for r in records:
        stat = stats.get(r.get("video_id"))
        if not stat:
            continue  # too recent for analytics to have processed yet, or not found
        mechanic = r.get("hook_mechanic", "unknown")
        bucket = by_mechanic.setdefault(mechanic, {"count": 0, "total_views": 0, "total_pct": 0.0})
        bucket["count"] += 1
        bucket["total_views"] += stat["views"]
        bucket["total_pct"] += stat["avg_view_percentage"]

    return [
        {
            "hook_mechanic": mechanic,
            "clip_count": b["count"],
            "avg_views": round(b["total_views"] / b["count"], 1),
            "avg_view_percentage": round(b["total_pct"] / b["count"], 1),
        }
        for mechanic, b in by_mechanic.items()
    ]


if __name__ == "__main__":
    for row in hook_mechanic_performance():
        print(f"{row['hook_mechanic']:20s} n={row['clip_count']:3d}  "
              f"avg_views={row['avg_views']:8.1f}  avg_view_pct={row['avg_view_percentage']:5.1f}%")
