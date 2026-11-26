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
        # Guy, Nov 18: a new rating waited ~a day for the next daily pass; recheck the US + countries that already have ratings every run (few lookups)
        todo = sorted({"US"} | {c for c, v in by.items() if v and v[0]})
    else:
        cc = json.load(open(CCACHE)) if os.path.exists(CCACHE) else {}
        todo = sorted({k for day in cc.values() for k in day} | {"US"})
    # Guy, Nov 19: Apple's lookup servers disagreed (3 vs 2 US ratings, flipping every run from Nov 18). Countries with ratings
    # (and the US) are asked 5 times; the most common answer wins, a tie goes to the lower count (what the App Store showed)
    multi = {"US"} | {c for c, v in by.items() if v and v[0]}
    for c in todo:
        got = []
        for k in range(5 if c in multi else 1):
            try:
                r = requests.get("https://itunes.apple.com/lookup", params={"id": app_id, "country": c.lower(), "t": f"{time.time():.0f}{k}"}, timeout=20)
                if r.status_code in (403, 429):   # rate limited: keep what we have, try again next run
                    time.sleep(30)
                    break
                res = r.json().get("results") or [{}]
                got.append((int(res[0].get("userRatingCount") or 0), float(res[0].get("averageUserRating") or 0)))
            except (requests.RequestException, ValueError):
                pass
            time.sleep(2)   # Apple allows about 20 lookups a minute
        if got:
            n = min(got, key=lambda x: (-sum(1 for g in got if g[0] == x[0]), x[0]))[0]
            by[c] = [n, next(a for m, a in got if m == n)]
    json.dump({"date": today.isoformat(), "by": by}, open(RCACHE, "w"), indent=0, sort_keys=True)
    return by


def fetch(keys_dir, today):
    cl = _Client(keys_dir)
    revs = cl.all(f"/v1/apps/{cl.c['app_id']}/customerReviews?limit=200&fields[customerReviews]=rating,territory")
    by = _stars(cl.c["app_id"], today)
    n = sum(v[0] for v in by.values())
    row = {"app_id": str(cl.c["app_id"]), "reviews": len(revs), "n": n,
           "avg": sum(v[0] * v[1] for v in by.values()) / n if n else None,
           "by": json.dumps({c: v for c, v in by.items() if v[0]}, sort_keys=True),   # Guy, Nov 26: countries with ratings, for the ratings list
           "us_n": (by.get("US") or [0, None])[0], "us_avg": (by.get("US") or [0, None])[1] if (by.get("US") or [0])[0] else None,
           "top": ", ".join(f"{c} {v[0]:,}" for c, v in sorted(by.items(), key=lambda x: -x[1][0]) if v[0])[:300]}
    return {"ASC Reviews Lite": (pd.DataFrame([row]), [])}
