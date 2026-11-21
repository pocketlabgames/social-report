"""RevenueCat new customers per day (first opens), for a same-day download estimate on the social report.
Key: Private Keys/revenuecat-key.txt (read-only v2 secret key; same as sources/revenuecat.py)."""
import datetime as dt
import os
import time

import pandas as pd
import requests

PROJECT = "projba36f536"
API = "https://api.revenuecat.com"


def _chart(key, name, start, today):
    url = f"{API}/v2/projects/{PROJECT}/charts/{name}"
    for attempt in range(4):
        r = requests.get(url, headers={"Authorization": "Bearer " + key}, timeout=60,
                         params={"start_date": start, "end_date": today.isoformat(), "resolution": "day"})
        if r.status_code == 429:
            time.sleep(int(r.headers.get("Retry-After", 5)))
            continue
        if not r.ok:
            raise RuntimeError(f"RevenueCat {name} {r.status_code}: {r.text[:200]}")
        return r.json()
    raise RuntimeError("RevenueCat rate limit")


def _ver(v):
    try:
        return tuple(int(x) for x in str(v).split("."))
    except ValueError:
        return ()


def _tests(key, keys_dir, start):
    """{UTC date: first opens on a build newer than the live App Store version} since start (RevenueCat customer list)."""
    try:
        from sources import ga4_game_lite as g
    except ImportError:
        import ga4_game_lite as g
    live = g._live(keys_dir)[0]
    t0 = pd.Timestamp(start, tz="UTC").timestamp() * 1000
    url, out = f"{API}/v2/projects/{PROJECT}/customers?limit=1000", {}
    for _ in range(50):
        r = requests.get(url, headers={"Authorization": "Bearer " + key}, timeout=60)
        if r.status_code == 429:
            time.sleep(int(r.headers.get("Retry-After", 5)))
            continue
        if not r.ok:
            raise RuntimeError(f"RevenueCat customers {r.status_code}: {r.text[:200]}")
        j = r.json()
        for c in j.get("items") or []:
            if c.get("first_seen_at", 0) >= t0 and _ver(c.get("last_seen_app_version")) > live:
                d = pd.Timestamp(c["first_seen_at"], unit="ms").strftime("%Y-%m-%d")
                out[d] = out.get(d, 0) + 1
        nxt = j.get("next_page")
        if not nxt:
            return out
        url = nxt if nxt.startswith("http") else API + nxt
    raise RuntimeError("RevenueCat customers: too many pages")


def fetch(keys_dir, today):
    key = open(os.path.join(keys_dir, "revenuecat-key.txt")).read().strip()
    start = (today - dt.timedelta(days=21)).isoformat()
    j = _chart(key, "customers_new", start, today)
    names = [m["display_name"] for m in j.get("measures") or []]
    idx = names.index("New Customers") if "New Customers" in names else 0
    rows = [{"date": pd.Timestamp(v["cohort"], unit="s").strftime("%Y-%m-%d"), "new": v["value"]}
            for v in j.get("values") or [] if v.get("measure", 0) == idx]
    # Guy, Nov 21: leave test installs out. A first open on a build newer than the App Store's live version can only be
    # TestFlight/Xcode (e.g. 12 on 1.3.19 on Nov 20, when 1.3.18 was live), so subtract those per day (UTC, like the chart).
    tests = _tests(key, keys_dir, start)
    for r in rows:
        r["new"] = max(0, r["new"] - tests.get(r["date"], 0))
    out = {"RC New Lite": (pd.DataFrame(rows), ["date"]), "RC Test Lite": (pd.DataFrame([{"date": d, "test": n} for d, n in sorted(tests.items())]), ["date"])}
    # Guy, Nov 18: real App Store purchases per day (RevenueCat leaves out sandbox/TestFlight/App Review test buys)
    try:
        j = _chart(key, "revenue", start, today)
        names = [m["display_name"] for m in j.get("measures") or []]
        it = names.index("Transactions") if "Transactions" in names else 1
        tx = [{"date": pd.Timestamp(v["cohort"], unit="s").strftime("%Y-%m-%d"), "tx": v["value"]}
              for v in j.get("values") or [] if v.get("measure") == it and v.get("segment", 0) == 0]
        out["RC Purchases Lite"] = (pd.DataFrame(tx), ["date"])
    except Exception:
        pass
    return out
