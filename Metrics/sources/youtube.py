"""YouTube: per-video stats (Data API + Analytics API) and channel daily totals."""
import datetime as dt
import os

import pandas as pd
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

SCOPES = [
    "https://www.googleapis.com/auth/youtube.readonly",
    "https://www.googleapis.com/auth/yt-analytics.readonly",
]
DAILY_DAYS = 90


def _creds(keys_dir):
    client_file = os.path.join(keys_dir, "youtube-oauth-client.json")
    token_file = os.path.join(keys_dir, "youtube-token.json")
    creds = None
    if os.path.exists(token_file):
        creds = Credentials.from_authorized_user_file(token_file, SCOPES)
    if creds and creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
        except Exception:
            creds = None
    if not creds or not creds.valid:
        if os.environ.get("CI"):   # GitHub Actions: no browser for a login
            raise RuntimeError("YouTube login needed: run the report once on the Mac")
        flow = InstalledAppFlow.from_client_secrets_file(client_file, SCOPES)
        creds = flow.run_local_server(port=0, prompt="consent")
    with open(token_file, "w") as f:
        f.write(creds.to_json())
    os.chmod(token_file, 0o600)
    return creds


def _et(ts):
    return pd.Timestamp(ts).tz_convert("America/New_York").strftime("%Y-%m-%d %H:%M")


def _iso_seconds(d):
    """PT1M5S -> 65"""
    import re
    m = re.fullmatch(r"P(?:\d+D)?T?(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", d or "")
    if not m:
        return None
    h, mi, s = (int(x or 0) for x in m.groups())
    return h * 3600 + mi * 60 + s


def _analytics(yta, **kw):
    r = yta.reports().query(ids="channel==MINE", **kw).execute()
    cols = [c["name"] for c in r.get("columnHeaders", [])]
    return pd.DataFrame(r.get("rows", []), columns=cols)


def fetch(keys_dir, today):
    creds = _creds(keys_dir)
    yt = build("youtube", "v3", credentials=creds, cache_discovery=False)
    yta = build("youtubeAnalytics", "v2", credentials=creds, cache_discovery=False)

    ch = yt.channels().list(part="snippet,statistics,contentDetails,brandingSettings", mine=True).execute()["items"][0]
    uploads = ch["contentDetails"]["relatedPlaylists"]["uploads"]

    ids, token = [], None
    while True:
        r = yt.playlistItems().list(part="contentDetails", playlistId=uploads,
                                    maxResults=50, pageToken=token).execute()
        ids += [i["contentDetails"]["videoId"] for i in r["items"]]
        token = r.get("nextPageToken")
        if not token:
            break

    rows = []
    for i in range(0, len(ids), 50):
        r = yt.videos().list(part="snippet,statistics,contentDetails,status",
                             id=",".join(ids[i:i + 50])).execute()
        for v in r["items"]:
            s = v.get("statistics", {})
            rows.append({
                "video_id": v["id"],
                "title": v["snippet"]["title"],
                "published": _et(v["snippet"]["publishedAt"]),
                "privacy": v["status"]["privacyStatus"],
                "length_s": _iso_seconds(v["contentDetails"].get("duration")),
                "views": int(s.get("viewCount", 0)),
                "likes": int(s.get("likeCount", 0)),
                "comments": int(s.get("commentCount", 0)),
                "favorites": int(s.get("favoriteCount", 0)),
                "description": v["snippet"].get("description"),
                "tags": ", ".join(v["snippet"].get("tags") or []),
                "category_id": v["snippet"].get("categoryId"),
                "language": v["snippet"].get("defaultLanguage") or v["snippet"].get("defaultAudioLanguage"),
                "definition": v["contentDetails"].get("definition"),
                "custom_thumbnail": v["contentDetails"].get("hasCustomThumbnail"),
                "made_for_kids": v["status"].get("madeForKids"),
                "thumbnail_url": ((v["snippet"].get("thumbnails") or {}).get("high") or {}).get("url"),
                "url": f"https://youtube.com/shorts/{v['id']}",
            })
    videos = pd.DataFrame(rows)

    end = today.isoformat()
    per_video = _analytics(
        yta, startDate=ch["snippet"]["publishedAt"][:10], endDate=end, dimensions="video",
        metrics="views,engagedViews,estimatedMinutesWatched,averageViewDuration,averageViewPercentage,"
                "shares,subscribersGained,subscribersLost,videosAddedToPlaylists,videosRemovedFromPlaylists,dislikes",
        sort="-views", maxResults=200,
    ).rename(columns={
        "video": "video_id", "views": "an_views", "engagedViews": "engaged_views",
        "estimatedMinutesWatched": "watch_min", "averageViewDuration": "avg_view_s",
        "averageViewPercentage": "avg_view_pct",
    })
    if not videos.empty:
        videos = videos.merge(per_video, on="video_id", how="left")
        videos.insert(0, "snapshot_date", end)

    start = (today - dt.timedelta(days=DAILY_DAYS)).isoformat()
    daily = _analytics(
        yta, startDate=start, endDate=end, dimensions="day",
        metrics="views,engagedViews,estimatedMinutesWatched,averageViewDuration,averageViewPercentage,likes,"
                "dislikes,comments,shares,subscribersGained,subscribersLost,videosAddedToPlaylists",
        sort="day",
    ).rename(columns={"day": "date", "estimatedMinutesWatched": "watch_min",
                      "averageViewDuration": "avg_view_s"})

    st = ch["statistics"]
    channel = pd.DataFrame([{
        "snapshot_date": end,
        "channel": ch["snippet"]["title"],
        "subscribers": int(st.get("subscriberCount", 0)),
        "total_views": int(st.get("viewCount", 0)),
        "videos": int(st.get("videoCount", 0)),
    }])

    # per-video daily, traffic sources, retention (one query per public/mapped video)
    first = ch["snippet"]["publishedAt"][:10]
    vid_daily, vid_traffic, retention = [], [], []
    for vid in (videos["video_id"] if not videos.empty else []):
        f = f"video=={vid}"
        d = _analytics(yta, startDate=first, endDate=end, dimensions="day", filters=f,
                       metrics="views,engagedViews,estimatedMinutesWatched,averageViewDuration,averageViewPercentage,"
                               "likes,comments,shares,subscribersGained")
        d.insert(0, "video_id", vid)
        vid_daily.append(d)
        t = _analytics(yta, startDate=first, endDate=end, dimensions="insightTrafficSourceType", filters=f,
                       metrics="views,estimatedMinutesWatched")
        t.insert(0, "video_id", vid)
        vid_traffic.append(t)
        try:  # YouTube sometimes answers 500 for a short/unlisted video's retention; skip that video, keep the run
            r = _analytics(yta, startDate=first, endDate=end, dimensions="elapsedVideoTimeRatio", filters=f,
                           metrics="audienceWatchRatio,relativeRetentionPerformance")
        except Exception:
            continue
        r.insert(0, "video_id", vid)
        retention.append(r)
    cat = lambda fs: pd.concat(fs, ignore_index=True) if fs else pd.DataFrame()
    video_daily = cat(vid_daily).rename(columns={"day": "date"})
    video_traffic = cat(vid_traffic)
    if not video_traffic.empty:
        video_traffic.insert(0, "snapshot_date", end)
    retention = cat(retention)
    if not retention.empty:
        retention.insert(0, "snapshot_date", end)

    # channel breakdowns
    traffic_daily = _analytics(yta, startDate=start, endDate=end, dimensions="day,insightTrafficSourceType",
                               metrics="views,engagedViews,estimatedMinutesWatched").rename(columns={"day": "date"})
    content_daily = _analytics(yta, startDate=start, endDate=end, dimensions="day,creatorContentType",
                               metrics="views,engagedViews,estimatedMinutesWatched").rename(columns={"day": "date"})
    search_terms = _analytics(yta, startDate=first, endDate=end, dimensions="insightTrafficSourceDetail",
                              filters="insightTrafficSourceType==YT_SEARCH", metrics="views",
                              sort="-views", maxResults=25)
    breakdown = []
    for dim, mets in [("country", "views,estimatedMinutesWatched,averageViewDuration,subscribersGained"),
                      ("deviceType", "views,estimatedMinutesWatched"), ("operatingSystem", "views,estimatedMinutesWatched"),
                      ("sharingService", "shares"), ("ageGroup,gender", "viewerPercentage")]:
        try:
            b = _analytics(yta, startDate=first, endDate=end, dimensions=dim, metrics=mets)
        except Exception:
            continue
        keys = dim.split(",")
        for rec in b.to_dict("records"):
            for m in mets.split(","):
                breakdown.append({"snapshot_date": end, "breakdown": dim, "key": "/".join(str(rec[k]) for k in keys),
                                  "metric": m, "value": rec.get(m)})
    for rec in search_terms.to_dict("records"):
        breakdown.append({"snapshot_date": end, "breakdown": "search_term", "key": rec["insightTrafficSourceDetail"],
                          "metric": "views", "value": rec["views"]})

    sn, br = ch["snippet"], (ch.get("brandingSettings") or {}).get("channel", {})
    profile = pd.DataFrame([{"snapshot_date": end, "platform": "YouTube", "handle": sn.get("customUrl"),
                             "name": sn.get("title"), "bio": sn.get("description"),
                             "profile_url": f"https://www.youtube.com/{sn.get('customUrl')}",
                             "picture_url": ((sn.get("thumbnails") or {}).get("high") or {}).get("url"),
                             "keywords": br.get("keywords"), "country": sn.get("country")}])

    return {
        "YouTube Videos": (videos, ["snapshot_date", "video_id"]),
        "YouTube Daily": (daily, ["date"]),
        "YouTube Channel": (channel, ["snapshot_date"]),
        "YouTube Video Daily": (video_daily, ["video_id", "date"]),
        "YouTube Video Traffic": (video_traffic, ["snapshot_date", "video_id", "insightTrafficSourceType"]),
        "YouTube Retention": (retention, ["snapshot_date", "video_id", "elapsedVideoTimeRatio"]),
        "YouTube Traffic Daily": (traffic_daily, ["date", "insightTrafficSourceType"]),
        "YouTube Content Type Daily": (content_daily, ["date", "creatorContentType"]),
        "YouTube Breakdowns": (pd.DataFrame(breakdown), ["snapshot_date", "breakdown", "key", "metric"]),
        "Profiles": (profile, ["snapshot_date", "platform"]),
    }
