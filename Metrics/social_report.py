"""Beaker Lab social report: the chat table + chart, outside the Claude app.

Run:  double-click "Refresh Social Report.command" (in this folder), or
      ~/.beakerlab-tools/metrics-venv/bin/python social_report.py
Pulls Instagram, Facebook, YouTube and TikTok from their APIs (same sources as metrics.py, but never
writes Beaker Lab Metrics.xlsx), adds the manual Reddit rows (data/Reddit_Posts_Manual.csv), compares with
the last check in social-stats-history.json (shared with the 7 AM / 2 PM scheduled report), appends this
check, and writes Social Report.html (table + interactive chart) and Social Report.xlsx (table + data).
Daily history for the chart: Azure view metrics.v_views_7d; if the database can't be reached, the last
snapshot per day from social-stats-history.json. Chart style = memory note social-chart-style.
"""
import math
import datetime as dt
import html
import json
import os
import sys
import webbrowser

import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
KEYS = os.path.join(os.path.dirname(HERE), "Private Keys")
HIST = os.path.join(HERE, "social-stats-history.json")
REDDIT = os.path.join(HERE, "data", "Reddit_Posts_Manual.csv")
OUT_HTML = os.path.join(HERE, "Social Report.html")
OUT_XLSX = os.path.join(HERE, "Social Report.xlsx")
LAYOUT = os.path.join(HERE, "report-layout.json")   # saved from the report's Edit Layout button
POSTS_HIST = os.path.join(HERE, "posts-history.json")   # per-post views at every complete check (for +24 h per post)
POSTS = []   # per-post rows from the latest fetch (filled by fetch())
INSTALLS = {}   # {date: first downloads} from App Store Connect (filled by fetch(); empty if the key is missing)
MONEY = {}      # {date: {"ads": usd, "iap": usd}} (filled by fetch(); empty if keys are missing)
ASCR = {}       # App Store Connect app numbers for the Retention card (asc_ret_lite; Guy, Oct 26)
ASC_D1_ON = False   # flip to True once ASC Analytics > Retention shows data (Guy wants Apple numbers when reliable)
RET = {}        # {"d1": %, "d1_n": players, "d7": %, "d7_n": players} from Firebase / GA4 (ga4_lite)
GADS = {}       # {date: Google Ads spend in USD} (gads_lite; empty if keys are missing)
RCNEW = {}      # {date: RevenueCat new customers (first opens)} for the same-day download estimate
LAST = os.path.join(HERE, "cache", "report-last.json")   # the previous run's table + chart, shown at the bottom (one run only, not a history)
SITE = os.environ.get("REPORT_SITE") == "1"   # GitHub Actions build for the website (no local helper, no xlsx)
ACTIONS = "https://github.com/pocketlabgames/social-report/actions/workflows/report.yml"
PLAT = ["instagram", "facebook", "youtube", "tiktok"]
NAME = {"instagram": "Instagram", "facebook": "Facebook", "youtube": "YouTube", "tiktok": "TikTok"}
IG_HANDLE = "beakerlab.game"
COLOR = {"instagram": "#E87BA4", "facebook": "#2A78D6", "youtube": "#E34948", "tiktok": "#14B8C6"}


def fetch():
    from sources import meta, tiktok, youtube
    try:
        from sources import asc_lite
    except ImportError:
        asc_lite = None
    try:
        from sources import money_lite
    except ImportError:
        money_lite = None
    try:
        from sources import rc_lite
    except ImportError:
        rc_lite = None
    try:
        from sources import ga4_lite
    except ImportError:
        ga4_lite = None
    try:
        from sources import asc_ret_lite
    except ImportError:
        asc_ret_lite = None
    try:
        from sources import gads_lite
    except ImportError:
        gads_lite = None
    out, errors = {}, []
    import re, time
    from concurrent.futures import ThreadPoolExecutor

    def pull(m):   # one site: up to 3 tries (e.g. YouTube Analytics 500s are usually temporary)
        for attempt in range(1, 4):
            try:
                return {k: df for k, (df, _) in m.fetch(KEYS, dt.date.today()).items()}, None
            except Exception as e:
                if attempt == 3:
                    msg = re.sub(r"(token|key|secret)=[^&\s'\"]+", r"\1=***", f"{type(e).__name__}: {e}", flags=re.I)   # never show keys
                    return {}, f"{m.__name__.split('.')[-1]} (3 tries): {msg}"[:200]
                time.sleep(10 * attempt)

    INSTALLS.clear(); MONEY.clear(); RCNEW.clear(); GADS.clear(); RET.clear(); ASCR.clear()
    srcs = [youtube, meta, tiktok] + ([asc_lite] if asc_lite and os.path.exists(os.path.join(KEYS, "asc-metrics.json")) else [])
    if money_lite and os.path.exists(os.path.join(KEYS, "asc-metrics.json")) and os.path.exists(os.path.join(KEYS, "admob-token.json")):
        srcs.append(money_lite)
    if rc_lite and os.path.exists(os.path.join(KEYS, "revenuecat-key.txt")):
        srcs.append(rc_lite)
    if ga4_lite and os.path.exists(os.path.join(KEYS, "ga4-token.json")):
        srcs.append(ga4_lite)
    if asc_ret_lite and os.path.exists(os.path.join(KEYS, "asc-metrics.json")):
        srcs.append(asc_ret_lite)
    if gads_lite and os.path.exists(os.path.join(KEYS, "googleads-token.json")):
        srcs.append(gads_lite)
    elif gads_lite and os.path.exists(gads_lite.CACHE):   # no keys here: still show the spend we already have
        GADS.update(json.load(open(gads_lite.CACHE)))
    with ThreadPoolExecutor(6) as ex:   # the sites, App Store installs and money in parallel
        for got, err in ex.map(pull, srcs):
            if "ASC Installs Lite" in got:
                d = got.pop("ASC Installs Lite")
                INSTALLS.update({r.date: (None if pd.isna(r.installs) else int(r.installs)) for r in d.itertuples()})
            if "GA4 Retention Lite" in got:
                r0 = got.pop("GA4 Retention Lite").iloc[0].to_dict()
                RET.update({k: (None if pd.isna(v) else v) for k, v in r0.items()})
            if "ASC Retention Lite" in got:
                r0 = got.pop("ASC Retention Lite").iloc[0].to_dict() if len(got.get("ASC Retention Lite", [])) else {}
                got.pop("ASC Retention Lite", None)
                ASCR.update({k: (None if pd.isna(v) else (v.item() if hasattr(v, "item") else v)) for k, v in r0.items()})
            if "GAds Spend Lite" in got:
                d = got.pop("GAds Spend Lite")
                GADS.update({r.date: float(r.spend) for r in d.itertuples() if pd.notna(r.spend)})
            if "RC New Lite" in got:
                d = got.pop("RC New Lite")
                RCNEW.update({r.date: int(r.new) for r in d.itertuples() if pd.notna(r.new)})
            if "Money Lite" in got:
                d = got.pop("Money Lite")
                MONEY.update({r.date: {"ads": None if pd.isna(r.ads) else float(r.ads), "iap": None if pd.isna(r.iap) else float(r.iap)} for r in d.itertuples()})
            out.update(got)
            if err:
                errors.append(err)
    snap = {}

    def watch(d):   # views-weighted average watch time (s) over the posts that report one
        col = "avg_watch_s" if "avg_watch_s" in d else "avg_view_s" if "avg_view_s" in d else None
        if not col:
            return None
        w = d[[col, "views"]].dropna()
        w = w[w.views > 0]
        return round(float((w[col] * w.views).sum() / w.views.sum()), 1) if len(w) else None

    def watch_pct(d):   # views-weighted share of the video that is watched (%)
        if "avg_view_pct" in d:
            w = d[["avg_view_pct", "views"]].dropna(); w = w[w.views > 0]
            return round(float((w.avg_view_pct * w.views).sum() / w.views.sum()), 1) if len(w) else None
        if "avg_watch_s" in d and "length_s" in d:
            w = d[["avg_watch_s", "length_s", "views"]].dropna(); w = w[(w.views > 0) & (w.length_s > 0)]
            return round(float((w.avg_watch_s / w.length_s * 100 * w.views).sum() / w.views.sum()), 1) if len(w) else None
        return None

    def v3(d):   # 3-second views: Facebook post_video_views, YouTube engagedViews; others have none
        col = "video_views_3s" if "video_views_3s" in d else "engaged_views" if "engaged_views" in d else None
        if not col or d[col].isna().all():
            return None
        return int(d[col].fillna(0).sum())

    def posts(name, likes):
        d = out.get(name)
        if d is None or d.empty:
            return None
        views, lk = int(d.views.fillna(0).sum()), (int(d[likes].fillna(0).sum()) if likes in d else None)
        return {"posts": len(d), "views": views, "top_views": int(d.views.fillna(0).max()),
                "likes": lk, "comments": int(d.comments.fillna(0).sum()) if "comments" in d else None,
                "top_url": d.sort_values("views").iloc[-1].get("url", ""),
                "avg_watch_s": watch(d), "watch_pct": watch_pct(d),
                "likes_per_k": round(lk / views * 1000, 1) if lk is not None and views else None,
                "views_3s": v3(d)}

    def collect(site, name, likes, title_col, created_col):   # one row per post for the Posts table
        d = out.get(name)
        if d is None or d.empty:
            return
        for _, r in d.iterrows():
            if site == "youtube" and str(r.get("privacy", "public")) != "public":
                continue
            v = r.get("views"); v = int(v) if pd.notna(v) else 0
            lk = r.get(likes) if likes in d else None; lk = int(lk) if pd.notna(lk) else None
            ln = r.get("length_s") if "length_s" in d else None; ln = float(ln) if pd.notna(ln) else None
            aw = r.get("avg_watch_s") if "avg_watch_s" in d else r.get("avg_view_s") if "avg_view_s" in d else None
            aw = float(aw) if pd.notna(aw) else None
            wp = r.get("avg_view_pct") if "avg_view_pct" in d else (aw / ln * 100 if aw is not None and ln else None)
            wp = float(wp) if wp is not None and pd.notna(wp) else None
            POSTS.append({"site": site, "id": f"{site}:{r.get('video_id', r.get('media_id', ''))}",
                          "title": str(r.get(title_col) or "").split("\n")[0][:90], "created": str(r.get(created_col) or "")[:16],
                          "length_s": ln, "views": v, "likes": lk,
                          "comments": int(r.comments) if "comments" in d and pd.notna(r.get("comments")) else None,
                          "avg_watch_s": aw, "watch_pct": wp, "url": str(r.get("url") or "")})

    POSTS.clear()
    collect("instagram", "IG Media", "likes", "caption", "created")
    collect("facebook", "FB Reels", "reactions", "caption", "created")
    collect("youtube", "YouTube Videos", "likes", "title", "published")
    collect("tiktok", "TikTok Videos", "likes", "caption", "created")

    acc = out.get("Meta Accounts")
    acc = acc.iloc[-1].to_dict() if acc is not None and not acc.empty else {}
    ig = posts("IG Media", "likes")
    if ig:
        ig["followers"] = acc.get("ig_followers")
        c = out.get("IG Comments")   # viewer comments only (not our own beakerlab.game comments/replies)
        if c is not None and not c.empty:
            ig["comments"] = int((c.author.astype(str).str.lower() != IG_HANDLE).sum())
        snap["instagram"] = ig
    fb = posts("FB Reels", "reactions")
    if fb:
        fb["followers"] = acc.get("fb_page_followers")
        c = out.get("FB Comments")   # viewer comments only (not the Page's own link comments)
        fb["comments"] = int((~c.from_page.astype(str).isin(["True", "1"])).sum()) if c is not None and not c.empty else 0
        snap["facebook"] = fb
    yt = posts("YouTube Videos", "likes")
    if yt:
        v = out["YouTube Videos"]
        pub = v[v.privacy == "public"]
        yt.update(public_posts=len(pub), public_views=int(pub.views.fillna(0).sum()))
        ch = out.get("YouTube Channel")
        yt["followers"] = int(ch.subscribers.iloc[-1]) if ch is not None and not ch.empty else None
        try:   # viewer comments only: the API count includes our own pinned comments, so subtract the channel's own
            own = yt_own_comments(list(v.video_id))
            if own is not None and yt.get("comments") is not None:
                yt["comments"] = max(0, yt["comments"] - own)
        except Exception as e:
            errors.append(f"youtube own-comment count: {type(e).__name__}"[:200])
        snap["youtube"] = yt
    tt = posts("TikTok Videos", "likes")
    if tt:
        a = out.get("TikTok Account")
        tt["followers"] = int(a.followers.iloc[-1]) if a is not None and not a.empty else None
        snap["tiktok"] = tt
    return snap, errors


def yt_own_comments(video_ids):
    """Our own comments on our YouTube videos, from data/youtube-own-comments.json (the read-only API can't see comment authors)."""
    p = os.path.join(HERE, "data", "youtube-own-comments.json")
    if not os.path.exists(p):
        return None
    own = json.load(open(p)).get("videos", {})
    return sum(int(own[vid].get("own_comments", 0)) for vid in video_ids if vid in own)


def reddit():
    if not os.path.exists(REDDIT):
        return None
    d = pd.read_csv(REDDIT)
    if d.empty:
        return None
    d["key"] = d.url.where(d.url.notna() & (d.url.astype(str).str.strip() != ""), d.subreddit.astype(str) + "|" + d.title.astype(str))   # posts with no URL yet: tell them apart by sub + title
    last = d.sort_values("snapshot_date").groupby("key").tail(1)
    removed = last.notes.fillna("").str.contains("REMOVED")
    live = last[~removed]
    views = pd.to_numeric(live.views, errors="coerce")
    ups = pd.to_numeric(live.upvotes, errors="coerce")
    com = pd.to_numeric(live.comments, errors="coerce")
    return {"posts": len(live), "removed": int(removed.sum()), "as_of": str(last.snapshot_date.max()),
            "views": int(views.sum()) if views.notna().any() else None,
            "unknown_views": int(views.isna().sum()),
            "top_views": int(views.max()) if views.notna().any() else None,
            "top_url": str(live.url.loc[views.idxmax()]) if views.notna().any() and pd.notna(live.url.loc[views.idxmax()]) else "",
            "likes": int(ups.sum()) if ups.notna().any() else None,
            "comments": int(com.sum()) if com.notna().any() else None}


def avg(p, s):
    if not s:
        return None
    if p == "youtube":
        return round(s["public_views"] / s["public_posts"]) if s.get("public_posts") else None
    return round(s["views"] / s["posts"]) if s.get("posts") else None


def gains(hist, snap, end, ndays=14):
    """Views gained per day per platform for the ndays ending on `end` (a datetime): last check of each day,
    the end day = `snap` (live) when given; a gap of several days spreads the gain evenly over the gap."""
    days = [end.date() - dt.timedelta(days=n) for n in range(ndays, -1, -1)]   # one extra day in front for the first diff
    level = {p: {} for p in PLAT}
    for h in hist:
        t = dt.datetime.strptime(h["checked_at"], "%Y-%m-%d %H:%M")
        if t > end:
            continue
        for p in PLAT:
            if isinstance(h.get(p), dict) and h[p].get("views") is not None:
                level[p][t.date()] = h[p]["views"]   # later checks overwrite: last check of the day wins
    if snap:
        for p in PLAT:
            if (snap.get(p) or {}).get("views") is not None:
                level[p][end.date()] = snap[p]["views"]
    series = {p: [None] * ndays for p in PLAT}
    for p in PLAT:
        known = sorted(d for d in level[p] if d <= end.date())
        for d in days[1:]:
            earlier = [k for k in known if k < d]
            if d in level[p] and earlier:
                k = earlier[-1]
                per_day = (level[p][d] - level[p][k]) / (d - k).days
                for n in range((d - k).days):   # spread over the gap (incl. this day)
                    dd = d - dt.timedelta(days=n)
                    if dd in days[1:]:
                        series[p][days[1:].index(dd)] = round(per_day)
    labels = [d.strftime("%-m/%-d") for d in days[1:]]   # Guy, Oct 27: short dates so every day gets a label
    return labels, series


def daily(now_label, snap):
    """Running total views per platform for the last 7 days (Eastern)."""
    today = dt.date.today()
    days = [today - dt.timedelta(days=n) for n in range(6, -1, -1)]
    series = {p: [None] * 7 for p in PLAT}
    source = "database"
    try:
        import warehouse
        con = warehouse.connect()
        cur = con.cursor()
        cur.execute("SELECT [Date], Instagram, Facebook, YouTube, TikTok FROM metrics.v_views_7d")
        for r in cur.fetchall():
            if r[0] in days:
                i = days.index(r[0])
                for j, p in enumerate(PLAT):
                    series[p][i] = None if r[j + 1] is None else int(r[j + 1])
        con.close()
    except Exception:
        source = "history file"
        if os.path.exists(HIST):
            for h in json.load(open(HIST)):
                d = dt.date.fromisoformat(h["checked_at"][:10])
                if d in days:
                    for p in PLAT:
                        if h.get(p, {}).get("views") is not None:
                            series[p][days.index(d)] = h[p]["views"]
    for p in PLAT:   # today's point = this run's live totals
        if snap.get(p):
            series[p][6] = snap[p]["views"]
    labels = [d.strftime("%b %-d") for d in days]
    labels[6] += f" ({now_label})"
    return labels, series, source


def fmt(v):
    if isinstance(v, str):
        return v
    return "?" if v is None else (f"{v:,.1f}" if isinstance(v, float) and v < 100 and v != int(v) else f"{v:,.0f}")


def delta(v, old):
    if v is None or old is None or isinstance(v, str) or isinstance(old, str):
        return ""
    d = v - old
    return f" ({'+' if d >= 0 else '−'}{abs(d):,.1f})" if isinstance(d, float) and abs(d) < 100 and d != int(d) else f" ({'+' if d >= 0 else '−'}{abs(d):,.0f})"


def build_rows(snap, prev, rd):
    metrics = [("Total views", "views"), ("Avg views per post", "avg"), ("Top post views", "top_views"),
               ("3-second views", "views_3s"), ("3-s views % of views", "hold_pct"),
               ("Avg watch time (s)", "avg_watch_s"), ("Watched % of video", "watch_pct"), ("Likes per 1K views", "likes_per_k"),
               ("Comments per 1K views", "comments_per_k"), ("Likes / upvotes", "likes"), ("Followers", "followers"), ("Posts", "posts")]   # Oct 26: grouped view rows
    rows = []
    for label, key in metrics:
        vals, olds = {}, {}
        for p in PLAT:
            s, o = snap.get(p), prev.get(p) if prev else None
            vals[p] = avg(p, s) if key == "avg" else (s or {}).get(key)
            olds[p] = avg(p, o) if key == "avg" else (o or {}).get(key)
            if key == "hold_pct":
                for d, src in ((vals, s), (olds, o)):
                    if src and src.get("views_3s") is not None and src.get("views"):
                        d[p] = round(src["views_3s"] / src["views"] * 100, 1)
            if key == "comments_per_k":
                for d, src in ((vals, s), (olds, o)):
                    d[p] = round(src["comments"] / src["views"] * 1000, 1) if src and src.get("comments") is not None and src.get("views") else None
            if key == "likes_per_k":   # older checks stored only likes + views
                for d, src in ((vals, s), (olds, o)):
                    if d[p] is None and src and src.get("likes") is not None and src.get("views"):
                        d[p] = round(src["likes"] / src["views"] * 1000, 1)
        known = [v for v in vals.values() if v is not None]
        top = max(known) if known else None
        best = [NAME[p] for p in PLAT if vals[p] is not None and vals[p] == top] if top is not None else []
        tot = sum(known) if known and key not in ("avg", "top_views") else None
        otot = sum(v for v in olds.values() if v is not None) if prev and key not in ("avg", "top_views") else None
        if key == "avg":
            tv = sum((snap.get(p) or {}).get("views", 0) for p in PLAT)
            tp = sum((snap.get(p) or {}).get("posts", 0) for p in PLAT)
            tot = round(tv / tp) if tp else None
            if prev:
                ov = sum((prev.get(p) or {}).get("views", 0) for p in PLAT)
                op = sum((prev.get(p) or {}).get("posts", 0) for p in PLAT)
                otot = round(ov / op) if op else None
        if key == "top_views":
            tot = otot = "—"
        if key == "avg_watch_s":   # total = views-weighted across the sites that report it
            def wavg(src):
                pairs = [(src[p]["avg_watch_s"], src[p]["views"]) for p in PLAT if src.get(p) and src[p].get("avg_watch_s") is not None and src[p].get("views")]
                return round(sum(a * v for a, v in pairs) / sum(v for _, v in pairs), 1) if pairs else None
            tot, otot = wavg(snap), (wavg(prev) if prev else None)
        if key == "watch_pct":
            def wavg(src):
                pairs = [(src[p]["watch_pct"], src[p]["views"]) for p in PLAT if src.get(p) and src[p].get("watch_pct") is not None and src[p].get("views")]
                return round(sum(a * v for a, v in pairs) / sum(v for _, v in pairs), 1) if pairs else None
            tot, otot = wavg(snap), (wavg(prev) if prev else None)
        if key == "hold_pct":
            def hp(src):
                pairs = [(src[p]["views_3s"], src[p]["views"]) for p in PLAT if src.get(p) and src[p].get("views_3s") is not None and src[p].get("views")]
                return round(sum(a for a, _ in pairs) / sum(v for _, v in pairs) * 100, 1) if pairs else None
            tot, otot = hp(snap), (hp(prev) if prev else None)
        if key == "likes_per_k":
            def lpk(src):
                tv = sum((src.get(p) or {}).get("views") or 0 for p in PLAT); tl = sum((src.get(p) or {}).get("likes") or 0 for p in PLAT)
                return round(tl / tv * 1000, 1) if tv else None
            tot, otot = lpk(snap), (lpk(prev) if prev else None)
        if key == "comments_per_k":
            def cpk(src):
                pr = [((src.get(p) or {}).get("comments"), (src.get(p) or {}).get("views")) for p in PLAT]
                tv = sum(v or 0 for c, v in pr if c is not None); tc = sum(c for c, v in pr if c is not None)
                return round(tc / tv * 1000, 1) if tv else None
            tot, otot = cpk(snap), (cpk(prev) if prev else None)
        rkey = {"comments_per_k": None, "avg": None, "followers": None, "avg_watch_s": None, "watch_pct": None, "likes_per_k": None, "views_3s": None, "hold_pct": None}.get(key, key)
        rv = None if not rd or rkey is None else rd.get(rkey)
        if key == "likes_per_k" and rd and rd.get("views") and rd.get("likes") is not None:
            rv = round(rd["likes"] / rd["views"] * 1000, 1)
        rows.append({"label": label, "vals": vals, "olds": olds, "top": top, "best": best, "total": tot, "ototal": otot, "reddit": rv})
    return rows


PICK_CTX = {"hist": [], "now": None}   # set by main() so pick() can use the last 7 days


def pick(snap):
    """Where to spend ad money: the site with the most views gained in the last 7 days (total views if no history)."""
    hist, now = PICK_CTX["hist"], PICK_CTX["now"]
    gain = {}
    if hist and now:
        target = now - dt.timedelta(days=7)
        for p in PLAT:
            hb = min((h for h in hist if isinstance(h.get(p), dict) and h[p].get("views") is not None),
                     key=lambda h: abs(dt.datetime.strptime(h["checked_at"], "%Y-%m-%d %H:%M") - target), default=None)
            if hb and (snap.get(p) or {}).get("views") is not None and abs(dt.datetime.strptime(hb["checked_at"], "%Y-%m-%d %H:%M") - target) <= dt.timedelta(days=3):
                gain[p] = snap[p]["views"] - hb[p]["views"]
    basis = "views gained in the last 7 days" if len(gain) == len(PLAT) else "total views"
    if len(gain) < len(PLAT):
        gain = {p: (snap.get(p) or {}).get("views") or 0 for p in PLAT}
    tot = sum(max(v, 0) for v in gain.values()) or 1
    order = sorted(PLAT, key=lambda p: -gain[p])
    if set(order[:2]) == {"instagram", "facebook"}:
        share = (max(gain["instagram"], 0) + max(gain["facebook"], 0)) / tot * 100
        return f"Instagram + Facebook (one Meta ad covers both; {share:.0f}% of {basis})"
    return f"{NAME[order[0]]} ({max(gain[order[0]], 0) / tot * 100:.0f}% of {basis})"


def today_change(snap, hist, now):
    """Views gained since midnight (Eastern): current totals minus the complete check closest to today's midnight."""
    midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
    cur = {p: (snap.get(p) or {}).get("views") for p in PLAT}
    if any(v is None for v in cur.values()):
        return None
    base = None   # the last complete check before midnight (same baseline as today's bar in the chart)
    for h in hist:
        if not all(isinstance(h.get(p), dict) and h[p].get("views") is not None for p in PLAT):
            continue
        t = dt.datetime.strptime(h["checked_at"], "%Y-%m-%d %H:%M")
        if t < midnight and (base is None or t > dt.datetime.strptime(base["checked_at"], "%Y-%m-%d %H:%M")):
            base = h
    if base is None:
        return None
    t = dt.datetime.strptime(base["checked_at"], "%Y-%m-%d %H:%M")
    per = {p: cur[p] - base[p]["views"] for p in PLAT}
    return {"total": sum(per.values()), "per": per, "since": t, "off_h": round((t - midnight).total_seconds() / 3600, 1)}


def day_change(snap, hist, now):
    """Views gained in the last 24 hours: current totals minus the newest complete check at least 24 h old."""
    cur = {p: (snap.get(p) or {}).get("views") for p in PLAT}
    if any(v is None for v in cur.values()):
        return None
    target = now - dt.timedelta(hours=24)
    base = None
    for h in hist:   # the complete check closest to 24 h ago (either side)
        if not all(isinstance(h.get(p), dict) and h[p].get("views") is not None for p in PLAT):
            continue
        t = dt.datetime.strptime(h["checked_at"], "%Y-%m-%d %H:%M")
        if base is None or abs(t - target) < abs(dt.datetime.strptime(base["checked_at"], "%Y-%m-%d %H:%M") - target):
            base = h
    if base is None:
        return None
    t = dt.datetime.strptime(base["checked_at"], "%Y-%m-%d %H:%M")
    per = {p: cur[p] - base[p]["views"] for p in PLAT}
    return {"total": sum(per.values()), "per": per, "since": t, "hours": round((now - t).total_seconds() / 3600)}


def history_html(hist):
    """One row per day, newest first (Guy, Oct 26): views GAINED that day on each site (that day's last complete
    check minus the previous day's last check) and their total. Followers and Likes stay running totals."""
    rows = [h for h in hist if all(isinstance(h.get(p), dict) for p in PLAT)]
    last = {}
    for h in sorted(rows, key=lambda h: h["checked_at"]):
        last[h["checked_at"][:10]] = h
    rows = [last[k] for k in sorted(last)]
    if not rows:
        return ""
    f = lambda v: "—" if v is None else f"{v:,}"
    sg = lambda v: "—" if v is None else (f"{v:,}" if v >= 0 else f"−{-v:,}")
    def d(v, o):
        if v is None or o is None or v == o: return ""
        return f" <span class='dl'>({'+' if v > o else '−'}{abs(v - o):,})</span>"
    out, prev = [], None
    for h in rows:
        v = {p: h[p].get("views") for p in PLAT}
        fol = sum(h[p].get("followers") or 0 for p in PLAT)
        lik = sum(h[p].get("likes") or 0 for p in PLAT)
        t = dt.datetime.strptime(h["checked_at"], "%Y-%m-%d %H:%M")
        when = t.strftime("%a %b %-d") + f" <small class='dl'>{t.strftime('%-I:%M %p')}</small>"
        if prev:
            g = {p: (None if v[p] is None or prev["v"][p] is None else v[p] - prev["v"][p]) for p in PLAT}
            gap = (t.date() - prev["day"]).days
            if gap > 1:   # no check on the days in between: the gain covers all of them
                when += f"<br><small class='dl'>since {prev['day'].strftime('%b %-d')} ({gap} days)</small>"
        else:
            g = {p: None for p in PLAT}
        known = [x for x in g.values() if x is not None]
        tot = sum(known) if known else None
        cells = "".join(f"<td class='hs{' gl' if i == 0 else ''}'>{sg(g[p])}</td>" for i, p in enumerate(PLAT))
        cum = sum(x or 0 for x in v.values())   # Guy, Oct 26: running total first; the day's gain in brackets
        out.append(f"<tr><th class='rl'>{when}</th><td><b>{sg(tot)}</b></td>{cells}"   # Guy, Oct 26: day's views left, running totals right
                   f"<td class='gl'>{f(cum)}</td><td class='hs'>{f(lik)}{d(lik, prev and prev['lik'])}</td><td>{f(fol)}{d(fol, prev and prev['fol'])}</td></tr>")
        prev = {"v": v, "fol": fol, "lik": lik, "day": t.date()}
    head = "".join(f"<th class='hs{' gl' if i == 0 else ''}'>{NAME[p]}</th>" for i, p in enumerate(PLAT))
    return (f"<style>.hist .gl{{border-left:1px solid var(--line)}} @media (max-width:700px){{.hist th.rl small{{display:block}} .hist th.rl br{{display:none}} .hist th,.hist td{{font-size:13px;padding:8px 4px}}}}</style><h2 class='ph' id='sec-history'>History</h2><p class='sub'>One row per day since {html.escape(rows[0]['checked_at'][:10])}, newest first (each day's last check; time beside the date). "
            f"Day's views and the site columns are views gained that day; Total views, Likes and Followers (right) are running totals.</p>"
            f"<div class='wrap hist'><table><thead><tr><th class='rl'>Day</th><th>Day's views</th>{head}<th class='gl'>Total views</th><th class='hs'>Likes</th><th>Followers</th></tr></thead>"
            f"<tbody>{''.join(reversed(out))}</tbody></table></div>")


VIDEO_MAP = os.path.join(HERE, "video-map.csv")


def group_videos(posts):
    """One group per video: video-map.csv names first, then posts on different sites that went up within 90 minutes."""
    name_of = {}
    if os.path.exists(VIDEO_MAP):
        try:
            vm = pd.read_csv(VIDEO_MAP, dtype=str).fillna("")
            for _, r in vm.iterrows():
                name_of[f"{r.platform.strip().lower()}:{r.post_id.strip()}"] = r.video.strip()
        except Exception:
            pass
    groups, by_name, loose = [], {}, []
    for r in sorted(posts, key=lambda r: r["created"]):
        n = name_of.get(r["id"])
        if n:
            g = by_name.get(n)
            if g is None:
                g = by_name[n] = {"name": n, "mapped": True, "posts": []}
                groups.append(g)
            g["posts"].append(r)
        else:
            loose.append(r)
    for r in loose:   # time clustering for unmapped posts
        try:
            t = dt.datetime.strptime(r["created"], "%Y-%m-%d %H:%M")
        except ValueError:
            groups.append({"name": "", "mapped": False, "posts": [r]}); continue
        placed = False
        for g in groups:
            if g["mapped"] or any(x["site"] == r["site"] for x in g["posts"]):
                continue
            try:
                t0 = dt.datetime.strptime(g["posts"][0]["created"], "%Y-%m-%d %H:%M")
            except ValueError:
                continue
            if abs((t - t0).total_seconds()) <= 90 * 60:
                g["posts"].append(r); placed = True; break
        if not placed:
            groups.append({"name": "", "mapped": False, "posts": [r]})
    for g in groups:
        if not g["name"]:
            yt = next((x for x in g["posts"] if x["site"] == "youtube" and x["title"]), None)
            src = yt["title"] if yt else max((x["title"] for x in g["posts"]), key=len, default="")
            g["name"] = src.replace("#shorts", "").strip() or "(no title)"
        g["created"] = min(x["created"] for x in g["posts"])
        g["posts"].sort(key=lambda x: PLAT.index(x["site"]) if x["site"] in PLAT else 9)
    return sorted(groups, key=lambda g: g["created"], reverse=True)


def posts_section(posts, phist, now):
    """One card per video with how it did on each site; last 10 days open, older behind a button."""
    if not posts:
        return ""
    e = html.escape
    base = None   # per-post views at the check closest to 24 h ago
    target = now - dt.timedelta(hours=24)
    for h in phist:
        t = dt.datetime.strptime(h["checked_at"], "%Y-%m-%d %H:%M")
        if base is None or abs(t - target) < abs(dt.datetime.strptime(base["checked_at"], "%Y-%m-%d %H:%M") - target):
            base = h
    bviews = base["posts"] if base else {}
    hrs = round((now - dt.datetime.strptime(base["checked_at"], "%Y-%m-%d %H:%M")).total_seconds() / 3600) if base else None
    gain_label = "+24 h" if hrs is not None and 20 <= hrs <= 28 else (f"+{hrs} h" if hrs else "+24 h")
    cutoff = (now - dt.timedelta(days=10)).strftime("%Y-%m-%d")
    def num(v, d=0): return "—" if v is None else f"{v:,.{d}f}"
    def sg(g): return "—" if g is None else ("+" if g >= 0 else "−") + f"{abs(g):,}"
    def when(c):
        try: return dt.datetime.strptime(c, "%Y-%m-%d %H:%M").strftime("%a %b %-d · %-I:%M %p")
        except ValueError: return c[:10]
    cards, hidden = [], 0
    groups = group_videos(posts)
    def age_h(g):
        try: return (now - dt.datetime.strptime(g["created"], "%Y-%m-%d %H:%M")).total_seconds() / 3600
        except ValueError: return 999
    tot = lambda g: sum(x["views"] for x in g["posts"])
    mature = sorted((g for g in groups if age_h(g) >= 48), key=lambda g: g["created"], reverse=True)[:15]
    typ = sorted(tot(g) for g in mature)
    M = (typ[len(typ) // 2] if len(typ) % 2 else (typ[len(typ) // 2 - 1] + typ[len(typ) // 2]) / 2) if typ else None
    def perf(g):   # Guy, Oct 24: views vs a typical video at the same age (median of the last 15 videos 2+ days old; most views come in the first 2 days)
        h = age_h(g)
        if h < 6 or not M: return "#B8B8B8", "Too early to judge (first 6 hours)"
        exp = M * (1 - math.exp(-h / 18)); sc = tot(g) / exp if exp else 0
        tip = f"{sc:.1f}x a typical video at this age (typical final views: {M:,.0f})"
        if sc >= 1.5: return "#1E9E55", tip
        if sc >= 0.5: return "#F5B400", tip
        return "#E5484D", tip
    def gm(g):   # per-video engagement metrics across sites
        v = tot(g); w = [(x["avg_watch_s"], x["views"]) for x in g["posts"] if x.get("avg_watch_s") is not None and x["views"]]
        lk = [x["likes"] for x in g["posts"] if x.get("likes") is not None]; cm = [x["comments"] for x in g["posts"] if x.get("comments") is not None]
        return {"watch": sum(a * b for a, b in w) / sum(b for a, b in w) if w else None,
                "likes": sum(lk) / v * 1000 if lk and v else None, "comments": sum(cm) / v * 1000 if cm and v else None}
    def med(xs):
        xs = sorted(x for x in xs if x is not None)
        return None if not xs else (xs[len(xs) // 2] if len(xs) % 2 else (xs[len(xs) // 2 - 1] + xs[len(xs) // 2]) / 2)
    base = {k: med(gm(g)[k] for g in mature) for k in ("watch", "likes", "comments")}
    def dist(g):   # Guy, Oct 27: our cross-site take on Meta's Distribution score (Meta's exact formula isn't public)
        if age_h(g) < 6 or not M: return None
        r = [min(tot(g) / (M * (1 - math.exp(-age_h(g) / 18))), 5)]
        m = gm(g)
        for k in ("watch", "likes", "comments"):
            if m[k] is not None and base[k]: r.append(min(m[k] / base[k], 5))
        return sum(r) / len(r) - 1
    for g in groups:
        old = g["created"] < cutoff
        hidden += old
        tv = sum(x["views"] for x in g["posts"])
        gains = [x["views"] - bviews[x["id"]] for x in g["posts"] if x["id"] in bviews]
        tg = sum(gains) if gains else None
        ln = next((x["length_s"] for x in g["posts"] if x["length_s"]), None)
        top = max(g["posts"], key=lambda x: x["views"])
        rows = ""
        for x in g["posts"]:
            gx = x["views"] - bviews[x["id"]] if x["id"] in bviews else None
            lpk = round(x["likes"] / x["views"] * 1000, 1) if x["likes"] is not None and x["views"] else None
            link = f"<a class='tp' href='{e(x['url'])}' target='_blank' rel='noopener'>{NAME[x['site']]}</a>" if x["url"] else NAME[x["site"]]
            rows += (f"<tr class='{'lead' if x is top and len(g['posts']) > 1 else ''}'><th class='rl'><span class='dot' style='background:{COLOR[x['site']]}'></span>{link}</th>"
                     f"<td><b>{num(x['views'])}</b></td><td>{sg(gx)}</td><td>{num(lpk, 1)}</td>"
                     f"<td class='aw'>{num(x['avg_watch_s'], 1) + ' s' if x['avg_watch_s'] is not None else '—'}</td><td>{num(x['watch_pct']) + '%' if x['watch_pct'] is not None else '—'}</td></tr>")
        missing = [NAME[p] for p in PLAT if not any(x["site"] == p for x in g["posts"])]
        pc, pt = perf(g)
        xh = age_h(g)   # Guy, Oct 27: one number = views vs a typical video at the same age (same measure as the dot)
        xv = (tot(g) / (M * (1 - math.exp(-xh / 18)))) if (M and xh >= 6) else None
        dhtml = "" if xv is None else f"<span class='pdist' title='Views compared with a typical video of yours at the same age (1.0× = typical)'>{xv:.1f}×</span>"
        cards.append(f"<div class='vc{' old' if old else ''}'><div class='vch'><div class='vcn'><b>{num(tv)}</b> <small>views{(' (' + sg(tg) + ')') if tg is not None else ''}</small></div>"
                     f"<span class='pcol'><span class='pdot' style='background:{pc}' title='{pt}'></span>{dhtml}</span></div><div class='vct'>{e(g['name'][:90])}</div>"
                     f"<div class='vcm'>{when(g['created'])}{(' · ' + num(ln) + ' s') if ln else ''}{(' · not on ' + ', '.join(missing)) if missing and len(missing) < 4 else ''}</div>"
                     f"<table class='vt'><thead><tr><th class='rl'>Site</th><th>Views</th><th>{gain_label}</th><th>Likes / 1K</th><th class='aw'>Avg watch</th><th>Watched</th></tr></thead><tbody>{rows}</tbody></table></div>")
    more = f"<button id='more' class='b gray' type='button'>Show {hidden} older video(s)</button>" if hidden else ""
    return (f"<h2 class='sh' id='sec-videos'>Videos</h2><p class='sub'>One card per video, newest first, with its numbers on each site. {gain_label} = views gained since the check closest to 24 h ago"
            f"{' (no earlier check yet)' if not base else ''}. Watched = share of the video watched on average; YouTube can pass 100% when Shorts loop. Dot = views vs a typical video at the same age: <span style='color:#1E9E55'>●</span> 1.5× or more, <span style='color:#F5B400'>●</span> 0.5–1.5×, <span style='color:#E5484D'>●</span> under 0.5×, <span style='color:#B8B8B8'>●</span> first 6 hours.</p>"
            f"<div class='vgrid'>{''.join(cards)}</div>{more}")


def level_at(hist, snap, when, now):
    """Total views (all sites) at the complete check closest to `when`; live `snap` counts as a check at `now`."""
    best = None
    for h in hist:
        if not all(isinstance(h.get(p), dict) and h[p].get("views") is not None for p in PLAT):
            continue
        t = dt.datetime.strptime(h["checked_at"], "%Y-%m-%d %H:%M")
        if best is None or abs(t - when) < abs(best[0] - when):
            best = (t, sum(h[p]["views"] for p in PLAT))
    if snap and all((snap.get(p) or {}).get("views") is not None for p in PLAT):
        t, v = now, sum(snap[p]["views"] for p in PLAT)
        if best is None or abs(t - when) < abs(best[0] - when):
            best = (t, v)
    return best


def best_slot(posts, now):
    """(slot name, posts, views per post per day) for the posting-time slot with the best views/day, or None."""
    acc = {}
    for r in posts:
        try:
            t = dt.datetime.strptime(r["created"], "%Y-%m-%d %H:%M")
        except ValueError:
            continue
        h = t.hour if t.hour >= 5 else t.hour + 24
        name = next(n for n, a, b in SLOTS if a <= h < b)
        acc.setdefault(name, []).append(r["views"] / max((now - t).total_seconds() / 86400, 1.0))
    if not acc:
        return None
    name, v = max(acc.items(), key=lambda kv: sum(kv[1]) / len(kv[1]))
    return name, len(v), sum(v) / len(v)


def dl_estimate(installs, rcnew, now):
    """Conservative download estimates from RevenueCat first opens for days Apple hasn't posted yet (today, maybe
    yesterday). Ratio = Apple first downloads / RevenueCat new customers, the lower of the last 7 and 14 complete
    days (capped at 1), times RevenueCat's count, rounded down. Returns {date: estimate}, or {} without data."""
    if not installs or not rcnew:
        return {}
    td = now.date()
    def ratio(n):
        days = [(td - dt.timedelta(days=k)).isoformat() for k in range(2, n + 2)]
        a = sum(installs[d] for d in days if installs.get(d) is not None and rcnew.get(d))
        b = sum(rcnew[d] for d in days if installs.get(d) is not None and rcnew.get(d))
        return a / b if b else None
    rs = [r for r in (ratio(7), ratio(14)) if r is not None]
    if not rs:
        return {}
    r = min(min(rs), 1.0)
    out = {}
    for k in (0, 1):
        d = (td - dt.timedelta(days=k)).isoformat()
        if installs.get(d) is None and rcnew.get(d) is not None:
            out[d] = int(rcnew[d] * r)
    return out


def money_bits(money, now):
    """(all-time total, yesterday, last 7 days, this month, ads total, iap total, yesterday_missing) in USD; None if no data."""
    if not money:
        return None
    td = now.date()
    def tot(days, k=None):
        v = 0.0
        for d in days:
            m = money.get(d) or {}
            for kk in ([k] if k else ("ads", "iap")):
                if m.get(kk) is not None:
                    v += m[kk]
        return v
    allk = sorted(money)
    y = (td - dt.timedelta(days=1)).isoformat()
    w = [d for d in allk if 0 <= (td - dt.date.fromisoformat(d)).days < 7]   # Guy, Oct 27 audit: was 8 days (<= 7); now today + 6 days, same window as views
    mo = [d for d in allk if d[:7] == td.strftime("%Y-%m")]
    return {"all": tot(allk), "t": tot([td.isoformat()]), "y": tot([y]), "w": tot(w), "m": tot(mo), "ads": tot(allk, "ads"), "iap": tot(allk, "iap"),
            "y_missing": (money.get(y) or {}).get("iap") is None, "month": td.strftime("%B")}


def week_box(snap, hist, posts, phist, installs, now):
    """'This week' summary: views and installs vs the week before, best and weakest post, best time, what to try."""
    e = html.escape
    lines = []
    a, b, c = level_at(hist, snap, now, now), level_at(hist, None, now - dt.timedelta(days=7), now), level_at(hist, None, now - dt.timedelta(days=14), now)
    if a and b and (a[0] - b[0]).days >= 5:
        this_w = a[1] - b[1]
        txt = f"<b>{this_w:+,}</b> views in the last 7 days"
        if c and (b[0] - c[0]).days >= 5 and (b[1] - c[1]) > 0:
            last_w = b[1] - c[1]
            txt += f" ({(this_w - last_w) / last_w * 100:+.0f}% vs the 7 days before)"
        lines.append(txt)
    if installs:
        days = sorted(d for d in installs if installs[d] is not None)
        w1 = [d for d in days if (now.date() - dt.date.fromisoformat(d)).days <= 7]
        w2 = [d for d in days if 7 < (now.date() - dt.date.fromisoformat(d)).days <= 14]
        i1, i2 = sum(installs[d] for d in w1), sum(installs[d] for d in w2)
        txt = f"<b>{i1:,}</b> App Store installs in the last 7 days"
        if w2:
            txt += f" ({i1 - i2:+,} vs the 7 days before)"
        if a and b and (a[0] - b[0]).days >= 5 and i1:
            txt += f" · about 1 install per {max(a[1] - b[1], 0) / i1:,.0f} views"
        lines.append(txt)
    # best post of the week: most views gained over ~7 days (posts history), else the best new post
    base = None
    for h in phist:
        t = dt.datetime.strptime(h["checked_at"], "%Y-%m-%d %H:%M")
        if (now - t).total_seconds() >= 6.5 * 86400 and (base is None or t > base[0]):
            base = (t, h["posts"])
    byid = {r["id"]: r for r in posts}
    if base:
        gains = sorted(((r["views"] - base[1].get(r["id"], 0), r) for r in posts), key=lambda x: -x[0])
        if gains and gains[0][0] > 0:
            g, r = gains[0]
            lines.append(f"Best post this week: <a class='tp' href='{e(r['url'])}' target='_blank' rel='noopener'>{e(r['title'][:70])}</a> on {NAME[r['site']]}, <b>+{g:,}</b> views")
    else:
        new = [r for r in posts if r["created"] >= (now - dt.timedelta(days=7)).strftime("%Y-%m-%d %H:%M")]
        if new:
            r = max(new, key=lambda r: r["views"])
            lines.append(f"Best new post: <a class='tp' href='{e(r['url'])}' target='_blank' rel='noopener'>{e(r['title'][:70])}</a> on {NAME[r['site']]}, <b>{r['views']:,}</b> views")
    older = [r for r in posts if (now - dt.timedelta(days=7)).strftime("%Y-%m-%d %H:%M") <= r["created"] <= (now - dt.timedelta(days=1)).strftime("%Y-%m-%d %H:%M")]
    if older:
        r = min(older, key=lambda r: r["views"])
        lines.append(f"Weakest new post (over a day old): <a class='tp' href='{e(r['url'])}' target='_blank' rel='noopener'>{e(r['title'][:70])}</a> on {NAME[r['site']]}, {r['views']:,} views")
    bs = best_slot(posts, now)
    tries = []
    if bs:
        tries.append(f"post in the <b>{e(bs[0].lower())}</b> slot ({bs[2]:,.0f} views per post per day over {bs[1]} posts)")
    if a and b and (a[0] - b[0]).days >= 5:
        per = {}
        for p in PLAT:
            hb = min((h for h in hist if isinstance(h.get(p), dict) and h[p].get("views") is not None),
                     key=lambda h: abs(dt.datetime.strptime(h["checked_at"], "%Y-%m-%d %H:%M") - (now - dt.timedelta(days=7))), default=None)
            if hb and (snap.get(p) or {}).get("views") is not None:
                per[p] = snap[p]["views"] - hb[p]["views"]
        tot = sum(v for v in per.values() if v > 0)
        if tot > 0:
            p, v = max(per.items(), key=lambda kv: kv[1])
            tries.append(f"lead with <b>{NAME[p]}</b>, {v / tot * 100:.0f}% of this week's new views")
    if tries:
        lines.append("Try next: " + "; ".join(tries) + ".")
    if not lines:
        return ""
    return "<div class='week'><div class='weekh'>This week</div><ul>" + "".join(f"<li>{x}</li>" for x in lines) + "</ul></div>"


SLOTS = [("Morning", 5, 11), ("Midday", 11, 14), ("Afternoon", 14, 17), ("Evening", 17, 21), ("Late night", 21, 29)]   # 21:00-04:59


def time_section(posts, now):
    """Which posting time gets the most views: public posts grouped by the hour they went up (Eastern)."""
    rows = []
    for r in posts:
        try:
            t = dt.datetime.strptime(r["created"], "%Y-%m-%d %H:%M")
        except ValueError:
            continue
        age = max((now - t).total_seconds() / 86400, 1.0)   # days live, at least 1
        h = t.hour if t.hour >= 5 else t.hour + 24
        slot = next(n for n, a, b in SLOTS if a <= h < b)
        rows.append((slot, r["site"], r["views"], r["views"] / age))
    if not rows:
        return ""
    e = html.escape
    out, best = [], None
    for name, a, b in SLOTS:
        rs = [x for x in rows if x[0] == name]
        if not rs:
            continue
        n, avg_v, per_day = len(rs), sum(x[2] for x in rs) / len(rs), sum(x[3] for x in rs) / len(rs)
        by_site = {p: [x for x in rs if x[1] == p] for p in PLAT}
        site_cells = "".join(f"<td class='hs'>{(sum(x[2] for x in v) / len(v)):,.0f} <small>({len(v)})</small></td>" if v else "<td class='hs'>—</td>" for p, v in by_site.items())
        label = f"{name} <small>{(a % 24):d}:00–{((b - 1) % 24):d}:59</small>"
        out.append([name, n, avg_v, per_day, f"<tr data-slot='{name}'><th class='rl'>{label}</th><td>{n}</td><td>{avg_v:,.0f}</td><td>{per_day:,.0f}</td>{site_cells}</tr>"])
        if best is None or per_day > best[3]:
            best = out[-1]
    trs = "".join(x[4].replace("<tr ", "<tr class='bestrow' ") if x is best else x[4] for x in out)
    heads = "".join(f"<th class='hs'>{NAME[p]}</th>" for p in PLAT)
    return (f"<h2 class='sh' id='sec-best'>Best posting time</h2><p class='sub'>Public posts grouped by the hour they went up (Eastern). "
            f"Views per day = views divided by days since posting, so new posts compare fairly with old ones. Best so far: <b>{e(best[0])}</b> "
            f"({best[1]} post(s), {best[3]:,.0f} views per post per day). Small numbers; treat as a hint until there are more posts.</p>"
            f"<div class='wrap'><table class='slots'><thead><tr><th class='rl'>Posted</th><th>Posts</th><th>Avg views</th><th>Views / day</th>{heads}</tr></thead>"
            f"<tbody>{trs}</tbody></table></div><p class='note hsn'>Site columns: average views per post (number of posts).</p>")


SHORT = {"instagram": "IG", "facebook": "FB", "youtube": "YT", "tiktok": "TT"}   # phone labels (Guy, Oct 25)


def write_html(stamp, rows, rd, snap, prev, labels, series, source, errors, hist=(), stale=None, day=None, old=None, dry=False, posts_html="", week_html="", installs=None, today=None, day_base=None, money=None, money_daily=None, est=None):
    e = html.escape
    cols = [{"id": "label", "label": stamp}] + [{"id": p, "label": NAME[p]} for p in PLAT] + [
        {"id": "total", "label": "Total"}, {"id": "best", "label": "Best for ads"}]   # Reddit column paused (Guy, Oct 22)
    trows = []
    for r in rows:
        cells = {}
        for p in PLAT:
            v = r["vals"][p]
            txt = e(fmt(v) + delta(v, r["olds"][p]))
            cells[p] = "<b>" + txt + "</b>" if v is not None and v == r["top"] and r["top"] else txt
            if r["label"] == "Top post views" and v is not None and (snap.get(p) or {}).get("top_url"):
                cells[p] = f"<a class='tp' href='{e(snap[p]['top_url'])}' target='_blank' rel='noopener'>{cells[p]}</a>"
        cells["reddit"] = "—" if r["label"] in ("Followers", "Avg views per post", "Avg watch time (s)", "Watched % of video") else fmt(r["reddit"])
        if r["label"] == "Top post views" and rd and rd.get("top_url") and r["reddit"] is not None:
            cells["reddit"] = f"<a class='tp' href='{e(rd['top_url'])}' target='_blank' rel='noopener'>{cells['reddit']}</a>"
        cells["total"] = e(fmt(r["total"]) + delta(r["total"], r["ototal"]))
        cells["best"] = e(" / ".join(r["best"]))
        trows.append({"id": r["label"], "label": r["label"], "cells": cells})
    trows.append({"id": "Pick for ads", "label": "Pick for ads", "full": f"<b>{e(pick(snap))}</b>"})
    table = json.dumps({"cols": cols, "rows": trows}).replace("</", "<\\/")
    asc_tpl = ""
    if ASCR.get("spd") is not None or ASCR.get("d1") is not None:   # Guy, Oct 26: App Store Connect numbers in the Retention card
        md = lambda d: dt.date.fromisoformat(d).strftime("%b %-d")
        tiles = []
        if ASCR.get("d1") is not None and ASC_D1_ON:   # Guy, Oct 27: hidden until Apple's Retention page shows data (opt-in sample too small); Firebase is the day-1 number for now
            tiles.append((f"{ASCR['d1']:.0f}%", "Day-1 return", f"of {ASCR.get('d1_n', 0):,} new devices opened it again the next day (estimate)"))
        if ASCR.get("spd") is not None:
            tiles.append((f"{ASCR['spd']:.1f}", "Sessions per device", "app opens per active device per day"))
        if ASCR.get("mins") is not None:
            tiles.append((f"{ASCR['mins']:.1f} min", "Avg session", "time per app open"))
        if ASCR.get("deletes") is not None:
            kept = f"  (~{max(0, 100 - round(ASCR['deletes'] / ASCR['installs'] * 100))}% kept)" if ASCR.get("installs") else ""   # Guy, Oct 26: rough, deletions include earlier installs
            tiles.append((f"{ASCR['deletes']:,}{kept}", "Deletions", f"vs {ASCR.get('installs', 0):,} new installs"))
        asc_tpl = ("<template id='ascret'><div class='asc'><div class='ash'>App · App Store Connect, "
                   f"{e(md(ASCR['first']))} – {e(md(ASCR['last']))} <small>(last {ASCR.get('days', 7)} days Apple has posted)</small></div><div class='atg'>"
                   + "".join(f"<div class='at'><b>{e(v)}</b><span>{e(l)}</span><small>{e(n)}</small></div>" for v, l, n in tiles)
                   + "</div></div></template>")
    layout = open(LAYOUT).read().replace("</", "<\\/") if os.path.exists(LAYOUT) else "null"
    rnote = (f"Reddit is entered by hand (Reddit hides views from its API): {rd['posts']} live post(s), {rd['removed']} removed, "
             f"last reading {rd['as_of']}, {rd['unknown_views']} post(s) without a view count yet.") if rd else "No Reddit rows yet."
    tops = sorted(((snap[p]["top_views"], snap[p].get("top_url", ""), NAME[p]) for p in PLAT if snap.get(p)), reverse=True)
    top_line = f"Most popular post: {tops[0][2]}, {tops[0][0]:,} views: <a href='{e(tops[0][1])}'>{e(tops[0][1])}</a>" if tops else ""
    legend = "".join(
        f"<span class='lg'><svg width='22' height='10'><line x1='0' y1='5' x2='22' y2='5' stroke='{COLOR[p]}' stroke-width='2'"
        f"{' stroke-dasharray=\"4 3\"' if p == 'instagram' else ''}/></svg>{NAME[p]} {fmt((snap.get(p) or {}).get('views'))}"
        f"{delta((snap.get(p) or {}).get('views'), (prev.get(p) or {}).get('views') if prev else None) or ''}</span>" for p in sorted(PLAT, key=lambda q: -((snap.get(q) or {}).get('views') or 0)))   # Guy, Oct 27: most to least
    inst_series = None
    if installs:
        td = dt.date.today()
        inst_series = [installs.get((td - dt.timedelta(days=len(labels) - 1 - i)).isoformat()) for i in range(len(labels))]
        inst_est = [(est or {}).get((td - dt.timedelta(days=len(labels) - 1 - i)).isoformat()) for i in range(len(labels))]
        inst_series = [v if v is not None else e for v, e in zip(inst_series, inst_est)]
    earn_series, earn_partial = None, []
    if money_daily:
        td = dt.date.today()
        def day_total(d):
            m = money_daily.get(d) or {}
            vals = [m.get("ads"), m.get("iap")]
            return None if all(v is None for v in vals) else round(sum(v or 0 for v in vals), 2)
        earn_series = [day_total((td - dt.timedelta(days=len(labels) - 1 - i)).isoformat()) for i in range(len(labels))]
        earn_partial = [i for i in range(len(labels)) if earn_series[i] is not None and (money_daily.get((td - dt.timedelta(days=len(labels) - 1 - i)).isoformat()) or {}).get("iap") is None]
    spend_series = [GADS.get((dt.date.today() - dt.timedelta(days=len(labels) - 1 - i)).isoformat()) for i in range(len(labels))] if GADS else None
    data = json.dumps({"labels": labels, "series": {NAME[p]: series[p] for p in PLAT}, "installs": inst_series, "earned": earn_series, "earnPart": earn_partial, "spend": spend_series,
                       "est": [i for i in range(len(labels)) if (est or {}).get((dt.date.today() - dt.timedelta(days=len(labels) - 1 - i)).isoformat()) is not None] if installs else []})
    if dry:
        return {"stamp": stamp, "table": {"cols": cols, "rows": trows}, "legend": legend,
                "data": {"labels": labels, "series": {NAME[p]: series[p] for p in PLAT}}}
    olds = json.dumps(old).replace("</", "<\\/") if old else "null"
    prev_html = (f"""<h2 class="ph">24 hours ago</h2><p class="sub">{e(old['stamp'])} · the check the card above compares with</p>
<div class="wrap ptw"><table id="pt"></table></div>""") if old else ""
    stale = stale or {}
    day_html = ""
    if day:
        sign = "+" if day["total"] >= 0 else "−"
        parts = " · ".join(f"<span style='color:{COLOR[p]}'>●</span> <span class='nf'>{NAME[p]}</span><span class='ns'>{SHORT[p]}</span> {'+' if day['per'][p] >= 0 else '−'}{abs(day['per'][p]):,}" for p in PLAT)
        when = "Last 24 hours" if 21 <= day["hours"] <= 27 else f"Last {day['hours']} hours (closest check to 24 h ago: {day['since'].strftime('%b %-d, %-I:%M %p')})"
        inst = ""
        if installs:
            days = sorted(d for d in installs if installs[d] is not None)
            y = (dt.date.today() - dt.timedelta(days=1)).isoformat()
            w = sum(installs[d] for d in days if (dt.date.today() - dt.date.fromisoformat(d)).days <= 7)
            est = est or {}
            td_s = dt.date.today().isoformat()
            m = sum(installs[d] for d in days if d[:7] == dt.date.today().strftime("%Y-%m"))
            month = dt.date.today().strftime("%B")
            tot = sum(installs[d] for d in days)
            tail = f" · <b>{w:,}</b> last 7 days · <b>{m:,}</b> in {month} · <b>{tot:,}</b> total since launch</div>"
            today_est = f"<b>~{est[td_s]:,}</b> today so far <small>(estimate)</small> · " if td_s in est else ""
            if installs.get(y) is not None:
                inst = f"<div class='dayp dayi'>App Store installs: {today_est}<b>{installs[y]:,}</b> yesterday" + tail
            elif y in est:
                inst = f"<div class='dayp dayi'>App Store installs: {today_est}<b>~{est[y]:,}</b> yesterday <small>(estimate; Apple posts it this morning)</small>" + tail
            else:
                inst = f"<div class='dayp dayi'>App Store installs: {today_est}yesterday not posted by Apple yet" + tail
        big, sub, head = f"{sign}{abs(day['total']):,}", "", e(when)
        if today:
            tsign = "+" if today["total"] >= 0 else "−"
            big = f"{tsign}{abs(today['total']):,}"
            yv = [series[q][-2] for q in PLAT] if series and all(len(series.get(q) or []) >= 2 for q in PLAT) else None
            if yv and all(v is not None for v in yv):   # yesterday = the chart's yesterday bar (same baseline)
                ytot = sum(yv)
                sub = f"<small class='sub2'>({'+' if ytot >= 0 else '−'}{abs(ytot):,} yesterday)</small>"
            else:
                sub = f"<small class='sub2'>({sign}{abs(day['total']):,} past 24 h)</small>"
            if prev and all(isinstance(prev.get(p), dict) and prev[p].get("views") is not None and (snap.get(p) or {}).get("views") is not None for p in PLAT):
                mv = sum(snap[p]["views"] - prev[p]["views"] for p in PLAT)
                since = dt.datetime.strptime(prev["checked_at"], "%Y-%m-%d %H:%M").strftime("%-I:%M %p")
                allv0 = sum((snap.get(p) or {}).get("views") or 0 for p in PLAT)   # Guy, Oct 26: JS swaps this for "since you last looked"
                sub = f"<small class='sub2' id='slv' data-total='{allv0}' data-stamp='{html.escape(stamp)}'>({'+' if mv >= 0 else '−'}{abs(mv):,} since the {since} refresh)</small>" + sub
            head = "Views today" + (f" <small>since the {today['since'].strftime('%b %-d, %-I:%M %p')} check</small>" if abs(today["off_h"]) > 2 else "")
            parts = " · ".join(f"<span style='color:{COLOR[p]}'>●</span> <span class='nf'>{NAME[p]}</span><span class='ns'>{SHORT[p]}</span> {'+' if today['per'][p] >= 0 else '−'}{abs(today['per'][p]):,}" for p in PLAT)
        allv = sum((snap.get(p) or {}).get("views") or 0 for p in PLAT)
        tot_dl = sum(v for v in installs.values() if v is not None) if installs else None
        right = f"<div class='dayt'>{allv:,} <small>total views</small></div>" + (f"<div class='dayt'>{tot_dl:,} <small>total downloads</small></div>" if tot_dl is not None else "")
        if RET.get("d1") is not None:   # Guy, Oct 26: Firebase next-day return of new players (last 7 complete days)
            tip = f"Day-1: {RET['d1']:.0f}% of {int(RET.get('d1_n') or 0):,} new players came back the next day" + (f" · Day-7: {RET['d7']:.0f}%" if RET.get("d7") is not None else "") + " (Firebase, last 7 complete days)"
            right += f"<div class='dayt' title='{tip}'>{RET['d1']:.0f}% <small>day-1 retention</small></div>"
        if money:
            right += f"<div class='dayt'>${money['all']:,.2f} <small>total earned</small></div>"
            inst += (f"<div class='dayp daym'>Earned: <b>${money['t']:,.2f}</b> today so far · <b>${money['y']:,.2f}</b> yesterday · <b>${money['w']:,.2f}</b> last 7 days · <b>${money['m']:,.2f}</b> in {money['month']}"
                     f" · ads ${money['ads']:,.2f} + App Store ${money['iap']:,.2f} since launch {' <small>(Apple hasn’t posted yesterday yet)</small>' if money['y_missing'] else ''}</div>")
        v3now = {p: (snap.get(p) or {}).get("views_3s") for p in PLAT}
        v3b = {p: (day_base.get(p) or {}).get("views_3s") for p in PLAT} if day_base else {}
        v3parts = " · ".join(f"<span style='color:{COLOR[p]}'>●</span> <span class='nf'>{NAME[p]}</span><span class='ns'>{SHORT[p]}</span> {v3now[p]:,}" + (f" <small>(+{v3now[p] - v3b[p]:,} 24 h)</small>" if v3b.get(p) is not None and v3now[p] - v3b[p] >= 0 else "") for p in PLAT if v3now[p] is not None)
        v3line = f"<div class='dayp day3'>3-second views: {v3parts}</div>" if v3parts else ""
        inst = v3line + inst
        day_html = (f"<div class='day'><div class='dayl'>{head}</div><div class='dayv'>{big} <small>views</small> {sub}</div>"
                    f"<div class='dayr'>{right}</div><div class='dayp dayps'>{parts}</div>{inst}</div>")
    stale_html = "".join(f"<p class='warn'>{NAME[p]} couldn’t be pulled after 3 tries, so its numbers are from the last good check ({e(t)}).</p>" for p, t in stale.items())
    if len(snap) == len(PLAT) and not stale:   # keep the last complete run (Mac report cache)
        os.makedirs(os.path.dirname(LAST), exist_ok=True)
        json.dump({"stamp": stamp, "table": {"cols": cols, "rows": trows}, "legend": legend,
                   "data": {"labels": labels, "series": {NAME[p]: series[p] for p in PLAT}}}, open(LAST, "w"))
    err = "".join(f"<li>{e(x)}</li>" for x in errors)
    doc = f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Beaker Lab - Social Report</title>
<link rel="icon" type="image/svg+xml" href="data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 64 64'><rect width='64' height='64' rx='14' fill='%232A78D6'/><g fill='%23fff' opacity='.35'><rect x='12' y='40' width='8' height='12' rx='2'/><rect x='25' y='32' width='8' height='20' rx='2'/><rect x='38' y='26' width='8' height='26' rx='2'/></g><polyline points='12,42 25,34 36,38 51,18' fill='none' stroke='%23fff' stroke-width='5' stroke-linecap='round' stroke-linejoin='round'/><polyline points='42,17 52,16 51,26' fill='none' stroke='%23fff' stroke-width='5' stroke-linecap='round' stroke-linejoin='round'/></svg>">
<style>
:root{{--bg:#fcfcfb;--ink:#0b0b0b;--ink2:#52514e;--muted:#898781;--line:#e1e0d9;--card:#fff}}
@media (prefers-color-scheme: dark){{:root{{--bg:#1a1a19;--ink:#f0efec;--ink2:#c3c2b7;--muted:#898781;--line:#2c2c2a;--card:#222220}}}}
body{{margin:0;background:var(--bg);color:var(--ink);font-family:Aptos,-apple-system,"Helvetica Neue",system-ui,sans-serif;font-size:15px}}
main{{max-width:1100px;margin:0 auto;padding:24px 16px}}
h1{{font-size:22px;font-weight:500;margin:0 0 4px}} .sub{{color:var(--muted);margin:0 0 20px}}
.wrap{{overflow-x:auto}} table{{border-collapse:collapse;width:100%;background:var(--card)}}
th,td{{border-bottom:1px solid var(--line);padding:8px 10px;text-align:right;white-space:nowrap;font-variant-numeric:tabular-nums}} #t td:nth-last-child(1),#t th:nth-last-child(1){{border-left:1px solid var(--line);padding-left:16px}} #t td:nth-child(2),#t th:nth-child(2){{padding-right:16px;border-right:1px solid var(--line)}}
th{{font-weight:500;color:var(--ink2)}} th.rl{{text-align:left}} thead th{{border-bottom:1px solid var(--muted)}}
#m{{display:none}} .mc{{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:12px 14px;margin:0 0 10px}}
.mh{{display:flex;justify-content:space-between;align-items:baseline;gap:8px;margin-bottom:8px}} .ml{{font-weight:600;font-size:16px}}
.mt{{font-size:19px;font-weight:600;font-variant-numeric:tabular-nums}} .mg{{display:grid;grid-template-columns:1fr 1fr;gap:8px}}
.mp{{display:flex;flex-direction:column;gap:2px;padding:6px 9px;border-radius:8px;background:var(--bg)}} .mp span{{font-size:12px;color:var(--muted);display:flex;align-items:center;gap:5px}}
.mp i{{width:8px;height:8px;border-radius:50%;display:inline-block}} .mp b{{font-size:17px;font-weight:600;font-variant-numeric:tabular-nums}} .mp.best{{box-shadow:inset 0 0 0 2px #2A78D6;background:rgba(42,120,214,.14)}} .mp.best span{{color:var(--ink2)}}
.mc small,.mp small{{color:var(--muted);font-size:12px;font-weight:400}} .mc small.up{{color:#1E9E55}} .mpick{{font-size:17px}}
@media (max-width:700px){{main{{padding:16px 14px}} h1{{font-size:24px}} .sub{{font-size:14px}} .tw,.ptw,#edit{{display:none}} #m{{display:block}} table.vt th,table.vt td{{padding:5px 3px;font-size:12px}}

 table.vt .aw{{display:none}} .vch{{flex-wrap:wrap}} .hs{{display:none}} .hist th,.hist td{{padding:8px 6px}} .chart{{height:260px}} .note{{font-size:12px}} .lgs{{gap:10px 16px}} h2.ph{{margin-top:32px}}}}
.day{{display:grid;grid-template-columns:1fr auto;grid-template-areas:"l r" "v r" "p r" "t r" "i r" "m r";align-items:start;column-gap:16px;row-gap:4px;background:var(--card);border:1px solid var(--line);border-radius:12px;padding:12px 16px;margin:0 0 14px}}
.dayv .sub2{{display:block;font-size:13px}} .dayt{{font-size:26px;font-weight:600;color:#5f5e5a;font-variant-numeric:tabular-nums;margin-top:6px;text-align:right}} .dayt small{{font-size:14px;color:var(--muted);font-weight:400}}
@media (prefers-color-scheme: dark){{.dayt{{color:#a9a89f}}}} .day{{position:sticky;top:8px;z-index:5;box-shadow:0 4px 14px rgba(0,0,0,.14)}} .dayl{{color:var(--ink2);font-weight:500}} .dayl small{{color:var(--muted);font-weight:400;font-size:12px}} .dayl{{grid-area:l}} .dayv{{grid-area:v;font-size:26px;font-weight:600;font-variant-numeric:tabular-nums;text-align:left;margin-top:2px;line-height:1.15}}
.dayr{{grid-area:r;text-align:right;margin-top:2px;align-self:start}} .day .dayp.dayps{{grid-area:p}} .day .dayp.dayi{{grid-area:i}} .day .dayp.day3{{grid-area:t}} .day .dayp.daym{{grid-area:m}} .dayr .dayt{{margin-top:0;line-height:1.15}} .dayr .dayt small{{display:block;font-size:13px}} .dayr .dayt+.dayt{{margin-top:8px}} .day .dayp{{grid-column:auto}} .dayv small{{font-size:14px;color:var(--muted);font-weight:400}}
.dayp{{grid-column:1/-1;font-size:13px;color:var(--ink2)}} a.tp{{color:inherit;text-decoration:underline;text-decoration-color:#2A78D6;text-underline-offset:3px}}
h2.sh{{font-size:18px;font-weight:500;margin:36px 0 10px}} .dot{{display:inline-block;width:8px;height:8px;border-radius:50%;margin-right:6px;vertical-align:middle}}
.old{{display:none}} .showold .old{{display:revert}} .vgrid{{display:grid;grid-template-columns:1fr 1fr;gap:12px}} @media (max-width:900px){{.vgrid{{grid-template-columns:1fr}}}}
.vc{{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:12px 14px}} .vch{{display:flex;justify-content:space-between;gap:10px;align-items:baseline}}
.rtt{{min-width:260px}} .rtt-bar{{display:flex;height:12px;border-radius:6px;overflow:hidden;margin:2px 0 10px;gap:2px}} .rtt-bar i{{display:block;height:100%}} .rtt .ctt-r{{display:grid;column-gap:10px;align-items:center}} .rtt .ctt-r.rb{{grid-template-columns:13px minmax(84px,1fr) 100px 52px}} .rtt .ctt-r.rs{{grid-template-columns:13px minmax(84px,1fr) 60px 42px}} .rtt .ctt-r b{{text-align:right}} .rtt-n{{white-space:nowrap}} .rtt .ctt-r b{{font-weight:600;font-variant-numeric:tabular-nums}} .rtt .ctt-r small{{width:42px;text-align:right;opacity:.75;font-variant-numeric:tabular-nums}} .rtt-m{{width:100px;height:8px;border-radius:4px;background:rgba(255,255,255,.12);overflow:hidden}} .rtt-m em{{display:block;height:100%;border-radius:4px}} .ctt{{position:absolute;pointer-events:none;z-index:5;opacity:0;transition:opacity .15s,left .12s ease-out,top .12s ease-out;background:rgba(18,18,20,.62);-webkit-backdrop-filter:blur(12px) saturate(140%);backdrop-filter:blur(12px) saturate(140%);color:#fff;border-radius:12px;padding:12px 16px 13px;box-shadow:0 8px 28px rgba(0,0,0,.28);font-size:16px;line-height:1.5;white-space:nowrap}} .ctt-h{{font-size:19px;font-weight:700;margin-bottom:6px}} .ctt-r{{display:flex;align-items:center;gap:9px}} .ctt-r i{{width:13px;height:13px;border-radius:3px;flex:none}} .ctt-sep{{height:1px;background:rgba(255,255,255,.7);margin:10px 0}} @media (max-width:700px){{.ctt{{font-size:14px;padding:10px 12px}} .ctt-h{{font-size:16px}}}} .ns{{display:none}} @media (max-width:700px){{.nf{{display:none}} .ns{{display:inline}}}} .vct{{font-weight:600;line-height:1.3;margin-top:2px}} .pcol{{display:flex;flex-direction:column;align-items:flex-end;gap:4px;flex:none}} .pdist{{font-size:13px;font-weight:700;color:var(--ink2);font-variant-numeric:tabular-nums;white-space:nowrap}} .pdot{{width:14px;height:14px;border-radius:50%;flex:none;align-self:center;box-shadow:0 0 0 3px var(--card),0 0 0 4px var(--line)}} .vcn{{white-space:nowrap;font-size:18px;font-variant-numeric:tabular-nums}} .vcn small{{font-size:12px;color:var(--muted);font-weight:400}}
.vcm{{color:var(--muted);font-size:12px;margin:2px 0 8px}} table.vt{{width:100%;background:transparent}} table.vt th,table.vt td{{padding:5px 6px;font-size:13px;border-bottom:1px solid var(--line)}}
table.vt thead th{{color:var(--muted);font-weight:500;border-bottom:1px solid var(--line)}} table.vt tbody tr:last-child th,table.vt tbody tr:last-child td{{border-bottom:0}}
table.vt tr.lead td,table.vt tr.lead th{{background:rgba(42,120,214,.10)}} table.vt a.tp{{text-decoration:none;color:inherit;border-bottom:1px solid #2A78D6}}
#more{{margin:4px 0 0}} .week{{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:12px 16px;margin:0 0 14px}}
.weekh{{color:var(--ink2);font-weight:500;margin-bottom:6px}} .weekh small{{color:var(--muted);font-weight:400;font-size:12px;margin-left:6px}}
 .week ul{{margin:0;padding-left:18px;color:var(--ink)}} .week li{{margin:3px 0;line-height:1.4}} tr.bestrow th,tr.bestrow td{{background:rgba(42,120,214,.12)}} table.slots small{{color:var(--muted);font-weight:400}}
@media (max-width:700px){{.hsn{{display:none}} table.slots th,table.slots td{{padding:8px 5px;font-size:13px}} table.slots small{{display:block;font-size:11px}}
.day{{grid-template-columns:1fr;grid-template-areas:"l" "v" "p" "t" "i" "m" "r"}} .day .dayp{{grid-column:1/-1}}
.dayr{{display:flex;justify-content:space-between;align-items:flex-end;gap:8px;margin-top:10px;padding-top:10px;border-top:1px solid var(--line)}} .dayr .dayt{{font-size:19px}} .dayr .dayt small{{font-size:12px}} .dayr .dayt{{margin:0 !important}} .dayr .dayt:first-child{{text-align:left}} .dayr .dayt:last-child{{text-align:right}}}}
tr.pick td{{text-align:left}} .warn{{margin:0 0 10px;padding:8px 12px;border-radius:8px;background:#FFF4CC;color:#5c4a00;font-size:14px}} .hist td,.hist th{{color:var(--ink2);font-size:14px}} .dl{{color:var(--muted);font-size:12px}} b{{font-weight:600}}
.lgs{{display:flex;flex-wrap:wrap;gap:16px;margin:28px 0 8px;font-size:12px;color:var(--ink2)}} .lg{{display:flex;align-items:center;gap:6px}}
.chart{{position:relative;height:340px}}
.rng{{position:relative;height:34px;margin:10px 0 0 52px;margin-right:52px;border-radius:9px;background:var(--line);touch-action:none;user-select:none;cursor:pointer}} .rng-c{{position:absolute;inset:0;width:100%;height:100%;border-radius:9px}}
.rng-w{{position:absolute;top:0;bottom:0;border-radius:9px;background:rgba(59,139,223,.16);border:2px solid #3B8BDF;cursor:grab;transition:left .18s cubic-bezier(.2,.8,.2,1);box-sizing:border-box}} .rng.drag .rng-w{{transition:none;cursor:grabbing}}
.rng-w i{{position:absolute;top:50%;width:3px;height:14px;margin-top:-7px;border-radius:2px;background:#3B8BDF}} .rng-w i:first-child{{left:6px}} .rng-w i:last-child{{right:6px}}
.rng-l{{display:flex;justify-content:space-between;margin:5px 52px 0;font-size:12px;color:var(--muted)}}
@media (max-width:700px){{.rng,.rng-l{{margin-left:8px;margin-right:8px}}}}
.bar{{display:flex;flex-wrap:wrap;align-items:center;gap:8px;margin:0 0 14px}} #tools{{display:inline-flex;flex-wrap:wrap;gap:8px}} #tools[hidden]{{display:none}}
.b{{border:0;border-radius:8px;padding:8px 14px;font:inherit;font-weight:600;color:#fff;cursor:pointer}} .b:disabled{{opacity:.6;cursor:default}}
html{{scroll-behavior:smooth}} h2.has-top{{display:flex;align-items:center;justify-content:space-between;gap:12px}} .b.totop{{padding:5px 14px;font-size:14px;font-weight:600;flex:none}} a.b.jump{{text-decoration:none;display:inline-block}} [id^="sec-"]{{scroll-margin-top:12px}} .red{{background:#D93A36}} .blue{{background:#2A78D6}} .green{{background:#1E9E55}} .gray{{background:#77756f}}
select{{font:inherit;padding:7px 8px;border-radius:8px;border:1px solid var(--line);background:var(--card);color:var(--ink)}}
table.fixed{{table-layout:fixed;width:auto}} table.fixed th,table.fixed td{{overflow:hidden;text-overflow:ellipsis}}
table.edit th,table.edit td{{position:relative;outline:1px dashed var(--line)}}
.h{{cursor:grab;color:var(--muted);margin-right:6px;user-select:none}} .x{{cursor:pointer;color:#D93A36;margin-left:6px;font-weight:600;user-select:none}}
.rz{{position:absolute;top:0;right:-3px;width:7px;height:100%;cursor:col-resize;z-index:2}} .rzr{{position:absolute;left:0;bottom:-3px;height:7px;width:100%;cursor:row-resize;z-index:2}}
.ed{{outline:none;min-width:30px;display:inline-block}} table.edit .ed{{background:rgba(42,120,214,.08)}}
h2.ph{{font-size:18px;font-weight:500;margin:48px 0 4px;padding-top:20px;border-top:1px solid var(--line)}} #pt th,#pt td{{color:var(--ink2)}}
.dropL{{box-shadow:inset 3px 0 0 #2A78D6}} .dropR{{box-shadow:inset -3px 0 0 #2A78D6}} .dropT{{box-shadow:inset 0 3px 0 #2A78D6}} .dropB{{box-shadow:inset 0 -3px 0 #2A78D6}} ul{{color:var(--ink2)}} .note{{color:var(--muted);font-size:13px}} a{{color:#2A78D6}}

#g .card{{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:16px 18px;margin:0 0 14px}}
#g .gh{{display:flex;align-items:baseline;gap:10px;flex-wrap:wrap;margin-bottom:10px}} #g h3{{margin:0;font-size:18px}} #g .gs{{color:var(--muted);font-size:13px}}
#g .shh{{font-size:13px;color:var(--ink2);margin-bottom:6px}} #g .sbar{{display:flex;height:14px;border-radius:7px;overflow:hidden;gap:2px}} #g .sbar i{{display:block}}
#g .sl{{display:flex;flex-wrap:wrap;gap:6px 16px;font-size:13px;color:var(--ink2);margin:7px 0 14px}} #g .sl b,#g .gd{{display:inline-block;width:9px;height:9px;border-radius:50%;margin-right:5px}}
#g table{{width:100%;table-layout:fixed;border-collapse:collapse;font-variant-numeric:tabular-nums;min-width:0}} #g th{{font-weight:500;color:var(--ink2);font-size:13px;text-align:right;padding:4px 8px;white-space:nowrap;border:0}}
#g th:first-child,#g td.lab{{width:24%}} #g td{{text-align:right;padding:8px;border:0;border-top:1px solid var(--line);white-space:nowrap}} #g td.lab{{text-align:left;color:var(--ink2);white-space:normal}} #g .tot{{font-weight:600}}
#g td.best{{background:rgba(42,120,214,.14);box-shadow:inset 0 0 0 1.5px #2A78D6;border-radius:6px}} #g small{{font-size:12px;color:var(--muted)}} #g small.up{{color:#1E9E55}} #g .na{{color:var(--muted);opacity:.6}} #g a.tp{{color:inherit}} #g .cv{{display:inline-grid;grid-template-columns:auto 66px;column-gap:5px;align-items:baseline}} #g .cv>span{{text-align:right}} #g th .gp{{display:inline-block;padding:3px 12px 4px;border-radius:999px;color:#fff;font-weight:600;font-size:13px;line-height:1.3}} #g .cv>small{{text-align:left}} @media (min-width:701px){{#g th:not(:first-child):not(.tl){{text-align:center}} #g td:not(.lab) .cv{{display:block;width:84px;margin:0 auto;text-align:right}} #g td.tl .cv{{margin:0 0 0 auto}} #g td:not(.lab) .cv>span{{display:block}} #g td:not(.lab) .cv>small{{display:block;text-align:right;line-height:1.2}}}} @media (max-width:1000px){{#g .cv{{display:block}} #g .cv>small{{display:block;text-align:right}}}}
#g .tl{{border-right:1px solid var(--line);padding-right:12px}} #g .gpick{{font-size:16px;margin:0 0 14px}} #g .ns{{display:none}}

#g .asc{{margin-top:14px;padding-top:12px;border-top:1px solid var(--line)}} #g .ash{{font-size:13px;color:var(--ink2);margin-bottom:8px}} #g .ash small{{display:inline;color:var(--muted)}}
#g .atg{{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:8px}} #g .at{{background:var(--bg);border-radius:10px;padding:9px 11px;display:flex;flex-direction:column;gap:1px}}
#g .at b{{white-space:pre;font-size:20px;font-weight:600;font-variant-numeric:tabular-nums}} #g .at span{{font-size:13px;color:var(--ink2)}} #g .at small{{display:block;font-size:11px;color:var(--muted);line-height:1.3}}
@media (max-width:700px){{#g .atg{{grid-template-columns:1fr 1fr}} #g .at b{{font-size:18px}}}}
body.editing #g{{display:none}} body:not(.editing) .tw{{display:none}} #m{{display:none !important}}
@media (max-width:700px){{#g .nf{{display:none}} #g .ns{{display:inline}} #g th,#g td{{padding:7px 3px;font-size:14px}} #g td.lab{{font-size:13px;width:25%}} #g th:first-child{{width:25%}} #g small{{display:block;font-size:11px}} #g .cv{{display:block}} #g .cv>small{{text-align:right}} #g .card{{padding:14px 12px}}}}
</style></head><body><main>
<h1>Beaker Lab - Social Report</h1><p class="sub">{e(stamp)} · changes in brackets are since the last check ({e(prev.get('checked_at', 'none') if prev else 'none')})</p>
<div class="bar"><button id="refresh" class="b red">Refresh</button><a class="b gray jump" href="#sec-best"><span class="nf">Best Posting Time</span><span class="ns">Best TOD</span></a><a class="b gray jump" href="#sec-videos">Videos</a><a class="b gray jump" href="#sec-history">History</a><button id="edit" class="b blue">Edit Layout</button>
<span id="tools" hidden><select id="addc"></select><select id="addr"></select><button id="cancel" class="b gray">Cancel</button><button id="reset" class="b gray">Reset Layout</button></span>
<span id="msg" class="note"></span></div>
{day_html}{week_html}<h2 class="sh" style="margin-top:4px">Views gained per day</h2>
<div class="lgs" style="margin-top:0">{legend}</div>
<div class="chart"><canvas id="c" role="img" aria-label="Views gained per day per platform"></canvas></div>
<div class="rng" id="rng" hidden><canvas class="rng-c"></canvas><div class="rng-w"><i></i><i></i></div></div><div class="rng-l" id="rngl" hidden><span></span><span></span></div>
<p class="note">Bars: last check of each day vs the day before; the last bar is today so far. Days with no check share the gain evenly. Purple line: App Store first downloads per day (right axis; Apple posts each day by the next morning; a hollow point is a conservative estimate from RevenueCat first opens until Apple posts). Green line: money earned that day, ads + App Store proceeds (hover for $). Dotted with hollow points until Apple posts that day's App Store proceeds; it turns solid once Apple's numbers are in. Gold bar (narrow, next to each day's views): Google Ads spend that day, on the Installs scale ($1 = 1 install), so a gold bar taller than that day's purple point means installs cost more than $1 each.</p>
{stale_html}<div id="g"></div>{asc_tpl}<div class="wrap tw"><table id="t"></table></div><div id="m"></div>
<p class="note">YouTube average uses public posts only. Facebook comments = viewer comments (the Page's own link comments are left out). Comments = viewer comments only (our own replies and pinned comments are left out).</p>
{posts_html}
<p>{top_line}</p>
{('<ul>' + err + '</ul>') if err else ''}
{history_html(hist)}
</main>
<script>
const T = {table}, SAVED = {layout}, OLD = {olds}, SITE = {json.dumps(SITE)}, ACT = {json.dumps(ACTIONS)};
const $ = id => document.getElementById(id), esc = t => String(t).replace(/[&<>"]/g, m => ({{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}})[m]);
const EX = 36, wd = c => (c.w || 110) + (editing ? EX : 0);   // edit mode adds room for the ⠿ and × handles
const served = location.protocol.startsWith('http'), cid = id => T.cols.find(c => c.id === id), rid = id => T.rows.find(r => r.id === id);
let L, editing = false, backup = null;
function load(l) {{   // saved layout + anything new in the data that the saved layout never knew about
  if (!l) return {{cols: T.cols.map(c => ({{id: c.id}})), rows: T.rows.map(r => ({{id: r.id}}))}};
  const known = new Set(l.known || []), n = JSON.parse(JSON.stringify(l));
  n.cols = n.cols.filter(c => c.custom || cid(c.id)); n.rows = n.rows.filter(r => r.custom || rid(r.id));
  if (!n.cols.some(c => c.id === 'label')) n.cols.unshift({{id: 'label'}});
  T.cols.forEach(c => {{ if (!known.has('c:' + c.id) && !n.cols.some(x => x.id === c.id)) n.cols.push({{id: c.id}}); }});
  T.rows.forEach(r => {{ if (!known.has('r:' + r.id) && !n.rows.some(x => x.id === r.id)) {{   // new metric rows go above "Pick for ads"
    const k = n.rows.findIndex(x => x.id === 'Pick for ads'); n.rows.splice(k < 0 ? n.rows.length : k, 0, {{id: r.id}}); }} }});
  return n;
}}
function cell(c, r) {{
  if (c.custom || r.custom) {{ const v = r.custom ? (r.cells || {{}})[c.id] : (c.cells || {{}})[r.id];
    return `<span class="ed" data-cell="${{esc(c.id)}}|${{esc(r.id)}}" ${{editing ? 'contenteditable' : ''}}>${{esc(v || '')}}</span>`; }}
  return rid(r.id).cells[c.id] ?? '';
}}
function render() {{
  const t = $('t'), fixed = L.cols.some(c => c.w);
  t.className = (fixed ? 'fixed ' : '') + (editing ? 'edit' : '');
  t.style.width = fixed ? L.cols.reduce((s, c) => s + wd(c), 0) + 'px' : '';
  let h = '<colgroup>' + L.cols.map(c => `<col style="${{c.w ? 'width:' + wd(c) + 'px' : ''}}">`).join('') + '</colgroup><thead><tr>';
  L.cols.forEach((c, i) => {{
    const lab = c.custom ? `<span class="ed" data-col="${{esc(c.id)}}" ${{editing ? 'contenteditable' : ''}}>${{esc(c.label || '')}}</span>` : esc(cid(c.id).label);
    const tools = editing && c.id !== 'label' ? [`<span class="h" draggable="true" data-dc="${{esc(c.id)}}" title="Drag to move">⠿</span>`, `<span class="x" data-xc="${{esc(c.id)}}" title="Remove column">×</span>`] : ['', ''];
    h += `<th class="${{c.id === 'label' ? 'rl' : ''}}" data-c="${{esc(c.id)}}">${{tools[0]}}${{lab}}${{tools[1]}}${{editing ? `<span class="rz" data-rc="${{i}}"></span>` : ''}}</th>`;
  }});
  h += '</tr></thead><tbody>';
  L.rows.forEach((r, i) => {{
    const d = r.custom ? null : rid(r.id);
    const lab = r.custom ? `<span class="ed" data-row="${{esc(r.id)}}" ${{editing ? 'contenteditable' : ''}}>${{esc(r.label || '')}}</span>` : esc(d.label);
    const tools = editing ? [`<span class="h" draggable="true" data-dr="${{esc(r.id)}}" title="Drag to move">⠿</span>`, `<span class="x" data-xr="${{esc(r.id)}}" title="Remove row">×</span>`] : ['', ''];
    h += `<tr data-r="${{esc(r.id)}}" style="${{r.h ? 'height:' + r.h + 'px' : ''}}" class="${{d && d.full ? 'pick' : ''}}">`;
    let first = true;
    L.cols.forEach(c => {{
      if (c.id === 'label') {{ h += `<th class="rl">${{tools[0]}}${{lab}}${{tools[1]}}${{editing ? `<span class="rzr" data-rr="${{i}}"></span>` : ''}}</th>`; return; }}
      if (d && d.full) {{ if (first) h += `<td colspan="${{L.cols.length - 1}}">${{d.full}}</td>`; first = false; return; }}
      h += `<td>${{cell(c, r)}}</td>`;
    }});
    h += '</tr>';
  }});
  t.innerHTML = h + '</tbody>';
  menus();
}}
function menus() {{
  const hc = T.cols.filter(c => !L.cols.some(x => x.id === c.id)), hr = T.rows.filter(r => !L.rows.some(x => x.id === r.id));
  $('addc').innerHTML = '<option value="">+ Add column…</option>' + hc.map(c => `<option value="${{esc(c.id)}}">${{esc(c.label)}}</option>`).join('') + '<option value="*">New blank column</option>';
  $('addr').innerHTML = '<option value="">+ Add row…</option>' + hr.map(r => `<option value="${{esc(r.id)}}">${{esc(r.label)}}</option>`).join('') + '<option value="*">New blank row</option>';
}}
function grab() {{   // keep typed text from blank columns/rows
  document.querySelectorAll('#t [data-col]').forEach(n => L.cols.find(c => c.id === n.dataset.col).label = n.textContent.trim());
  document.querySelectorAll('#t [data-row]').forEach(n => L.rows.find(r => r.id === n.dataset.row).label = n.textContent.trim());
  document.querySelectorAll('#t [data-cell]').forEach(n => {{ const [ci, ri] = n.dataset.cell.split('|'), c = L.cols.find(x => x.id === ci), r = L.rows.find(x => x.id === ri);
    if (r.custom) (r.cells = r.cells || {{}})[ci] = n.textContent.trim(); else (c.cells = c.cells || {{}})[ri] = n.textContent.trim(); }});
}}
function setEdit(on) {{
  editing = on; $('tools').hidden = !on; document.body.classList.toggle('editing', on);
  $('edit').textContent = on ? 'Save Layout' : 'Edit Layout'; $('edit').className = 'b ' + (on ? 'green' : 'blue');
  if (on) {{ backup = JSON.stringify(L); const ths = document.querySelectorAll('#t thead th'); L.cols.forEach((c, i) => c.w = c.w || Math.ceil(ths[i].getBoundingClientRect().width)); }}
  render();
}}
const msg = t => $('msg').textContent = t;
$('edit').onclick = async () => {{
  if (!editing) return setEdit(true);
  grab();
  const body = JSON.stringify({{...L, known: T.cols.map(c => 'c:' + c.id).concat(T.rows.map(r => 'r:' + r.id))}});
  if (!served) return msg('Can’t save from this copy. Run "Refresh Social Report" once, then use the report it opens.');
  try {{ const r = await fetch('/layout', {{method: 'POST', body}}); if (!r.ok) throw 0; setEdit(false); renderG(); msg('Layout saved. Future reports will use it.'); }}
  catch (e) {{ msg('Save failed: the report helper isn’t running. Run "Refresh Social Report" once, then try again.'); }}
}};
$('cancel').onclick = () => {{ L = JSON.parse(backup); setEdit(false); renderG(); msg(''); }};
$('reset').onclick = async () => {{
  if (!confirm('Go back to the default layout for this and all future reports?')) return;
  if (served) try {{ await fetch('/layout', {{method: 'DELETE'}}); }} catch (e) {{}}
  L = load(null); setEdit(false); renderG(); msg('Layout reset to default.');
}};
$('addc').onchange = e => {{ grab(); const v = e.target.value; if (!v) return;
  L.cols.push(v === '*' ? {{id: 'x' + Date.now(), custom: true, label: 'New column', w: 140}} : {{id: v, w: 120}}); render(); }};
$('addr').onchange = e => {{ grab(); const v = e.target.value; if (!v) return;
  L.rows.push(v === '*' ? {{id: 'x' + Date.now(), custom: true, label: 'New row'}} : {{id: v}}); render(); }};
$('t').addEventListener('click', e => {{
  const x = e.target.dataset; if (!x.xc && !x.xr) return; grab();
  if (x.xc) L.cols = L.cols.filter(c => c.id !== x.xc); else L.rows = L.rows.filter(r => r.id !== x.xr);
  render();
}});
let drag = null;   // move columns / rows by dragging the ⠿ handle
const clearDrop = () => document.querySelectorAll('.dropL,.dropR,.dropT,.dropB').forEach(n => n.classList.remove('dropL', 'dropR', 'dropT', 'dropB'));
$('t').addEventListener('dragstart', e => {{ const d = e.target.dataset; if (!d.dc && !d.dr) return; grab();
  drag = d.dc ? {{k: 'cols', id: d.dc}} : {{k: 'rows', id: d.dr}}; e.dataTransfer.effectAllowed = 'move'; e.dataTransfer.setData('text/plain', 'x'); }});
function target(e) {{
  if (!drag) return null;
  if (drag.k === 'cols') {{ const th = e.target.closest('th[data-c]'); if (!th || th.dataset.c === 'label') return null;
    const b = th.getBoundingClientRect(); return {{n: th, id: th.dataset.c, after: e.clientX > b.left + b.width / 2}}; }}
  const tr = e.target.closest('tbody tr'); if (!tr) return null;
  const b = tr.getBoundingClientRect(); return {{n: tr, id: tr.dataset.r, after: e.clientY > b.top + b.height / 2}};
}}
$('t').addEventListener('dragover', e => {{ const t = target(e); if (!t) return; e.preventDefault(); clearDrop();
  (drag.k === 'cols' ? [t.n] : [...t.n.children]).forEach(n => n.classList.add(drag.k === 'cols' ? (t.after ? 'dropR' : 'dropL') : (t.after ? 'dropB' : 'dropT'))); }});
$('t').addEventListener('drop', e => {{ const t = target(e); clearDrop(); if (!t) return; e.preventDefault();
  const a = L[drag.k], item = a.find(x => x.id === drag.id); if (t.id === drag.id) return;
  a.splice(a.indexOf(item), 1); a.splice(a.findIndex(x => x.id === t.id) + (t.after ? 1 : 0), 0, item); drag = null; render(); }});
$('t').addEventListener('dragend', () => {{ drag = null; clearDrop(); }});
$('t').addEventListener('mousedown', e => {{   // resize: right edge of a header = column width, bottom edge of a row name = row height
  const d = e.target.dataset; if (d.rc === undefined && d.rr === undefined) return; e.preventDefault(); grab();
  const col = d.rc !== undefined, item = col ? L.cols[+d.rc] : L.rows[+d.rr], x0 = e.clientX, y0 = e.clientY;
  const el = col ? $('t').querySelectorAll('col')[+d.rc] : $('t').tBodies[0].rows[+d.rr];
  const start = col ? item.w : el.getBoundingClientRect().height;
  const mv = m => {{ if (col) {{ item.w = Math.max(50, Math.round(start + m.clientX - x0)); el.style.width = wd(item) + 'px';
      $('t').style.width = L.cols.reduce((s, c) => s + wd(c), 0) + 'px'; }}
    else {{ item.h = Math.max(24, Math.round(start + m.clientY - y0)); el.style.height = item.h + 'px'; }} }};
  const up = () => {{ removeEventListener('mousemove', mv); removeEventListener('mouseup', up); }};
  addEventListener('mousemove', mv); addEventListener('mouseup', up);
}});
$('refresh').onclick = async () => {{
  if (SITE) {{ window.open(ACT, '_blank'); return msg('On GitHub, tap Run workflow. This page updates about 10 minutes later.'); }}
  if (!served) return msg('Refresh needs the report helper. Run "Refresh Social Report" once, then use the report it opens.');
  const b = $('refresh'); b.disabled = true; b.textContent = 'Refreshing…'; msg('Pulling Instagram, Facebook, YouTube and TikTok (a few minutes). This page reloads when it’s done.');
  try {{ await fetch('/refresh', {{method: 'POST'}});
    while (true) {{ await new Promise(r => setTimeout(r, 3000)); const s = await (await fetch('/status')).json();
      if (!s.running) {{ if (!s.error) {{ location.reload(); return; }} msg(s.error); break; }} }} }}
  catch (e) {{ msg('Refresh failed: the report helper stopped. Run "Refresh Social Report" again.'); }}
  b.disabled = false; b.textContent = 'Refresh';
}};
function renderPrev() {{   // previous run's table, in the current layout's order (no editing)
  if (!OLD || !$('pt')) return; const P = OLD.table, pc = id => P.cols.find(c => c.id === id), pr = id => P.rows.find(r => r.id === id);
  const cols = L.cols.filter(c => !c.custom && pc(c.id)).map(c => pc(c.id)); P.cols.forEach(c => {{ if (!cols.includes(c)) cols.push(c); }});
  let rows = L.rows.filter(r => !r.custom && pr(r.id)).map(r => pr(r.id)); P.rows.forEach(r => {{ if (!rows.includes(r)) rows.push(r); }});
  rows = rows.filter(r => r.full || Object.values(r.cells || {{}}).some(v => v && v !== '?' && v !== '—'));   // skip metrics that check didn't have
  let h = '<thead><tr>' + cols.map(c => `<th class="${{c.id === 'label' ? 'rl' : ''}}">${{esc(c.label)}}</th>`).join('') + '</tr></thead><tbody>';
  rows.forEach(r => {{ h += `<tr class="${{r.full ? 'pick' : ''}}">`; let first = true;
    cols.forEach(c => {{ if (c.id === 'label') {{ h += `<th class="rl">${{esc(r.label)}}</th>`; return; }}
      if (r.full) {{ if (first) h += `<td colspan="${{cols.length - 1}}">${{r.full}}</td>`; first = false; return; }}
      h += `<td>${{(r.cells || {{}})[c.id] ?? ''}}</td>`; }}); h += '</tr>'; }});
  $('pt').innerHTML = h + '</tbody>';
}}
function renderM() {{   // phone view: one card per metric, sites in a 2x2 grid
  const m = $('m'); if (!m) return;
  const PC = {{instagram:'#E87BA4', facebook:'#2A78D6', youtube:'#E34948', tiktok:'#14B8C6', reddit:'#FF6A2A'}};
  const sp = s => {{ const t = String(s ?? '').replace(/<[^>]+>/g, ''); const i = t.indexOf(' ('); return i < 0 ? [t, ''] : [t.slice(0, i), t.slice(i + 1)]; }};
  const dl = d => d ? `<small class="${{/^\\(\\+[1-9]/.test(d) ? 'up' : ''}}">${{esc(d)}}</small>` : '';
  const sites = L.cols.filter(c => !c.custom && PC[c.id] && cid(c.id));
  let h = '';
  L.rows.forEach(r => {{ const d = r.custom ? null : rid(r.id); if (!d) return;
    if (d.full) {{ h += `<div class="mc"><div class="mh"><span class="ml">${{esc(d.label)}}</span></div><div class="mpick">${{d.full}}</div></div>`; return; }}
    const [tv, td] = sp(d.cells.total);
    h += `<div class="mc"><div class="mh"><span class="ml">${{esc(d.label)}}</span>${{tv && tv !== '—' ? `<span class="mt">${{esc(tv)}} ${{dl(td)}}</span>` : ''}}</div><div class="mg">`;
    sites.forEach(c => {{ const raw = d.cells[c.id]; const [v, dd] = sp(raw); if (!v || v === '—' || v === '?') return;
      const href = (raw || '').match(/href='([^']+)'/); const val = href ? `<a class="tp" href="${{href[1]}}" target="_blank" rel="noopener"><b>${{esc(v)}}</b></a>` : `<b>${{esc(v)}}</b>`;
      h += `<div class="mp${{/<b>/.test(raw || '') ? ' best' : ''}}"><span><i style="background:${{PC[c.id]}}"></i>${{esc(cid(c.id).label.replace(' (manual)', ''))}}</span><div>${{val}} ${{dl(dd)}}</div></div>`; }});
    h += '</div></div>';
  }});
  m.innerHTML = h;
}}

function renderG() {{   // Oct 26: Reach / Engagement / Retention cards, best cell highlighted, zero changes hidden, share-of-views bar
  const g = $('g'); if (!g) return;
  const PC = {{instagram:'#E87BA4', facebook:'#2A78D6', youtube:'#E34948', tiktok:'#14B8C6'}};
  const GS = {{instagram:'IG', facebook:'FB', youtube:'YT', tiktok:'TT'}};   // Guy, Oct 26: platform pills (short names on phones)
  const GR = [['Reach', '', ["Today's views", "Yesterday's views", "Total views", "Avg views per post", "Top post views", "Followers", "Posts"]],
              ['Engagement', 'per 1,000 views, so big and small sites compare fairly', ["Likes per 1K views", "Comments per 1K views"]],
              ['Retention', 'how long people keep watching', ["3-s views % of views", "Avg watch time (s)", "Watched % of video"]]];
  const sites = L.cols.filter(c => !c.custom && PC[c.id] && cid(c.id));
  const num = t => {{ const n = parseFloat(String(t).replace(/,/g, '')); return isNaN(n) ? null : n; }};
  const k = (t, sign, lim = 10000) => {{ const n = num(t); if (n == null || Math.abs(n) < lim) return esc(t);
    return `<span class="nf">${{esc(t)}}</span><span class="ns">${{sign || ''}}${{(Math.abs(n) / 1000).toFixed(1)}}K</span>`; }};
  const parse = raw => {{ raw = raw ?? ''; const t = String(raw).replace(/<[^>]+>/g, ''), i = t.indexOf(' (');
    const v = i < 0 ? t : t.slice(0, i), d = i < 0 ? '' : t.slice(i + 2, -1);
    return {{v, d: /^[+−-]0(\\.0)?$/.test(d) ? '' : d, best: /<b>/.test(raw), href: (String(raw).match(/href='([^']+)'/) || [])[1]}}; }};
  const show = x => {{ if (!x.v || x.v === '?' || x.v === '—') return '<span class="cv"><span class="na">–</span><small></small></span>';   // Guy, Oct 26: number right-aligned, change left-aligned in its own slot
    let h = k(x.v); if (x.href) h = `<a class="tp" href="${{x.href}}" target="_blank" rel="noopener">${{h}}</a>`;
    const s = x.d ? x.d[0] : '';
    return `<span class="cv"><span>${{h}}</span><small class="${{s === '+' ? 'up' : ''}}">${{x.d ? `(${{s}}${{k(x.d.slice(1), '', 1000)}})` : ''}}</small></span>`; }};
  const order = L.rows.filter(r => !r.custom).map(r => r.id);
  let h = '';
  GR.forEach(([name, sub, ids]) => {{
    const rows = ids.filter(id => rid(id))   // Guy, Oct 26: fixed order per card (Reach: Today, Yesterday, Total first)
      .filter(id => sites.some(c => {{ const v = parse(rid(id).cells[c.id]).v; return v && v !== '?' && v !== '—'; }}));
    const asc = name === 'Retention' && $('ascret') ? $('ascret').innerHTML : '';
    if (!rows.length && !asc) return;
    h += `<section class="card"><div class="gh"><h3>${{name}}</h3>${{sub ? `<span class="gs">${{sub}}</span>` : ''}}</div>`;
    const tv = rid('Total views');
    if (name === 'Reach' && tv) {{ const vals = sites.map(c => num(parse(tv.cells[c.id]).v) || 0), tot = vals.reduce((a, b) => a + b, 0);
      const ix = sites.map((c, i) => i).sort((a, b) => vals[b] - vals[a]);   // Guy, Oct 27: most to least
      if (tot) h += '<div class="shh">Share of total views</div><div class="sbar">' + ix.map(i => sites[i]).map((c, j, _, i = ix[j]) => `<i style="width:${{vals[i] / tot * 100}}%;background:${{PC[c.id]}}"></i>`).join('') +
        '</div><div class="sl">' + ix.map(i => sites[i]).map((c, j, _, i = ix[j]) => `<span><b style="background:${{PC[c.id]}}"></b>${{esc(cid(c.id).label)}} ${{Math.round(vals[i] / tot * 100)}}%</span>`).join('') + '</div>'; }}
    if (rows.length) h += '<table><thead><tr><th></th><th class="tl">Total</th>' + sites.map(c => `<th><span class="gp" style="background:${{PC[c.id]}}"><span class="nf">${{esc(cid(c.id).label)}}</span><span class="ns">${{GS[c.id] || ''}}</span></span></th>`).join('') + '</tr></thead><tbody>';
    rows.forEach(id => {{ const d = rid(id);
      const t = parse(d.cells.total);   // Guy, Oct 26: Total column first, divider after it
      h += `<tr data-r="${{esc(id)}}" data-g="${{name}}"><td class="lab">${{esc(d.label)}}</td><td class="tot tl">${{show(t)}}</td>` + sites.map(c => {{ const x = parse(d.cells[c.id]); return `<td class="${{x.best ? 'best' : ''}}">${{show(x)}}</td>`; }}).join('');
      h += '</tr>'; }});
    if (rows.length) h += '</tbody></table>';
    h += asc + '</section>';
  }});
  const pk = rid('Pick for ads'); if (pk && pk.full) h += `<p class="gpick">Pick for ads: ${{pk.full}}</p>`;
  g.innerHTML = h;
  // Guy, Oct 26: hover a row = pop-up with that metric split by site (share bar for counts, side-by-side bars for rates)
  let tip = document.querySelector('.rtt'); if (!tip) {{ tip = document.createElement('div'); tip.className = 'ctt rtt'; tip.style.position = 'fixed'; document.body.appendChild(tip); }}
  const fill = tr => {{ const d = rid(tr.dataset.r); if (!d) return false;
    const vals = sites.map(c => num(parse(d.cells[c.id]).v)), ok = vals.map(v => v != null && v >= 0), tot = vals.reduce((a, v, i) => a + (ok[i] ? v : 0), 0);
    if (!tot) return false;
    const share = tr.dataset.g === 'Reach' && !/^Avg|^Top/.test(d.label), mx = Math.max(...vals.filter((v, i) => ok[i]));
    const ord = sites.map((c, i) => i).filter(i => ok[i]).sort((a, b) => vals[b] - vals[a]);   // Guy, Oct 27: most to least
    let h = `<div class="ctt-h">${{esc(d.label)}}</div>`;
    if (share) h += '<div class="rtt-bar">' + ord.map(i => vals[i] ? `<i style="width:${{vals[i] / tot * 100}}%;background:${{PC[sites[i].id]}}"></i>` : '').join('') + '</div>';
    ord.forEach(i => {{ const c = sites[i], v = parse(d.cells[c.id]).v;
      h += `<div class="ctt-r ${{share ? 'rs' : 'rb'}}"><i style="background:${{PC[c.id]}}"></i><span class="rtt-n">${{esc(cid(c.id).label)}}</span>` + (share ? `<b>${{esc(v)}}</b><small>${{Math.round(vals[i] / tot * 100)}}%</small>` : `<span class="rtt-m"><em style="width:${{mx ? vals[i] / mx * 100 : 0}}%;background:${{PC[c.id]}}"></em></span><b>${{esc(v)}}</b>`) + '</div>'; }});
    tip.innerHTML = h; return true; }};
  const place = e => {{ const w = tip.offsetWidth, hh = tip.offsetHeight; let x = e.clientX + 16, y = e.clientY + 16;
    if (x + w > innerWidth - 8) x = e.clientX - w - 16; if (y + hh > innerHeight - 8) y = e.clientY - hh - 16; tip.style.left = Math.max(8, x) + 'px'; tip.style.top = Math.max(8, y) + 'px'; }};
  g.querySelectorAll('tr[data-r]').forEach(tr => {{
    tr.addEventListener('mouseenter', e => {{ if (fill(tr)) {{ tip.style.opacity = 1; place(e); }} }});
    tr.addEventListener('mousemove', place);
    tr.addEventListener('mouseleave', () => {{ tip.style.opacity = 0; }}); }});
}}
if (/^#sec-/.test(location.hash)) history.replaceState(null, '', location.pathname + location.search);   // Guy, Oct 26: a reload opens at the top, not at an old jump target
if ('scrollRestoration' in history) history.scrollRestoration = 'manual'; scrollTo(0, 0);
L = load(SAVED); render(); renderPrev(); renderM(); renderG();
(() => {{   // Guy, Oct 26: views gained since this browser last opened the report (kept per device)
  const el = $('slv'); if (!el) return; const tot = +el.dataset.total, stamp = el.dataset.stamp || document.title; let v = null;
  try {{ v = JSON.parse(localStorage.getItem('bl_lastview') || 'null'); }} catch (e) {{}}
  // same report reloaded: keep the earlier baseline; new report: the last report seen becomes the baseline
  const base = v ? (v.stamp === stamp ? v.base : {{total: v.total, at: v.at}}) : null;
  if (base && base.total != null) {{ const d = tot - base.total, t = new Date(base.at);
    const when = t.toDateString() === new Date().toDateString() ? t.toLocaleTimeString([], {{hour: 'numeric', minute: '2-digit'}}) : t.toLocaleDateString([], {{weekday: 'short'}}) + ' ' + t.toLocaleTimeString([], {{hour: 'numeric', minute: '2-digit'}});
    el.textContent = `(${{d >= 0 ? '+' : '−'}}${{Math.abs(d).toLocaleString()}} since you last looked, ${{when}})`; }}
  try {{ localStorage.setItem('bl_lastview', JSON.stringify({{stamp, total: tot, at: v && v.stamp === stamp ? v.at : Date.now(), base: base}})); }} catch (e) {{}}
}})();
document.querySelectorAll('h2.sh, h2.ph').forEach(h => {{ if (/Views gained per day/.test(h.textContent)) return;   // Guy, Oct 26: Top button right of each section title
  h.classList.add('has-top'); h.insertAdjacentHTML('beforeend', '<button type="button" class="b gray totop">Top</button>'); }});
document.addEventListener('click', e => {{ if (e.target.closest('.totop')) scrollTo({{top: 0, behavior: 'smooth'}}); }});
document.addEventListener('click', e => {{ const j = e.target.closest('a.jump'); if (!j) return;   // Guy, Oct 26: land below the pinned day card
  const t = document.querySelector(j.getAttribute('href')); if (!t) return; e.preventDefault();
  const pin = document.querySelector('.day'), off = (pin ? pin.offsetHeight + 8 : 0) + 14;
  scrollTo({{top: t.getBoundingClientRect().top + scrollY - off, behavior: 'smooth'}}); }});
const moreBtn = $('more'); if (moreBtn) moreBtn.onclick = () => {{ document.body.classList.toggle('showold'); moreBtn.textContent = document.body.classList.contains('showold') ? 'Hide older videos' : moreBtn.dataset.t; }}; if (moreBtn) moreBtn.dataset.t = moreBtn.textContent;
if (SITE) $('edit').hidden = true;
if (served && !SITE) fetch('/layout').then(r => r.json()).then(l => {{ if (!editing && JSON.stringify(l) !== JSON.stringify(SAVED)) {{ L = load(l); render(); renderPrev(); renderM(); renderG(); }} }}).catch(() => {{}});
</script>
<script src="https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.1/chart.umd.js"></script>
<script>
const D = {data};
const dark = matchMedia('(prefers-color-scheme: dark)').matches, grid = dark ? '#2c2c2a' : '#e1e0d9', muted = '#898781';
const C = {{Instagram:['#E87BA4','circle',[6,4]], Facebook:['#2A78D6','rect',[]], YouTube:['#E34948','triangle',[]], TikTok:['#14B8C6','circle',[]]}};
const fmt = v => Math.round(v).toLocaleString(), sg = v => (v < 0 ? '−' : '+') + fmt(Math.abs(v));
const prevVal = (d, i) => {{ for(let j = i - 1; j >= 0; j--) if(d[j] != null) return [d[j], j]; return [null, -1]; }};
function mk(canvas, D) {{ if (!canvas) return;
 if (false) {{   // phones: was a hard cut to 8 days; the range slider now picks the window (Guy, Oct 27)
   const k = D.labels.length - 8, cut = a => a ? a.slice(k) : a;
   D = Object.assign({{}}, D, {{labels: cut(D.labels), installs: cut(D.installs), earned: cut(D.earned), spend: cut(D.spend), est: (D.est || []).map(i => i - k).filter(i => i >= 0), earnPart: (D.earnPart || []).map(i => i - k).filter(i => i >= 0),
     series: Object.fromEntries(Object.entries(D.series).map(([n, s]) => [n, cut(s)]))}}); }}
 const EST = new Set(D.est || []), EP = new Set(D.earnPart || []); const O = {{v:0}};   // window offset (range slider)
 const TT = ({{chart: ch, tooltip: t}}) => {{   // HTML pop-up: frosted glass, bigger type, views then installs / earned / spend
   let el = ch.canvas.parentNode.querySelector('.ctt');
   if (!el) {{ el = document.createElement('div'); el.className = 'ctt'; ch.canvas.parentNode.style.position = 'relative'; ch.canvas.parentNode.appendChild(el); }}
   if (!t.opacity) {{ el.style.opacity = 0; return; }}
   const rows = t.dataPoints.map((p, i) => ({{v: p.dataset.stack === 'v', c: t.labelColors[i].backgroundColor, txt: t.body[i].lines.join(' ')}}));
   let h = `<div class="ctt-h">${{t.title.join(' ')}}</div>`, sep = false;
   rows.forEach(r => {{ if (!r.v && !sep && rows.some(x => x.v)) {{ h += '<div class="ctt-sep"></div>'; sep = true; }} h += `<div class="ctt-r"><i style="background:${{r.c}}"></i>${{r.txt}}</div>`; }});
   el.innerHTML = h; el.style.opacity = 1;
   const W = ch.canvas.parentNode.clientWidth, w = el.offsetWidth, hh = el.offsetHeight;
   let x = t.caretX + 16; if (x + w > W) x = t.caretX - w - 16; if (x < 0) x = Math.max(0, (W - w) / 2);
   let y = Math.max(0, Math.min(t.caretY - hh / 2, ch.canvas.clientHeight - hh));
   el.style.left = x + 'px'; el.style.top = y + 'px'; }};
 const LASTV = Object.keys(D.series).length - 1;   // index of the last view dataset (views are added first)
 const TTR = c => c.dataset.stack === 'v' ? c.datasetIndex : ({{Installs:100, Earned:101}}[c.dataset.label] ?? 102);   // tooltip: views first, then installs, earned, ad spend
 const SEP = {{id:'ttsep', afterTooltipDraw(ch, args) {{ const t = args.tooltip; if (!t.opacity) return; const o = t.options, H = Chart.helpers, pad = H.toPadding(o.padding);
   const k = t.dataPoints.filter(p => p.dataset.stack === 'v').length; if (!k || k === t.dataPoints.length) return;
   const tf = H.toFont(o.titleFont), bf = H.toFont(o.bodyFont), nt = t.title.length;
   let y = t.y + pad.top + nt*tf.lineHeight + Math.max(0, nt - 1)*o.titleSpacing + o.titleMarginBottom + k*(Math.max(bf.lineHeight, o.boxHeight || bf.size) + o.bodySpacing) - o.bodySpacing + bf.lineHeight/2;
   const x = ch.ctx; x.save(); x.strokeStyle = 'rgba(255,255,255,.75)'; x.lineWidth = 1; x.beginPath(); x.moveTo(t.x + pad.left, Math.round(y) + .5); x.lineTo(t.x + t.width - pad.right, Math.round(y) + .5); x.stroke(); x.restore(); }}}};
 const chart = new Chart(canvas, {{type:'bar',
 data:{{labels:D.labels, datasets:Object.entries(D.series).map(([n, d]) => ({{label:n, data:d.map(v => v == null ? v : Math.max(0, v)), backgroundColor:C[n][0], borderRadius:3, maxBarThickness:34, stack:'v', barPercentage:0.95, order:2}}))
   .concat(D.spend ? [{{label:'Google Ads', data:D.spend, backgroundColor:'#C9A227', borderRadius:3, maxBarThickness:17, stack:'s', barPercentage:0.475, yAxisID:D.installs ? 'y2' : 'y4', order:3}}] : [])
   .concat(D.installs ? [{{type:'line', label:'Installs', data:D.installs, borderColor:'#7B4FD6', backgroundColor:c => EST.has(c.dataIndex + O.v) ? '#fff' : '#7B4FD6', pointBorderWidth:2, yAxisID:'y2', pointRadius:c => EST.has(c.dataIndex + O.v) ? 4 : 3, segment:{{borderDash:c => EST.has(c.p1DataIndex + O.v) ? [4,3] : undefined}}, borderWidth:2, tension:0.2, spanGaps:true, order:1}}] : [])
   .concat(D.earned ? [{{type:'line', label:'Earned', data:D.earned, borderColor:'#1E9E55', backgroundColor:c => EP.has(c.dataIndex + O.v) ? '#fff' : '#1E9E55', pointBorderWidth:2, yAxisID:'y3', pointRadius:c => EP.has(c.dataIndex + O.v) ? 4 : 3, pointStyle:'rectRot', borderWidth:2, segment:{{borderDash:c => EP.has(c.p1DataIndex + O.v) ? [4,3] : undefined}}, tension:0.2, spanGaps:true, order:0}}] : [])}},
 options:{{responsive:true, maintainAspectRatio:false, interaction:{{mode:'index', intersect:false}},
  plugins:{{legend:{{display:false}}, tooltip:{{enabled:false, external:TT, itemSort:(a, b) => TTR(a) - TTR(b), callbacks:{{
   labelColor: c => ({{borderColor:'rgba(0,0,0,0)', backgroundColor: c.dataset.type === 'line' ? c.dataset.borderColor : c.dataset.backgroundColor, borderWidth:1, borderRadius:2}}),
   title: it => {{ const t = it.filter(c => c.dataset.type !== 'line' && c.dataset.stack !== 's').reduce((s, c) => s + (c.parsed.y || 0), 0); return it[0].label + ' · ' + sg(t) + ' views'; }},
   label: c => c.dataset.stack === 's' ? 'Google Ads spend: $' + (c.parsed.y || 0).toFixed(2) : c.dataset.label === 'Earned' ? 'Earned: $' + c.parsed.y.toFixed(2) + (EP.has(c.dataIndex + O.v) ? ' (Ads only)' : '') : c.dataset.type === 'line' ? 'Installs: ' + (EST.has(c.dataIndex + O.v) ? '~' : '') + fmt(c.parsed.y) + (EST.has(c.dataIndex + O.v) ? ' (estimate)' : '') : c.dataset.label + ': ' + sg(c.parsed.y) }}}}}},
  scales:{{x:{{stacked:true, grid:{{display:false}}, ticks:{{color:muted, maxRotation:0, autoSkip:false, font:{{size:12}}, callback(v) {{ return this.getLabelForValue(v).split(' ')[0]; }}}}}}, y:{{stacked:true, beginAtZero:true, min:0, grid:{{color:grid}}, ticks:{{color:muted, callback:v => v.toLocaleString()}}, title:{{display:true, text:'Views gained', color:muted}}}},
   ...(D.installs ? {{y2:{{position:'right', beginAtZero:true, grid:{{display:false}}, ticks:{{color:'#7B4FD6', precision:0}}, title:{{display:true, text:'Installs', color:'#7B4FD6'}}}}}} : {{}}),
   ...(D.earned ? {{y3:{{display:false, beginAtZero:true}}}} : {{}}),
   ...(D.spend && !D.installs ? {{y4:{{display:false, beginAtZero:true, stacked:false}}}} : {{}})}}}}}}); 
 rangeSlider(chart, D, O); 
 const hide = () => {{ if (chart.tooltip.getActiveElements().length) {{ chart.tooltip.setActiveElements([], {{x:0, y:0}}); chart.setActiveElements([]); chart.update('none'); }} const el = canvas.parentNode.querySelector('.ctt'); if (el) el.style.opacity = 0; }};   // phones: no mouse-out, so tap outside the chart or scroll to close the pop-up
 document.addEventListener('touchstart', ev => {{ if (ev.target !== canvas) hide(); }}, {{passive:true}});
 addEventListener('scroll', hide, {{passive:true}}); }}
function rangeSlider(chart, D, O) {{   // Guy, Oct 27: drag the blue window to look further back
 const n = D.labels.length, win = matchMedia('(max-width:700px)').matches ? 8 : 14, box = document.getElementById('rng'); if (!box || n <= win) return;
 box.hidden = false; document.getElementById('rngl').hidden = false;
 const w = box.querySelector('.rng-w'), cv = box.querySelector('.rng-c'), lab = document.getElementById('rngl').children;
 const tot = D.labels.map((_, i) => Object.values(D.series).reduce((s, a) => s + Math.max(0, a[i] || 0), 0)), mx = Math.max(1, ...tot);
 const draw = () => {{ const r = devicePixelRatio || 1, W = box.clientWidth, H = box.clientHeight; cv.width = W * r; cv.height = H * r; const x = cv.getContext('2d'); x.scale(r, r);
   const bw = W / n; x.fillStyle = dark ? 'rgba(255,255,255,.22)' : 'rgba(0,0,0,.16)'; tot.forEach((v, i) => {{ const h = Math.max(1, (H - 8) * v / mx); x.fillRect(i * bw + bw * .2, H - 4 - h, bw * .6, h); }}); }};
 let s = n - win;
 const set = (v, upd) => {{ s = Math.max(0, Math.min(n - win, Math.round(v))); w.style.left = (100 * s / n) + '%'; w.style.width = (100 * win / n) + '%';
   lab[0].textContent = D.labels[s]; lab[1].textContent = D.labels[s + win - 1];
   O.v = s; chart.data.labels = D.labels.slice(s, s + win); chart.data.datasets.forEach((d, i) => d.data = FULL[i].slice(s, s + win)); chart.stop(); chart.update('none'); }};
 const FULL = chart.data.datasets.map(d => d.data.slice());
 Object.entries(chart.scales).forEach(([id, sc]) => {{ if (id !== 'x') chart.options.scales[id].max = sc.max; }});   // Guy, Oct 27: lock every axis to the full 30 days so sliding never rescales
 set(s, true); draw(); addEventListener('resize', draw);
 let x0 = null, s0 = 0;
 box.addEventListener('pointerdown', e => {{ box.setPointerCapture(e.pointerId); const bw = box.clientWidth / n;
   if (e.target.closest('.rng-w')) {{ x0 = e.clientX; s0 = s; box.classList.add('drag'); }}
   else set((e.clientX - box.getBoundingClientRect().left) / bw - win / 2, true); }});
 box.addEventListener('pointermove', e => {{ if (x0 == null) return; const ns = Math.round(s0 + (e.clientX - x0) / (box.clientWidth / n)); if (ns !== s) set(ns, true); }});
 const up = () => {{ x0 = null; box.classList.remove('drag'); }}; box.addEventListener('pointerup', up); box.addEventListener('pointercancel', up); }}
mk(document.getElementById('c'), D);
</script></body></html>"""
    open(OUT_HTML, "w").write(doc)
    return {"stamp": stamp, "table": {"cols": cols, "rows": trows}, "legend": legend,
            "data": {"labels": labels, "series": {NAME[p]: series[p] for p in PLAT}}}


def write_xlsx(stamp, rows, labels, series):
    from openpyxl import Workbook
    from openpyxl.chart import LineChart, Reference
    from openpyxl.styles import Font
    wb = Workbook()
    ws = wb.active
    ws.title = "Report"
    f = lambda **k: Font(name="Aptos", **k)
    ws.append([stamp] + [NAME[p] for p in PLAT] + ["Reddit (manual)", "Total", "Best for ads"])
    for c in ws[1]:
        c.font = f(bold=True)
    for r in rows:
        line = [r["label"]] + [fmt(r["vals"][p]) + delta(r["vals"][p], r["olds"][p]) for p in PLAT]
        line += ["—" if r["label"] in ("Followers", "Avg views per post") else fmt(r["reddit"]),
                 fmt(r["total"]) + delta(r["total"], r["ototal"]), " / ".join(r["best"])]
        ws.append(line)
        for j, p in enumerate(PLAT, start=2):
            if r["vals"][p] is not None and r["vals"][p] == r["top"] and r["top"]:
                ws.cell(ws.max_row, j).font = f(bold=True)
    for col, w in zip("ABCDEFGH", (22, 16, 16, 16, 16, 18, 16, 26)):
        ws.column_dimensions[col].width = w
    d = wb.create_sheet("Daily views")
    d.append(["Day"] + [NAME[p] for p in PLAT])
    for i, lab in enumerate(labels):
        d.append([lab] + [series[p][i] for p in PLAT])
    ch = LineChart()
    ch.title, ch.y_axis.title, ch.height, ch.width = "Total views by platform, last 7 days", "Total views", 10, 20
    ch.add_data(Reference(d, min_col=2, max_col=5, min_row=1, max_row=8), titles_from_data=True)
    ch.set_categories(Reference(d, min_col=1, min_row=2, max_row=8))
    for s, p in zip(ch.series, PLAT):
        s.graphicalProperties.line.solidFill = COLOR[p][1:]
        s.graphicalProperties.line.width = 25400
        if p == "instagram":
            s.graphicalProperties.line.dashStyle = "dash"
    ch.display_blanks = "span"
    ch.x_axis.delete = ch.y_axis.delete = False
    d.add_chart(ch, "G2")
    try:
        wb.save(OUT_XLSX)
    except PermissionError:
        print("Close 'Social Report.xlsx' in Excel to update it (the HTML report was still written).")


def main():
    now = dt.datetime.now()
    stamp = now.strftime("%b %-d, %Y · %-I:%M %p")
    snap, errors = fetch()
    hist = json.load(open(HIST)) if os.path.exists(HIST) else []
    prev = hist[-1] if hist else None
    stale = {}   # platform -> time of the last good check whose numbers are reused
    for p in PLAT:
        if p not in snap:
            last = next((h for h in reversed(hist) if isinstance(h.get(p), dict)), None)
            if last:
                snap[p] = dict(last[p], top_url="")
                stale[p] = dt.datetime.strptime(last["checked_at"], "%Y-%m-%d %H:%M").strftime("%b %-d, %-I:%M %p")
    rd = None   # Reddit tracking paused (Guy, Oct 22); reddit() still works if we bring it back
    rows = build_rows(snap, prev, rd)
    labels, series = gains(hist, snap, now, 30); source = "history file"   # Guy, Oct 27: 30 days; slider shows 14 at a time
    yv = {q: (series.get(q) or [None, None])[-2] for q in PLAT}      # yesterday's bar in the chart
    yo = {q: (series.get(q) or [None, None, None])[-3] if len(series.get(q) or []) >= 3 else None for q in PLAT}   # the day before
    if all(v is not None for v in yv.values()):   # Guy, Oct 23: views gained yesterday, (+/-) vs the day before
        ytop = max(yv.values())
        rows.insert(1, {"label": "Yesterday's views", "vals": yv, "olds": yo, "top": ytop,
                        "best": [NAME[q] for q in PLAT if yv[q] == ytop], "total": sum(yv.values()),
                        "ototal": sum(yo.values()) if all(v is not None for v in yo.values()) else None, "reddit": None})
    tv = {q: (series.get(q) or [None])[-1] for q in PLAT}   # today's bar in the chart (so far); (+N) = since the last check
    if all(v is not None for v in tv.values()):   # Guy, Oct 24
        to = {q: (tv[q] - ((snap.get(q) or {}).get("views", 0) - ((prev or {}).get(q) or {}).get("views", (snap.get(q) or {}).get("views", 0)))) if prev else None for q in PLAT}
        ttop = max(tv.values())
        rows.insert(1, {"label": "Today's views", "vals": tv, "olds": to, "top": ttop,
                        "best": [NAME[q] for q in PLAT if tv[q] == ttop], "total": sum(tv.values()),
                        "ototal": sum(to.values()) if all(v is not None for v in to.values()) else None, "reddit": None})
    labels[-1] += " (so far)"
    complete = len(snap) == len(PLAT) and not stale   # only record complete checks, so the next deltas stay honest
    if complete:
        entry = {"checked_at": now.strftime("%Y-%m-%d %H:%M"), "source": "social_report.py"}
        entry.update({p: {k: v for k, v in snap[p].items() if k != "top_url"} for p in PLAT})
        hist.append(entry)
    before = hist[:-1] if complete else hist   # history before this run
    PICK_CTX.update(hist=before, now=now)
    day = day_change(snap, before, now)
    today = today_change(snap, before, now)
    old = None
    if day:   # rebuild the comparison check's table + chart from history
        key = day["since"].strftime("%Y-%m-%d %H:%M")
        i = next((n for n, h in enumerate(before) if h["checked_at"] == key), None)
        if i is not None:
            bsnap = {p: dict(before[i][p], top_url="") for p in PLAT}
            bprev = next((h for h in reversed(before[:i]) if all(isinstance(h.get(p), dict) for p in PLAT)), None)
            blabels, bser = gains(before[:i + 1], None, day["since"])
            blabels[-1] += f" (to {day['since'].strftime('%-I:%M %p')})"
            old = write_html(day["since"].strftime("%b %-d, %Y · %-I:%M %p"), build_rows(bsnap, bprev, rd), rd, bsnap, bprev,
                             blabels, bser, "history file", [], (), None, None, None, dry=True)
    phist = json.load(open(POSTS_HIST)) if os.path.exists(POSTS_HIST) else []
    posts_html = time_section(POSTS, now) + posts_section(POSTS, phist, now)
    if complete and POSTS:
        phist.append({"checked_at": now.strftime("%Y-%m-%d %H:%M"), "posts": {r["id"]: r["views"] for r in POSTS}})
        json.dump(phist, open(POSTS_HIST, "w"))
    week_html = week_box(snap, before, POSTS, phist[:-1] if (complete and POSTS) else phist, INSTALLS, now)
    write_html(stamp, rows, rd, snap, prev, labels, series, source, errors, hist, stale, day, old, posts_html=posts_html,
               week_html=week_html, installs=dict(INSTALLS) or None, today=today,
               day_base=next((h for h in before if day and h["checked_at"] == day["since"].strftime("%Y-%m-%d %H:%M")), None),
               money=money_bits(dict(MONEY), now), money_daily=dict(MONEY), est=dl_estimate(dict(INSTALLS), dict(RCNEW), now))
    if not SITE:
        write_xlsx(stamp, rows, labels, series)
    if complete:
        json.dump(hist, open(HIST, "w"), indent=2)
    for x in errors:
        print("ERROR", x)
    print("Saved:", OUT_HTML)
    if "--no-open" not in sys.argv:
        import report_server   # local helper behind the Refresh / Save Layout buttons
        url = report_server.URL if report_server.ensure_running() else "file://" + OUT_HTML
        if os.system(f"open -a 'Google Chrome' '{url}'") != 0:
            webbrowser.open(url)


if __name__ == "__main__":
    main()
