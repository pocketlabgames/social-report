"""App Store Connect installs for the social report: daily SALES/SUMMARY reports (first downloads = installs)
from launch (Sep 26, 2026) to yesterday. Same key as sources/appstore.py (Private Keys/asc-metrics.json + .p8).
Days are cached in Metrics/installs-cache.json; only missing days and the last 3 (Apple restates them) are fetched."""
import gzip
import io
import json
import os
import time

import jwt
import pandas as pd
import requests

API = "https://api.appstoreconnect.apple.com"
FIRST = {"1", "1F", "1T"}   # Apple product type codes for a first download
LAUNCH = pd.Timestamp("2026-09-26").date()
CACHE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "installs-cache.json")


def _token(c, key):
    n = int(time.time())
    return jwt.encode({"iss": c["issuer_id"], "iat": n, "exp": n + 1100, "aud": "appstoreconnect-v1"},
                      key, algorithm="ES256", headers={"kid": c["key_id"], "typ": "JWT"})


def installs(keys_dir, today):
    """{date: first downloads} for every day from launch to yesterday (None = not posted by Apple yet)."""
    c = json.load(open(os.path.join(keys_dir, "asc-metrics.json")))
    key = open(os.path.join(keys_dir, c["key_file"])).read()
    cache = json.load(open(CACHE)) if os.path.exists(CACHE) else {}
    out, day = {}, LAUNCH
    while day < today:
        d = day.isoformat()
        age = (today - day).days
        if d in cache and cache[d] is not None and age > 3:
            out[d] = cache[d]
        else:
            r = requests.get(API + "/v1/salesReports", headers={"Authorization": "Bearer " + _token(c, key)}, timeout=60,
                             params={"filter[frequency]": "DAILY", "filter[reportType]": "SALES", "filter[reportSubType]": "SUMMARY",
                                     "filter[vendorNumber]": c["vendor_number"], "filter[reportDate]": d, "filter[version]": "1_1"})
            if r.status_code == 404:   # no units that day, or (yesterday) not posted yet
                out[d] = None if age == 1 else 0
            elif not r.ok:
                raise RuntimeError(f"salesReports {d} {r.status_code}: {r.text[:200]}")
            else:
                df = pd.read_csv(io.StringIO(gzip.decompress(r.content).decode("utf-8")), sep="\t", dtype=str)
                units = pd.to_numeric(df["Units"], errors="coerce").fillna(0)
                out[d] = int(units[df["Product Type Identifier"].isin(FIRST)].sum())
        day += pd.Timedelta(days=1)
    cache.update({k: v for k, v in out.items() if v is not None})
    json.dump(cache, open(CACHE, "w"), indent=0, sort_keys=True)
    return out


def fetch(keys_dir, today):
    d = installs(keys_dir, today)
    return {"ASC Installs Lite": (pd.DataFrame({"date": list(d), "installs": list(d.values())}), ["date"])}
