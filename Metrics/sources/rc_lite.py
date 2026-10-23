"""RevenueCat new customers per day (first opens), for a same-day download estimate on the social report.
Key: Private Keys/revenuecat-key.txt (read-only v2 secret key; same as sources/revenuecat.py)."""
import datetime as dt
import os
import time

import pandas as pd
import requests

PROJECT = "projba36f536"
API = "https://api.revenuecat.com"


def fetch(keys_dir, today):
    key = open(os.path.join(keys_dir, "revenuecat-key.txt")).read().strip()
    start = (today - dt.timedelta(days=21)).isoformat()
    url = f"{API}/v2/projects/{PROJECT}/charts/customers_new"
    for attempt in range(4):
        r = requests.get(url, headers={"Authorization": "Bearer " + key}, timeout=60,
                         params={"start_date": start, "end_date": today.isoformat(), "resolution": "day"})
        if r.status_code == 429:
            time.sleep(int(r.headers.get("Retry-After", 5)))
            continue
        if not r.ok:
            raise RuntimeError(f"RevenueCat customers_new {r.status_code}: {r.text[:200]}")
        break
    else:
        raise RuntimeError("RevenueCat rate limit")
    j = r.json()
    names = [m["display_name"] for m in j.get("measures") or []]
    idx = names.index("New Customers") if "New Customers" in names else 0
    rows = [{"date": pd.Timestamp(v["cohort"], unit="s").strftime("%Y-%m-%d"), "new": v["value"]}
            for v in j.get("values") or [] if v.get("measure", 0) == idx]
    return {"RC New Lite": (pd.DataFrame(rows), ["date"])}
