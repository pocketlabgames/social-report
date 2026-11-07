"""Money for the social report: AdMob estimated earnings per day (networkReport, USD) and App Store proceeds per day
(Apple SALES/SUMMARY 'Developer Proceeds' for in-app purchases and paid units; other currencies converted to US dollars at that day's European Central Bank rate, so the figure is close to what Apple pays, not exact).
Keys: Private Keys/youtube-oauth-client.json + admob-token.json (same as sources/admob.py) and asc-metrics.json + .p8.
Cached per day in Metrics/money-cache.json; only missing days and the last 3 are re-fetched."""
import datetime as dt
import gzip
import io
import json
import os
import time

import jwt
import pandas as pd
import requests
from google.auth.transport.requests import AuthorizedSession, Request
from google.oauth2.credentials import Credentials

LAUNCH = dt.date(2026, 9, 26)
CACHE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "money-cache.json")
ADMOB = "https://admob.googleapis.com/v1/"
ASC = "https://api.appstoreconnect.apple.com"
IAP_TYPES = {"IA1", "IA9", "IAY", "IAC", "FI1", "1", "1F", "1T"}   # in-app purchases, subscriptions, paid downloads


def _admob(keys_dir, start, end):
    """{date: usd} from AdMob for start..end."""
    tok = os.path.join(keys_dir, "admob-token.json")
    creds = Credentials.from_authorized_user_file(tok, ["https://www.googleapis.com/auth/admob.readonly", "https://www.googleapis.com/auth/admob.report"])
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
        with open(tok, "w") as f:
            f.write(creds.to_json())
    s = AuthorizedSession(creds)
    accounts = s.get(ADMOB + "accounts", timeout=60).json().get("account", [])
    if not accounts:
        raise RuntimeError("AdMob: no account visible")
    acct = accounts[0]["name"]
    body = {"reportSpec": {"dateRange": {"startDate": {"year": start.year, "month": start.month, "day": start.day},
                                         "endDate": {"year": end.year, "month": end.month, "day": end.day}},
                           "dimensions": ["DATE"], "metrics": ["ESTIMATED_EARNINGS"],
                           "localizationSettings": {"currencyCode": "USD"}}}
    r = s.post(f"{ADMOB}{acct}/networkReport:generate", json=body, timeout=120)
    if not r.ok:
        raise RuntimeError(f"AdMob report {r.status_code}: {r.text[:200]}")
    out = {}
    for item in r.json():
        row = item.get("row")
        if not row:
            continue
        d = row["dimensionValues"]["DATE"]["value"]
        v = row["metricValues"]["ESTIMATED_EARNINGS"]
        out[f"{d[:4]}-{d[4:6]}-{d[6:]}"] = round(int(v.get("microsValue", 0)) / 1e6, 4)
    return out


_RATES = {}


def usd_rate(cur, day):
    """US dollars per 1 unit of cur on that day (European Central Bank rates). Guy, Nov 6: non-US sales were being dropped. Raises if there's no rate, so a sale is never silently lost."""
    if cur == "USD":
        return 1.0
    if (cur, day) not in _RATES:
        r = requests.get(f"https://api.frankfurter.dev/v1/{day}", params={"base": cur, "symbols": "USD"}, timeout=30)
        r.raise_for_status()
        _RATES[(cur, day)] = float(r.json()["rates"]["USD"])
    return _RATES[(cur, day)]


def _asc_day(c, key, day):
    """(Apple proceeds in USD, paid in-app purchases) for one day, or None when Apple hasn't posted it."""
    n = int(time.time())
    token = jwt.encode({"iss": c["issuer_id"], "iat": n, "exp": n + 1100, "aud": "appstoreconnect-v1"}, key,
                       algorithm="ES256", headers={"kid": c["key_id"], "typ": "JWT"})
    r = requests.get(ASC + "/v1/salesReports", headers={"Authorization": "Bearer " + token}, timeout=60,
                     params={"filter[frequency]": "DAILY", "filter[reportType]": "SALES", "filter[reportSubType]": "SUMMARY",
                             "filter[vendorNumber]": c["vendor_number"], "filter[reportDate]": day.isoformat(), "filter[version]": "1_1"})
    if r.status_code == 404:
        return None
    if not r.ok:
        raise RuntimeError(f"salesReports {day} {r.status_code}: {r.text[:200]}")
    df = pd.read_csv(io.StringIO(gzip.decompress(r.content).decode("utf-8")), sep="\t", dtype=str)
    units = pd.to_numeric(df["Units"], errors="coerce").fillna(0)
    proceeds = pd.to_numeric(df["Developer Proceeds"], errors="coerce").fillna(0)
    sel = df["Product Type Identifier"].isin(IAP_TYPES) & (proceeds != 0)
    usd = round(sum(u * v * usd_rate(c, day.isoformat()) for u, v, c in zip(units[sel], proceeds[sel], df["Currency of Proceeds"][sel])), 2)
    return usd, int(sum(u for u in units[sel] if u > 0))   # paid purchases only: App Review / sandbox buys never reach this report (Guy, Nov 7)


def fetch(keys_dir, today):
    cache = json.load(open(CACHE)) if os.path.exists(CACHE) else {"ads": {}, "iap": {}}
    ads, iap, iapn = cache.get("ads", {}), cache.get("iap", {}), cache.get("iapn", {})
    # ads: refetch the last 3 days plus any gap since launch (one API call)
    have = sorted(d for d in ads)
    start = LAUNCH if not have else min(dt.date.fromisoformat(have[-1]) - dt.timedelta(days=3), dt.date.fromisoformat(have[-1]))
    try:
        ads.update(_admob(keys_dir, start, today))
    except Exception as e:
        if not ads:
            raise
    # iap: per day, cached
    c = json.load(open(os.path.join(keys_dir, "asc-metrics.json")))
    key = open(os.path.join(keys_dir, c["key_file"])).read()
    day = LAUNCH
    while day < today:
        d = day.isoformat()
        age = (today - day).days
        if d not in iap or iap[d] is None or d not in iapn or age <= 3:
            v = _asc_day(c, key, day)
            if v is not None or age > 1:
                iap[d], iapn[d] = v if v is not None else (0.0, 0)
        day += dt.timedelta(days=1)
    json.dump({"ads": ads, "iap": iap, "iapn": iapn}, open(CACHE, "w"), indent=0, sort_keys=True)
    days = sorted(set(ads) | set(iap))
    return {"Money Lite": (pd.DataFrame({"date": days, "ads": [ads.get(d) for d in days], "iap": [iap.get(d) for d in days], "iapn": [iapn.get(d) for d in days]}), ["date"])}
