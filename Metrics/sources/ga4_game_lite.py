"""Firebase / Google Analytics 4 game stats for the social report (Guy, Nov 2): players, furthest level, win rate, ads,
Super Stir / Super Solve and purchases. Only released builds count (1.3.1 up to the App Store's live version, from Nov 1). Only builds 1.3.1+ send these events (save 167 mirrors the game's TelemetryDeck
events to Firebase); custom dimensions level / outcome / kind / placement / max_level / has_everything exist from Nov 2.
Key: Private Keys/ga4-token.json (same as ga4_lite). Property: beaker-lab (558070583)."""
import datetime as dt
import json
import os

import pandas as pd
import requests
from google.auth.transport.requests import AuthorizedSession, Request
from google.oauth2.credentials import Credentials

PROPERTY = "558070583"
SCOPES = ["https://www.googleapis.com/auth/analytics.readonly"]
FIRST = (1, 3, 1)   # first app version that sends the game events
START = dt.date(2026, 11, 1)   # 1.3.1 went live Nov 1; earlier days were test devices only (Guy, Nov 2)
APP_ID = "6816478290"
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


def _live():
    """Version on the App Store now; builds newer than this (in review / TestFlight) are test devices, so they're left out."""
    try:
        return _ver(requests.get("https://itunes.apple.com/lookup", params={"id": APP_ID, "country": "us"}, timeout=20).json()["results"][0]["version"])
    except Exception:
        return FIRST


def fetch(keys_dir, today):
    creds = Credentials.from_authorized_user_file(os.path.join(keys_dir, "ga4-token.json"), SCOPES)
    if not creds.valid:
        creds.refresh(Request())
    s = AuthorizedSession(creds)
    rng = lambda days, end=0: {"startDate": max(today - dt.timedelta(days=days), START).isoformat(), "endDate": max(today - dt.timedelta(days=end), START).isoformat()}
    ev = lambda name: {"filter": {"fieldName": "eventName", "stringFilter": {"value": name}}}
    d14, d7, d28 = rng(14), rng(7, 1), rng(28)   # d7 = last 7 complete days; none start before Nov 1
    live = _live()
    vers = [v[0] for v, _ in _run(s, {"dateRanges": [d28], "dimensions": [{"name": "appVersion"}], "metrics": [{"name": "activeUsers"}]}) if FIRST <= _ver(v[0]) <= live]
    out = {"versions": vers, "live": ".".join(map(str, live)), "daily": {}, "week": {}, "outcome": {}, "kind": {}, "max_level": {}}
    if not vers:
        return {"GA4 Game Lite": (pd.DataFrame([{"json": json.dumps(out)}]), None)}
    newer = {"filter": {"fieldName": "appVersion", "inListFilter": {"values": vers}}}
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
    for (lv,), (n,) in _run(s, {"dateRanges": [d28], "dimensions": [{"name": "customUser:max_level"}], "metrics": [{"name": "activeUsers"}], "dimensionFilter": newer}):
        if lv.isdigit():
            out["max_level"][lv] = int(n)
    return {"GA4 Game Lite": (pd.DataFrame([{"json": json.dumps(out)}]), None)}
