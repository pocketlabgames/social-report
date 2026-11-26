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


def fetch(keys_dir, today):
    creds = Credentials.from_authorized_user_file(os.path.join(keys_dir, "ga4-token.json"), SCOPES)
    if not creds.valid:
        creds.refresh(Request())
    s = AuthorizedSession(creds)
    d1 = _cohorts(s, today - dt.timedelta(days=8), today - dt.timedelta(days=2), 1)     # last 7 complete day-1 cohorts
    d7 = _cohorts(s, today - dt.timedelta(days=14), today - dt.timedelta(days=8), 7)    # last 7 complete day-7 cohorts
    r1, n1 = _rate(d1, 1)
    # Guy, Nov 8: Day-7 = came back on day 7 OR LATER (distinct players), not "played exactly on day 7" (that showed 0% while 2 of 52 came back on day 8)
    n7 = sum(v.get(0, 0) for v in d7.values()); back7 = 0
    for c in d7:
        d = dt.date.fromisoformat(c)
        body = {"dateRanges": [{"startDate": (d + dt.timedelta(days=7)).isoformat(), "endDate": today.isoformat()}], "metrics": [{"name": "activeUsers"}],
                "dimensionFilter": {"andGroup": {"expressions": [{"filter": {"fieldName": "firstSessionDate", "stringFilter": {"value": d.strftime("%Y%m%d")}}}, NO_CT]}}}
        r = s.post(f"https://analyticsdata.googleapis.com/v1beta/properties/{PROPERTY}:runReport", json=body, timeout=60)
        if not r.ok:
            raise RuntimeError(f"GA4 {r.status_code}: {r.text[:200]}")
        back7 += sum(int(x["metricValues"][0]["value"]) for x in r.json().get("rows", []))
    r7 = round(back7 / n7 * 100, 1) if n7 else None
    # Guy, Nov 23: "Day-1 return" chart: every complete start day since Nov 1, same cohort question as the badge (7 days per question)
    days, d = {}, dt.date(2026, 11, 1)
    while d <= today - dt.timedelta(days=2):
        e = min(d + dt.timedelta(days=6), today - dt.timedelta(days=2))
        for c, v in _cohorts(s, d, e, 1).items():
            days[c] = [v.get(0, 0), v.get(1, 0)]
        d = e + dt.timedelta(days=1)
    return {"GA4 Retention Lite": (pd.DataFrame([{"d1": r1, "d1_n": n1, "d7": r7, "d7_n": n7, "d1days": json.dumps(days, sort_keys=True)}]), None)}
