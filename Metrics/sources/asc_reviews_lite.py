"""App Store reviews for the social report's pinned day card (Guy, Oct 29, 2026): every customer review (all countries)
from the App Store Connect API, so the card can show the count and average stars and link to Ratings and Reviews.
Same key as asc_lite (Private Keys/asc-metrics.json). Star-only ratings without a written review aren't in this API."""
import pandas as pd

from sources.asc_ret_lite import _Client


def fetch(keys_dir, today):
    cl = _Client(keys_dir)
    revs = cl.all(f"/v1/apps/{cl.c['app_id']}/customerReviews?limit=200&fields[customerReviews]=rating,territory")
    stars = [r["attributes"]["rating"] for r in revs if r.get("attributes", {}).get("rating")]
    row = {"app_id": str(cl.c["app_id"]), "n": len(revs), "avg": sum(stars) / len(stars) if stars else None}
    return {"ASC Reviews Lite": (pd.DataFrame([row]), [])}
