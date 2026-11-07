"""Firebase / Google Analytics 4 game stats for the social report (Guy, Nov 2): players, furthest level, win rate, ads,
Super Stir / Super Solve and purchases. Only released builds count (1.3.1 up to the App Store's live version, from Nov 1). Only builds 1.3.1+ send these events (save 167 mirrors the game's TelemetryDeck
events to Firebase); custom dimensions level / outcome / kind / placement / max_level / has_everything exist from Nov 2.
Key: Private Keys/ga4-token.json (same as ga4_lite). Property: beaker-lab (558070583)."""
import datetime as dt
import json
import os
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
STEPS = list(range(1, 11)) + [11, 16, 21, 26, 31]   # Guy, Nov 6: "Where players stop" bars: levels 1-10 one by one, then steps of 5, then 31+
RELEASED = {"1.3.1": START, "1.3.2": dt.date(2026, 11, 4), "1.3.3": dt.date(2026, 11, 6)}   # App Store release days; later versions use Apple's date while live
COMPARE = (1, 3, 4)   # first version with the new-player changes; new players on it vs new players before it
EVENTS = ["level_end", "level_up", "ad_shown", "purchase_ok", "super_stir", "super_solve"]


def _run(s, body):
    r = s.post(f"https://analyticsdata.googleapis.com/v1beta/properties/{PROPERTY}:runReport", json=body, timeout=60)
    if not r.ok:
        raise RuntimeError(f"GA4 {r.status_code}: {r.text[:200]}")
    return [([d["value"] for d in row.get("dimensionValues", [])], [float(m["value"]) for m in row["metricValues"]]) for row in r.json().get("rows", [])]


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
            r = requests.get("https://itunes.apple.com/lookup", params={"id": APP_ID, "country": "us"}, timeout=20).json()["results"][0]
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
    d14, d7, dall = rng(14), rng(7, 1), rng(9999)   # d7 = last 7 complete days; dall = everything since Nov 1
    live, released = _live(keys_dir)
    first_day = lambda v: min((dt.date(int(d[:4]), int(d[4:6]), int(d[6:])) for (d,), (n,) in _run(s, {"dateRanges": [dall], "dimensions": [{"name": "date"}], "metrics": [{"name": "activeUsers"}], "dimensionFilter": {"filter": {"fieldName": "appVersion", "stringFilter": {"value": v}}}}) if n >= 5), default=None)   # first day a version had 5+ players
    released = released or first_day(".".join(map(str, live))) or today
    vers = [v[0] for v, _ in _run(s, {"dateRanges": [dall], "dimensions": [{"name": "appVersion"}], "metrics": [{"name": "activeUsers"}]}) if FIRST <= _ver(v[0]) <= live]
    out = {"versions": vers, "live": ".".join(map(str, live)), "daily": {}, "week": {}, "outcome": {}, "kind": {}, "reach": {}, "all": {}}
    if not vers:
        return {"GA4 Game Lite": (pd.DataFrame([{"json": json.dumps(out)}]), None)}
    newer = {"filter": {"fieldName": "appVersion", "inListFilter": {"values": vers}}}
    # Guy, Nov 4: before its release day a version only ran on review/test devices (1.3.2: 2 purchases, 14 Super Solves), so those days don't count.
    # Nov 6: this must hold for every version, not just the live one, or old test data comes back each time a new version ships.
    rel = lambda v: RELEASED.get(v) or (released if _ver(v) == live else first_day(v) or today)
    tests = [{"andGroup": {"expressions": [{"filter": {"fieldName": "appVersion", "stringFilter": {"value": v}}},
                                           {"filter": {"fieldName": "date", "inListFilter": {"values": pre}}}]}}
             for v in vers for pre in [[(START + dt.timedelta(days=i)).strftime("%Y%m%d") for i in range((rel(v) - START).days)]] if pre]
    if tests:
        newer = {"andGroup": {"expressions": [newer, {"notExpression": {"orGroup": {"expressions": tests}}}]}}
    for (d,), (n,) in _run(s, {"dateRanges": [d14], "dimensions": [{"name": "date"}], "metrics": [{"name": "activeUsers"}], "dimensionFilter": newer}):
        out["daily"].setdefault(f"{d[:4]}-{d[4:6]}-{d[6:]}", {})["players"] = int(n)
    evf = {"andGroup": {"expressions": [{"filter": {"fieldName": "eventName", "inListFilter": {"values": EVENTS}}}, newer]}}
    one = lambda name: {"andGroup": {"expressions": [ev(name), newer]}}
    for (d, e), (n,) in _run(s, {"dateRanges": [d14], "dimensions": [{"name": "date"}, {"name": "eventName"}], "metrics": [{"name": "eventCount"}], "dimensionFilter": evf}):
        out["daily"].setdefault(f"{d[:4]}-{d[4:6]}-{d[6:]}", {})[e] = int(n)
    wk = _run(s, {"dateRanges": [d7], "metrics": [{"name": "activeUsers"}], "dimensionFilter": newer})
    out["week"]["players"] = int(wk[0][1][0]) if wk else 0
    for (e,), (n,) in _run(s, {"dateRanges": [d7], "dimensions": [{"name": "eventName"}], "metrics": [{"name": "eventCount"}], "dimensionFilter": evf}):
        out["week"][e] = int(n)
    for (o,), (n,) in _run(s, {"dateRanges": [d7], "dimensions": [{"name": "customEvent:outcome"}], "metrics": [{"name": "eventCount"}], "dimensionFilter": one("level_end")}):
        if o != "(not set)":
            out["outcome"][o] = int(n)
    for (k,), (n,) in _run(s, {"dateRanges": [d7], "dimensions": [{"name": "customEvent:kind"}], "metrics": [{"name": "eventCount"}], "dimensionFilter": one("ad_shown")}):
        if k != "(not set)":
            out["kind"][k] = int(n)
    # Guy, Nov 4: a player whose furthest level changes shows up once per level in a by-level report (285 "players" vs 53 real),
    # so ask for each level how many different players reached it or beyond
    lvs = sorted(int(lv) for (lv,), _ in _run(s, {"dateRanges": [dall], "dimensions": [{"name": "customUser:max_level"}], "metrics": [{"name": "activeUsers"}], "dimensionFilter": newer, "limit": 1000}) if lv.isdigit())
    for lv in lvs:
        f = {"andGroup": {"expressions": [newer, {"filter": {"fieldName": "customUser:max_level", "inListFilter": {"values": [str(x) for x in lvs if x >= lv]}}}]}}
        r = _run(s, {"dateRanges": [{"startDate": dall["startDate"], "endDate": dall["endDate"]}], "metrics": [{"name": "activeUsers"}], "dimensionFilter": f})
        out["reach"][str(lv)] = int(r[0][1][0]) if r else 0
    # Guy, Nov 6: split each bar: played in the last 3 days (today + 2 before) = still playing; the rest of that bar has left
    reached = lambda base, dr, st: {str(lv): int(next(iter(_run(s, {"dateRanges": [dr], "metrics": [{"name": "activeUsers"}], "dimensionFilter": {"andGroup": {"expressions": [base, {"filter": {"fieldName": "customUser:max_level", "inListFilter": {"values": [str(x) for x in lvs if x >= lv]}}}]}}})), ([], [0]))[1][0]) for lv in st if any(x >= lv for x in lvs)}
    out["active"] = reached(newer, {"startDate": max(today - dt.timedelta(days=2), START).isoformat(), "endDate": today.isoformat()}, STEPS)
    # Guy, Nov 6: did 1.3.4 help? New players only (first opened the game after it came out) vs new players before it, so updaters with high levels don't flatter it
    cmp = {"version": ".".join(map(str, COMPARE)), "live": live >= COMPARE}
    if live >= COMPARE:
        since = released if live == COMPARE else None
        since = since or first_day(cmp["version"])   # a later version is live, so Apple only gives that one's date
        if since:
            dates = lambda a, b: [(a + dt.timedelta(days=i)).strftime("%Y%m%d") for i in range((b - a).days + 1)]
            group = lambda vs, ds: {"andGroup": {"expressions": [newer, {"filter": {"fieldName": "appVersion", "inListFilter": {"values": vs}}}, {"filter": {"fieldName": "firstSessionDate", "inListFilter": {"values": ds}}}]}}
            cmp["since"] = since.isoformat()
            cmp["new"] = reached(group([v for v in vers if _ver(v) >= COMPARE], dates(since, today)), dall, STEPS)
            cmp["old"] = reached(group([v for v in vers if _ver(v) < COMPARE], dates(START, since - dt.timedelta(days=1))), dall, STEPS)
    out["compare"] = cmp
    # active players on every app version (the game events above only come from 1.3.1+)
    span = lambda a: {"startDate": a, "endDate": today.isoformat()}
    total = lambda a: int(next(iter(_run(s, {"dateRanges": [span(a)], "metrics": [{"name": "activeUsers"}]})), ([], [0]))[1][0])
    out["all"] = {"today": total(today.isoformat()), "week": total((today - dt.timedelta(days=6)).isoformat()), "ever": total("2026-01-01"),
                  "daily": {f"{d[:4]}-{d[4:6]}-{d[6:]}": int(n) for (d,), (n,) in _run(s, {"dateRanges": [d14], "dimensions": [{"name": "date"}], "metrics": [{"name": "activeUsers"}]})}}
    return {"GA4 Game Lite": (pd.DataFrame([{"json": json.dumps(out)}]), None)}
