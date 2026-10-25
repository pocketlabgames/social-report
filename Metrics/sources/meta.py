"""Facebook Page + Instagram (Graph API, system-user token in Private Keys/meta-token.txt)."""
import datetime as dt
import os

import pandas as pd
import requests

G = "https://graph.facebook.com/v24.0/"
IG_DAYS = 30
PAGE_DAYS = 90
PAGE_METRICS = ["page_follows", "page_daily_follows", "page_daily_follows_unique", "page_daily_unfollows_unique",
                "page_views_total", "page_post_engagements", "page_total_actions", "page_media_view",
                "page_total_media_view_unique", "page_video_views", "page_video_views_organic",
                "page_video_views_paid", "page_video_complete_views_30s", "page_video_repeat_views",
                "page_video_view_time", "page_actions_post_reactions_like_total"]
# post_total_media_view_unique left out: Oct 10 it returned ~197 "unique viewers" for a Reel with 41 views
POST_METRICS = ["post_media_view", "post_video_views", "post_clicks",
                "post_clicks_by_type", "post_reactions_by_type_total", "post_activity_by_action_type"]
REACTIONS = ["like", "love", "wow", "haha", "sorry", "anger"]
IG_MEDIA_METRICS = ["views", "reach", "likes", "comments", "shares", "saved", "total_interactions", "reposts",
                    "reels_skip_rate", "ig_reels_avg_watch_time", "ig_reels_video_view_total_time",
                    "profile_visits", "follows", "profile_activity"]  # last 3: photo posts only
IG_STORY_METRICS = ["views", "reach", "replies", "shares", "total_interactions", "follows", "profile_visits",
                    "navigation"]
IG_DAY_TOTALS = ["views", "reach", "accounts_engaged", "total_interactions", "likes", "comments", "shares", "saves",
                 "replies", "reposts", "profile_views", "website_clicks", "profile_links_taps"]
IG_DAY_BREAKDOWNS = [("views", "follow_type"), ("views", "media_product_type"), ("reach", "follow_type"),
                     ("reach", "media_product_type"), ("total_interactions", "media_product_type"),
                     ("follows_and_unfollows", "follow_type"), ("profile_links_taps", "contact_button_type")]
IG_DEMOGRAPHICS = [("engaged_audience_demographics", "this_month"), ("reached_audience_demographics", "this_month"),
                   ("follower_demographics", None)]


# Website build (REPORT_SITE=1, GitHub Actions): skip the per-post insights, daily history, audience, stories and inbox
# that only the Mac Metrics workbook uses; the report needs just the per-post totals, comments and follower counts.
LITE = __import__("os").environ.get("REPORT_SITE") == "1"


def _et(ts):
    return pd.Timestamp(ts).tz_convert("America/New_York").strftime("%Y-%m-%d %H:%M")


def _day(end_time):
    # period=day end_time is the start of the NEXT day; the value belongs to the day before
    return (dt.date.fromisoformat(end_time[:10]) - dt.timedelta(days=1)).isoformat()


def _get(path, token, **params):
    params["access_token"] = token
    j = requests.get(G + path, params=params, timeout=60).json()
    if "error" in j:
        raise RuntimeError(f"{path.split('/')[-1]}: {j['error'].get('message', '')[:200]}")
    return j


def _all(path, token, **params):
    out, j = [], _get(path, token, **params)
    while True:
        out += j.get("data", [])
        nxt = j.get("paging", {}).get("next")
        if not nxt:
            return out
        j = requests.get(nxt, timeout=60).json()


def _post_insights(post_id, token):
    out = {}
    for met in POST_METRICS:
        try:
            data = _get(f"{post_id}/insights", token, metric=met)["data"]
            life = [d for d in data if d.get("period") == "lifetime"] or data
            out[met] = life[0]["values"][0]["value"]
        except (RuntimeError, IndexError, KeyError):
            pass
    return out


def _post_insights_lite(post_id, token):   # website: only the 3-second view count
    try:
        data = _get(f"{post_id}/insights", token, metric="post_video_views")["data"]
        life = [d for d in data if d.get("period") == "lifetime"] or data
        return {"post_video_views": life[0]["values"][0]["value"]}
    except (RuntimeError, IndexError, KeyError):
        return {}


def _media_insights(mid, token):
    row, mets = {}, (["views", "likes", "comments", "ig_reels_avg_watch_time"] if LITE else IG_MEDIA_METRICS)   # all the website shows
    try:
        j = _get(f"{mid}/insights", token, metric=",".join(mets))
        for m in j["data"]:
            row[m["name"]] = m["values"][0]["value"]
    except RuntimeError:  # one unsupported metric fails the batch; fall back one by one
        for met in mets:
            try:
                row[met] = _get(f"{mid}/insights", token, metric=met)["data"][0]["values"][0]["value"]
            except (RuntimeError, IndexError, KeyError):
                row[met] = None
    return row


def fetch(keys_dir, today):
    """Tables whose permission is missing come back empty; the reason is printed."""
    token = open(os.path.join(keys_dir, "meta-token.txt")).read().strip()
    page = _get("me/accounts", token, fields="id,name,access_token,followers_count,instagram_business_account")["data"][0]
    pt, pid = page["access_token"], page["id"]
    ig = page["instagram_business_account"]["id"]
    snap = today.isoformat()

    # Facebook Page profile
    pg = _get(pid, pt, fields="name,username,about,description,website,link,category,emails,picture{url},"
                              "cover{source},verification_status,followers_count,fan_count")
    profile = pd.DataFrame([{"snapshot_date": snap, "platform": "Facebook", "handle": pg.get("username"),
                             "name": pg.get("name"), "bio": pg.get("about"), "description": pg.get("description"),
                             "website": pg.get("website"), "profile_url": pg.get("link"),
                             "picture_url": (pg.get("picture") or {}).get("data", {}).get("url"),
                             "cover_url": (pg.get("cover") or {}).get("source"), "category": pg.get("category"),
                             "email": ", ".join(pg.get("emails") or []),
                             "verified": pg.get("verification_status")}])

    # Facebook posts (Reels + photo posts): post-level insights
    reel_ids, fb, retention = set(), [], []
    reels = _all(f"{pid}/video_reels", pt, fields="id,description,created_time,permalink_url,length,views,post_id,"
                                                  "content_category,updated_time", limit=50)
    for v in reels:
        reel_ids.add(str(v.get("post_id")))
        ins = {m["name"]: m["values"][0]["value"] for m in _get(f"{v['id']}/video_insights", pt).get("data", [])}
        social = ins.get("post_video_social_actions") or {}
        reacts = ins.get("post_video_likes_by_reaction_type") or {}
        post = (_post_insights(f"{pid}_{v['post_id']}", pt) if not LITE else _post_insights_lite(f"{pid}_{v['post_id']}", pt)) if v.get("post_id") else {}
        row = {
            "snapshot_date": snap, "video_id": v["id"], "post_id": v.get("post_id"), "type": "Reel",
            "created": _et(v["created_time"]), "caption": (v.get("description") or "").split("\n")[0][:120],
            "full_caption": v.get("description"), "length_s": v.get("length"),
            "views": v.get("views"),
            "plays": ins.get("blue_reels_play_count"), "total_plays": ins.get("fb_reels_total_plays"),
            "replays": ins.get("fb_reels_replay_count"), "video_views_3s": post.get("post_video_views"),
            "avg_watch_s": round(ins["post_video_avg_time_watched"] / 1000, 2) if ins.get("post_video_avg_time_watched") is not None else None,
            "watch_time_s": round(ins["post_video_view_time"] / 1000) if ins.get("post_video_view_time") is not None else None,
            "reactions": sum(reacts.values()) if isinstance(reacts, dict) else None,
            "comments": social.get("COMMENT", 0) if isinstance(social, dict) else None,
            "shares": social.get("SHARE", 0) if isinstance(social, dict) else None,
            "clicks": post.get("post_clicks"), "follows": ins.get("post_video_followers"),
            "content_category": v.get("content_category"),
            "url": "https://www.facebook.com" + v["permalink_url"] if str(v.get("permalink_url", "")).startswith("/") else v.get("permalink_url"),
        }
        for r in REACTIONS:
            row["react_" + r] = (reacts or {}).get("REACTION_" + r.upper(), 0) if isinstance(reacts, dict) else None
        fb.append(row)
        graph = ins.get("post_video_retention_graph") or {}
        for k, pct in (graph.items() if isinstance(graph, dict) else []):
            retention.append({"snapshot_date": snap, "video_id": v["id"], "interval": int(k), "pct_still_watching": pct})

    other = []
    for p in _all(f"{pid}/posts", pt, fields="id,message,created_time,permalink_url,status_type", limit=50):
        if p["id"].split("_")[-1] in reel_ids or p.get("status_type") == "added_video":
            continue
        post = {} if LITE else _post_insights(p["id"], pt)
        other.append({"snapshot_date": snap, "post_id": p["id"].split("_")[-1], "type": p.get("status_type"),
                      "created": _et(p["created_time"]), "caption": (p.get("message") or "").split("\n")[0][:120],
                      "full_caption": p.get("message"), "views": post.get("post_media_view"),
                      "clicks": post.get("post_clicks"),
                      "url": p.get("permalink_url")})

    # Facebook comments (needs pages_read_user_content; skipped until the token has it)
    comments, notes = [], []
    post_ids = [r["post_id"] for r in fb if r.get("post_id")] + [r["post_id"] for r in other]
    for post in post_ids:
        try:
            for c in _all(f"{pid}_{post}/comments", pt, fields="id,message,created_time,like_count,comment_count,"
                                                                 "from{name,id},parent{id}", filter="stream", limit=100):
                comments.append({"comment_id": c["id"], "post_id": post, "created": _et(c["created_time"]),
                                 "author": (c.get("from") or {}).get("name"),
                                 "from_page": (c.get("from") or {}).get("id") == pid,
                                 "reply_to": (c.get("parent") or {}).get("id"), "message": c.get("message"),
                                 "likes": c.get("like_count"), "replies": c.get("comment_count"), "as_of": snap})
        except RuntimeError as e:
            notes.append(str(e))
            break

    # Facebook Stories
    stories = [{"story_id": st.get("post_id"), "created": _et(st["creation_time"]) if st.get("creation_time") else None,
                "media_type": st.get("media_type"), "status": st.get("status"), "url": st.get("url"), "as_of": snap}
               for st in ([] if LITE else _all(f"{pid}/stories", pt, limit=50))]

    # Facebook audience (Meta returns these only once the Page has ~100 followers)
    demo = []
    for met in ([] if LITE else ["page_follows_country", "page_follows_city"]):
        try:
            for d in _get(f"{pid}/insights", pt, metric=met, period="lifetime")["data"]:
                for k, v in (d["values"][-1]["value"] or {}).items():
                    demo.append({"snapshot_date": snap, "platform": "Facebook", "breakdown": met.split("_")[-1],
                                 "key": k, "value": v})
        except (RuntimeError, IndexError, KeyError):
            pass

    # Facebook inbox (needs pages_messaging)
    inbox = []
    try:
        for cv in ([] if LITE else _all(f"{pid}/conversations", pt, fields="id,updated_time,message_count,unread_count", limit=100)):
            inbox.append({"conversation_id": cv["id"], "updated": _et(cv["updated_time"]),
                          "messages": cv.get("message_count"), "unread": cv.get("unread_count"), "as_of": snap})
    except RuntimeError as e:
        notes.append(str(e))

    # Instagram media (Reels and posts) + comments
    igm, ig_comments = [], []
    for m in _all(f"{ig}/media", token, fields="id,caption,media_type,media_product_type,timestamp,permalink,shortcode,"
                                               "thumbnail_url,is_shared_to_feed,like_count,comments_count", limit=50):
        row = {"snapshot_date": snap, "media_id": m["id"], "created": _et(m["timestamp"]),
               "type": m.get("media_product_type"), "media_type": m.get("media_type"),
               "caption": (m.get("caption") or "").split("\n")[0][:120], "full_caption": m.get("caption"),
               "shortcode": m.get("shortcode"), "shared_to_feed": m.get("is_shared_to_feed"),
               "thumbnail_url": m.get("thumbnail_url")}
        row.update(_media_insights(m["id"], token))
        for k in ("ig_reels_avg_watch_time", "ig_reels_video_view_total_time"):
            if row.get(k) is not None:
                row[k] = round(row[k] / 1000, 2)
        row = {("avg_watch_s" if k == "ig_reels_avg_watch_time" else "watch_time_s" if k == "ig_reels_video_view_total_time"
                else "skip_rate_pct" if k == "reels_skip_rate" else k): v for k, v in row.items()}
        row["url"] = m.get("permalink")
        igm.append(row)
        try:
            for c in _all(f"{m['id']}/comments", token, fields="id,text,timestamp,username,like_count,"
                                                               "replies{id,text,timestamp,username,like_count}", limit=50):
                for x, parent in [(c, None)] + [(r, c["id"]) for r in (c.get("replies") or {}).get("data", [])]:
                    ig_comments.append({"comment_id": x["id"], "media_id": m["id"], "created": _et(x["timestamp"]),
                                        "author": x.get("username"), "reply_to": parent, "message": x.get("text"),
                                        "likes": x.get("like_count"), "as_of": snap})
        except RuntimeError as e:
            notes.append(str(e))

    # Instagram Stories (only live ones, last 24 h; the daily run keeps them)
    ig_stories = []
    for st in ([] if LITE else _all(f"{ig}/stories", token, fields="id,media_type,timestamp,permalink,caption", limit=50)):
        row = {"story_id": st["id"], "created": _et(st["timestamp"]), "media_type": st.get("media_type"),
               "caption": st.get("caption"), "url": st.get("permalink"), "as_of": snap}
        for met in IG_STORY_METRICS:
            try:
                d = _get(f"{st['id']}/insights", token, metric=met)["data"][0]
                row[met] = d.get("total_value", {}).get("value", d.get("values", [{}])[0].get("value"))
            except (RuntimeError, IndexError, KeyError):
                pass
        ig_stories.append(row)

    # Instagram profile
    igp = _get(ig, token, fields="username,name,biography,website,profile_picture_url,followers_count,follows_count,media_count")
    profile = pd.concat([profile, pd.DataFrame([{
        "snapshot_date": snap, "platform": "Instagram", "handle": igp.get("username"), "name": igp.get("name"),
        "bio": igp.get("biography"), "website": igp.get("website"),
        "profile_url": f"https://www.instagram.com/{igp.get('username')}/", "picture_url": igp.get("profile_picture_url")}])],
        ignore_index=True)

    # Instagram audience (engaged/reached this month; followers once ~100)
    for met, tf in ([] if LITE else IG_DEMOGRAPHICS):
        for bd in ["country", "city", "age", "gender"]:
            try:
                kw = {"timeframe": tf} if tf else {}
                for d in _get(f"{ig}/insights", token, metric=met, period="lifetime", metric_type="total_value",
                              breakdown=bd, **kw)["data"]:
                    for b in d["total_value"].get("breakdowns", []):
                        for r in b.get("results", []):
                            demo.append({"snapshot_date": snap, "platform": "Instagram",
                                         "breakdown": met.replace("_demographics", "") + "_" + bd,
                                         "key": "/".join(r["dimension_values"]), "value": r["value"]})
            except (RuntimeError, KeyError):
                pass

    # Facebook Page daily
    since = int(dt.datetime.combine(today - dt.timedelta(days=PAGE_DAYS), dt.time()).timestamp())
    until = int(dt.datetime.combine(today, dt.time()).timestamp())
    days = {}
    for met in ([] if LITE else PAGE_METRICS):
        try:
            for d in _get(f"{pid}/insights", pt, metric=met, period="day", since=since, until=until)["data"]:
                for v in d["values"]:
                    days.setdefault(_day(v["end_time"]), {})[met] = v["value"]
        except RuntimeError:
            pass
    page_daily = pd.DataFrame([{"date": k, **v} for k, v in sorted(days.items())])

    # Instagram daily
    igd = {}
    try:
        s = int(dt.datetime.combine(today - dt.timedelta(days=IG_DAYS), dt.time()).timestamp())
        for v in [] if LITE else _get(f"{ig}/insights", token, metric="reach", period="day", since=s, until=until)["data"][0]["values"]:
            igd.setdefault(_day(v["end_time"]), {})["reach"] = v["value"]
    except (RuntimeError, IndexError):
        pass
    ig_bd = []
    for i in range(1, 0 if LITE else IG_DAYS + 1):
        day = today - dt.timedelta(days=i)
        s = int(dt.datetime.combine(day, dt.time()).timestamp())
        try:
            j = _get(f"{ig}/insights", token, metric=",".join(IG_DAY_TOTALS), period="day",
                     metric_type="total_value", since=s, until=s + 86400)
            for d in j["data"]:
                igd.setdefault(day.isoformat(), {})[d["name"]] = d["total_value"]["value"]
        except RuntimeError as e:
            notes.append(str(e))
        for met, bd in IG_DAY_BREAKDOWNS:
            try:
                for d in _get(f"{ig}/insights", token, metric=met, period="day", metric_type="total_value",
                              breakdown=bd, since=s, until=s + 86400)["data"]:
                    for b in d["total_value"].get("breakdowns", []):
                        for r in b.get("results", []):
                            ig_bd.append({"date": day.isoformat(), "metric": met, "breakdown": bd,
                                          "key": "/".join(r["dimension_values"]), "value": r["value"]})
            except (RuntimeError, KeyError):
                pass
    ig_daily = pd.DataFrame([{"date": k, **v} for k, v in sorted(igd.items())])

    acct = _get(ig, token, fields="username,followers_count,media_count")
    accounts = pd.DataFrame([{"snapshot_date": snap, "fb_page_followers": page.get("followers_count"),
                              "ig_followers": acct.get("followers_count"), "ig_posts": acct.get("media_count")}])

    for n in sorted(set(notes)):
        print("meta note:", n)
    return {
        "FB Reels": (pd.DataFrame(fb), ["snapshot_date", "video_id"]),
        "FB Reel Retention": (pd.DataFrame(retention), ["snapshot_date", "video_id", "interval"]),
        "FB Posts": (pd.DataFrame(other), ["snapshot_date", "post_id"]),
        "Profiles": (profile, ["snapshot_date", "platform"]),
        "FB Comments": (pd.DataFrame(comments), ["comment_id"]),
        "FB Stories": (pd.DataFrame(stories), ["story_id"]),
        "Demographics": (pd.DataFrame(demo), ["snapshot_date", "platform", "breakdown", "key"]),
        "FB Inbox": (pd.DataFrame(inbox), ["conversation_id"]),
        "IG Media": (pd.DataFrame(igm), ["snapshot_date", "media_id"]),
        "IG Comments": (pd.DataFrame(ig_comments), ["comment_id"]),
        "IG Stories": (pd.DataFrame(ig_stories), ["story_id"]),
        "IG Daily Breakdown": (pd.DataFrame(ig_bd), ["date", "metric", "breakdown", "key"]),
        "FB Page Daily": (page_daily, ["date"]),
        "IG Daily": (ig_daily, ["date"]),
        "Meta Accounts": (accounts, ["snapshot_date"]),
    }
