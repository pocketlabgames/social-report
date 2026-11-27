"""Firebase / Google Analytics 4 game stats for the social report (Guy, Nov 2): players, furthest level, win rate, ads,
Super Stir / Super Solve and purchases. Only released builds count (1.3.1 up to the App Store's live version, from Nov 1). Only builds 1.3.1+ send these events (save 167 mirrors the game's TelemetryDeck
events to Firebase); custom dimensions level / outcome / kind / placement / max_level / has_everything exist from Nov 2.
Key: Private Keys/ga4-token.json (same as ga4_lite). Property: beaker-lab (558070583)."""
import datetime as dt
import json
import os
import threading
import time

import jwt
import pandas as pd
import requests
from google.auth.transport.requests import AuthorizedSession, Request
from google.oauth2.credentials import Credentials

PROPERTY = "558070583"
SCOPES = ["https://www.googleapis.com/auth/analytics.readonly"]
FIRST = (1, 3, 1)   # first app version that sends the game events
START = dt.date(2026, 11, 1)   # 1.3.1 went live Nov 1; earlier days were test devices only (Guy, Nov 2)
APP_ID = "6816478290"
QUIT_DAYS = 9   # Guy, Nov 23: "Quit is 9+ days ago" (was 3): still playing = played today or in the 8 days before
RELFILE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "released-days.json")   # Apple release day of each version, saved while it is live
STEPS = list(range(1, 11)) + [11, 16, 21, 26, 31]   # Guy, Nov 6: "Where players stop" bars: levels 1-10 one by one, then steps of 5, then 31+
RELEASED = {"1.3.1": START, "1.3.2": dt.date(2026, 11, 4), "1.3.3": dt.date(2026, 11, 6), "1.3.11": dt.date(2026, 11, 15), "1.3.18": dt.date(2026, 11, 20), "1.3.19": dt.date(2026, 11, 21), "1.3.20": dt.date(2026, 11, 21)}   # App Store release days; later versions use Apple's date while live
VF = (1, 3, 11)   # Guy, Nov 16: Game stats filter "1.3.11+"
VF_TO = (1, 3, 17)   # Guy, Nov 22: "1.3.11 to 1.3.17" (only the newest option keeps the +)
VX = [((1, 3, 18), (1, 3, 23), "1.3.18 to 1.3.23"), ((1, 4, 0), (1, 4, 2), "1.4.0 to 1.4.2"), ((1, 5, 0), None, None)]   # Guy, Nov 26: "Build a 1.5.0+ section into game analytics wherever it needs it"; 1.4.0+ became 1.4.0 to 1.4.2
   # Guy, Nov 24: 1.3.18 to 1.3.23 grouped, new 1.4.0+ (was 1.3.18/19 and 1.3.20+, Nov 22); only an open-ended option has a +; each option shows once that version is on the App Store (vers stops at the live version), until then "vxnext" lists its label for the Day-1 chart
QS_FROM = dt.date(2026, 11, 25)   # Guy, Nov 24: "track the quiet start update made today" (live config, done Nov 24 10:13 AM ET). "why isn't it showing the 3 new players": Nov 24 counts from 10:13 AM (Google's clock here is UTC-4, so hour 11+; nobody first opened 11:00-11:12), today so far included
QS_OLDER = (dt.date(2026, 11, 15), dt.date(2026, 11, 23))   # Guy, Nov 25: "add the version before" = 1.3.11 to 1.3.17, the same first days as its tiles
QS_BEFORE = (dt.date(2026, 11, 21), dt.date(2026, 11, 23))   # before = new players on 1.3.20+ on these first days
COMPARE = (1, 3, 20)   # Guy, Nov 21: "Did 1.3.20+ help?" vs 1.3.11+ (1.3.11 to 1.3.19); Nov 20 was 1.3.18; was 1.3.11 vs before.
BASE = (1, 3, 11)   # reference line: new players who started on BASE..COMPARE-1, from BASE's release to the day before COMPARE's
# Guy, Nov 16: "Did 1.3.11 help?" (was 1.3.4); first version with the new-player changes; new players on it vs new players before it
EVENTS = ["level_end", "level_up", "ad_shown", "purchase_ok", "super_stir", "super_solve"]


NO_CT = {"andGroup": {"expressions": [{"notExpression": {"filter": {"fieldName": "region", "stringFilter": {"value": "Connecticut"}}}}, {"notExpression": {"filter": {"fieldName": "region", "stringFilter": {"value": "California"}}}},   # Guy, Nov 25 2026 "yes, for now": California left out (looks like Apple review devices on normal models; 15 started level 1, 3 won, Nov 19-25)
                                     
                                      {"notExpression": {"filter": {"fieldName": "deviceModel", "stringFilter": {"matchType": "BEGINS_WITH", "value": "iPhone99,"}}}},   # Guy, Nov 24 "remove test devices": Apple test devices (model not sold)
                                      {"notExpression": {"filter": {"fieldName": "operatingSystemVersion", "stringFilter": {"matchType": "EXACT", "value": "27.1"}}}}]}}   # iOS 27.1: 0 App Store downloads ever (27.2 has 86), all US   # Guy, Nov 21: Connecticut = Guy's own test plays (11 of 12 "1.3.20 players"); left out of every game stat


# Guy, Nov 27 2026 ("how come only 50% passed level one?" ... "fix the card. fix other areas of social report that have this bug too"):
# a reinstall that gets its saved progress back (iCloud / Keychain) has a new first day but opens past level 1 (1.5.0 card: 2 of 6 "new" players opened
# on level 6). New player = first day on these versions AND a level-1 event that day (level_start / lv_move / level_end on level 1, first_open_level,
# level1_open). 84 of 758 first-day players since Nov 2 never touched level 1. Counts of new players use L1 as an event filter; anything else they did
# (came back, won level 2+, reminders) goes through a funnel with step 1 = L1 on the first day (_fun).
L1 = {"orGroup": {"expressions": [{"andGroup": {"expressions": [{"filter": {"fieldName": "eventName", "inListFilter": {"values": ["level_start", "lv_move", "level_end"]}}},
                                                                {"filter": {"fieldName": "customEvent:level", "stringFilter": {"value": "1"}}}]}},
                                  {"filter": {"fieldName": "eventName", "inListFilter": {"values": ["first_open_level", "level1_open"]}}}]}}


def no_ct(body):
    """Same question without Connecticut players (Guy testing)."""
    f = body.get("dimensionFilter")
    return {**body, "dimensionFilter": {"andGroup": {"expressions": [f, NO_CT]}} if f else NO_CT}


# Guy, Nov 24: refresh took almost 10 min (1,085 questions, one version group at a time). Now at most 8 at once over every group
# (GA4 allows 10 per property) and each group asks only for the levels its tile needs. CALLS is checked in verify_report.py.
_SEM, CALLS = threading.BoundedSemaphore(8), [0]


def _post(s, *a, **k):
    with _SEM:
        CALLS[0] += 1
        return s.post(*a, **k)


def _run(s, body):
    body = no_ct(body)
    for wait in (2, 5, 10, 0):   # 429 / 5xx: wait and ask again (queries now run several at a time)
        r = _post(s, f"https://analyticsdata.googleapis.com/v1beta/properties/{PROPERTY}:runReport", json=body, timeout=60)
        if r.ok or r.status_code not in (429, 500, 503) or not wait:
            break
        time.sleep(wait)
    if not r.ok:
        raise RuntimeError(f"GA4 {r.status_code}: {r.text[:200]}")
    return [([d["value"] for d in row.get("dimensionValues", [])], [float(m["value"]) for m in row["metricValues"]]) for row in r.json().get("rows", [])]


def _ff(x):
    """A Data API filter as a funnel filter (same fields, "filter" is called "funnelFieldFilter" there)."""
    if isinstance(x, dict):
        return {("funnelFieldFilter" if k == "filter" else k): _ff(v) for k, v in x.items()}
    return [_ff(v) for v in x] if isinstance(x, list) else x


_BACK = {}
# Nov 27: funnel answers for finished days (end date 3+ days ago) are kept in cache/funnel-cache.json and not asked again; the level-1 rule added
# per-day funnels and took a refresh to 1,009 questions (limit 1,000). A new version changes the version filter, so its questions are new.
FCACHE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "cache", "funnel-cache.json")
try:
    _KEEP = json.load(open(FCACHE))
except Exception:
    _KEEP = {}
_KEEP_NEW = {}


def _back(s, days, flt, until=None):
    """Guy, Nov 24: new players of each first day (YYYYMMDD) who played the next day, tied to the version they STARTED on (funnel: step 1 = first
    day on these versions, step 2 = next day). Before, anyone with that first day who came back on these or later versions was counted, so players
    who started on 1.3.18/19 were added to "1.3.11 to 1.3.17" (29 shown, really 16). With until = day 7 OR LATER, up to that day (Day-7 tiles)."""
    from concurrent.futures import ThreadPoolExecutor

    # Nov 27: step 1 also needs a level-1 event that first day (L1), so reinstalls that got their progress back are not "new players"
    def nxt(d):
        d0 = dt.datetime.strptime(d, "%Y%m%d").date()
        a, n = d0 + dt.timedelta(days=7 if until else 1), until or d0 + dt.timedelta(days=1)
        return {"filter": {"fieldName": "date", "inListFilter": {"values": [(a + dt.timedelta(days=i)).strftime("%Y%m%d") for i in range((n - a).days + 1)]}}}, n
    return _fun(s, days, flt, nxt)


def _fun1(s, steps, start, end):
    """One funnel question: users through every step (each step = one event matching its filter, in order). Returns [users at step 1, step 2, ...]."""
    body = {"dateRanges": [{"startDate": start, "endDate": end}], "funnel": {"steps": [{"name": f"s{i}", "filterExpression": _ff(x)} for i, x in enumerate(steps)]}}
    key = json.dumps(body, sort_keys=True)
    if key not in _BACK and key in _KEEP:
        _BACK[key] = _KEEP[key]
    if key not in _BACK:
        for wait in (2, 5, 10, 0):
            r = _post(s, f"https://analyticsdata.googleapis.com/v1alpha/properties/{PROPERTY}:runFunnelReport", json=body, timeout=60)
            if r.ok or r.status_code not in (429, 500, 503) or not wait:
                break
            time.sleep(wait)
        if not r.ok:
            raise RuntimeError(f"GA4 funnel {r.status_code}: {r.text[:200]}")
        q = {row["dimensionValues"][0]["value"].split(".")[0]: int(row["metricValues"][0]["value"]) for row in r.json().get("funnelTable", {}).get("rows", [])}
        _BACK[key] = [q.get(str(i + 1), 0) for i in range(len(steps))]
    if end <= (dt.date.today() - dt.timedelta(days=3)).isoformat():
        _KEEP_NEW[key] = _BACK[key]
    return _BACK[key]


def _fun(s, days, flt, step2, first=False):
    """Nov 27: new players of each first day d (on these versions, played level 1 that day) who then did step2(d) -> (filter, last date).
    first=True: step2's event comes BEFORE the level-1 event (the quiet-reminder status is sent at launch, before the first pour)."""
    from concurrent.futures import ThreadPoolExecutor
    on = lambda f, v: {"filter": {"fieldName": f, "stringFilter": {"value": v}}}

    def ask(d):
        f2, n = step2(d)
        s1 = {"andGroup": {"expressions": [flt, on("firstSessionDate", d), on("date", d), L1, NO_CT]}}
        if first:
            return _fun1(s, [{"andGroup": {"expressions": [flt, on("firstSessionDate", d), f2, NO_CT]}}, s1], f"{d[:4]}-{d[4:6]}-{d[6:]}", n.isoformat())[1]
        return _fun1(s, [s1, f2], f"{d[:4]}-{d[4:6]}-{d[6:]}", n.isoformat())[1]
    with ThreadPoolExecutor(8) as ex:
        return dict(zip(days, ex.map(ask, days)))


# Guy, Nov 22: "remove tutorial uses from the super stir/solve card". From 1.3.19 every new player gets a free Super Stir
# on level 4 and a free Super Solve on level 5 as part of the tutorial (kind "free", level param = that level); those are left out.
TUT_VERS = r"1\.3\.(19|[2-9][0-9])|1\.([4-9]|[1-9][0-9])\..*|([2-9]|[1-9][0-9])\..*"
SUPERS = ["super_stir", "super_solve"]


def _tut():
    v = {"filter": {"fieldName": "appVersion", "stringFilter": {"matchType": "FULL_REGEXP", "value": TUT_VERS}}}
    f = lambda e, l: {"andGroup": {"expressions": [{"filter": {"fieldName": "eventName", "stringFilter": {"value": e}}}, {"filter": {"fieldName": "customEvent:kind", "stringFilter": {"value": "free"}}},
                                                   {"filter": {"fieldName": "customEvent:level", "stringFilter": {"value": l}}}, v]}}
    return {"orGroup": {"expressions": [f("super_stir", "4"), f("super_solve", "5")]}}


def _supers(s, dr, fil):
    """Super Stir / Super Solve uses without the tutorial ones, plus how many players made them."""
    f = {"andGroup": {"expressions": [fil, {"filter": {"fieldName": "eventName", "inListFilter": {"values": SUPERS}}}, {"notExpression": _tut()}]}}
    n = {e: int(c) for (e,), (c,) in _run(s, {"dateRanges": [dr], "dimensions": [{"name": "eventName"}], "metrics": [{"name": "eventCount"}], "dimensionFilter": f})}
    u = _run(s, {"dateRanges": [dr], "metrics": [{"name": "activeUsers"}], "dimensionFilter": f})
    return {"super_stir": n.get("super_stir", 0), "super_solve": n.get("super_solve", 0), "super_users": int(u[0][1][0]) if u else 0}


def _many(s, bodies):
    """Guy, Nov 20: the per-level questions ran one after another and the step took ~10 min (one more question per new
    highest level, every day). Same questions, 8 at a time (GA4 allows 10 at once per property); answers in the same order."""
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(8) as ex:
        return list(ex.map(lambda b: _run(s, b), bodies))


def _ver(v):
    try:
        return tuple(int(x) for x in v.split("."))
    except ValueError:
        return ()


def _asc_live(keys_dir):
    """Newest version on sale per App Store Connect. Guy, Nov 6: Apple's public lookup kept telling the report's server 1.3.2 hours after 1.3.3 went live, which dropped 1.3.3 players."""
    c = json.load(open(os.path.join(keys_dir, "asc-metrics.json")))
    now = int(time.time())
    tok = jwt.encode({"iss": c["issuer_id"], "iat": now, "exp": now + 600, "aud": "appstoreconnect-v1"}, open(os.path.join(keys_dir, c["key_file"])).read(), algorithm="ES256", headers={"kid": c["key_id"], "typ": "JWT"})
    r = requests.get(f"https://api.appstoreconnect.apple.com/v1/apps/{APP_ID}/appStoreVersions", headers={"Authorization": "Bearer " + tok}, timeout=30,
                     params={"filter[platform]": "IOS", "filter[appStoreState]": "READY_FOR_SALE", "limit": 20, "fields[appStoreVersions]": "versionString"})
    r.raise_for_status()
    return max((_ver(x["attributes"]["versionString"]) for x in r.json()["data"]), default=())


def _live(keys_dir):
    """Version on the App Store now + its release date (None = unknown); builds newer than this (in review / TestFlight) are test devices, so they're left out."""
    ver, day = (), None
    for _ in range(3):
        try:
            r = requests.get("https://itunes.apple.com/lookup", params={"id": APP_ID, "country": "us", "t": int(time.time())}, timeout=20).json()["results"][0]   # Guy, Nov 21: "t" skips Apple's cached answer (said 1.3.17 for 9+ hours after 1.3.18 went live, so 1.3.18+ started a day late)
            ver, day = _ver(r["version"]), pd.Timestamp(r["currentVersionReleaseDate"]).tz_convert("America/New_York").date()
            break
        except Exception:
            pass
    try:
        asc = _asc_live(keys_dir)
        if asc and asc != ver:
            ver, day = asc, None
    except Exception:
        pass
    return (ver, day) if ver else (FIRST, START)


def fetch(keys_dir, today):
    creds = Credentials.from_authorized_user_file(os.path.join(keys_dir, "ga4-token.json"), SCOPES)
    if not creds.valid:
        creds.refresh(Request())
    s = AuthorizedSession(creds)
    rng = lambda days, end=0: {"startDate": max(today - dt.timedelta(days=days), START).isoformat(), "endDate": max(today - dt.timedelta(days=end), START).isoformat()}
    ev = lambda name: {"filter": {"fieldName": "eventName", "stringFilter": {"value": name}}}
    d14, d7, dall = rng(14), rng(6, 0), rng(9999)   # d7 = last 7 days incl. today (Guy, Nov 21: "All versions should include today too"); dall = everything since Nov 1
    CALLS[0] = 0
    live, released = _live(keys_dir)
    first_day = lambda v: min((dt.date(int(d[:4]), int(d[4:6]), int(d[6:])) for (d,), (n,) in _run(s, {"dateRanges": [dall], "dimensions": [{"name": "date"}], "metrics": [{"name": "activeUsers"}], "dimensionFilter": {"filter": {"fieldName": "appVersion", "stringFilter": {"value": v}}}}) if n >= 5), default=None)   # first day a version had 5+ players
    # Guy, Nov 21: 1.3.18+ moved from Nov 20 to Nov 21 once 1.3.19 shipped (a version no longer live fell back to its first 5-player day).
    # Apple's own date is saved while a version is live and used from then on.
    _lv = ".".join(map(str, live))
    try: _saved = json.load(open(RELFILE))
    except Exception: _saved = {}
    if released and _lv not in RELEASED and _saved.get(_lv) != released.isoformat():
        _saved[_lv] = released.isoformat()
        try: json.dump(_saved, open(RELFILE, "w"), indent=1, sort_keys=True)
        except Exception: pass
    for _v, _d in _saved.items():
        RELEASED.setdefault(_v, dt.date.fromisoformat(_d))
    released = released or RELEASED.get(_lv) or first_day(_lv) or today
    vers = [v[0] for v, _ in _run(s, {"dateRanges": [dall], "dimensions": [{"name": "appVersion"}], "metrics": [{"name": "activeUsers"}]}) if FIRST <= _ver(v[0]) <= live]
    out = {"versions": vers, "live": ".".join(map(str, live)), "daily": {}, "week": {}, "outcome": {}, "kind": {}, "reach": {}, "all": {}}
    if not vers:
        return {"GA4 Game Lite": (pd.DataFrame([{"json": json.dumps(out)}]), None)}
    newer = {"filter": {"fieldName": "appVersion", "inListFilter": {"values": vers}}}
    # Guy, Nov 4: before its release day a version only ran on review/test devices (1.3.2: 2 purchases, 14 Super Solves), so those days don't count.
    # Nov 6: this must hold for every version, not just the live one, or old test data comes back each time a new version ships.
    rel = lambda v: RELEASED.get(v) or (released if _ver(v) == live else first_day(v) or today)
    out["released"] = {v: rel(v).isoformat() for v in vers}
    tests = [{"andGroup": {"expressions": [{"filter": {"fieldName": "appVersion", "stringFilter": {"value": v}}},
                                           {"filter": {"fieldName": "date", "inListFilter": {"values": pre}}}]}}
             for v in vers for pre in [[(START + dt.timedelta(days=i)).strftime("%Y%m%d") for i in range((rel(v) - START).days)]] if pre]
    if tests:
        newer = {"andGroup": {"expressions": [newer, {"notExpression": {"orGroup": {"expressions": tests}}}]}}
    for (d,), (n,) in _run(s, {"dateRanges": [dall], "dimensions": [{"name": "date"}], "metrics": [{"name": "activeUsers"}], "dimensionFilter": newer}):
        out["daily"].setdefault(f"{d[:4]}-{d[4:6]}-{d[6:]}", {})["players"] = int(n)
    evf = {"andGroup": {"expressions": [{"filter": {"fieldName": "eventName", "inListFilter": {"values": EVENTS}}}, newer]}}
    one = lambda name: {"andGroup": {"expressions": [ev(name), newer]}}
    for (d, e), (n,) in _run(s, {"dateRanges": [dall], "dimensions": [{"name": "date"}, {"name": "eventName"}], "metrics": [{"name": "eventCount"}], "dimensionFilter": evf}):
        out["daily"].setdefault(f"{d[:4]}-{d[4:6]}-{d[6:]}", {})[e] = int(n)
    wk = _run(s, {"dateRanges": [d7], "metrics": [{"name": "activeUsers"}], "dimensionFilter": newer})
    out["week"]["players"] = int(wk[0][1][0]) if wk else 0
    for (e,), (n,) in _run(s, {"dateRanges": [d7], "dimensions": [{"name": "eventName"}], "metrics": [{"name": "eventCount"}], "dimensionFilter": evf}):
        out["week"][e] = int(n)
    out["week"].update(_supers(s, d7, newer))   # Guy, Nov 22: tutorial uses left out
    for (o,), (n,) in _run(s, {"dateRanges": [d7], "dimensions": [{"name": "customEvent:outcome"}], "metrics": [{"name": "eventCount"}], "dimensionFilter": one("level_end")}):
        if o != "(not set)":
            out["outcome"][o] = int(n)
    for (k,), (n,) in _run(s, {"dateRanges": [d7], "dimensions": [{"name": "customEvent:kind"}], "metrics": [{"name": "eventCount"}], "dimensionFilter": one("ad_shown")}):
        if k != "(not set)":
            out["kind"][k] = int(n)
    # Guy, Nov 12: finished shares (game save 205+ logs share_done; kind = what was shared), last 7 days incl. today
    out["shares"] = {"by": {}}
    for (k,), (c, u) in _run(s, {"dateRanges": [d7], "dimensions": [{"name": "customEvent:kind"}], "metrics": [{"name": "eventCount"}, {"name": "totalUsers"}], "dimensionFilter": one("share_done")}):
        out["shares"]["by"][k] = int(c)
    r = _run(s, {"dateRanges": [d7], "metrics": [{"name": "eventCount"}, {"name": "totalUsers"}], "dimensionFilter": one("share_done")})
    out["shares"]["n"], out["shares"]["players"] = (int(r[0][1][0]), int(r[0][1][1])) if r else (0, 0)
    # Guy, Nov 9: +Moves videos (out of moves popup) are revenue: offers vs watched, last 7 complete days
    out["moves"] = {}
    for e in ("rewarded_offer_shown", "rewarded_watched"):
        f = {"andGroup": {"expressions": [one(e), {"filter": {"fieldName": "customEvent:placement", "stringFilter": {"value": "out_of_moves"}}}]}}
        r = _run(s, {"dateRanges": [d7], "metrics": [{"name": "eventCount"}, {"name": "totalUsers"}], "dimensionFilter": f})
        out["moves"][e] = [int(r[0][1][0]), int(r[0][1][1])] if r else [0, 0]
    # Guy, Nov 4: a player whose furthest level changes shows up once per level in a by-level report (285 "players" vs 53 real),
    # so ask for each level how many different players reached it or beyond
    lvs = sorted(int(lv) for (lv,), _ in _run(s, {"dateRanges": [dall], "dimensions": [{"name": "customUser:max_level"}], "metrics": [{"name": "activeUsers"}], "dimensionFilter": newer, "limit": 1000}) if lv.isdigit())
    rs = _many(s, [{"dateRanges": [{"startDate": dall["startDate"], "endDate": dall["endDate"]}], "metrics": [{"name": "activeUsers"}],
                    "dimensionFilter": {"andGroup": {"expressions": [newer, {"filter": {"fieldName": "customUser:max_level", "inListFilter": {"values": [str(x) for x in lvs if x >= lv]}}}]}}} for lv in lvs])
    for lv, r in zip(lvs, rs):
        out["reach"][str(lv)] = int(r[0][1][0]) if r else 0
    # Guy, Nov 6: split each bar: played in the last 3 days (today + 2 before) = still playing; the rest of that bar has left
    def reached(base, dr, st, l1=False):   # l1 (Nov 27): new players only = played level 1, then reached the level (funnel; only where the plain count is above 0)
        ks = [lv for lv in st if any(x >= lv for x in lvs)]
        if l1:
            plain = reached(base, dr, st)
            ml = lambda lv: {"filter": {"fieldName": "customUser:max_level", "inListFilter": {"values": [str(x) for x in lvs if x >= lv]}}}
            return {str(lv): (_fun1(s, [{"andGroup": {"expressions": [base, L1, NO_CT]}}, {"andGroup": {"expressions": [base, ml(lv), NO_CT]}}], dr["startDate"], dr["endDate"])[0 if lv <= 1 else 1]
                              if plain.get(str(lv)) else 0) for lv in ks}
        rs = _many(s, [{"dateRanges": [dr], "metrics": [{"name": "activeUsers"}], "dimensionFilter": {"andGroup": {"expressions": [base] + [{"filter": {"fieldName": "customUser:max_level", "inListFilter": {"values": [str(x) for x in lvs if x >= lv]}}}]}}} for lv in ks])
        return {str(lv): int(next(iter(r), ([], [0]))[1][0]) for lv, r in zip(ks, rs)}
    out["active"] = reached(newer, {"startDate": max(today - dt.timedelta(days=QUIT_DAYS - 1), START).isoformat(), "endDate": today.isoformat()}, STEPS)
    # Guy, Nov 6: did 1.3.4 help? New players only (first opened the game after it came out) vs new players before it, so updaters with high levels don't flatter it
    cmp = {"version": ".".join(map(str, COMPARE)), "live": live >= COMPARE}
    if live >= COMPARE:
        since = released if live == COMPARE else RELEASED.get(cmp["version"])
        since = since or first_day(cmp["version"])   # a later version is live, so Apple only gives that one's date
        if since:
            dates = lambda a, b: [(a + dt.timedelta(days=i)).strftime("%Y%m%d") for i in range((b - a).days + 1)]
            group = lambda vs, ds: {"andGroup": {"expressions": [newer, {"filter": {"fieldName": "appVersion", "inListFilter": {"values": vs}}}, {"filter": {"fieldName": "firstSessionDate", "inListFilter": {"values": ds}}}]}}
            cmp["since"] = since.isoformat()
            cmp["new"] = reached(group([v for v in vers if _ver(v) >= COMPARE], dates(since, today)), dall, STEPS, True)
            b0 = RELEASED.get(".".join(map(str, BASE))) or START
            cmp["base"], cmp["bsince"] = ".".join(map(str, BASE)), b0.isoformat()
            cmp["old"] = reached(group([v for v in vers if BASE <= _ver(v) < COMPARE], dates(b0, since - dt.timedelta(days=1))), dall, STEPS, True)
    out["compare"] = cmp
    # Guy, Nov 8: win rate per level. 1.3.4+ sends lv_start_N / lv_win_N for levels 1-25 (players = different people; tries = every start)
    lvf = {"andGroup": {"expressions": [newer, {"filter": {"fieldName": "eventName", "stringFilter": {"matchType": "BEGINS_WITH", "value": "lv_"}}}]}}
    out["lv"] = {}
    for (e,), (u, c) in _run(s, {"dateRanges": [dall], "dimensions": [{"name": "eventName"}], "metrics": [{"name": "totalUsers"}, {"name": "eventCount"}], "dimensionFilter": lvf}):
        kind, _, n = e.rpartition("_")
        if kind in ("lv_start", "lv_win") and n.isdigit():
            row = out["lv"].setdefault(n, {})
            row[kind[3:]], row[kind[3:] + "s"] = int(u), int(c)
    # Guy, Nov 21: "add quiet reminders opt-in rate". New players (first opened in the window, on these versions) who get reminders:
    # soft_provisional = Apple's quiet trial (game save 290+, 1.3.19+), soft_authorized / remind_allow = full permission; off = soft_denied / remind_off
    R_ON, R_OFF = ["soft_provisional", "soft_authorized", "remind_allow"], ["soft_denied", "remind_off"]
    # Guy, Nov 16: the same tiles for the newest versions only (1.3.11+), from the first one's release day to today
    # Guy, Nov 19: and for the versions before 1.3.11, over the same number of days just before 1.3.11 came out (each 1.3.11+ tile compares to it)
    # Guy, Nov 25: "add another drop down: Today, last 7 days, this month, last month" + "clean up the section to make the cards and data consistent":
    # every card of a view counts the same players over the same days. One question answers up to four periods (GA4 takes 4 date ranges) and both player
    # filters (the first-day dimension: each player has exactly one first day, so the days add up to the players).
    m0 = today.replace(day=1); m1 = (m0 - dt.timedelta(days=1)).replace(day=1)
    PER = [(k, max(a, START), b) for k, a, b in (("today", today, today), ("yest", today - dt.timedelta(days=1), today - dt.timedelta(days=1)), ("d7", today - dt.timedelta(days=6), today), ("month", m0, today), ("last", m1, m0 - dt.timedelta(days=1))) if b >= START]
    out["periods"] = {k: [a.isoformat(), b.isoformat()] for k, a, b in PER}
    key = lambda d: d.strftime("%Y%m%d")
    span = lambda a, b: [a + dt.timedelta(days=i) for i in range((b - a).days + 1)] if b >= a else []
    FDS = {k: {key(d) for d in span(a, b)} for k, a, b in PER}
    AND = lambda *x: {"andGroup": {"expressions": [y for y in x if y]}}
    INN = lambda f, v: {"filter": {"fieldName": f, "inListFilter": {"values": list(v)}}}

    def tiles(vs, allv, since=START, until=today):   # since / until = the version group's own days: new players of a group started on it (players who updated into it are not new)
        FD = {k: {d for d in v if key(since) <= d <= key(until)} for k, v in FDS.items()}
        fil = AND(newer, INN("appVersion", vs))
        rgs = [{"startDate": a.isoformat(), "endDate": b.isoformat(), "name": k} for k, a, b in PER]

        def q(dims, mets, *f):   # rows as (first day, other dims..., period), values
            return [(r[0], r[1]) if len(ch) > 1 else (r[0] + [ch[0]["name"]], r[1]) for ch in (rgs[i:i + 4] for i in range(0, len(rgs), 4)) for r in _run(s, {"dateRanges": ch, "dimensions": [{"name": d} for d in ["firstSessionDate"] + dims], "metrics": [{"name": m} for m in mets], "dimensionFilter": AND(fil, *f), "limit": 100000})]

        def add(rows, pick=lambda d: "n", i=0):   # {(period, who): {name: total}}
            o = {}
            for d, v in rows:
                for who in ("all",) + (("new",) if d[0] in FD[d[-1]] else ()):
                    x = o.setdefault((d[-1], who), {}); k = pick(d); x[k] = x.get(k, 0) + int(v[i])
            return o
        players = add(q([], ["activeUsers"]))
        outc = add(q(["customEvent:outcome"], ["eventCount"], ev("level_end")), lambda d: d[1])
        kind = add(q(["customEvent:kind"], ["eventCount"], ev("ad_shown")), lambda d: d[1])
        sf = AND(INN("eventName", SUPERS), {"notExpression": _tut()})
        sup, supu = add(q(["eventName"], ["eventCount"], sf), lambda d: d[1]), add(q([], ["activeUsers"], sf))
        mvr = q(["eventName"], ["eventCount", "totalUsers"], INN("eventName", ["rewarded_offer_shown", "rewarded_watched"]), {"filter": {"fieldName": "customEvent:placement", "stringFilter": {"value": "out_of_moves"}}})
        mv, mvu = add(mvr, lambda d: d[1]), add(mvr, lambda d: d[1], 1)
        sh, shu = add(q(["customEvent:kind"], ["eventCount"], ev("share_done")), lambda d: d[1]), add(q([], ["totalUsers"], ev("share_done")))
        # furthest level of the middle player
        # Nov 27: the "new" side only counts players who played level 1 (L1), so a reinstall that came back on level 6 is not a new player on level 6
        lvl = {}
        for d, v in q(["customUser:max_level"], ["activeUsers"]):   # GA4 lists every level in every period, with 0 players
            if d[1].isdigit() and v[0]:
                for who in ("all",) + (("new",) if d[0] in FD[d[-1]] else ()):
                    lvl.setdefault((d[-1], who), set()).add(int(d[1]))
        every, cache = sorted({x for v in lvl.values() for x in v}), {}

        def reach(lv):   # plain counts; for "new" an upper bound (reinstalls included), see half_new
            if lv not in cache:
                cache[lv] = add(q([], ["activeUsers"], INN("customUser:max_level", [str(x) for x in every if x >= lv])))
            return cache[lv]
        half = {}
        for sr, ls in lvl.items():
            if sr[1] == "new":
                continue
            v = sorted(ls); top = reach(v[0]).get(sr, {}).get("n", 0); lo, hi = 0, len(v)
            while hi - lo > 1:
                m = (lo + hi) // 2
                if reach(v[m]).get(sr, {}).get("n", 0) * 2 >= top: lo = m
                else: hi = m
            half[sr] = [v[lo], top, v[-1]]
        # first days: level 10 on day one, next day, day 7 or later
        first = min(a for _, a, _ in PER); whole = {"startDate": first.isoformat(), "endDate": today.isoformat()}
        first14 = max(START, min(first, today - dt.timedelta(days=14))); fw = {"startDate": first14.isoformat(), "endDate": today.isoformat()}
        two = lambda *f: {(d, d2): int(n) for (d, d2), (n,) in _run(s, {"dateRanges": [fw], "dimensions": [{"name": "firstSessionDate"}, {"name": "date"}], "metrics": [{"name": "activeUsers"}], "dimensionFilter": AND(fil, INN("firstSessionDate", [key(d) for d in span(first14, today)]), *f), "limit": 100000})}
        # Nov 27: new players = first day on these versions AND a level-1 event that day (L1); level 10 = the same players (max level is per player)
        pair = two(L1); base = {d: n for (d, d2), n in pair.items() if d == d2}
        # level 10 on day one: the max level can't sit in the same question as L1 (GA4 reads it off the level-1 event = 1), so funnel L1 -> level 10+ that day,
        # only on days where the plain count (reinstalls included) is above 0
        D = lambda k: dt.datetime.strptime(k, "%Y%m%d").date()
        _m10 = INN("customUser:max_level", [str(x) for x in lvs if x >= 10] or ["x"])
        _h = [d for (d, d2), n in two(_m10).items() if d == d2 and n and base.get(d)]
        hi10 = {(d, d): n for d, n in _fun(s, _h, fil, lambda d: (AND(_m10, INN("date", [d])), D(d))).items()}
        W1 = {"today": span(max(START, today - dt.timedelta(days=1)), today - dt.timedelta(days=1)), "yest": span(max(START, today - dt.timedelta(days=2)), today - dt.timedelta(days=2)), "d7": span(max(START, today - dt.timedelta(days=8)), today - dt.timedelta(days=2))}
        W7 = {"today": [], "yest": span(max(START, today - dt.timedelta(days=8)), today - dt.timedelta(days=8)), "d7": span(max(START, today - dt.timedelta(days=14)), today - dt.timedelta(days=8))}
        for k, a, b in PER:
            if k in ("month", "last"):
                W1[k], W7[k] = span(a, min(b, today - dt.timedelta(days=2))), span(a, min(b, today - dt.timedelta(days=8)))
        W1, W7 = ({k: [d for d in w if since <= d <= until] for k, w in W.items()} for W in (W1, W7))
        n1 = sorted({key(d) for w in W1.values() for d in w if base.get(key(d))}); n7 = sorted({key(d) for w in W7.values() for d in w if base.get(key(d))})
        D = lambda k: dt.datetime.strptime(k, "%Y%m%d").date()
        b1, b7 = _back(s, n1, fil), _back(s, n7, fil, until=today)   # Nov 27: every group through the funnel (step 1 = played level 1 on the first day); all versions used plain counts before
        ret = lambda w, bk: [sum(min(bk.get(key(d), 0), base.get(key(d), 0)) for d in w), sum(base.get(key(d), 0) for d in w)] + ([w[0].isoformat(), w[-1].isoformat()] if w else [None, None])
        # reminders: new players of the period (counted up to today)
        # Nov 27: only new players who played level 1: funnel reminder status (sent at launch) -> level-1 event, first day in the period
        def rq(names, ds):
            if not ds:
                return 0
            fd = INN("firstSessionDate", sorted(ds))
            return _fun1(s, [AND(fil, fd, INN("eventName", names), NO_CT), AND(fil, fd, L1, NO_CT)], min(D(d) for d in ds).isoformat(), today.isoformat())[1]
        ron, roff = {k: rq(R_ON, FD[k]) for k, _, _ in PER}, {k: rq(R_OFF, FD[k]) for k, _, _ in PER}
        NEWN = {k: sum(base.get(d, 0) for d in FD[k]) for k, _, _ in PER}   # new players = first day on these versions, one number on every card
        # Nov 27: typical / top level of new players (played level 1): funnel L1 -> max level >= lv, asked only where the plain count could pass
        for k, _, _ in PER:
            ls = sorted(lvl.get((k, "new"), ()))
            top = NEWN[k]
            if not ls or not top:
                continue
            ds = sorted(FD[k]); fd = INN("firstSessionDate", ds); memo = {}

            def ex(lv):
                if lv <= ls[0]:
                    return top
                if not reach(lv).get((k, "new"), {}).get("n", 0):
                    return 0
                if lv not in memo:
                    memo[lv] = _fun1(s, [AND(fil, fd, L1, NO_CT), AND(fil, fd, INN("customUser:max_level", [str(x) for x in every if x >= lv]), NO_CT)], D(ds[0]).isoformat(), today.isoformat())[1]
                return memo[lv]
            lo, hi = 0, len(ls)
            while hi - lo > 1:
                m = (lo + hi) // 2
                if reach(ls[m]).get((k, "new"), {}).get("n", 0) * 2 >= top and ex(ls[m]) * 2 >= top: lo = m
                else: hi = m
            t0, t1 = 0, len(ls)   # top player: highest level a new player reached
            while t1 - t0 > 1:
                m = (t0 + t1) // 2
                if ex(ls[m]) > 0: t0 = m
                else: t1 = m
            half[(k, "new")] = [ls[lo], top, ls[t0]]
        S = {}
        for k, a, b in PER:
            for who in ("all", "new"):
                g = lambda o: o.get((k, who), {})
                S[k + "|" + who] = {"players": g(players).get("n", 0) if who == "all" else NEWN[k], "other": NEWN[k] if who == "all" else players.get((k, "all"), {}).get("n", 0), "outcome": {x: n for x, n in g(outc).items() if x not in ("", "(not set)")},
                                    "kind": {x: n for x, n in g(kind).items() if x not in ("", "(not set)")}, "stir": g(sup).get("super_stir", 0), "solve": g(sup).get("super_solve", 0), "superu": g(supu).get("n", 0),
                                    "offers": g(mv).get("rewarded_offer_shown", 0), "watched": g(mv).get("rewarded_watched", 0), "watchu": g(mvu).get("rewarded_watched", 0), "shares": sum(g(sh).values()), "shareu": g(shu).get("n", 0),
                                    "half": half.get((k, who)), "l10": [sum(hi10.get((d, d), 0) for d in FD[k]), NEWN[k]], "d1": ret(W1[k], b1), "d7": ret(W7[k], b7),
                                    "remind": [min(NEWN[k], ron[k]), NEWN[k], roff[k]]}
        return S

    def block(vf, since, until, label):
        vfil = {"andGroup": {"expressions": [newer, {"filter": {"fieldName": "appVersion", "inListFilter": {"values": vf}}}]}}   # newer already drops pre-release test days
        dr = {"startDate": since.isoformat(), "endDate": until.isoformat()}
        B = {"label": label, "vers": vf, "since": since.isoformat(), "until": until.isoformat()}   # Guy, Nov 25: the cards have their own counts (tiles, below); blocks feed the charts
        B["freach"] = reached(vfil, dr, STEPS)   # Guy, Nov 16: "How far players get" for the newest versions (players who reached each step)
        B["factive"] = reached(vfil, {"startDate": max(until - dt.timedelta(days=QUIT_DAYS - 1), since).isoformat(), "endDate": until.isoformat()}, STEPS)   # still playing = played in the last QUIT_DAYS - 1 days
        B["lv"] = {}   # Guy, Nov 16: win rate per level for the newest versions too
        lvf2 = {"andGroup": {"expressions": [vfil, {"filter": {"fieldName": "eventName", "stringFilter": {"matchType": "BEGINS_WITH", "value": "lv_"}}}]}}
        for (e,), (u, c) in _run(s, {"dateRanges": [dr], "dimensions": [{"name": "eventName"}], "metrics": [{"name": "totalUsers"}, {"name": "eventCount"}], "dimensionFilter": lvf2}):
            kind, _, n = e.rpartition("_")
            if kind in ("lv_start", "lv_win") and n.isdigit():
                row = B["lv"].setdefault(n, {})
                row[kind[3:]], row[kind[3:] + "s"] = int(u), int(c)
        # Guy, Nov 19: Day-1 return = new players (first day on these versions) who played again the very next day; complete days only
        c_end = min(until, today - dt.timedelta(days=2))
        if c_end >= since:
            cd = lambda a, b: [(a + dt.timedelta(days=i)).strftime("%Y%m%d") for i in range((b - a).days + 1)]
            base = {d: int(n) for (d, d2), (n,) in _run(s, {"dateRanges": [{"startDate": since.isoformat(), "endDate": c_end.isoformat()}], "dimensions": [{"name": "firstSessionDate"}, {"name": "date"}], "metrics": [{"name": "activeUsers"}],
                    "dimensionFilter": {"andGroup": {"expressions": [vfil, L1, {"filter": {"fieldName": "firstSessionDate", "inListFilter": {"values": cd(since, c_end)}}}]}}, "limit": 10000}) if d == d2}   # Nov 27: + played level 1 that day
            back = {d: min(n, base[d]) for d, n in _back(s, list(base), vfil).items()}   # Guy, Nov 24: only players who started on these versions
            B["d1"] = [sum(back.get(d, 0) for d in base), sum(base.values()), since.isoformat(), c_end.isoformat()]
            # Guy, Nov 22: "Day-1 return by version" chart: the same players split by Google Ads (firstUserMedium cpc) vs everyone else
            B["d1src"] = {}
            for med, mf in (("ads", {"filter": {"fieldName": "firstUserMedium", "stringFilter": {"value": "cpc"}}}), ("other", {"notExpression": {"filter": {"fieldName": "firstUserMedium", "stringFilter": {"value": "cpc"}}}})):
                b2 = {d: int(n) for (d, d2), (n,) in _run(s, {"dateRanges": [{"startDate": since.isoformat(), "endDate": c_end.isoformat()}], "dimensions": [{"name": "firstSessionDate"}, {"name": "date"}], "metrics": [{"name": "activeUsers"}],
                      "dimensionFilter": {"andGroup": {"expressions": [vfil, mf, L1, {"filter": {"fieldName": "firstSessionDate", "inListFilter": {"values": cd(since, c_end)}}}]}}, "limit": 10000}) if d == d2}
                k2 = {d: min(n, b2[d]) for d, n in _back(s, list(b2), {"andGroup": {"expressions": [vfil, mf]}}).items()}
                B["d1src"][med] = [sum(k2.get(d, 0) for d in b2), sum(b2.values())]
        return B
    from concurrent.futures import ThreadPoolExecutor
    J, R = {}, {}   # every version group, asked side by side
    vf = [v for v in vers if VF <= _ver(v) <= VF_TO]
    if vf:
        since = min(rel(v) for v in vf)
        J["vf"] = (vf, since, today, ".".join(map(str, VF)) + " to " + ".".join(map(str, VF_TO)))
        pv = [v for v in vers if _ver(v) < VF]
        n = (today - since).days + 1
        p0, p1 = max(since - dt.timedelta(days=n), START), since - dt.timedelta(days=1)
        if pv and p1 >= p0:
            J["pre"] = (pv, p0, p1, "Before " + ".".join(map(str, VF)))
    for X, H, L in VX:
        xv = [v for v in vers if X <= _ver(v) <= (H or (999,))]
        if xv:
            k = "v" + "_".join(map(str, X))
            J[k] = (xv, min(rel(v) for v in xv), today, L or ".".join(map(str, X)) + "+")
            R[k] = [".".join(map(str, X)), ".".join(map(str, H)) if H else None]
    def quiet(vs, a, b):   # one row of the Quiet start card: new players' first day (today so far included), and the next day (complete days only)
        ds = [(a + dt.timedelta(days=i)).strftime("%Y%m%d") for i in range((b - a).days + 1)]
        if not vs or not ds:
            return {"n": 0}
        fil = {"andGroup": {"expressions": [newer, {"filter": {"fieldName": "appVersion", "inListFilter": {"values": vs}}}]}}
        E = ["lv_win_1", "lv_win_2", "lv_win_3", "lv_win_7"]
        ask = lambda dims, m, *x: _run(s, {"dateRanges": [{"startDate": a.isoformat(), "endDate": b.isoformat()}], "dimensions": [{"name": d} for d in dims], "metrics": [{"name": m}], "limit": 10000,
                     "dimensionFilter": {"andGroup": {"expressions": [fil, {"filter": {"fieldName": "firstSessionDate", "inListFilter": {"values": ds}}}, *x]}}})
        r = ask(["firstSessionDate", "date", "eventName"], "totalUsers", {"filter": {"fieldName": "eventName", "inListFilter": {"values": E}}})
        # Nov 27 (Guy: "how come only 50% passed level one?"): new players = played level 1 on their first day (L1); 2 of the 6 "1.5.0+" players were
        # reinstalls that opened on level 6. Won level 2 / 3 / 7 the same day go through a funnel (step 1 = L1 that day), so a reinstall's wins never count.
        base = {d: int(n) for (d, d2), (n,) in ask(["firstSessionDate", "date"], "activeUsers", L1) if d == d2}
        m10 = {"filter": {"fieldName": "customUser:max_level", "inListFilter": {"values": [str(x) for x in lvs if x >= 10] or ["x"]}}}
        D0 = lambda d: dt.datetime.strptime(d, "%Y%m%d").date()
        on = lambda f, v: {"filter": {"fieldName": f, "stringFilter": {"value": v}}}
        h10 = [d for (d, d2), (n,) in ask(["firstSessionDate", "date"], "activeUsers", m10) if d == d2 and n and base.get(d)]   # plain count first, funnel only where it is above 0
        l10 = sum(_fun(s, h10, fil, lambda d: ({"andGroup": {"expressions": [m10, on("date", d)]}}, D0(d))).values())
        nx = [d for d in base if d <= (today - dt.timedelta(days=2)).strftime("%Y%m%d")]
        bk = _back(s, nx, fil)
        hit = lambda e: sorted({d for (d, d2, x), (n,) in r if d == d2 and x == e and n and base.get(d)})   # days where the plain count is above 0
        won = {e[7:]: sum(_fun(s, hit(e), fil, lambda d, e=e: ({"andGroup": {"expressions": [on("eventName", e), on("date", d)]}}, D0(d))).values()) for e in E[1:]}
        won["1"] = sum(int(n) for (d, d2, x), (n,) in r if d == d2 and x == E[0])   # winning level 1 = played level 1
        return {"n": sum(base.values()), "l10": l10, "w": won,
                "back": [sum(min(bk[d], base[d]) for d in nx), sum(base[d] for d in nx)], "a": a.isoformat(), "b": b.isoformat()}

    def quiet24(vs):   # Nov 24 from 10:13 AM: the players whose first open was in those hours (funnel step 1), then what they did
        on = lambda f, v: {"filter": {"fieldName": f, "stringFilter": {"value": v}}}
        st = {"andGroup": {"expressions": [on("eventName", "first_open"), on("date", "20261124"), {"filter": {"fieldName": "dateHour", "inListFilter": {"values": [f"20261124{h:02d}" for h in range(11, 24)]}}},
                                           {"filter": {"fieldName": "appVersion", "inListFilter": {"values": vs}}}, NO_CT]}}
        lv1 = {"andGroup": {"expressions": [L1, on("date", "20261124"), NO_CT]}}   # Nov 27: and played level 1 that day (reinstalls with their progress back are not new)

        def two(step2, end="2026-11-24"):
            r = _fun1(s, [st, lv1, step2], "2026-11-24", end)
            return r[1], r[2]
        W = {k: two({"andGroup": {"expressions": [on("eventName", "lv_win_" + k), on("date", "20261124")]}}) for k in ("1", "2", "3", "7")}
        n = W["1"][0]
        l10 = two({"andGroup": {"expressions": [{"filter": {"fieldName": "customUser:max_level", "inListFilter": {"values": [str(x) for x in lvs if x >= 10]}}}, on("date", "20261124")]}})[1]
        bk = [two(on("date", "20261125"), "2026-11-25")[1], n] if today >= dt.date(2026, 11, 26) else [0, 0]
        return {"n": n, "l10": l10, "w": {k: v[1] for k, v in W.items()}, "back": bk}

    def quiet_after(vs):
        A, B1 = quiet24([v for v in vs if _ver(v) <= (1, 3, 23)]), quiet(vs, QS_FROM, today)
        if not B1.get("n"):
            return A
        return {"n": A["n"] + B1["n"], "l10": A["l10"] + B1["l10"], "w": {k: A["w"][k] + B1["w"][k] for k in A["w"]}, "back": [A["back"][i] + B1["back"][i] for i in (0, 1)]}
    with ThreadPoolExecutor(12) as ex:
        Q = {"older": ex.submit(quiet, [v for v in vers if (1, 3, 11) <= _ver(v) <= (1, 3, 17)], *QS_OLDER),
             "before": ex.submit(quiet, [v for v in vers if (1, 3, 20) <= _ver(v) < (1, 4, 0)], *QS_BEFORE),
             "after": ex.submit(quiet_after, [v for v in vers if (1, 3, 20) <= _ver(v) < (1, 4, 0)]),
             "after140": ex.submit(quiet, [v for v in vers if (1, 4, 0) <= _ver(v) < (1, 5, 0)], QS_FROM, today),
             "after150": ex.submit(quiet, [v for v in vers if _ver(v) >= (1, 5, 0)], QS_FROM, today)}   # Guy, Nov 26: 1.5.0+ row (0 until it is on the App Store)
        F = {k: ex.submit(block, *v) for k, v in J.items()}
        TL = {"all": ex.submit(tiles, vers, True)}
        TL.update({k: ex.submit(tiles, v[0], False, START if k == "pre" else v[1], v[2]) for k, v in J.items()})
    out["quiet"] = {k: f.result() for k, f in Q.items()}
    for k in ("vf", "pre"):
        if k in F:
            out[k] = F[k].result()
    out["vx"] = {k: {**F[k].result(), "range": R[k]} for k in R}
    out["vxnext"] = [L or ".".join(map(str, X)) + "+" for X, H, L in VX if X > live]   # Guy, Nov 24: groups not on the App Store yet (1.4.0+)
    out["tiles"] = {k: f.result() for k, f in TL.items()}
    # active players on every app version (the game events above only come from 1.3.1+)
    spanx = lambda a: {"startDate": a, "endDate": today.isoformat()}
    total = lambda a: int(next(iter(_run(s, {"dateRanges": [spanx(a)], "metrics": [{"name": "activeUsers"}]})), ([], [0]))[1][0])
    out["all"] = {"today": total(today.isoformat()), "week": total((today - dt.timedelta(days=6)).isoformat()), "m30": total((today - dt.timedelta(days=29)).isoformat()), "ever": total("2026-01-01"),
                  "daily": {f"{d[:4]}-{d[4:6]}-{d[6:]}": int(n) for (d,), (n,) in _run(s, {"dateRanges": [dall], "dimensions": [{"name": "date"}], "metrics": [{"name": "activeUsers"}]})}}
    out["calls"] = CALLS[0]
    try:   # keep only what this refresh used (old versions' questions drop out by themselves)
        json.dump(_KEEP_NEW, open(FCACHE, "w"), sort_keys=True)
    except Exception:
        pass
    return {"GA4 Game Lite": (pd.DataFrame([{"json": json.dumps(out)}]), None)}
