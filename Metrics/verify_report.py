"""Guy, Nov 6: independent data check, run on every report build. It reads the numbers off the finished page, pulls them again
straight from the source with its own queries, and puts a red banner at the top of the report when they disagree. If it can't
run or can't find a number on the page, that is a failure too: it never passes by default.
Allowed gaps: 1 player on counts that include today (players arrive between the two pulls), 10 cents on money. Days older than yesterday must match exactly.
Guy, Nov 7: Firebase keeps processing yesterday, and its answers flip from pull to pull (wins 376, 382, 376; rewarded ads 69, 64), so event counts that include yesterday or today get wobble(): 10%, at least 2. Purchases stay exact.
Not compared with a second source: Instagram, Facebook and TikTok views (only failed pulls and falling totals are caught), Google/Meta ad spend, ratings values."""
import csv
import datetime as dt
import gzip
import html
import io
import json
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor

import jwt
import requests
from google.auth.transport.requests import AuthorizedSession, Request
from google.oauth2.credentials import Credentials

from sources import money_lite

PROPERTY = "558070583"
APP_ID = "6816478290"
LAUNCH = dt.date(2026, 9, 26)
START = dt.date(2026, 11, 1)


def wobble(n):
    """Allowed gap on event counts Firebase is still processing: 10%, at least 2."""
    return max(2, n * 0.10)


class Checks:
    def __init__(self):
        self.ok, self.fails = 0, []

    def same(self, name, shown, source, gap=0):
        if shown is None:
            self.fails.append(f"{name}: not found on the page (source says {source})")
        elif abs(shown - source) > gap + 1e-9:
            self.fails.append(f"{name}: report shows {shown:,}, source says {source:,}")
        else:
            self.ok += 1

    def true(self, name, good, why=""):
        if good:
            self.ok += 1
        else:
            self.fails.append(f"{name}{': ' + why if why else ''}")


def _num(pattern, page, cast=float):
    m = re.search(pattern, page)
    return cast(m.group(1).replace(",", "")) if m else None


def _sales(keys):
    """Every day since launch straight from Apple: {date: rows}; days Apple hasn't posted are left out."""
    c = json.load(open(os.path.join(keys, "asc-metrics.json")))
    now = int(time.time())
    tok = jwt.encode({"iss": c["issuer_id"], "iat": now, "exp": now + 1100, "aud": "appstoreconnect-v1"}, open(os.path.join(keys, c["key_file"])).read(), algorithm="ES256", headers={"kid": c["key_id"], "typ": "JWT"})
    head = {"Authorization": "Bearer " + tok}

    def one(d):
        for _ in range(3):
            r = requests.get("https://api.appstoreconnect.apple.com/v1/salesReports", headers=head, timeout=60,
                             params={"filter[frequency]": "DAILY", "filter[reportType]": "SALES", "filter[reportSubType]": "SUMMARY", "filter[vendorNumber]": c["vendor_number"], "filter[reportDate]": d, "filter[version]": "1_1"})
            if r.status_code == 404:
                return d, None
            if r.ok:
                return d, list(csv.DictReader(io.StringIO(gzip.decompress(r.content).decode()), delimiter="\t"))
            time.sleep(3)
        raise RuntimeError(f"Apple sales report {d}: {r.status_code}")
    today = dt.date.today()
    days = [(LAUNCH + dt.timedelta(days=i)).isoformat() for i in range((today - LAUNCH).days)]
    with ThreadPoolExecutor(6) as ex:
        sales = dict(ex.map(one, days))
    versions = requests.get(f"https://api.appstoreconnect.apple.com/v1/apps/{APP_ID}/appStoreVersions", headers=head, timeout=30, params={"filter[platform]": "IOS", "filter[appStoreState]": "READY_FOR_SALE", "limit": 20, "fields[appStoreVersions]": "versionString"})
    versions.raise_for_status()
    return {d: r for d, r in sales.items() if r is not None}, [x["attributes"]["versionString"] for x in versions.json()["data"]]


def _ver(v):
    try:
        return tuple(int(x) for x in v.split("."))
    except ValueError:
        return ()


def _check_store(C, page, keys, today):
    sales, on_sale = _sales(keys)
    first = {"1", "1F", "1T"}
    per = {d: int(sum(float(x["Units"] or 0) for x in rows if x["Product Type Identifier"] in first)) for d, rows in sales.items()}
    ds = sorted(per)
    y = (today - dt.timedelta(days=1)).isoformat()
    C.same("Total downloads", _num(r"([\d,]+)(?:<span class='ns'>.*?</span>)? <small><span class='nf'>total downloads", page, int), sum(per.values()))
    C.same("Installs, last 7 days Apple has posted", _num(r"<b>([\d,]+)</b> last 7 days", page, int), sum(per[d] for d in ds[-7:]))
    C.same("Installs this month", _num(r"last 7 days · <b>([\d,]+)</b> in ", page, int), sum(per[d] for d in ds if d[:7] == today.strftime("%Y-%m")))
    C.same("Installs since launch", _num(r"<b>([\d,]+)</b> total since launch", page, int), sum(per.values()))
    if y in per:
        C.same("Installs yesterday", _num(r"<b>([\d,]+)</b> yesterday · <b>[\d,]+</b> last 7", page, int), per[y])
    countries = {x["Country Code"] for rows in sales.values() for x in rows if x["Product Type Identifier"] in first and float(x["Units"] or 0) > 0}
    C.same("Countries", _num(r"([\d,]+) <small>countries</small>", page, int), len(countries))
    # money: every currency, not only US dollars
    ads = money_lite._admob(keys, LAUNCH, today)
    iap = {}
    for d, rows in sales.items():
        v = 0.0
        for x in rows:
            if x["Product Type Identifier"] in money_lite.IAP_TYPES and float(x["Developer Proceeds"] or 0):
                v += float(x["Units"] or 0) * float(x["Developer Proceeds"]) * money_lite.usd_rate(x["Currency of Proceeds"], d)
        iap[d] = v
    both = lambda ds: sum(ads.get(d, 0) + iap.get(d, 0) for d in ds)
    td = today.isoformat()
    month = [d for d in set(ads) | set(iap) if d[:7] == today.strftime("%Y-%m")]
    week = [(today - dt.timedelta(days=i)).isoformat() for i in range(7)]
    for name, pat, val in (("Earned today", r"Earned: <b>\$([\d,.]+)</b> today", both([td])), ("Earned yesterday", r"today · <b>\$([\d,.]+)</b> yesterday · <b>\$", both([y])),
                           ("Earned last 7 days", r"yesterday · <b>\$([\d,.]+)</b> last 7 days · <b>\$", both(week)), ("Earned this month", r"last 7 days · <b>\$([\d,.]+)</b> in ", both(month)),
                           ("Earned from ads this month", r"\(ads \$([\d,.]+) \+ App Store", sum(ads.get(d, 0) for d in month)), ("Earned from App Store this month", r"App Store \$([\d,.]+)\)", sum(iap.get(d, 0) for d in month))):
        C.same(name, _num(pat, page), round(val, 2), 0.10)
    return on_sale


def _check_game(C, page, keys, today, G, on_sale):
    creds = Credentials.from_authorized_user_file(os.path.join(keys, "ga4-token.json"), ["https://www.googleapis.com/auth/analytics.readonly"])
    if not creds.valid:
        creds.refresh(Request())
    s = AuthorizedSession(creds)

    def run(dates, dims=(), metrics=("activeUsers",), flt=None):
        body = {"dateRanges": [{"startDate": dates[0].isoformat(), "endDate": dates[1].isoformat()}], "dimensions": [{"name": d} for d in dims], "metrics": [{"name": m} for m in metrics], "limit": 2000}
        if flt:
            body["dimensionFilter"] = flt
        r = s.post(f"https://analyticsdata.googleapis.com/v1beta/properties/{PROPERTY}:runReport", json=body, timeout=60)
        r.raise_for_status()
        return [([x["value"] for x in row.get("dimensionValues", [])], [float(x["value"]) for x in row["metricValues"]]) for row in r.json().get("rows", [])]

    one = lambda *a, **k: int(next(iter(run(*a, **k)), ([], [0]))[1][0])
    has = lambda f, v: {"filter": {"fieldName": f, "stringFilter": {"value": v}}}
    among = lambda f, vs: {"filter": {"fieldName": f, "inListFilter": {"values": list(vs)}}}
    AND = lambda *x: {"andGroup": {"expressions": list(x)}}
    # the version the report calls live must be what App Store Connect has on sale, and nothing on sale may be missing
    newest = max(map(_ver, on_sale))
    C.true("Live version", _ver(G.get("live", "")) == newest, f"report uses {G.get('live')}, App Store Connect has {'.'.join(map(str, newest))} on sale")
    seen = [r[0][0] for r in run((START, today), ["appVersion"])]
    want = sorted((v for v in seen if (1, 3, 1) <= _ver(v) <= newest), key=_ver)
    C.true("Versions counted", sorted(G.get("versions", []), key=_ver) == want, f"report counts {G.get('versions')}, should be {want}")
    rel = {v: dt.date.fromisoformat(d) for v, d in G["released"].items()}

    def released_only(a, b, versions=None):
        """Only days on or after each version's release: test devices before that don't count."""
        out = []
        for v in versions or want:
            r = max(rel[v], a)
            if r <= b:
                out.append(AND(has("appVersion", v), among("date", [(r + dt.timedelta(days=i)).strftime("%Y%m%d") for i in range((b - r).days + 1)])))
        return {"orGroup": {"expressions": out}}

    d7 = (max(today - dt.timedelta(days=7), START), max(today - dt.timedelta(days=1), START))
    wk = released_only(*d7)
    ev = {r[0][0]: int(r[1][0]) for r in run(d7, ["eventName"], ["eventCount"], wk)}
    players = one(d7, flt=wk)
    outcome = {r[0][0]: int(r[1][0]) for r in run(d7, ["customEvent:outcome"], ["eventCount"], AND(wk, has("eventName", "level_end"))) if r[0][0] != "(not set)"}
    kind = {r[0][0]: int(r[1][0]) for r in run(d7, ["customEvent:kind"], ["eventCount"], AND(wk, has("eventName", "ad_shown"))) if r[0][0] != "(not set)"}
    tiles = {html.unescape(l): (html.unescape(v), html.unescape(n)) for v, l, n in re.findall(r"<div class='gt'><b>(.*?)</b><span>(.*?)</span><small>(.*?)</small></div>", page)}
    tile = lambda l: tiles.get(l, ("", ""))
    n1 = lambda text, pat: _num(pat, text, int)
    wins, tries = outcome.get("win", 0), sum(outcome.values())
    C.same("Win rate: wins", n1(tile("Win rate")[1], r"([\d,]+) wins"), wins, wobble(wins))
    C.same("Win rate: attempts", n1(tile("Win rate")[1], r"of ([\d,]+) level"), tries, wobble(tries))
    C.same("Win rate", n1(tile("Win rate")[0], r"(\d+)%"), round(wins / tries * 100) if tries else 0, 2)
    C.same("Super Stir uses", n1(tile("Super Stir / Solve uses")[1], r"([\d,]+) Super Stir"), ev.get("super_stir", 0), wobble(ev.get("super_stir", 0)))
    C.same("Super Solve uses", n1(tile("Super Stir / Solve uses")[1], r"([\d,]+) Super Solve"), ev.get("super_solve", 0), wobble(ev.get("super_solve", 0)))
    C.same("Purchases", n1(tile("Purchases")[0], r"([\d,]+)"), ev.get("purchase_ok", 0))
    C.same("Players, last 7 days", n1(tile("Purchases")[1], r"by ([\d,]+) player"), players, 1)
    C.same("Ad views per player", _num(r"([\d.]+)", tile("Ad views per player")[0]), round(ev.get("ad_shown", 0) / players, 1) if players else 0, 0.3)
    C.same("Rewarded ads", n1(tile("Ad views per player")[1], r"([\d,]+) rewarded"), kind.get("rewarded", 0), wobble(kind.get("rewarded", 0)))
    C.same("Ads between levels", n1(tile("Ad views per player")[1], r"([\d,]+) between levels"), kind.get("interstitial", 0), wobble(kind.get("interstitial", 0)))
    C.same("Active players, last 7 days", n1(tile("Active players")[0], r"([\d,]+)"), one((today - dt.timedelta(days=6), today)), 1)
    C.same("Active players today", n1(tile("Active players")[1], r"([\d,]+) today"), one((today, today)), 1)
    C.same("Active players since launch", n1(tile("Active players")[1], r"([\d,]+) since launch"), one((dt.date(2026, 1, 1), today)), 1)
    # levels
    everyone = released_only(START, today)
    levels = sorted(int(r[0][0]) for r in run((START, today), ["customUser:max_level"], flt=everyone) if r[0][0].isdigit())

    def reach_of(lv, flt, dates):
        return one(dates, flt=AND(flt, among("customUser:max_level", [str(x) for x in levels if x >= lv])))
    with ThreadPoolExecutor(5) as ex:
        by = dict(zip(levels, ex.map(lambda lv: reach_of(lv, everyone, (START, today)), levels)))
    top = by[levels[0]] if levels else 0
    avg = sum(lv * (by[lv] - (by[levels[i + 1]] if i + 1 < len(levels) else 0)) for i, lv in enumerate(levels)) / top if top else 0
    half = max((lv for lv in levels if by[lv] * 2 >= top), default=0)
    C.same("Avg furthest level", _num(r"([\d.]+)", tile("Avg furthest level")[0]), round(avg, 1), 0.5)
    C.same("All players on the level chart", n1(tile("Avg furthest level")[1], r"half of ([\d,]+) player"), top, 1)
    C.same("Half of players reached level", n1(tile("Avg furthest level")[1], r"reached level (\d+)\+"), half, 1)
    m = re.search(r"window\.GAMECHART = \(\) => \{ const X = (\{.*?\}); if \(!window\.Chart\)", page, re.S)
    C.true("Level chart data found on the page", bool(m))
    if not m:
        return
    X = json.loads(m.group(1))
    recent = released_only(today - dt.timedelta(days=2), today)
    for i, st in enumerate(X["steps"]):
        C.same(f"Reached level {st}", X["reach"][i], next((by[k] for k in levels if k >= st), 0), 1)
        C.same(f"Still playing at level {st}", X["playing"][i], min(reach_of(st, recent, (today - dt.timedelta(days=2), today)), X["reach"][i]), 1)
        C.true(f"Level {st} bar adds up", X["playing"][i] <= X["reach"][i] and (i == 0 or X["reach"][i] <= X["reach"][i - 1]))
    # players per day chart
    daily = {r[0][0]: int(r[1][0]) for r in run((START, today), ["date"])}
    newer = {r[0][0]: int(r[1][0]) for r in run((START, today), ["date"], flt=everyone)}
    day_ev = {(r[0][0], r[0][1]): int(r[1][0]) for r in run((START, today), ["date", "eventName"], ["eventCount"], everyone)}
    for i, lab in enumerate(X["labels"]):
        d = dt.datetime.strptime(f"{lab} {today.year}", "%b %d %Y").date()
        k, gap, recent_day = d.strftime("%Y%m%d"), (1 if d >= today - dt.timedelta(days=1) else 0), d >= today - dt.timedelta(days=1)
        C.same(f"Players on {lab}", X["players"][i], daily.get(k, 0), gap)
        C.same(f"Players on released versions, {lab}", X["newer"][i], newer.get(k, 0), gap)
        for e in ("purchase_ok", "super_solve", "super_stir", "ad_shown", "level_up", "level_end"):
            C.same(f"{e} on {lab}", X[e][i], day_ev.get((k, e), 0), 0 if e == "purchase_ok" and d < today else wobble(day_ev.get((k, e), 0)) if recent_day else 0)
    # new-version comparison
    if X.get("cver") and (G.get("compare") or {}).get("since"):
        since, ver = dt.date.fromisoformat(G["compare"]["since"]), _ver(X["cver"])
        dates = lambda a, b: [(a + dt.timedelta(days=i)).strftime("%Y%m%d") for i in range((b - a).days + 1)]
        new = AND(released_only(START, today, [v for v in want if _ver(v) >= ver]), among("firstSessionDate", dates(since, today)))
        old = AND(released_only(START, today, [v for v in want if _ver(v) < ver]), among("firstSessionDate", dates(START, since - dt.timedelta(days=1))))
        C.same("New players on the new version", X["cn"], reach_of(1, new, (START, today)), 1)
        C.same("New players before the new version", X["co"], reach_of(1, old, (START, today)), 1)
    # retention (the same way Firebase's cohorts define it)
    a, b = today - dt.timedelta(days=8), today - dt.timedelta(days=2)
    body = {"dimensions": [{"name": "cohort"}, {"name": "cohortNthDay"}], "metrics": [{"name": "cohortActiveUsers"}], "cohortSpec": {"cohortsRange": {"granularity": "DAILY", "startOffset": 0, "endOffset": 1},
            "cohorts": [{"name": str(i), "dimension": "firstSessionDate", "dateRange": {"startDate": (a + dt.timedelta(days=i)).isoformat(), "endDate": (a + dt.timedelta(days=i)).isoformat()}} for i in range((b - a).days + 1)]}}
    rows = s.post(f"https://analyticsdata.googleapis.com/v1beta/properties/{PROPERTY}:runReport", json=body, timeout=60).json().get("rows", [])
    base = sum(int(r["metricValues"][0]["value"]) for r in rows if int(r["dimensionValues"][1]["value"]) == 0)
    back = sum(int(r["metricValues"][0]["value"]) for r in rows if int(r["dimensionValues"][1]["value"]) == 1)
    C.same("Day-1 retention", _num(r"(\d+)% <small><span class='nf'>day-1 retention", page), round(back / base * 100) if base else 0, 1)


def _check_views(C, page, snap, prev, stale, errors, plats):
    C.true("Every source pulled", not errors, "; ".join(errors)[:300])
    C.true("No site showing old numbers", not stale, ", ".join(stale))
    C.same("Total views", _num(r"([\d,]+) <small><span class='nf'>total views", page, int), sum((snap.get(p) or {}).get("views") or 0 for p in plats))
    for p in plats:
        now, was = (snap.get(p) or {}).get("views"), ((prev or {}).get(p) or {}).get("views")
        C.true(f"{p} views present", now is not None)
        if now is not None and was:
            C.true(f"{p} views didn't fall", now >= was * 0.99, f"{was:,} at the last check, {now:,} now")


def run(html_path, keys, G, snap, prev, stale, errors, plats, today=None):
    """Compares the finished page with the sources. Returns the Checks; the page is not changed."""
    today = today or dt.date.today()
    page = open(html_path, encoding="utf-8").read()
    C = Checks()
    for name, step in (("Views", lambda: _check_views(C, page, snap, prev, stale, errors, plats)), ("App Store, downloads and money", lambda: C.__setattr__("on_sale", _check_store(C, page, keys, today))),
                       ("Game stats", lambda: _check_game(C, page, keys, today, G, C.on_sale))):
        try:
            step()
        except Exception as e:
            msg = re.sub(r"(token|key|secret)=[^&\s'\"]+", r"\1=***", f"{type(e).__name__}: {e}", flags=re.I)
            C.fails.append(f"{name} check could not run: {msg}"[:240])
    # Guy, Nov 7: the data check is a build step, not part of the report; results go to the build log only, nothing on the page
    return C
