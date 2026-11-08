"""Firebase / Google Analytics 4 retention for the social report: day-1 and day-7 return rate of new players.
Key: Private Keys/ga4-token.json (analytics.readonly, made once with make_ga4_token.py). Property: beaker-lab (558070583)."""
import datetime as dt
import os

import pandas as pd
from google.auth.transport.requests import AuthorizedSession, Request
from google.oauth2.credentials import Credentials

PROPERTY = "558070583"
SCOPES = ["https://www.googleapis.com/auth/analytics.readonly"]


def _cohorts(s, start, end, nth):
    days = (end - start).days + 1
    body = {"dimensions": [{"name": "cohort"}, {"name": "cohortNthDay"}], "metrics": [{"name": "cohortActiveUsers"}],
            "cohortSpec": {"cohorts": [{"name": d.isoformat(), "dimension": "firstSessionDate",
                                        "dateRange": {"startDate": d.isoformat(), "endDate": d.isoformat()}}
                                       for d in (start + dt.timedelta(days=i) for i in range(days))],
                           "cohortsRange": {"granularity": "DAILY", "startOffset": 0, "endOffset": nth}}}
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
                "dimensionFilter": {"filter": {"fieldName": "firstSessionDate", "stringFilter": {"value": d.strftime("%Y%m%d")}}}}
        r = s.post(f"https://analyticsdata.googleapis.com/v1beta/properties/{PROPERTY}:runReport", json=body, timeout=60)
        if not r.ok:
            raise RuntimeError(f"GA4 {r.status_code}: {r.text[:200]}")
        back7 += sum(int(x["metricValues"][0]["value"]) for x in r.json().get("rows", []))
    r7 = round(back7 / n7 * 100, 1) if n7 else None
    return {"GA4 Retention Lite": (pd.DataFrame([{"d1": r1, "d1_n": n1, "d7": r7, "d7_n": n7}]), None)}
