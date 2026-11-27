"""Firebase / Google Analytics 4 retention for the social report: day-1 and day-7 return rate of new players.
Key: Private Keys/ga4-token.json (analytics.readonly, made once with make_ga4_token.py). Property: beaker-lab (558070583)."""
import datetime as dt
import json
import os

import pandas as pd
from google.auth.transport.requests import AuthorizedSession, Request
from google.oauth2.credentials import Credentials

PROPERTY = "558070583"
SCOPES = ["https://www.googleapis.com/auth/analytics.readonly"]


NO_CT = {"andGroup": {"expressions": [{"notExpression": {"filter": {"fieldName": "region", "stringFilter": {"value": "Connecticut"}}}}, {"notExpression": {"filter": {"fieldName": "region", "stringFilter": {"value": "California"}}}},   # Guy, Nov 25 2026 "yes, for now": California left out (looks like Apple review devices on normal models; 15 started level 1, 3 won, Nov 19-25)
                                     
                                      {"notExpression": {"filter": {"fieldName": "deviceModel", "stringFilter": {"matchType": "BEGINS_WITH", "value": "iPhone99,"}}}},   # Guy, Nov 24 "remove test devices": Apple test devices (model not sold)
                                      {"notExpression": {"filter": {"fieldName": "operatingSystemVersion", "stringFilter": {"matchType": "EXACT", "value": "27.1"}}}}]}}   # iOS 27.1: 0 App Store downloads ever (27.2 has 86), all US   # Guy, Nov 21: his own test plays


def _cohorts(s, start, end, nth):
    days = (end - start).days + 1
    body = {"dimensions": [{"name": "cohort"}, {"name": "cohortNthDay"}], "metrics": [{"name": "cohortActiveUsers"}],
            "cohortSpec": {"cohorts": [{"name": d.isoformat(), "dimension": "firstSessionDate",
                                        "dateRange": {"startDate": d.isoformat(), "endDate": d.isoformat()}}
                                       for d in (start + dt.timedelta(days=i) for i in range(days))],
                           "cohortsRange": {"granularity": "DAILY", "startOffset": 0, "endOffset": nth}}, "dimensionFilter": NO_CT}   # Guy, Nov 21: Connecticut = Guy testing, left out
    r = s.post(f"https://analyticsdata.googleapis.com/v1beta/properties/{PROPERTY}:runReport", json=body, timeout=60)
    if not r.ok:
        raise RuntimeError(f"GA4 {r.status_code}: {r.text[:200]}")
    out = {}
    for row in r.json().get("rows", []):
        c, n = row["dimensionValues"][0]["value"], int(row["dimensionValues"][1]["value"])
        out.setdefault(c, {})[n] = int(row["metricValues"][0]["value"])
    return out


def _rate(data, n):
    base = sum(v.get(0, 0) for v in data.values()); back = sum(v.get(n, 0) for v in data.values())
    return (round(back / base * 100, 1), base) if base else (None, 0)


# Guy, Nov 27 2026 ("fix other areas of social report that have this bug too"): new player = first day AND played level 1 that day (L1, see
# ga4_game_lite); reinstalls that got their saved progress back opened past level 1 and were counted as new. Funnel per first day:
# step 1 = L1 on the first day, step 2 = played on the day(s) after. Replaces the cohort question (which had no way to require level 1).
from .ga4_game_lite import L1, _ff


def _fun(s, d, back_days):
    on = lambda f, v: {"filter": {"fieldName": f, "stringFilter": {"value": v}}}
    k = d.strftime("%Y%m%d")
    s1 = {"andGroup": {"expressions": [on("firstSessionDate", k), on("date", k), L1, NO_CT]}}
    s2 = {"filter": {"fieldName": "date", "inListFilter": {"values": [x.strftime("%Y%m%d") for x in back_days]}}}
    body = {"dateRanges": [{"startDate": d.isoformat(), "endDate": back_days[-1].isoformat()}], "funnel": {"steps": [{"name": "a", "filterExpression": _ff(s1)}, {"name": "b", "filterExpression": _ff(s2)}]}}
    for wait in (2, 5, 10, 0):
        r = s.post(f"https://analyticsdata.googleapis.com/v1alpha/properties/{PROPERTY}:runFunnelReport", json=body, timeout=60)
        if r.ok or r.status_code not in (429, 500, 503) or not wait:
            break
        import time; time.sleep(wait)
    if not r.ok:
        raise RuntimeError(f"GA4 funnel {r.status_code}: {r.text[:200]}")
    q = {row["dimensionValues"][0]["value"].split(".")[0]: int(row["metricValues"][0]["value"]) for row in r.json().get("funnelTable", {}).get("rows", [])}
    return q.get("1", 0), q.get("2", 0)


def fetch(keys_dir, today):
    from concurrent.futures import ThreadPoolExecutor
    creds = Credentials.from_authorized_user_file(os.path.join(keys_dir, "ga4-token.json"), SCOPES)
    if not creds.valid:
        creds.refresh(Request())
    s = AuthorizedSession(creds)
    span = lambda a, b: [a + dt.timedelta(days=i) for i in range((b - a).days + 1)]
    d1days = span(dt.date(2026, 11, 1), today - dt.timedelta(days=2))   # every complete start day since Nov 1 (chart) incl. the last 7 (badge)
    d7days = span(today - dt.timedelta(days=14), today - dt.timedelta(days=8))
    with ThreadPoolExecutor(6) as ex:
        one = dict(zip(d1days, ex.map(lambda d: _fun(s, d, [d + dt.timedelta(days=1)]), d1days)))
        seven = dict(zip(d7days, ex.map(lambda d: _fun(s, d, span(d + dt.timedelta(days=7), today)), d7days)))   # Guy, Nov 8: day 7 OR LATER
    last7 = [one[d] for d in d1days if d >= today - dt.timedelta(days=8)]
    n1, b1 = sum(x[0] for x in last7), sum(x[1] for x in last7)
    n7, b7 = sum(x[0] for x in seven.values()), sum(x[1] for x in seven.values())
    r1 = round(b1 / n1 * 100, 1) if n1 else None
    r7 = round(b7 / n7 * 100, 1) if n7 else None
    days = {d.isoformat(): [v[0], v[1]] for d, v in one.items()}
    return {"GA4 Retention Lite": (pd.DataFrame([{"d1": r1, "d1_n": n1, "d7": r7, "d7_n": n7, "d1days": json.dumps(days, sort_keys=True)}]), None)}
