"""Meta ads (Facebook + Instagram boosts/campaigns) per day, for the social report (Guy, Nov 1, 2026): spend, link clicks
and Meta's own install count. Cached in Metrics/metaads-cache.json.
Key: Private Keys/meta-token.txt (same system-user token as meta.py); it needs the ads_read permission and the ad account
assigned to the system user. Without that, this returns nothing and the report says Meta ads aren't connected yet.
Installs = Meta's count (Meta SDK in the app from 1.3.1, Nov 1); earlier boosts sent people to the App Store link, so they only have clicks."""
import datetime as dt
import json
import os

import pandas as pd
import requests

G = "https://graph.facebook.com/v24.0/"
START = dt.date(2026, 10, 27)   # first Meta paid test (Trick or Treat boost)
CACHE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "metaads-cache.json")
INSTALL_TYPES = ("omni_app_install", "mobile_app_install", "app_install")   # first one present wins (they overlap)


def _get(path, token, **params):
    params["access_token"] = token
    j = requests.get(G + path, params=params, timeout=60).json()
    if "error" in j:
        raise RuntimeError(f"{path.split('/')[-1]}: {j['error'].get('message', '')[:200]}")
    return j


def fetch(keys_dir, today):
    token = open(os.path.join(keys_dir, "meta-token.txt")).read().strip()
    try:
        accts = _get("me/adaccounts", token, fields="id,name", limit=50).get("data", [])
    except RuntimeError as e:
        if "permission" in str(e).lower():
            if not os.path.exists(CACHE):   # report.yml saves this file every run, so it must exist (runs #444/#445 failed without it)
                json.dump({}, open(CACHE, "w"))
            # token has no ads_read: use the numbers read daily from Ads Manager in Chrome (scheduled task meta-ads-daily; Guy, Nov 6)
            cache = json.load(open(CACHE))
            if not cache:
                return {"Meta Ads Lite": (pd.DataFrame(), None)}
            return {"Meta Ads Lite": (pd.DataFrame([{"date": k, **cache[k]} for k in sorted(cache)]), ["date"])}
        raise
    cache = json.load(open(CACHE)) if os.path.exists(CACHE) else {}
    start = START if not cache else min(dt.date.fromisoformat(max(cache)) - dt.timedelta(days=3), today)
    got = {}
    for a in accts:
        url, params = f"{a['id']}/insights", {"fields": "spend,inline_link_clicks,actions", "time_increment": 1, "level": "account",
                                              "time_range": json.dumps({"since": start.isoformat(), "until": today.isoformat()}), "limit": 100}
        while url:
            j = _get(url, token, **params) if params else requests.get(url, timeout=60).json()
            for r in j.get("data", []):
                acts = {x["action_type"]: float(x.get("value") or 0) for x in r.get("actions", [])}
                inst = next((acts[k] for k in INSTALL_TYPES if k in acts), 0)
                g = got.setdefault(r["date_start"], {"spend": 0.0, "clicks": 0, "installs": 0})
                g["spend"] += float(r.get("spend") or 0); g["clicks"] += int(r.get("inline_link_clicks") or 0); g["installs"] += int(inst)
            url, params = j.get("paging", {}).get("next"), None
    d = start
    while d <= today:   # days with no rows = nothing spent
        g = got.get(d.isoformat(), {"spend": 0.0, "clicks": 0, "installs": 0})
        cache[d.isoformat()] = {"spend": round(g["spend"], 2), "clicks": g["clicks"], "installs": g["installs"]}
        d += dt.timedelta(days=1)
    json.dump(cache, open(CACHE, "w"), indent=0, sort_keys=True)
    return {"Meta Ads Lite": (pd.DataFrame([{"date": k, **cache[k]} for k in sorted(cache)]), ["date"])}
