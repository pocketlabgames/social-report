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
LAST = os.path.join(HERE, "cache", "report-last.json")   # the previous run's table + chart, shown at the bottom (one run only, not a history)
SITE = os.environ.get("REPORT_SITE") == "1"   # GitHub Actions build for the website (no local helper, no xlsx)
ACTIONS = "https://github.com/pocketlabgames/social-report/actions/workflows/report.yml"
PLAT = ["instagram", "facebook", "youtube", "tiktok"]
NAME = {"instagram": "Instagram", "facebook": "Facebook", "youtube": "YouTube", "tiktok": "TikTok"}
IG_HANDLE = "beakerlab.game"
COLOR = {"instagram": "#E87BA4", "facebook": "#2A78D6", "youtube": "#E34948", "tiktok": "#14B8C6"}


def fetch():
    from sources import meta, tiktok, youtube
    out, errors = {}, []
    import re, time
    for m in (youtube, meta, tiktok):
        for attempt in range(1, 4):   # up to 3 tries (e.g. YouTube Analytics 500s are usually temporary)
            try:
                for k, (df, _) in m.fetch(KEYS, dt.date.today()).items():
                    out[k] = df
                break
            except Exception as e:
                if attempt == 3:
                    msg = re.sub(r"(token|key|secret)=[^&\s'\"]+", r"\1=***", f"{type(e).__name__}: {e}", flags=re.I)   # never show keys
                    errors.append(f"{m.__name__.split('.')[-1]} (3 tries): {msg}"[:200])
                else:
                    time.sleep(10 * attempt)
    snap = {}

    def posts(name, likes):
        d = out.get(name)
        if d is None or d.empty:
            return None
        return {"posts": len(d), "views": int(d.views.fillna(0).sum()), "top_views": int(d.views.fillna(0).max()),
                "likes": int(d[likes].fillna(0).sum()) if likes in d else None,
                "comments": int(d.comments.fillna(0).sum()) if "comments" in d else None,
                "top_url": d.sort_values("views").iloc[-1].get("url", "")}

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
    """How many comments (top-level + replies) on our videos were written by our own channel. Read-only."""
    from sources import youtube
    from googleapiclient.discovery import build
    yt = build("youtube", "v3", credentials=youtube._creds(KEYS), cache_discovery=False)
    me = yt.channels().list(part="id", mine=True).execute()["items"][0]["id"]
    n = 0
    for vid in video_ids:
        tok = None
        while True:
            try:
                r = yt.commentThreads().list(part="snippet,replies", videoId=vid, maxResults=100, pageToken=tok).execute()
            except Exception:
                break   # comments off / not public yet
            for t in r.get("items", []):
                top = t["snippet"]["topLevelComment"]["snippet"]
                n += (top.get("authorChannelId") or {}).get("value") == me
                n += sum((x["snippet"].get("authorChannelId") or {}).get("value") == me for x in (t.get("replies") or {}).get("comments", []))
            tok = r.get("nextPageToken")
            if not tok:
                break
    return n


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
            "likes": int(ups.sum()) if ups.notna().any() else None,
            "comments": int(com.sum()) if com.notna().any() else None}


def avg(p, s):
    if not s:
        return None
    if p == "youtube":
        return round(s["public_views"] / s["public_posts"]) if s.get("public_posts") else None
    return round(s["views"] / s["posts"]) if s.get("posts") else None


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
    return "?" if v is None else f"{v:,.0f}"


def delta(v, old):
    if v is None or old is None or isinstance(v, str) or isinstance(old, str):
        return ""
    d = v - old
    return f" ({'+' if d >= 0 else '−'}{abs(d):,.0f})"


def build_rows(snap, prev, rd):
    metrics = [("Followers", "followers"), ("Posts", "posts"), ("Total views", "views"), ("Avg views per post", "avg"),
               ("Top post views", "top_views"), ("Likes / upvotes", "likes"), ("Comments", "comments")]
    rows = []
    for label, key in metrics:
        vals, olds = {}, {}
        for p in PLAT:
            s, o = snap.get(p), prev.get(p) if prev else None
            vals[p] = avg(p, s) if key == "avg" else (s or {}).get(key)
            olds[p] = avg(p, o) if key == "avg" else (o or {}).get(key)
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
        rkey = {"avg": None, "followers": None}.get(key, key)
        rv = None if not rd or rkey is None else rd.get(rkey)
        rows.append({"label": label, "vals": vals, "olds": olds, "top": top, "best": best, "total": tot, "ototal": otot, "reddit": rv})
    return rows


def pick(snap):
    v = {p: (snap.get(p) or {}).get("views") or 0 for p in PLAT}
    t = {p: (snap.get(p) or {}).get("top_views") or 0 for p in PLAT}
    score = {p: sorted(v.values()).index(v[p]) + sorted(t.values()).index(t[p]) for p in PLAT}
    top2 = sorted(PLAT, key=lambda p: -score[p])[:2]
    return "Instagram + Facebook (one Meta ad covers both)" if set(top2) == {"instagram", "facebook"} else NAME[top2[0]]


def history_html(hist):
    """Every complete check in social-stats-history.json, newest first (shown under Previous results)."""
    rows = [h for h in hist if all(isinstance(h.get(p), dict) for p in PLAT)]
    f = lambda v: "—" if v is None else f"{v:,}"
    def d(v, o):
        if v is None or o is None or v == o: return ""
        return f" <span class='dl'>({'+' if v > o else '−'}{abs(v - o):,})</span>"
    out, prev = [], None
    for h in rows:
        v = {p: h[p].get("views") for p in PLAT}
        tot = sum(x or 0 for x in v.values())
        fol = sum(h[p].get("followers") or 0 for p in PLAT)
        lik = sum(h[p].get("likes") or 0 for p in PLAT)
        when = dt.datetime.strptime(h["checked_at"], "%Y-%m-%d %H:%M").strftime("%a %b %-d · %-I:%M %p")
        pv = prev or {}
        cells = "".join(f"<td class='hs'>{f(v[p])}{d(v[p], pv.get('v', {}).get(p))}</td>" for p in PLAT)
        out.append(f"<tr><th class='rl'>{when}</th>{cells}<td><b>{f(tot)}</b>{d(tot, pv.get('tot'))}</td>"
                   f"<td>{f(fol)}{d(fol, pv.get('fol'))}</td><td class='hs'>{f(lik)}{d(lik, pv.get('lik'))}</td></tr>")
        prev = {"v": v, "tot": tot, "fol": fol, "lik": lik}
    if not rows:
        return ""
    head = "".join(f"<th class='hs'>{NAME[p]}</th>" for p in PLAT)
    return (f"<h2 class='ph'>History</h2><p class='sub'>Every check since {html.escape(rows[0]['checked_at'][:10])} "
            f"({len(rows)} checks), newest first. Views per site; changes in brackets are since the check below.</p>"
            f"<div class='wrap hist'><table><thead><tr><th class='rl'>Checked</th>{head}<th>Total views</th><th>Followers</th><th class='hs'>Likes</th></tr></thead>"
            f"<tbody>{''.join(reversed(out))}</tbody></table></div>")


def write_html(stamp, rows, rd, snap, prev, labels, series, source, errors, hist=(), stale=None):
    e = html.escape
    old = json.load(open(LAST)) if os.path.exists(LAST) else None
    cols = [{"id": "label", "label": stamp}] + [{"id": p, "label": NAME[p]} for p in PLAT] + [
        {"id": "reddit", "label": "Reddit (manual)"}, {"id": "total", "label": "Total"}, {"id": "best", "label": "Best for ads"}]
    trows = []
    for r in rows:
        cells = {}
        for p in PLAT:
            v = r["vals"][p]
            txt = e(fmt(v) + delta(v, r["olds"][p]))
            cells[p] = "<b>" + txt + "</b>" if v is not None and v == r["top"] and r["top"] else txt
        cells["reddit"] = "—" if r["label"] in ("Followers", "Avg views per post") else fmt(r["reddit"])
        cells["total"] = e(fmt(r["total"]) + delta(r["total"], r["ototal"]))
        cells["best"] = e(" / ".join(r["best"]))
        trows.append({"id": r["label"], "label": r["label"], "cells": cells})
    trows.append({"id": "Pick for ads", "label": "Pick for ads", "full": f"<b>{e(pick(snap))}</b>"})
    table = json.dumps({"cols": cols, "rows": trows}).replace("</", "<\\/")
    layout = open(LAYOUT).read().replace("</", "<\\/") if os.path.exists(LAYOUT) else "null"
    rnote = (f"Reddit is entered by hand (Reddit hides views from its API): {rd['posts']} live post(s), {rd['removed']} removed, "
             f"last reading {rd['as_of']}, {rd['unknown_views']} post(s) without a view count yet.") if rd else "No Reddit rows yet."
    tops = sorted(((snap[p]["top_views"], snap[p].get("top_url", ""), NAME[p]) for p in PLAT if snap.get(p)), reverse=True)
    top_line = f"Most popular post: {tops[0][2]}, {tops[0][0]:,} views: <a href='{e(tops[0][1])}'>{e(tops[0][1])}</a>" if tops else ""
    legend = "".join(
        f"<span class='lg'><svg width='22' height='10'><line x1='0' y1='5' x2='22' y2='5' stroke='{COLOR[p]}' stroke-width='2'"
        f"{' stroke-dasharray=\"4 3\"' if p == 'instagram' else ''}/></svg>{NAME[p]} {fmt((snap.get(p) or {}).get('views'))}"
        f"{delta((snap.get(p) or {}).get('views'), (prev.get(p) or {}).get('views') if prev else None) or ''}</span>" for p in PLAT)
    data = json.dumps({"labels": labels, "series": {NAME[p]: series[p] for p in PLAT}})
    olds = json.dumps(old).replace("</", "<\\/") if old else "null"
    prev_html = (f"""<h2 class="ph">Previous results</h2><p class="sub">{e(old['stamp'])}</p>
<div class="wrap ptw"><table id="pt"></table></div>
<div class="lgs">{old['legend']}</div>
<div class="chart"><canvas id="pc" role="img" aria-label="Previous report: running total views per platform"></canvas></div>""") if old else ""
    stale = stale or {}
    stale_html = "".join(f"<p class='warn'>{NAME[p]} couldn’t be pulled after 3 tries, so its numbers are from the last good check ({e(t)}).</p>" for p, t in stale.items())
    if len(snap) == len(PLAT) and not stale:   # this run becomes "Previous results" in the next report
        os.makedirs(os.path.dirname(LAST), exist_ok=True)
        json.dump({"stamp": stamp, "table": {"cols": cols, "rows": trows}, "legend": legend,
                   "data": {"labels": labels, "series": {NAME[p]: series[p] for p in PLAT}}}, open(LAST, "w"))
    err = "".join(f"<li>{e(x)}</li>" for x in errors)
    doc = f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Beaker Lab Social Report</title>
<link rel="icon" type="image/svg+xml" href="data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 64 64'><rect width='64' height='64' rx='14' fill='%232A78D6'/><g fill='%23fff' opacity='.35'><rect x='12' y='40' width='8' height='12' rx='2'/><rect x='25' y='32' width='8' height='20' rx='2'/><rect x='38' y='26' width='8' height='26' rx='2'/></g><polyline points='12,42 25,34 36,38 51,18' fill='none' stroke='%23fff' stroke-width='5' stroke-linecap='round' stroke-linejoin='round'/><polyline points='42,17 52,16 51,26' fill='none' stroke='%23fff' stroke-width='5' stroke-linecap='round' stroke-linejoin='round'/></svg>">
<style>
:root{{--bg:#fcfcfb;--ink:#0b0b0b;--ink2:#52514e;--muted:#898781;--line:#e1e0d9;--card:#fff}}
@media (prefers-color-scheme: dark){{:root{{--bg:#1a1a19;--ink:#f0efec;--ink2:#c3c2b7;--muted:#898781;--line:#2c2c2a;--card:#222220}}}}
body{{margin:0;background:var(--bg);color:var(--ink);font-family:Aptos,-apple-system,"Helvetica Neue",system-ui,sans-serif;font-size:15px}}
main{{max-width:1100px;margin:0 auto;padding:24px 16px}}
h1{{font-size:22px;font-weight:500;margin:0 0 4px}} .sub{{color:var(--muted);margin:0 0 20px}}
.wrap{{overflow-x:auto}} table{{border-collapse:collapse;width:100%;background:var(--card)}}
th,td{{border-bottom:1px solid var(--line);padding:8px 10px;text-align:right;white-space:nowrap;font-variant-numeric:tabular-nums}}
th{{font-weight:500;color:var(--ink2)}} th.rl{{text-align:left}} thead th{{border-bottom:1px solid var(--muted)}}
#m{{display:none}} .mc{{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:12px 14px;margin:0 0 10px}}
.mh{{display:flex;justify-content:space-between;align-items:baseline;gap:8px;margin-bottom:8px}} .ml{{font-weight:600;font-size:16px}}
.mt{{font-size:19px;font-weight:600;font-variant-numeric:tabular-nums}} .mg{{display:grid;grid-template-columns:1fr 1fr;gap:8px}}
.mp{{display:flex;flex-direction:column;gap:2px;padding:6px 9px;border-radius:8px;background:var(--bg)}} .mp span{{font-size:12px;color:var(--muted);display:flex;align-items:center;gap:5px}}
.mp i{{width:8px;height:8px;border-radius:50%;display:inline-block}} .mp b{{font-size:17px;font-weight:600;font-variant-numeric:tabular-nums}} .mp.best{{box-shadow:inset 0 0 0 2px #2A78D6;background:rgba(42,120,214,.14)}} .mp.best span{{color:var(--ink2)}}
.mc small,.mp small{{color:var(--muted);font-size:12px;font-weight:400}} .mc small.up{{color:#1E9E55}} .mpick{{font-size:17px}}
@media (max-width:700px){{main{{padding:16px 14px}} h1{{font-size:24px}} .sub{{font-size:14px}} .tw,.ptw,#edit{{display:none}} #m{{display:block}} .hs{{display:none}} .hist th,.hist td{{padding:8px 6px}} .chart{{height:260px}} .note{{font-size:12px}} .lgs{{gap:10px 16px}} h2.ph{{margin-top:32px}}}}
tr.pick td{{text-align:left}} .warn{{margin:0 0 10px;padding:8px 12px;border-radius:8px;background:#FFF4CC;color:#5c4a00;font-size:14px}} .hist td,.hist th{{color:var(--ink2);font-size:14px}} .dl{{color:var(--muted);font-size:12px}} b{{font-weight:600}}
.lgs{{display:flex;flex-wrap:wrap;gap:16px;margin:28px 0 8px;font-size:12px;color:var(--ink2)}} .lg{{display:flex;align-items:center;gap:6px}}
.chart{{position:relative;height:340px}}
.bar{{display:flex;flex-wrap:wrap;align-items:center;gap:8px;margin:0 0 14px}} #tools{{display:inline-flex;flex-wrap:wrap;gap:8px}} #tools[hidden]{{display:none}}
.b{{border:0;border-radius:8px;padding:8px 14px;font:inherit;font-weight:600;color:#fff;cursor:pointer}} .b:disabled{{opacity:.6;cursor:default}}
.red{{background:#D93A36}} .blue{{background:#2A78D6}} .green{{background:#1E9E55}} .gray{{background:#77756f}}
select{{font:inherit;padding:7px 8px;border-radius:8px;border:1px solid var(--line);background:var(--card);color:var(--ink)}}
table.fixed{{table-layout:fixed;width:auto}} table.fixed th,table.fixed td{{overflow:hidden;text-overflow:ellipsis}}
table.edit th,table.edit td{{position:relative;outline:1px dashed var(--line)}}
.h{{cursor:grab;color:var(--muted);margin-right:6px;user-select:none}} .x{{cursor:pointer;color:#D93A36;margin-left:6px;font-weight:600;user-select:none}}
.rz{{position:absolute;top:0;right:-3px;width:7px;height:100%;cursor:col-resize;z-index:2}} .rzr{{position:absolute;left:0;bottom:-3px;height:7px;width:100%;cursor:row-resize;z-index:2}}
.ed{{outline:none;min-width:30px;display:inline-block}} table.edit .ed{{background:rgba(42,120,214,.08)}}
h2.ph{{font-size:18px;font-weight:500;margin:48px 0 4px;padding-top:20px;border-top:1px solid var(--line)}} #pt th,#pt td{{color:var(--ink2)}}
.dropL{{box-shadow:inset 3px 0 0 #2A78D6}} .dropR{{box-shadow:inset -3px 0 0 #2A78D6}} .dropT{{box-shadow:inset 0 3px 0 #2A78D6}} .dropB{{box-shadow:inset 0 -3px 0 #2A78D6}} ul{{color:var(--ink2)}} .note{{color:var(--muted);font-size:13px}} a{{color:#2A78D6}}
</style></head><body><main>
<h1>Beaker Lab social report</h1><p class="sub">{e(stamp)} · changes in brackets are since the last check ({e(prev.get('checked_at', 'none') if prev else 'none')})</p>
<div class="bar"><button id="refresh" class="b red">Refresh</button><button id="edit" class="b blue">Edit Layout</button>
<span id="tools" hidden><select id="addc"></select><select id="addr"></select><button id="cancel" class="b gray">Cancel</button><button id="reset" class="b gray">Reset Layout</button></span>
<span id="msg" class="note"></span></div>
{stale_html}<div class="wrap tw"><table id="t"></table></div><div id="m"></div>
<p class="note">YouTube average uses public posts only. Facebook comments = viewer comments (the Page's own link comments are left out). Comments = viewer comments only (our own replies and pinned comments are left out). Total excludes Reddit. {e(rnote)}</p>
<div class="lgs">{legend}</div>
<div class="chart"><canvas id="c" role="img" aria-label="Running total views per platform, last 7 days"></canvas></div>
<p class="note">Daily history from the {e(source)}; the last point is this run's live totals.</p>
<p>{top_line}</p>
{('<ul>' + err + '</ul>') if err else ''}
{prev_html}
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
  T.rows.forEach(r => {{ if (!known.has('r:' + r.id) && !n.rows.some(x => x.id === r.id)) n.rows.push({{id: r.id}}); }});
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
  editing = on; $('tools').hidden = !on;
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
  try {{ const r = await fetch('/layout', {{method: 'POST', body}}); if (!r.ok) throw 0; setEdit(false); msg('Layout saved. Future reports will use it.'); }}
  catch (e) {{ msg('Save failed: the report helper isn’t running. Run "Refresh Social Report" once, then try again.'); }}
}};
$('cancel').onclick = () => {{ L = JSON.parse(backup); setEdit(false); msg(''); }};
$('reset').onclick = async () => {{
  if (!confirm('Go back to the default layout for this and all future reports?')) return;
  if (served) try {{ await fetch('/layout', {{method: 'DELETE'}}); }} catch (e) {{}}
  L = load(null); setEdit(false); msg('Layout reset to default.');
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
  const rows = L.rows.filter(r => !r.custom && pr(r.id)).map(r => pr(r.id)); P.rows.forEach(r => {{ if (!rows.includes(r)) rows.push(r); }});
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
      h += `<div class="mp${{/<b>/.test(raw || '') ? ' best' : ''}}"><span><i style="background:${{PC[c.id]}}"></i>${{esc(cid(c.id).label.replace(' (manual)', ''))}}</span><div><b>${{esc(v)}}</b> ${{dl(dd)}}</div></div>`; }});
    h += '</div></div>';
  }});
  m.innerHTML = h;
}}
L = load(SAVED); render(); renderPrev(); renderM();
if (SITE) $('edit').hidden = true;
if (served && !SITE) fetch('/layout').then(r => r.json()).then(l => {{ if (!editing && JSON.stringify(l) !== JSON.stringify(SAVED)) {{ L = load(l); render(); renderPrev(); renderM(); }} }}).catch(() => {{}});
</script>
<script src="https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.1/chart.umd.js"></script>
<script>
const D = {data};
const dark = matchMedia('(prefers-color-scheme: dark)').matches, grid = dark ? '#2c2c2a' : '#e1e0d9', muted = '#898781';
const C = {{Instagram:['#E87BA4','circle',[6,4]], Facebook:['#2A78D6','rect',[]], YouTube:['#E34948','triangle',[]], TikTok:['#14B8C6','circle',[]]}};
const fmt = v => Math.round(v).toLocaleString(), sg = v => (v < 0 ? '−' : '+') + fmt(Math.abs(v));
const prevVal = (d, i) => {{ for(let j = i - 1; j >= 0; j--) if(d[j] != null) return [d[j], j]; return [null, -1]; }};
function mk(canvas, D) {{ if (!canvas) return; const chart = new Chart(canvas, {{type:'line',
 data:{{labels:D.labels, datasets:Object.entries(D.series).map(([n, d]) => ({{label:n, data:d, borderColor:C[n][0], backgroundColor:C[n][0], pointStyle:C[n][1], borderDash:C[n][2], borderWidth:2, pointRadius:4, pointHoverRadius:6, tension:0, spanGaps:true, borderCapStyle:'round'}}))}},
 options:{{responsive:true, maintainAspectRatio:false, interaction:{{mode:'index', intersect:false}},
  plugins:{{legend:{{display:false}}, tooltip:{{callbacks:{{
   title: it => {{ const t = it.reduce((s, c) => s + (c.parsed.y || 0), 0); return it[0].label + ' · Total ' + fmt(t) + (it.length < 4 ? ' (missing: ' + Object.keys(D.series).filter(n => !it.some(c => c.dataset.label === n)).join(', ') + ')' : ''); }},
   beforeBody: it => {{ const i = it[0].dataIndex; if(i === 0) return 'First day shown'; let g = 0, n = 0; chart.data.datasets.forEach(d => {{ const a = d.data[i], b = d.data[i-1]; if(a != null && b != null){{ g += a - b; n++; }} }}); return '(' + sg(g) + ') vs ' + chart.data.labels[i-1] + (n < 4 ? ' (sites with data both days)' : ''); }},
   label: c => {{ const i = c.dataIndex; let s = c.dataset.label + ': ' + fmt(c.parsed.y); if(i === 0) return s; const [p, j] = prevVal(c.dataset.data, i); if(p == null) return s; return s + ' (' + sg(c.parsed.y - p) + ')' + (j < i - 1 ? ' since ' + chart.data.labels[j] : ''); }} }}}}}},
  scales:{{x:{{grid:{{display:false}}, ticks:{{color:muted}}}}, y:{{beginAtZero:true, grid:{{color:grid}}, ticks:{{color:muted, callback:v => v.toLocaleString()}}, title:{{display:true, text:'Total views', color:muted}}}}}}}}}}); }}
mk(document.getElementById('c'), D); if (OLD) mk(document.getElementById('pc'), OLD.data);
</script></body></html>"""
    open(OUT_HTML, "w").write(doc)


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
    rd = reddit()
    rows = build_rows(snap, prev, rd)
    labels, series, source = daily(now.strftime("%-I:%M %p"), snap)
    complete = len(snap) == len(PLAT) and not stale   # only record complete checks, so the next deltas stay honest
    if complete:
        entry = {"checked_at": now.strftime("%Y-%m-%d %H:%M"), "source": "social_report.py"}
        entry.update({p: {k: v for k, v in snap[p].items() if k != "top_url"} for p in PLAT})
        hist.append(entry)
    write_html(stamp, rows, rd, snap, prev, labels, series, source, errors, hist, stale)
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
