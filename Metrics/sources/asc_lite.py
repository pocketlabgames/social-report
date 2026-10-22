"""App Store Connect installs for the social report: daily SALES/SUMMARY reports for the last N days only
(first downloads = installs). Same key as sources/appstore.py (Private Keys/asc-metrics.json + .p8); no cache needed."""
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


def _token(c, key):
    n = int(time.time())
    return jwt.encode({"iss": c["issuer_id"], "iat": n, "exp": n + 1100, "aud": "appstoreconnect-v1"},
                      key, algorithm="ES256", headers={"kid": c["key_id"], "typ": "JWT"})


def installs(keys_dir, today, days=16):
    """{date: first downloads} for the last `days` days before today (Apple posts a day by the next morning PT)."""
    c = json.load(open(os.path.join(keys_dir, "asc-metrics.json")))
    key = open(os.path.join(keys_dir, c["key_file"])).read()
    out, missing = {}, 0
    for n in range(1, days + 1):
        day = today - pd.Timedelta(days=n)
        r = requests.get(API + "/v1/salesReports", headers={"Authorization": "Bearer " + _token(c, key)}, timeout=60,
                         params={"filter[frequency]": "DAILY", "filter[reportType]": "SALES", "filter[reportSubType]": "SUMMARY",
                                 "filter[vendorNumber]": c["vendor_number"], "filter[reportDate]": day.isoformat(), "filter[version]": "1_1"})
        if r.status_code == 404:   # no report = no units that day, or not posted yet (yesterday, early)
            out[day.isoformat()] = 0 if n > 1 else None
            missing += n == 1
            continue
        if not r.ok:
            raise RuntimeError(f"salesReports {day} {r.status_code}: {r.text[:200]}")
        df = pd.read_csv(io.StringIO(gzip.decompress(r.content).decode("utf-8")), sep="\t", dtype=str)
        units = pd.to_numeric(df["Units"], errors="coerce").fillna(0)
        out[day.isoformat()] = int(units[df["Product Type Identifier"].isin(FIRST)].sum())
    return out


def fetch(keys_dir, today):
    d = installs(keys_dir, today)
    return {"ASC Installs Lite": (pd.DataFrame({"date": list(d), "installs": list(d.values())}), ["date"])}
