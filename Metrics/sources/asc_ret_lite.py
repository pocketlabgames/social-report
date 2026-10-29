"""App Store Connect app numbers for the social report's Retention card (Guy, Oct 26, 2026).
Analytics Reports API (the ONGOING request appstore.py made): "App Sessions Standard" and
"App Store Installation and Deletion Standard", daily instances processed in the last 21 days.
Same key as asc_lite (Private Keys/asc-metrics.json). Apple's data lags 2-3 days and hides small groups,
so every number here is for the last 7 days Apple has posted, and Day-1 return is an estimate:
devices that downloaded on day D and opened the app on day D+1, divided by first-time installs on day D."""
import datetime as dt
import gzip
import io
import json
import os
import time

import jwt
import pandas as pd
import requests

API = "https://api.appstoreconnect.apple.com"
_ROOT = os.environ.get("BEAKERLAB_METRICS_DIR") or ("/Users/guydifa/Library/Mobile Documents/com~apple~CloudDocs/[Projects]/Game Development/Beaker Lab/Metrics" if os.path.isdir("/Users/guydifa/Library/Mobile Documents/com~apple~CloudDocs/[Projects]/Game Development/Beaker Lab/Metrics") else os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
CACHE = os.path.join(_ROOT, "cache", "asc")   # same folders as appstore.py (one TSV per report instance)
WANT = {"App Sessions Standard": "ASC_Sessions", "App Store Installation and Deletion Standard": "ASC_Installs",
        "App Store Discovery and Engagement Standard": "ASC_Discovery", "App Downloads Standard": "ASC_Downloads"}   # Guy, Oct 29: page views + downloads by source


class _Client:
    def __init__(self, keys_dir):
        self.c = json.load(open(os.path.join(keys_dir, "asc-metrics.json")))
        self.key = open(os.path.join(keys_dir, self.c["key_file"])).read()

    def get(self, url):
        n = int(time.time())
        tok = jwt.encode({"iss": self.c["issuer_id"], "iat": n, "exp": n + 1100, "aud": "appstoreconnect-v1"},
                         self.key, algorithm="ES256", headers={"kid": self.c["key_id"], "typ": "JWT"})
        r = requests.get(url if url.startswith("http") else API + url, headers={"Authorization": "Bearer " + tok}, timeout=60)
        if not r.ok:
            raise RuntimeError(f"GET {url.split('?')[0]} {r.status_code}: {r.text[:200]}")
        return r.json()

    def all(self, url):
        out = []
        while url:
            j = self.get(url)
            out += j["data"]
            url = j.get("links", {}).get("next")
        return out


def _frames(cl, today):
    since = (today - dt.timedelta(days=21)).isoformat()
    got = {v: [] for v in WANT.values()}
    for rq in cl.all(f"/v1/apps/{cl.c['app_id']}/analyticsReportRequests"):
        if rq["attributes"]["accessType"] != "ONGOING":
            continue
        for rep in cl.all(f"/v1/analyticsReportRequests/{rq['id']}/reports?limit=200"):
            folder = WANT.get(rep["attributes"]["name"])
            if not folder:
                continue
            os.makedirs(os.path.join(CACHE, folder), exist_ok=True)
            for inst in cl.all(f"/v1/analyticsReports/{rep['id']}/instances?filter[granularity]=DAILY&limit=200"):
                if (inst["attributes"].get("processingDate") or "") < since:
                    continue
                path = os.path.join(CACHE, folder, inst["id"] + ".tsv")
                if not os.path.exists(path):
                    parts = [gzip.decompress(requests.get(s["attributes"]["url"], timeout=120).content).decode("utf-8")
                             for s in cl.all(f"/v1/analyticsReportInstances/{inst['id']}/segments")]
                    lines = []
                    for i, p in enumerate(parts):
                        rows = p.splitlines()
                        lines += rows if i == 0 else rows[1:]
                    with open(path, "w") as f:
                        f.write("\n".join(lines) + ("\n" if lines else ""))
                if os.path.getsize(path):
                    got[folder].append(pd.read_csv(path, sep="\t", dtype=str))
    return {k: (pd.concat(v, ignore_index=True).drop_duplicates() if v else pd.DataFrame()) for k, v in got.items()}


def summary(ses, ins):
    num = lambda s: pd.to_numeric(s, errors="coerce").fillna(0)
    if ses.empty:
        return {}
    days = sorted(ses["Date"].dropna().unique())[-7:]
    s = ses[ses["Date"].isin(days)]
    S, T, U = num(s["Sessions"]).sum(), num(s["Total Session Duration"]).sum(), num(s["Unique Devices"]).sum()
    out = {"first": days[0], "last": days[-1], "days": len(days),
           "spd": round(S / U, 1) if U else None, "mins": round(T / S / 60, 1) if S else None}
    if not ins.empty:
        w = ins[ins["Date"].isin(days)]
        new = w[(w["Event"] == "Install") & (w["Download Type"] == "First-time download")]
        out["installs"] = int(num(new["Counts"]).sum())
        out["deletes"] = int(num(w[w["Event"] == "Delete"]["Counts"]).sum())
        base = ins[(ins["Event"] == "Install") & (ins["Download Type"] == "First-time download")]
        base = base.assign(n=num(base["Unique Devices"])).groupby("Date")["n"].sum()
        have = set(ses["Date"].dropna())
        nxt = lambda d: (dt.date.fromisoformat(d) + dt.timedelta(days=1)).isoformat()
        cohort = [d for d in base.index if nxt(d) in have and base[d] > 0][-7:]
        if cohort:
            back = sum(num(ses[(ses["App Download Date"] == d) & (ses["Date"] == nxt(d))]["Unique Devices"]).sum() for d in cohort)
            n = sum(base[d] for d in cohort)
            out.update({"d1": round(back / n * 100), "d1_n": int(n)})
    return out


SRC = {"App referrer": "ads", "App Store search": "search", "App Store browse": "browse"}   # everything else (Unavailable, Web referrer) = "other"


def sources(disc, dls):
    """Per day: App Store product page views (unique devices) and first-time downloads by source (Guy, Oct 29).
    App referrer = views from inside another app; ours come from Google Ads (social posts carry no App Store link)."""
    num = lambda s: pd.to_numeric(s, errors="coerce").fillna(0)
    out = {}
    if not disc.empty:
        pv = disc[disc["Event"] == "Page view"]
        for (d, st), n in pv.assign(n=num(pv["Unique Counts"])).groupby(["Date", "Source Type"])["n"].sum().items():
            r = out.setdefault(d, {}); k = "pv_" + SRC.get(st, "other"); r[k] = r.get(k, 0) + int(n)
    if not dls.empty:
        fd = dls[dls["Download Type"] == "First-time download"]
        for (d, st), n in fd.assign(n=num(fd["Counts"])).groupby(["Date", "Source Type"])["n"].sum().items():
            r = out.setdefault(d, {}); k = "dl_" + SRC.get(st, "other"); r[k] = r.get(k, 0) + int(n)
    return pd.DataFrame([{"date": d, **r} for d, r in sorted(out.items())])


def fetch(keys_dir, today):
    f = _frames(_Client(keys_dir), today)
    return {"ASC Retention Lite": (pd.DataFrame([summary(f["ASC_Sessions"], f["ASC_Installs"])]), None),
            "ASC Sources Lite": (sources(f["ASC_Discovery"], f["ASC_Downloads"]), None)}
