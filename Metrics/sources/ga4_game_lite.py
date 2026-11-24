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
VX = [((1, 3, 18), (1, 3, 23), "1.3.18 to 1.3.23"), ((1, 4, 0), None, None)]   # Guy, Nov 24: 1.3.18 to 1.3.23 grouped, new 1.4.0+ (was 1.3.18/19 and 1.3.20+, Nov 22); only an open-ended option has a +; each option shows once that version is on the App Store (vers stops at the live version), until then "vxnext" lists its label for the Day-1 chart
QS_FROM = dt.date(2026, 11, 25)   # Guy, Nov 24: "track the quiet start update made today" (live config, done Nov 24 10:13 AM ET; that day is in neither group)
QS_BEFORE = (dt.date(2026, 11, 21), dt.date(2026, 11, 23))   # before = new players on 1.3.20+ on these first days
COMPARE = (1, 3, 20)   # Guy, Nov 21: "Did 1.3.20+ help?" vs 1.3.11+ (1.3.11 to 1.3.19); Nov 20 was 1.3.18; was 1.3.11 vs before.
BASE = (1, 3, 11)   # reference line: new players who started on BASE..COMPARE-1, from BASE's release to the day before COMPARE's
# Guy, Nov 16: "Did 1.3.11 help?" (was 1.3.4); first version with the new-player changes; new players on it vs new players before it
EVENTS = ["level_end", "level_up", "ad_shown", "purchase_ok", "super_stir", "super_solve"]


NO_CT = {"andGroup": {"expressions": [{"notExpression": {"filter": {"fieldName": "region", "stringFilter": {"value": "Connecticut"}}}},
                                      {"notExpression": {"filter": {"fieldName": "deviceModel", "stringFilter": {"matchType": "BEGINS_WITH", "value": "iPhone99,"}}}},   # Guy, Nov 24 "remove test devices": Apple test devices (model not sold)
                                      {"notExpression": {"filter": {"fieldName": "operatingSystemVersion", "stringFilter": {"matchType": "EXACT", "value": "27.1"}}}}]}}   # iOS 27.1: 0 App Store downloads ever (27.2 has 86), all US   # Guy, Nov 21: Connecticut = Guy's own test plays (11 of 12 "1.3.20 players"); left out of every game stat


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


def _back(s, days, flt, until=None):
    """Guy, Nov 24: new players of each first day (YYYYMMDD) who played the next day, tied to the version they STARTED on (funnel: step 1 = first
    day on these versions, step 2 = next day). Before, anyone with that first day who came back on these or later versions was counted, so players
    who started on 1.3.18/19 were added to "1.3.11 to 1.3.17" (29 shown, really 16). With until = day 7 OR LATER, up to that day (Day-7 tiles)."""
    from concurrent.futures import ThreadPoolExecutor

    def ask(d):
        d0 = dt.datetime.strptime(d, "%Y%m%d").date()
        a, n = d0 + dt.timedelta(days=7 if until else 1), until or d0 + dt.timedelta(days=1)
        ret = [(a + dt.timedelta(days=i)).strftime("%Y%m%d") for i in range((n - a).days + 1)]
        on = lambda f, v: {"filter": {"fieldName": f, "stringFilter": {"value": v}}}
        step1 = {"andGroup": {"expressions": [flt, on("firstSessionDate", d), on("date", d), NO_CT]}}
        body = {"dateRanges": [{"startDate": f"{d[:4]}-{d[4:6]}-{d[6:]}", "endDate": n.isoformat()}],
                "funnel": {"steps": [{"name": "start", "filterExpression": _ff(step1)}, {"name": "back", "filterExpression": _ff({"filter": {"fieldName": "date", "inListFilter": {"values": ret}}})}]}}
        key = json.dumps(body, sort_keys=True)
        if key not in _BACK:
            for wait in (2, 5, 10, 0):
                r = _post(s, f"https://analyticsdata.googleapis.com/v1alpha/properties/{PROPERTY}:runFunnelReport", json=body, timeout=60)
                if r.ok or r.status_code not in (429, 500, 503) or not wait:
                    break
                time.sleep(wait)
            if not r.ok:
                raise RuntimeError(f"GA4 funnel {r.status_code}: {r.text[:200]}")
            _BACK[key] = {row["dimensionValues"][0]["value"][:1]: int(row["metricValues"][0]["value"]) for row in r.json().get("funnelTable", {}).get("rows", [])}.get("2", 0)
        return _BACK[key]
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
    def reached(base, dr, st):
        ks = [lv for lv in st if any(x >= lv for x in lvs)]
        rs = _many(s, [{"dateRanges": [dr], "metrics": [{"name": "activeUsers"}], "dimensionFilter": {"andGroup": {"expressions": [base, {"filter": {"fieldName": "customUser:max_level", "inListFilter": {"values": [str(x) for x in lvs if x >= lv]}}}]}}} for lv in ks])
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
            cmp["new"] = reached(group([v for v in vers if _ver(v) >= COMPARE], dates(since, today)), dall, STEPS)
            b0 = RELEASED.get(".".join(map(str, BASE))) or START
            cmp["base"], cmp["bsince"] = ".".join(map(str, BASE)), b0.isoformat()
            cmp["old"] = reached(group([v for v in vers if BASE <= _ver(v) < COMPARE], dates(b0, since - dt.timedelta(days=1))), dall, STEPS)
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
    def remind(fil, since, until):
        days = [(since + dt.timedelta(days=i)).strftime("%Y%m%d") for i in range((until - since).days + 1)]
        co = {"andGroup": {"expressions": [fil, {"filter": {"fieldName": "firstSessionDate", "inListFilter": {"values": days}}}]}}
        n1 = lambda dr, f: int(next(iter(_run(s, {"dateRanges": [dr], "metrics": [{"name": "totalUsers"}], "dimensionFilter": f})), ([], [0]))[1][0])
        win, upto = {"startDate": since.isoformat(), "endDate": until.isoformat()}, {"startDate": since.isoformat(), "endDate": today.isoformat()}
        evs = lambda names: {"andGroup": {"expressions": [co, {"filter": {"fieldName": "eventName", "inListFilter": {"values": names}}}]}}
        by = {e: int(u) for (e,), (u,) in _run(s, {"dateRanges": [upto], "dimensions": [{"name": "eventName"}], "metrics": [{"name": "totalUsers"}], "dimensionFilter": evs(R_ON + R_OFF)})}
        return {"new": n1(win, co), "on": n1(upto, evs(R_ON)), "off": n1(upto, evs(R_OFF)), "quiet": by.get("soft_provisional", 0), "yes": by.get("remind_allow", 0) + by.get("soft_authorized", 0)}
    out["remind"] = remind(newer, max(today - dt.timedelta(days=6), START), today)
    # Guy, Nov 16: the same tiles for the newest versions only (1.3.11+), from the first one's release day to today
    # Guy, Nov 19: and for the versions before 1.3.11, over the same number of days just before 1.3.11 came out (each 1.3.11+ tile compares to it)
    def day1_l10(fil, since, until):   # Guy, Nov 24: "add the level 10 card": new players whose next level was 10+ by the end of their first day; complete days only
        c = min(until, today - dt.timedelta(days=1))
        if c < since:
            return None
        ds = [(since + dt.timedelta(days=i)).strftime("%Y%m%d") for i in range((c - since).days + 1)]
        ask = lambda *x: sum(int(n) for (d, d2), (n,) in _run(s, {"dateRanges": [{"startDate": since.isoformat(), "endDate": c.isoformat()}], "dimensions": [{"name": "firstSessionDate"}, {"name": "date"}], "metrics": [{"name": "activeUsers"}],
              "dimensionFilter": {"andGroup": {"expressions": [fil, {"filter": {"fieldName": "firstSessionDate", "inListFilter": {"values": ds}}}, *x]}}, "limit": 10000}) if d == d2)
        hi = [str(x) for x in lvs if x >= 10]
        return [ask({"filter": {"fieldName": "customUser:max_level", "inListFilter": {"values": hi}}}) if hi else 0, ask(), since.isoformat(), c.isoformat()]
    out["l10"] = day1_l10(newer, START, today)

    def block(vf, since, until, label, new=False):
        vfil = {"andGroup": {"expressions": [newer, {"filter": {"fieldName": "appVersion", "inListFilter": {"values": vf}}}]}}   # newer already drops pre-release test days
        if new:   # Guy, Nov 22: Players filter "New" = players whose first day falls in this view's days
            vfil = {"andGroup": {"expressions": [vfil, {"filter": {"fieldName": "firstSessionDate", "inListFilter": {"values": [(since + dt.timedelta(days=i)).strftime("%Y%m%d") for i in range((until - since).days + 1)]}}}]}}
        dr = {"startDate": since.isoformat(), "endDate": until.isoformat()}
        one2 = lambda name: {"andGroup": {"expressions": [ev(name), vfil]}}
        B = {"label": label, "vers": vf, "since": since.isoformat(), "until": until.isoformat(), "week": {}, "outcome": {}, "kind": {}, "shares": {"by": {}}, "moves": {}, "reach": {}}
        r = _run(s, {"dateRanges": [dr], "metrics": [{"name": "activeUsers"}], "dimensionFilter": vfil})
        B["week"]["players"] = int(r[0][1][0]) if r else 0
        r = _run(s, {"dateRanges": [{"startDate": today.isoformat(), "endDate": today.isoformat()}], "metrics": [{"name": "activeUsers"}], "dimensionFilter": vfil})
        B["today"] = int(r[0][1][0]) if r else 0
        for (e,), (n,) in _run(s, {"dateRanges": [dr], "dimensions": [{"name": "eventName"}], "metrics": [{"name": "eventCount"}], "dimensionFilter": {"andGroup": {"expressions": [{"filter": {"fieldName": "eventName", "inListFilter": {"values": EVENTS}}}, vfil]}}}):
            B["week"][e] = int(n)
        B["week"].update(_supers(s, dr, vfil))   # Guy, Nov 22: tutorial uses left out
        for (o,), (n,) in _run(s, {"dateRanges": [dr], "dimensions": [{"name": "customEvent:outcome"}], "metrics": [{"name": "eventCount"}], "dimensionFilter": one2("level_end")}):
            if o not in ("(not set)", ""):
                B["outcome"][o] = int(n)
        for (k,), (n,) in _run(s, {"dateRanges": [dr], "dimensions": [{"name": "customEvent:kind"}], "metrics": [{"name": "eventCount"}], "dimensionFilter": one2("ad_shown")}):
            if k not in ("(not set)", ""):
                B["kind"][k] = int(n)
        for (k,), (c, u) in _run(s, {"dateRanges": [dr], "dimensions": [{"name": "customEvent:kind"}], "metrics": [{"name": "eventCount"}, {"name": "totalUsers"}], "dimensionFilter": one2("share_done")}):
            B["shares"]["by"][k] = int(c)
        r = _run(s, {"dateRanges": [dr], "metrics": [{"name": "eventCount"}, {"name": "totalUsers"}], "dimensionFilter": one2("share_done")})
        B["shares"]["n"], B["shares"]["players"] = (int(r[0][1][0]), int(r[0][1][1])) if r else (0, 0)
        for e in ("rewarded_offer_shown", "rewarded_watched"):
            f = {"andGroup": {"expressions": [one2(e), {"filter": {"fieldName": "customEvent:placement", "stringFilter": {"value": "out_of_moves"}}}]}}
            r = _run(s, {"dateRanges": [dr], "metrics": [{"name": "eventCount"}, {"name": "totalUsers"}], "dimensionFilter": f})
            B["moves"][e] = [int(r[0][1][0]), int(r[0][1][1])] if r else [0, 0]
        vl = sorted(int(lv) for (lv,), _ in _run(s, {"dateRanges": [dr], "dimensions": [{"name": "customUser:max_level"}], "metrics": [{"name": "activeUsers"}], "dimensionFilter": vfil, "limit": 1000}) if lv.isdigit())
        ask = lambda lv: int((_run(s, {"dateRanges": [dr], "metrics": [{"name": "activeUsers"}], "dimensionFilter": {"andGroup": {"expressions": [vfil, {"filter": {"fieldName": "customUser:max_level", "inListFilter": {"values": [str(x) for x in vl if x >= lv]}}}]}}}) or [([], [0])])[0][1][0])
        if vl:
            B["reach"][str(vl[0])] = top = ask(vl[0])
            if len(vl) > 1:
                B["reach"][str(vl[-1])] = ask(vl[-1])   # "top player" on the tile
            lo, hi = 0, len(vl)   # middle player only (the tile shows nothing else): halve the range instead of asking every level
            while hi - lo > 1:
                m = (lo + hi) // 2; n = B["reach"][str(vl[m])] = ask(vl[m])
                if n * 2 >= top: lo = m
                else: hi = m
        B["freach"] = reached(vfil, dr, STEPS)   # Guy, Nov 16: "How far players get" for the newest versions (players who reached each step)
        B["factive"] = reached(vfil, {"startDate": max(until - dt.timedelta(days=QUIT_DAYS - 1), since).isoformat(), "endDate": until.isoformat()}, STEPS)   # still playing = played in the last QUIT_DAYS - 1 days
        B["lv"] = {}   # Guy, Nov 16: win rate per level for the newest versions too
        lvf2 = {"andGroup": {"expressions": [vfil, {"filter": {"fieldName": "eventName", "stringFilter": {"matchType": "BEGINS_WITH", "value": "lv_"}}}]}}
        for (e,), (u, c) in _run(s, {"dateRanges": [dr], "dimensions": [{"name": "eventName"}], "metrics": [{"name": "totalUsers"}, {"name": "eventCount"}], "dimensionFilter": lvf2}):
            kind, _, n = e.rpartition("_")
            if kind in ("lv_start", "lv_win") and n.isdigit():
                row = B["lv"].setdefault(n, {})
                row[kind[3:]], row[kind[3:] + "s"] = int(u), int(c)
        B["remind"] = remind(vfil, since, until)
        B["l10"] = day1_l10(vfil, since, until)
        # Guy, Nov 19: Day-1 return = new players (first day on these versions) who played again the very next day; complete days only
        c_end = min(until, today - dt.timedelta(days=2))
        if c_end >= since:
            cd = lambda a, b: [(a + dt.timedelta(days=i)).strftime("%Y%m%d") for i in range((b - a).days + 1)]
            base = {d: int(n) for (d, d2), (n,) in _run(s, {"dateRanges": [{"startDate": since.isoformat(), "endDate": c_end.isoformat()}], "dimensions": [{"name": "firstSessionDate"}, {"name": "date"}], "metrics": [{"name": "activeUsers"}],
                    "dimensionFilter": {"andGroup": {"expressions": [vfil, {"filter": {"fieldName": "firstSessionDate", "inListFilter": {"values": cd(since, c_end)}}}]}}, "limit": 10000}) if d == d2}
            back = {d: min(n, base[d]) for d, n in _back(s, list(base), vfil).items()}   # Guy, Nov 24: only players who started on these versions
            B["d1"] = [sum(back.get(d, 0) for d in base), sum(base.values()), since.isoformat(), c_end.isoformat()]
            # Guy, Nov 22: "Day-1 return by version" chart: the same players split by Google Ads (firstUserMedium cpc) vs everyone else
            B["d1src"] = {}
            for med, mf in (("ads", {"filter": {"fieldName": "firstUserMedium", "stringFilter": {"value": "cpc"}}}), ("other", {"notExpression": {"filter": {"fieldName": "firstUserMedium", "stringFilter": {"value": "cpc"}}}})):
                b2 = {d: int(n) for (d, d2), (n,) in _run(s, {"dateRanges": [{"startDate": since.isoformat(), "endDate": c_end.isoformat()}], "dimensions": [{"name": "firstSessionDate"}, {"name": "date"}], "metrics": [{"name": "activeUsers"}],
                      "dimensionFilter": {"andGroup": {"expressions": [vfil, mf, {"filter": {"fieldName": "firstSessionDate", "inListFilter": {"values": cd(since, c_end)}}}]}}, "limit": 10000}) if d == d2}
                k2 = {d: min(n, b2[d]) for d, n in _back(s, list(b2), {"andGroup": {"expressions": [vfil, mf]}}).items()}
                B["d1src"][med] = [sum(k2.get(d, 0) for d in b2), sum(b2.values())]
        # Guy, Nov 21: "add d-7 after d-1 card". Day-7 return = new players (first day on these versions) who played again on day 7 OR LATER
        # (same rule as the all-versions Day-7, Guy Nov 8); only first days with a complete day 7 (first day <= today - 8)
        c7 = min(until, today - dt.timedelta(days=8))
        if c7 >= since:
            cd7 = [(since + dt.timedelta(days=i)) for i in range((c7 - since).days + 1)]
            base7 = {d: int(n) for (d, d2), (n,) in _run(s, {"dateRanges": [{"startDate": since.isoformat(), "endDate": c7.isoformat()}], "dimensions": [{"name": "firstSessionDate"}, {"name": "date"}], "metrics": [{"name": "activeUsers"}],
                     "dimensionFilter": {"andGroup": {"expressions": [vfil, {"filter": {"fieldName": "firstSessionDate", "inListFilter": {"values": [x.strftime("%Y%m%d") for x in cd7]}}}]}}, "limit": 10000}) if d == d2}
            days7 = [x for x in cd7 if base7.get(x.strftime("%Y%m%d"))]
            b7 = _back(s, [x.strftime("%Y%m%d") for x in days7], vfil, until=today)   # Guy, Nov 24: only players who started on these versions
            B["d7"] = [sum(min(n, base7[d]) for d, n in b7.items()), sum(base7.values()), since.isoformat(), c7.isoformat()]
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
    def quiet(vs, a, b):   # one row of the Quiet start card: new players' first day (complete days), and the next day
        ds = [(a + dt.timedelta(days=i)).strftime("%Y%m%d") for i in range((b - a).days + 1)]
        if not vs or not ds:
            return {"n": 0}
        fil = {"andGroup": {"expressions": [newer, {"filter": {"fieldName": "appVersion", "inListFilter": {"values": vs}}}]}}
        E = ["lv_win_1", "lv_win_2", "lv_win_3", "lv_win_7"]
        r = _run(s, {"dateRanges": [{"startDate": a.isoformat(), "endDate": b.isoformat()}], "dimensions": [{"name": "firstSessionDate"}, {"name": "date"}, {"name": "eventName"}], "metrics": [{"name": "totalUsers"}], "limit": 10000,
                     "dimensionFilter": {"andGroup": {"expressions": [fil, {"filter": {"fieldName": "firstSessionDate", "inListFilter": {"values": ds}}}, {"filter": {"fieldName": "eventName", "inListFilter": {"values": E}}}]}}})
        l10 = day1_l10(fil, a, b)
        base = {d: int(n) for (d, d2), (n,) in _run(s, {"dateRanges": [{"startDate": a.isoformat(), "endDate": b.isoformat()}], "dimensions": [{"name": "firstSessionDate"}, {"name": "date"}], "metrics": [{"name": "activeUsers"}], "limit": 10000,
                "dimensionFilter": {"andGroup": {"expressions": [fil, {"filter": {"fieldName": "firstSessionDate", "inListFilter": {"values": ds}}}]}}}) if d == d2}
        nx = [d for d in base if d <= (today - dt.timedelta(days=2)).strftime("%Y%m%d")]
        bk = _back(s, nx, fil)
        return {"n": l10[1], "l10": l10[0], "w": {e[7:]: sum(int(n) for (d, d2, x), (n,) in r if d == d2 and x == e) for e in E},
                "back": [sum(min(bk[d], base[d]) for d in nx), sum(base[d] for d in nx)], "a": a.isoformat(), "b": b.isoformat()}
    with ThreadPoolExecutor(12) as ex:
        yday = today - dt.timedelta(days=1)
        Q = {"before": ex.submit(quiet, [v for v in vers if (1, 3, 20) <= _ver(v) < (1, 4, 0)], *QS_BEFORE),
             "after": ex.submit(quiet, [v for v in vers if (1, 3, 20) <= _ver(v) < (1, 4, 0)], QS_FROM, yday),
             "after140": ex.submit(quiet, [v for v in vers if _ver(v) >= (1, 4, 0)], QS_FROM, yday)}
        F = {k: ex.submit(block, *v) for k, v in J.items()}
        # Guy, Nov 22: "Players (all, new)" filter: the same tile sets for new players only (first day in each view's days)
        N = {"all": ex.submit(block, vers, max(today - dt.timedelta(days=6), START), today, "All versions", True)}
        N.update({k: ex.submit(block, *v, True) for k, v in J.items()})
    out["quiet"] = {k: f.result() for k, f in Q.items()}
    for k in ("vf", "pre"):
        if k in F:
            out[k] = F[k].result()
    out["vx"] = {k: {**F[k].result(), "range": R[k]} for k in R}
    out["vxnext"] = [L or ".".join(map(str, X)) + "+" for X, H, L in VX if X > live]   # Guy, Nov 24: groups not on the App Store yet (1.4.0+)
    out["new"] = {k: f.result() for k, f in N.items()}
    # active players on every app version (the game events above only come from 1.3.1+)
    span = lambda a: {"startDate": a, "endDate": today.isoformat()}
    total = lambda a: int(next(iter(_run(s, {"dateRanges": [span(a)], "metrics": [{"name": "activeUsers"}]})), ([], [0]))[1][0])
    out["all"] = {"today": total(today.isoformat()), "week": total((today - dt.timedelta(days=6)).isoformat()), "m30": total((today - dt.timedelta(days=29)).isoformat()), "ever": total("2026-01-01"),
                  "daily": {f"{d[:4]}-{d[4:6]}-{d[6:]}": int(n) for (d,), (n,) in _run(s, {"dateRanges": [dall], "dimensions": [{"name": "date"}], "metrics": [{"name": "activeUsers"}]})}}
    out["calls"] = CALLS[0]
    return {"GA4 Game Lite": (pd.DataFrame([{"json": json.dumps(out)}]), None)}
