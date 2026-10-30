"""App Store ratings and reviews for the social report's pinned day card (Guy, Oct 29-30, 2026).
Written reviews (all countries) come from the App Store Connect API. Star ratings (most players leave stars only, which
that API doesn't return) come from Apple's public lookup, one country at a time, for every country with a download in
countries-cache.json. The lookup is rate-limited, so it runs once a day and is cached in Metrics/ratings-cache.json.
Same key as asc_lite (Private Keys/asc-metrics.json)."""
import json
import os
import time

import pandas as pd
import requests

from sources.asc_lite import CCACHE
from sources.asc_ret_lite import _Client

RCACHE = os.path.join(os.path.dirname(CCACHE), "ratings-cache.json")


def _stars(app_id, today):
    """{country code: [ratings, average]} from Apple's public lookup; refreshed once a day, last good values kept on errors."""
    cache = json.load(open(RCACHE)) if os.path.exists(RCACHE) else {}
    by = cache.get("by", {})
    if cache.get("date") == today.isoformat():
        return by
    cc = json.load(open(CCACHE)) if os.path.exists(CCACHE) else {}
    for c in sorted({k for day in cc.values() for k in day} | {"US"}):
        try:
            r = requests.get("https://itunes.apple.com/lookup", params={"id": app_id, "country": c.lower()}, timeout=20)
            if r.status_code in (403, 429):   # rate limited: keep what we have, try again next run
                time.sleep(30)
                continue
            res = r.json().get("results") or [{}]
            by[c] = [int(res[0].get("userRatingCount") or 0), float(res[0].get("averageUserRating") or 0)]
        except (requests.RequestException, ValueError):
            pass
        time.sleep(2)   # Apple allows about 20 lookups a minute
    json.dump({"date": today.isoformat(), "by": by}, open(RCACHE, "w"), indent=0, sort_keys=True)
    return by


def fetch(keys_dir, today):
    cl = _Client(keys_dir)
    revs = cl.all(f"/v1/apps/{cl.c['app_id']}/customerReviews?limit=200&fields[customerReviews]=rating,territory")
    by = _stars(cl.c["app_id"], today)
    n = sum(v[0] for v in by.values())
    row = {"app_id": str(cl.c["app_id"]), "reviews": len(revs), "n": n,
           "avg": sum(v[0] * v[1] for v in by.values()) / n if n else None,
           "top": ", ".join(f"{c} {v[0]:,}" for c, v in sorted(by.items(), key=lambda x: -x[1][0]) if v[0])[:300]}
    return {"ASC Reviews Lite": (pd.DataFrame([row]), [])}
