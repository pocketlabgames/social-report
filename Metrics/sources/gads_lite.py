"""Google Ads spend per day (all campaigns), for the social report chart. Cached in Metrics/gads-cache.json.
Keys (Private Keys, also in the KEYS_TGZ secret): googleads-token.json (OAuth token incl. refresh token) + googleads-developer-token.txt."""
import datetime as dt
import json
import os

import pandas as pd
from google.auth.transport.requests import AuthorizedSession, Request
from google.oauth2.credentials import Credentials

SCOPES = ["https://www.googleapis.com/auth/adwords"]
VERSIONS = ["v24", "v23", "v22", "v21"]
CUSTOMER = "8121668766"   # Beaker Lab
START = dt.date(2026, 9, 26)
CACHE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "gads-cache.json")


def fetch(keys_dir, today):
    creds = Credentials.from_authorized_user_file(os.path.join(keys_dir, "googleads-token.json"), SCOPES)
    if not creds.valid:
        creds.refresh(Request())
    s = AuthorizedSession(creds)
    s.headers.update({"developer-token": open(os.path.join(keys_dir, "googleads-developer-token.txt")).read().strip()})
    cache = json.load(open(CACHE)) if os.path.exists(CACHE) else {}
    start = START if not cache else min(dt.date.fromisoformat(max(cache)) - dt.timedelta(days=3), today)
    q = f"SELECT segments.date, metrics.cost_micros FROM campaign WHERE segments.date BETWEEN '{start}' AND '{today}'"
    r = None
    for v in VERSIONS:
        r = s.post(f"https://googleads.googleapis.com/{v}/customers/{CUSTOMER}/googleAds:searchStream", json={"query": q}, timeout=120)
        if r.status_code != 404:
            break
    if not r.ok:
        raise RuntimeError(f"Google Ads {r.status_code}: {r.text[:200]}")
    got = {}
    for batch in r.json():
        for x in batch.get("results", []):
            d = x["segments"]["date"]
            got[d] = got.get(d, 0) + int(x.get("metrics", {}).get("costMicros", 0)) / 1e6
    d = start
    while d <= today:   # days with no rows = $0 spent
        cache[d.isoformat()] = round(got.get(d.isoformat(), 0.0), 2)
        d += dt.timedelta(days=1)
    json.dump(cache, open(CACHE, "w"), indent=0, sort_keys=True)
    return {"GAds Spend Lite": (pd.DataFrame({"date": sorted(cache), "spend": [cache[k] for k in sorted(cache)]}), ["date"])}
