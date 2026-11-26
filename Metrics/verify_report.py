"""Guy, Nov 6: independent data check, run on every report build. It reads the numbers off the finished page, pulls them again
straight from the source with its own queries, and puts a red banner at the top of the report when they disagree. If it can't
run or can't find a number on the page, that is a failure too: it never passes by default.
Allowed gaps: 1 player on counts that include today (players arrive between the two pulls), 10 cents on money. Days older than yesterday must match exactly.
Guy, Nov 7: Firebase keeps processing yesterday, and its answers flip from pull to pull (wins 376, 382, 376; rewarded ads 69, 64), so event counts that include yesterday or today get wobble(): 10%, at least 2. Purchases stay exact.
Not compared with a second source: Instagram, Facebook and TikTok views (only failed pulls and falling totals are caught), Google/Meta ad spend, ratings values."""
import csv
import datetime as dt
import gzip
import html
import io
import json
import os
import re
import time

NO_CT = {"andGroup": {"expressions": [{"notExpression": {"filter": {"fieldName": "region", "stringFilter": {"value": "Connecticut"}}}}, {"notExpression": {"filter": {"fieldName": "region", "stringFilter": {"value": "California"}}}},   # Guy, Nov 25 2026 "yes, for now": California left out (looks like Apple review devices on normal models; 15 started level 1, 3 won, Nov 19-25)
                                     
                                      {"notExpression": {"filter": {"fieldName": "deviceModel", "stringFilter": {"matchType": "BEGINS_WITH", "value": "iPhone99,"}}}},   # Guy, Nov 24 "remove test devices": Apple test devices (model not sold)
                                      {"notExpression": {"filter": {"fieldName": "operatingSystemVersion", "stringFilter": {"matchType": "EXACT", "value": "27.1"}}}}]}}   # iOS 27.1: 0 App Store downloads ever (27.2 has 86), all US   # Guy, Nov 21: Connecticut = Guy testing, left out of game stats (own copy so the check stays independent)
from concurrent.futures import ThreadPoolExecutor

import jwt
import requests
from google.auth.transport.requests import AuthorizedSession, Request
from google.oauth2.credentials import Credentials

from sources import money_lite

PROPERTY = "558070583"
APP_ID = "6816478290"
LAUNCH = dt.date(2026, 9, 26)
START = dt.date(2026, 11, 1)


def wobble(n):
    """Allowed gap on event counts Firebase is still processing: 10%, at least 2."""
    return max(2, n * 0.10)


class Checks:
    def __init__(self):
        self.ok, self.fails, self.iapn = 0, [], {}   # iapn: App Store paid purchases per day, filled by the store check

    def same(self, name, shown, source, gap=0):
        if shown is None:
            self.fails.append(f"{name}: not found on the page (source says {source})")
        elif abs(shown - source) > gap + 1e-9:
            self.fails.append(f"{name}: report shows {shown:,}, source says {source:,}")
        else:
            self.ok += 1

    def true(self, name, good, why=""):
        if good:
            self.ok += 1
        else:
            self.fails.append(f"{name}{': ' + why if why else ''}")


def _num(pattern, page, cast=float):
    m = re.search(pattern, page)
    return cast(m.group(1).replace(",", "")) if m else None


def _sales(keys):
    """Every day since launch straight from Apple: {date: rows}; days Apple hasn't posted are left out."""
    c = json.load(open(os.path.join(keys, "asc-metrics.json")))
    now = int(time.time())
    tok = jwt.encode({"iss": c["issuer_id"], "iat": now, "exp": now + 1100, "aud": "appstoreconnect-v1"}, open(os.path.join(keys, c["key_file"])).read(), algorithm="ES256", headers={"kid": c["key_id"], "typ": "JWT"})
    head = {"Authorization": "Bearer " + tok}

    def one(d):
        for _ in range(3):
            r = requests.get("https://api.appstoreconnect.apple.com/v1/salesReports", headers=head, timeout=60,
                             params={"filter[frequency]": "DAILY", "filter[reportType]": "SALES", "filter[reportSubType]": "SUMMARY", "filter[vendorNumber]": c["vendor_number"], "filter[reportDate]": d, "filter[version]": "1_1"})
            if r.status_code == 404:
                return d, None
            if r.ok:
                return d, list(csv.DictReader(io.StringIO(gzip.decompress(r.content).decode()), delimiter="\t"))
            time.sleep(3)
        raise RuntimeError(f"Apple sales report {d}: {r.status_code}")
    today = dt.date.today()
    days = [(LAUNCH + dt.timedelta(days=i)).isoformat() for i in range((today - LAUNCH).days)]
    with ThreadPoolExecutor(6) as ex:
        sales = dict(ex.map(one, days))
    versions = requests.get(f"https://api.appstoreconnect.apple.com/v1/apps/{APP_ID}/appStoreVersions", headers=head, timeout=30, params={"filter[platform]": "IOS", "filter[appStoreState]": "READY_FOR_SALE", "limit": 20, "fields[appStoreVersions]": "versionString"})
    versions.raise_for_status()
    return {d: r for d, r in sales.items() if r is not None}, [x["attributes"]["versionString"] for x in versions.json()["data"]]


def _ver(v):
    try:
        return tuple(int(x) for x in v.split("."))
    except ValueError:
        return ()


def _check_store(C, page, keys, today):
    sales, on_sale = _sales(keys)
    first = {"1", "1F", "1T"}
    per = {d: int(sum(float(x["Units"] or 0) for x in rows if x["Product Type Identifier"] in first)) for d, rows in sales.items()}
    ds = sorted(per)
    y = (today - dt.timedelta(days=1)).isoformat()
    C.same("Total downloads", _num(r"([\d,]+)(?:<span class='ns'>.*?</span>)? <small><span class='nf'>total downloads", page, int), sum(per.values()))
    C.same("Installs, last 7 days Apple has posted", _num(r"<b>([\d,]+)</b> last 7 days", page, int), sum(per[d] for d in ds[-7:]))
    C.same("Installs this month", _num(r"last 7 days · <b>([\d,]+)</b> in ", page, int), sum(per[d] for d in ds if d[:7] == today.strftime("%Y-%m")))
    C.same("Installs since launch", _num(r"<b>([\d,]+)</b> total since launch", page, int), sum(per.values()))
    if y in per:
        C.same("Installs yesterday", _num(r"<b>([\d,]+)</b> yesterday · <b>[\d,]+</b> last 7", page, int), per[y])
    countries = {x["Country Code"] for rows in sales.values() for x in rows if x["Product Type Identifier"] in first and float(x["Units"] or 0) > 0}
    C.same("Countries", _num(r"([\d,]+) <small>countries</small>", page, int), len(countries))
    # money: every currency, not only US dollars
    ads = money_lite._admob(keys, LAUNCH, today)[0]
    iap = {}
    for d, rows in sales.items():
        v = 0.0
        for x in rows:
            if x["Product Type Identifier"] in money_lite.IAP_TYPES and float(x["Developer Proceeds"] or 0):
                v += float(x["Units"] or 0) * float(x["Developer Proceeds"]) * money_lite.usd_rate(x["Currency of Proceeds"], d)
        iap[d] = v
        C.iapn[d] = int(sum(float(x["Units"] or 0) for x in rows if x["Product Type Identifier"] in money_lite.IAP_TYPES and float(x["Developer Proceeds"] or 0) and float(x["Units"] or 0) > 0))
    both = lambda ds: sum(ads.get(d, 0) + iap.get(d, 0) for d in ds)
    td = today.isoformat()
    month = [d for d in set(ads) | set(iap) if d[:7] == today.strftime("%Y-%m")]
    week = [(today - dt.timedelta(days=i)).isoformat() for i in range(7)]
    for name, pat, val in (("Earned today", r"Earned: <b>\$([\d,.]+)</b> today", both([td])), ("Earned yesterday", r"today · <b>\$([\d,.]+)</b> yesterday · <b>\$", both([y])),
                           ("Earned last 7 days", r"yesterday · <b>\$([\d,.]+)</b> last 7 days · <b>\$", both(week)), ("Earned this month", r"last 7 days · <b>\$([\d,.]+)</b> in ", both(month)),
                           ("Earned from ads this month", r"\(ads \$([\d,.]+) \+ App Store", sum(ads.get(d, 0) for d in month)), ("Earned from App Store this month", r"App Store \$([\d,.]+)\)", sum(iap.get(d, 0) for d in month))):
        C.same(name, _num(pat, page), round(val, 2), 0.10)
    # Earned pop-up (since launch): dollars only (Guy, Nov 9: it showed $390.99 because video and sale counts were added as dollars)
    m = re.search(r"const EM = (\{.*?\});", page)
    if m:
        em = json.loads(m.group(1)).values()   # Nov 18: [ads $, App Store $] per day
        C.same("Earned since launch (pop-up)", round(sum(a + p for a, p in em), 2), round(both(set(ads) | set(iap)), 2), 0.10)
        C.same("Earned from ads since launch (pop-up)", round(sum(a for a, p in em), 2), round(sum(ads.values()), 2), 0.10)
        C.same("Earned from App Store since launch (pop-up)", round(sum(p for a, p in em), 2), round(sum(iap.values()), 2), 0.10)
    return on_sale


def _check_game(C, page, keys, today, G, on_sale):
    creds = Credentials.from_authorized_user_file(os.path.join(keys, "ga4-token.json"), ["https://www.googleapis.com/auth/analytics.readonly"])
    if not creds.valid:
        creds.refresh(Request())
    s = AuthorizedSession(creds)

    def run(dates, dims=(), metrics=("activeUsers",), flt=None):
        body = {"dateRanges": [{"startDate": dates[0].isoformat(), "endDate": dates[1].isoformat()}], "dimensions": [{"name": d} for d in dims], "metrics": [{"name": m} for m in metrics], "limit": 100000}   # Nov 21: 2,000 rows cut off date x eventName (per-level events), so super_solve on 11/17 read 0
        body["dimensionFilter"] = {"andGroup": {"expressions": [flt, NO_CT]}} if flt else NO_CT   # Guy, Nov 21: same as the report, Connecticut (Guy testing) left out
        r = s.post(f"https://analyticsdata.googleapis.com/v1beta/properties/{PROPERTY}:runReport", json=body, timeout=60)
        r.raise_for_status()
        rows = r.json().get("rows", [])
        C.true(f"Google Analytics answer complete ({', '.join(dims) or 'totals'})", r.json().get("rowCount", len(rows)) <= len(rows), "rows were cut off, so missing ones would read as 0")   # Nov 21: super_solve 11/17 read 0 from a cut-off answer
        return [([x["value"] for x in row.get("dimensionValues", [])], [float(x["value"]) for x in row["metricValues"]]) for row in rows]

    one = lambda *a, **k: int(next(iter(run(*a, **k)), ([], [0]))[1][0])
    has = lambda f, v: {"filter": {"fieldName": f, "stringFilter": {"value": v}}}
    among = lambda f, vs: {"filter": {"fieldName": f, "inListFilter": {"values": list(vs)}}}
    AND = lambda *x: {"andGroup": {"expressions": list(x)}}
    # the version the report calls live must be what App Store Connect has on sale, and nothing on sale may be missing
    newest = max(map(_ver, on_sale))
    C.true("Live version", _ver(G.get("live", "")) == newest, f"report uses {G.get('live')}, App Store Connect has {'.'.join(map(str, newest))} on sale")
    seen = [r[0][0] for r in run((START, today), ["appVersion"])]
    want = sorted((v for v in seen if (1, 3, 1) <= _ver(v) <= newest), key=_ver)
    C.true("Versions counted", sorted(G.get("versions", []), key=_ver) == want, f"report counts {G.get('versions')}, should be {want}")
    rel = {v: dt.date.fromisoformat(d) for v, d in G["released"].items()}

    def released_only(a, b, versions=None):
        """Only days on or after each version's release: test devices before that don't count."""
        out = []
        for v in versions or want:
            r = max(rel[v], a)
            if r <= b:
                out.append(AND(has("appVersion", v), among("date", [(r + dt.timedelta(days=i)).strftime("%Y%m%d") for i in range((b - r).days + 1)])))
        return {"orGroup": {"expressions": out}}

    d7 = (max(today - dt.timedelta(days=6), START), today)   # Guy, Nov 21: All versions tiles include today, like the version views
    wk = released_only(*d7)
    ev = {r[0][0]: int(r[1][0]) for r in run(d7, ["eventName"], ["eventCount"], wk)}
    players = one(d7, flt=wk)
    outcome = {r[0][0]: int(r[1][0]) for r in run(d7, ["customEvent:outcome"], ["eventCount"], AND(wk, has("eventName", "level_end"))) if r[0][0] != "(not set)"}
    kind = {r[0][0]: int(r[1][0]) for r in run(d7, ["customEvent:kind"], ["eventCount"], AND(wk, has("eventName", "ad_shown"))) if r[0][0] != "(not set)"}
    parse = lambda blk: {html.unescape(l): (html.unescape(v), html.unescape(n)) for v, l, n in re.findall(r"<div class='gt'><b>(.*?)</b><span>(.*?)</span><small>(.*?)</small>(?:<em class='gcmp[^']*'>.*?</em>)?</div>", blk)}
    def seg(i):   # one set of Game stats cards (view-period-players)
        x = page.find(f"id='{i}'"); y = page.find("<div class='gst'", x + 10); z = page.find("</div></div>", x)
        return "" if x < 0 else page[x:min(q for q in (y, z + 12) if q > x)]
    v0 = page.find("id='gst-vf-d7-all'")
    tiles = parse(seg("gst-all-d7-all"))   # Guy, Nov 25: the All versions / Last 7 days / All players cards
    tile = lambda l: tiles.get(l, ("", ""))
    n1 = lambda text, pat: _num(pat, text, int)
    VB = G.get("vf")
    if VB and v0 >= 0:   # the newest-versions tiles must match their own numbers
        # Guy, Nov 18: version Purchases tile = real App Store purchases from RevenueCat (own pull), never Firebase test buys
        try:
            from sources import rc_lite
            import pandas as _pd
            _rcall = rc_lite.fetch(keys, today); _rc = _rcall.get("RC Purchases Lite")
        except Exception:
            _rcall = _rc = None
        try:   # Guy, Nov 21: "~N today" leaves out test installs (first opens on a build newer than the App Store's live version)
            _new = {r.date: int(r.new) for r in _rcall["RC New Lite"][0].itertuples()}
            _ins = {k: v for k, v in json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "installs-cache.json"))).items() if v is not None}
            import social_report as _sr
            _now = dt.datetime.now(); _td = _now.date().isoformat()   # same clock as the report's "today" (dl_estimate / write_html)
            _est = _sr.dl_estimate(_ins, _new, _now)
            _m = re.search(r"App Store installs: <b>~([\d,]+)</b> today", page)
            if _td in _est:
                C.same("Installs today estimate (test installs left out)", int(_m.group(1).replace(",", "")) if _m else None, _est[_td], 2)
            # Guy, Nov 22: "today" showed 58 at 3 AM because RevenueCat's chart counts UTC days (from 7 PM ET the night before).
            # Own count: customers first seen since Eastern midnight; today's estimate can never be more than that.
            import requests as _rq
            _key = open(os.path.join(keys, "revenuecat-key.txt")).read().strip()
            _t0 = dt.datetime.combine(_now.date(), dt.time()).astimezone().timestamp() * 1000
            _u, _since = f"{rc_lite.API}/v2/projects/{rc_lite.PROJECT}/customers?limit=1000", 0
            while _u:
                _j = _rq.get(_u, headers={"Authorization": "Bearer " + _key}, timeout=60).json()
                _since += sum(1 for c in _j.get("items") or [] if c.get("first_seen_at", 0) >= _t0)
                _n = _j.get("next_page"); _u = _n if not _n or _n.startswith("http") else (rc_lite.API + _n if _n else None)
            if _m:
                C.true("Installs today estimate counts only since midnight (Eastern)", int(_m.group(1).replace(",", "")) <= _since,
                       f"page ~{_m.group(1)} today, RevenueCat has {_since} new players since midnight")
        except Exception as _e:
            C.fails.append(f"Installs estimate check could not run: {type(_e).__name__}: {_e}"[:240])
        # Guy, Nov 19: Day-1 return tiles and the Before 1.3.11 set (own pulls, not the report's numbers)
        def next_day(day, vs, lo=1, hi=1):   # own copy: players whose first day was on these released versions (funnel step 1) and who played the next day (step 2)
            f = lambda x: {("funnelFieldFilter" if k == "filter" else k): f(v) for k, v in x.items()} if isinstance(x, dict) else [f(v) for v in x] if isinstance(x, list) else x
            k1, n1d = day.strftime("%Y%m%d"), day + dt.timedelta(days=hi)
            body = {"dateRanges": [{"startDate": day.isoformat(), "endDate": n1d.isoformat()}], "funnel": {"steps": [
                {"name": "start", "filterExpression": f(AND(released_only(day, day, vs), has("firstSessionDate", k1), has("date", k1), NO_CT))},
                {"name": "back", "filterExpression": f(among("date", [(day + dt.timedelta(days=i)).strftime("%Y%m%d") for i in range(lo, hi + 1)]))}]}}
            r = s.post(f"https://analyticsdata.googleapis.com/v1alpha/properties/{PROPERTY}:runFunnelReport", json=body, timeout=60)
            r.raise_for_status()
            return sum(int(x["metricValues"][0]["value"]) for x in r.json().get("funnelTable", {}).get("rows", []) if x["dimensionValues"][0]["value"].startswith("2"))
        def d1_check(name, B, tl):
            d = B.get("d1")
            if not d:
                return
            vs = [v for v in want if ((_ver(v) < (1, 3, 11)) if B["label"].startswith("Before") else ((1, 3, 11) <= _ver(v) <= (1, 3, 17)))]   # Guy, Nov 22: "1.3.11 to 1.3.17"
            a, b = dt.date.fromisoformat(d[2]), dt.date.fromisoformat(d[3])
            base = back = 0
            for i in range((b - a).days + 1):
                day = a + dt.timedelta(days=i); key = day.strftime("%Y%m%d")
                n0 = one((day, day), flt=AND(released_only(day, day, vs), has("firstSessionDate", key)))
                base += n0
                if n0:
                    back += min(n0, next_day(day, vs))   # Guy, Nov 24: returners tied to their start version
            C.same(f"{name} Day-1: new players", n1(tl("Day-1 return")[1], r"of ([\d,]+) new"), base, 0)
            C.same(f"{name} Day-1: came back", n1(tl("Day-1 return")[1], r"^([\d,]+) of"), back, 0)
        def d7_check(name, B, tl):   # Guy, Nov 21: Day-7 return tile (came back on day 7 or later), own pulls
            d = B.get("d7")
            if not d:
                C.true(f"{name} Day-7 tile says no data yet", "no player has reached day 7 yet" in tl("Day-7 return")[1], f"tile says {tl('Day-7 return')}")
                return
            vs = [v for v in want if ((_ver(v) < (1, 3, 11)) if B["label"].startswith("Before") else ((1, 3, 11) <= _ver(v) <= (1, 3, 17)))]   # Guy, Nov 22: "1.3.11 to 1.3.17"
            a, b = dt.date.fromisoformat(d[2]), dt.date.fromisoformat(d[3])
            base = back = 0
            for i in range((b - a).days + 1):
                day = a + dt.timedelta(days=i); key = day.strftime("%Y%m%d")
                n0 = one((day, day), flt=AND(released_only(day, day, vs), has("firstSessionDate", key)))
                base += n0
                if n0:
                    back += min(n0, next_day(day, vs, 7, (today - day).days))   # Guy, Nov 24: returners tied to their start version
            C.same(f"{name} Day-7: new players", n1(tl("Day-7 return")[1], r"of ([\d,]+) new"), base, 1)
            C.same(f"{name} Day-7: came back", n1(tl("Day-7 return")[1], r"^([\d,]+) of"), back, 1)
        # Guy, Nov 24: Quiet start card, own pulls per row (first-day wins, level 10, next day)
        _qh = page[page.find("<div class='qs' id='quiet'>"):][:6000] if "<div class='qs' id='quiet'>" in page else ""
        C.true("Quiet start card on the page", bool(_qh), "missing")
        C.true("Quiet start has the After, 1.4.0 to 1.4.2 and After, 1.5.0+ rows", "<b>After, 1.4.0 to 1.4.2</b>" in _qh and "<b>After, 1.5.0+</b>" in _qh, "missing")   # Guy, Nov 25
        C.true("Quiet start table has no background of its own", ".qs .qsw table{width:100%;border-collapse:collapse;background:none}" in page, "white box behind the table")   # Guy, Nov 24
        _qn = [(m[1], re.findall(r"<td[^>]*>(.*?)</td>", m[2])) for m in re.finditer(r"<tr[^>]*><td><b>(.*?)</b><small>.*?</small></td>(.*?)</tr>", _qh)]
        _qd = dict(_qn); _qsum = 0
        for _k, _lab, _a, _c, _in in (("older", "Earlier", dt.date(2026, 11, 15), dt.date(2026, 11, 23), lambda x: (1, 3, 11) <= x <= (1, 3, 17)), ("before", "Before", dt.date(2026, 11, 21), dt.date(2026, 11, 23), lambda x: (1, 3, 20) <= x < (1, 4, 0)), ("after", "After", dt.date(2026, 11, 25), today, lambda x: (1, 3, 20) <= x < (1, 4, 0)), ("after140", "After, 1.4.0 to 1.4.2", dt.date(2026, 11, 25), today, lambda x: (1, 4, 0) <= x < (1, 5, 0)), ("after150", "After, 1.5.0+", dt.date(2026, 11, 25), today, lambda x: x >= (1, 5, 0))):
            _vs = [v for v in want if _in(_ver(v))]
            _n24, _w24 = 0, {}
            if _k == "after":   # Nov 24 from 10:13 AM ET = 11:13 on Google's UTC-4 clock (Guy: "why isn't it showing the 3 new players")
                _f24 = AND(among("appVersion", _vs), has("firstSessionDate", "20261124"))
                _n24 = sum(int(r[1][0]) for r in run((dt.date(2026, 11, 24), dt.date(2026, 11, 24)), ["dateHourMinute"], ["totalUsers"], AND(_f24, has("eventName", "first_open"))) if r[0][0] >= "202611241113")
                C.true("Quiet start After: Nov 24 players are on the card", n1((_qd.get("After") or ["", ""])[0] or "0", r"([\d,]+)") >= _n24 - 1, f"{_n24} first opens since 10:13 AM, card {(_qd.get('After') or ['?'])[0]}")
                for _l in ("1", "2", "3", "7"):   # nobody who started before 10:13 AM: wins after it by players who first opened after it can't exceed those counts
                    _w24[_l] = sum(int(r[1][0]) for r in run((dt.date(2026, 11, 24), dt.date(2026, 11, 24)), ["dateHourMinute"], ["totalUsers"], AND(_f24, has("eventName", "lv_win_" + _l))) if r[0][0] >= "202611241113")
            if _k == "after" and _c < _a:
                _cl = _qd.get(_lab) or []
                C.true("Quiet start After: every level column is out of all new players", len({n1(x, r"of ([\d,]+)<") for x in _cl[1:6] if "%" in x}) <= 1, str(_cl))   # Guy, Nov 24: level 7 was out of level 1 winners
                if len(_cl) == 7 and _n24:
                    C.same("Quiet start After: new players (Nov 24)", n1(_cl[0], r"([\d,]+)"), _n24, 1)
                    for _i, _l in ((1, "1"), (2, "2"), (3, "3"), (4, "7")):
                        C.true(f"Quiet start After: won level {_l} (Nov 24) not above Google's count", (n1(_cl[_i], r"<small>([\d,]+) of") or 0) <= _w24[_l] + 1, f"card {_cl[_i]}, Google {_w24[_l]}")
            if _c < _a or not _vs:
                continue
            _rel = [v for v in _vs if rel[v] <= _c]
            if not _rel:
                continue
            _fl = AND(released_only(_a, _c, _rel), among("firstSessionDate", [(_a + dt.timedelta(days=i)).strftime("%Y%m%d") for i in range((_c - _a).days + 1)]))
            _nn = sum(int(r[1][0]) for r in run((_a, _c), ["firstSessionDate", "date"], flt=_fl) if r[0][0] == r[0][1]); _qsum += _nn
            if not _nn:
                continue
            _nn += _n24
            _ev = dict(_w24)
            for r in run((_a, _c), ["firstSessionDate", "date", "eventName"], ["totalUsers"], AND(_fl, among("eventName", ["lv_win_1", "lv_win_2", "lv_win_3", "lv_win_7"]))):
                if r[0][0] == r[0][1]:
                    _ev[r[0][2][7:]] = _ev.get(r[0][2][7:], 0) + int(r[1][0])
            _cl = _qd.get(_lab) or []
            C.true(f"Quiet start {_lab}: row with 7 numbers", len(_cl) == 7, f"{len(_cl)} cells")
            if len(_cl) == 7:
                C.same(f"Quiet start {_lab}: new players", n1(_cl[0], r"([\d,]+)"), _nn, 1)
                for _i, _l in ((1, "1"), (2, "2"), (3, "3"), (4, "7")):
                    C.same(f"Quiet start {_lab}: won level {_l}", n1(_cl[_i], r"<small>([\d,]+) of"), _ev.get(_l, 0), 3 if _k == "after" else 1) if "%" in _cl[_i] else C.true(f"Quiet start {_lab}: won level {_l} empty", not _ev.get("1"), _cl[_i])
                C.same(f"Quiet start {_lab}: level 7 is a share of all new players, like the other columns", n1(_cl[4], r"of ([\d,]+)<") or 0, n1(_cl[0], r"([\d,]+)"), 0)
                _nb = sum(min(one((_d0, _d0), flt=AND(released_only(_d0, _d0, _rel), has("firstSessionDate", _d0.strftime("%Y%m%d")))), next_day(_d0, _rel)) for _d0 in (_a + dt.timedelta(days=i) for i in range((min(_c, today - dt.timedelta(days=2)) - _a).days + 1)) if any(rel[v] <= _d0 for v in _rel)) if _k == "before" else None   # the later rows use the same code path; before is fixed and cheap to recount
                if _nb is not None:
                    C.same(f"Quiet start {_lab}: came back next day", n1(_cl[6], r"<small>([\d,]+) of"), _nb, 1)
        C.same("Quiet start: new players since Nov 25", n1(_qh, r"<b>([\d,]+) of 200</b>") if _qh else None, sum((G.get("quiet", {}).get(k) or {}).get("n", 0) for k in ("after", "after140", "after150")), 0)
        C.true("1.3.11 to 1.3.17 label (only the newest option has a +)", VB.get("label") == "1.3.11 to 1.3.17", VB.get("label"))
        PB = G.get("pre")
        C.true("Before 1.3.11 option in the version filter", bool(PB) == ("<option value='pre'>" in page), "drop-down option and data disagree")
        _o = re.findall(r"<select id='gsel'.*?</select>", page)
        C.true("Version filter order: All, Before 1.3.11, 1.3.11 to 1.3.17, 1.3.18 to 1.3.23, 1.4.0+ once live", bool(_o) and re.findall(r"value='(\w+)'", _o[0]) == (["all", "pre", "vf"] if PB else ["all", "vf"]) + list((G.get("vx") or {}).keys()), f"order is {re.findall(r'value=.(\w+).', _o[0]) if _o else 'missing'}")
        C.true("Version filter opens on the saved default, else All versions", "go(o ? o.value : 'all')" in page and "id='gdef'" in page and "getItem('gsel')" not in page,
               "missing Set as default button, or the filter remembers the last choice instead of the set default")   # Guy, Nov 19 + Nov 20 (Set as default)
        for k, BX in (G.get("vx") or {}).items():   # Guy, Nov 19: 1.3.18+ once live
            X = _ver(BX["range"][0]); H = _ver(BX["range"][1]) if BX["range"][1] else (999,)   # Guy, Nov 22: closed ranges (1.3.18/19); only the newest is open (+)
            C.true(f"{BX['label']}: + only on the newest option", (k == list(G["vx"])[-1] or not BX["label"].endswith("+")) and (BX["label"].endswith("+") == (BX["range"][1] is None)), BX["label"])
            xo = page.find(f"id='gst-{k}-d7-all'"); C.true(f"{BX['label']} tile set", xo >= 0, "missing")
            _xl = BX["range"][0]; C.true(f"{BX['label']} starts on its App Store release day", BX.get("since") == (G.get("released") or {}).get(_xl), f"starts {BX.get('since')}, released {(G.get('released') or {}).get(_xl)}")   # Nov 21: 1.3.18+ slid to Nov 21
            if xo >= 0:
                C.true(f"{BX['label']} is on the App Store", X <= _ver(G.get("live", "0")), f"live is {G.get('live')}")
                if X == _ver(G.get("live", "0")):   # Guy, Nov 21: 1.3.18+ started a day late (Apple's cached lookup still said 1.3.17); start = Apple's release day (ET), fresh lookup
                    try:
                        import requests as _rq, time as _t
                        _r = _rq.get("https://itunes.apple.com/lookup", params={"id": "6816478290", "country": "us", "t": f"{_t.time():.0f}rel"}, timeout=20).json()["results"][0]
                        if _ver(_r["version"]) == X:
                            _rd = dt.datetime.fromisoformat(_r["currentVersionReleaseDate"].replace("Z", "+00:00")).astimezone(__import__("zoneinfo").ZoneInfo("America/New_York")).date()
                            C.true(f"{BX['label']} starts on Apple's release day", BX["since"] == _rd.isoformat(), f"report starts {BX['since']}, Apple released {_rd.isoformat()}")
                    except Exception as _e:
                        C.fails.append(f"{BX['label']} release-day check could not run: {type(_e).__name__}"[:240])
    wins, tries = outcome.get("win", 0), sum(v for k, v in outcome.items() if k != "skip")   # Guy, Nov 19: skips left out of win rate
    C.same("Win rate: wins", n1(tile("Win rate")[1], r"^([\d,]+) of"), wins, wobble(wins))
    C.same("Win rate: attempts", n1(tile("Win rate")[1], r"of ([\d,]+) level"), tries, wobble(tries))
    C.same("Win rate", n1(tile("Win rate")[0], r"(\d+)%"), round(wins / tries * 100) if tries else 0, 2)
    # Guy, Nov 22: tutorial uses (free Super Stir on level 4, free Super Solve on level 5, 1.3.19+) are left out of the card; counted here per row
    _tutv = lambda v: (1, 3, 19) <= _ver(v)
    _sup = {"super_stir": 0, "super_solve": 0}
    for (e, k, l, v), (n,) in run(d7, ["eventName", "customEvent:kind", "customEvent:level", "appVersion"], ["eventCount"], AND(wk, among("eventName", list(_sup)))):
        if not (k == "free" and _tutv(v) and (e, l) in (("super_stir", "4"), ("super_solve", "5"))):
            _sup[e] += int(n)
    _tutf = {"orGroup": {"expressions": [AND(has("eventName", e), has("customEvent:kind", "free"), has("customEvent:level", l), among("appVersion", [v for v in seen if _tutv(v)] or ["none"])) for e, l in (("super_stir", "4"), ("super_solve", "5"))]}}
    _supu = one(d7, flt=AND(wk, among("eventName", list(_sup)), {"notExpression": _tutf}))
    C.same("Super Stir uses (tutorial left out)", n1(tile("Super Stir / Solve uses")[1], r"([\d,]+) Stir"), _sup["super_stir"], wobble(_sup["super_stir"]))
    C.same("Super Solve uses (tutorial left out)", n1(tile("Super Stir / Solve uses")[1], r"([\d,]+) Solve"), _sup["super_solve"], wobble(_sup["super_solve"]))
    C.same("Players who used Super Stir / Solve", n1(tile("Super Stir / Solve uses")[1], r"([\d,]+) player"), _supu, max(1, wobble(_supu)))
    C.same("Ad views per player", _num(r"([\d.]+)", tile("Ad views per player")[0]), round(ev.get("ad_shown", 0) / players, 1) if players else 0, 0.3)
    # Guy, Nov 22 audit: the tile must equal its own listed counts / its own listed players (0.7 read as 160/260 = 0.6 before)
    _at = tile("Ad views per player")
    _ap = n1(tile("Active players")[0], r"([\d,]+)")
    _ak = sum(int(x.replace(",", "")) for x in re.findall(r"([\d,]+) (?:between levels|rewarded)", _at[1]))
    C.true("Ad views per player = its listed ads / its listed players", _ap is not None and _num(r"([\d.]+)", _at[0]) == round(_ak / _ap, 1), f"tile {_at[0]}, {_ak} ads, players {_ap}")
    C.same("Rewarded ads", n1(tile("Ad views per player")[1], r"([\d,]+) rewarded"), kind.get("rewarded", 0), wobble(kind.get("rewarded", 0)))
    C.same("Ads between levels", n1(tile("Ad views per player")[1], r"([\d,]+) between levels"), kind.get("interstitial", 0), wobble(kind.get("interstitial", 0)))
    mv = lambda e, m="eventCount": int(next(iter(run(d7, (), (m,), AND(wk, has("eventName", e), has("customEvent:placement", "out_of_moves")))), ([], [0]))[1][0])
    mw, mo = mv("rewarded_watched"), mv("rewarded_offer_shown")
    C.same("+Moves videos watched", n1(tile("+Moves videos watched")[0], r"([\d,]+)"), mw, wobble(mw))
    C.same("+Moves video offers", n1(tile("+Moves videos watched")[1], r"of ([\d,]+) offers"), mo, wobble(mo))
    C.same("Active players, last 7 days (1.3.1+, test days left out)", n1(tile("Active players")[0], r"([\d,]+)"), players, 2)
    try:   # Guy, Nov 21: All versions Day-7 tile, own pull (first days 8-14 days ago, back on day 7 or later)
        _b7 = _k7 = 0
        for i in range(8, 15):
            _d = today - dt.timedelta(days=i); _key = _d.strftime("%Y%m%d")
            _n = one((_d, _d), flt=has("firstSessionDate", _key)); _b7 += _n
            if _n:
                _k7 += one((_d + dt.timedelta(days=7), today), flt=has("firstSessionDate", _key))
        _t7 = tile("Day-7 return")
        C.same("Day-7 return: new players (all versions)", n1(_t7[1], r"of ([\d,]+) new"), _b7, max(2, wobble(_b7)))
        C.same("Day-7 return: came back (all versions)", n1(_t7[1], r"^([\d,]+) of"), _k7, 1)
    except Exception as _e7:
        C.fails.append(f"Day-7 check could not run: {type(_e7).__name__}: {_e7}"[:240])
    # Guy, Nov 21: Reminders on = new players (first opened in the last 7 days) with quiet (soft_provisional) or full reminders (soft_authorized / remind_allow)
    try:
        _co = AND(wk, among("firstSessionDate", [(d7[0] + dt.timedelta(days=i)).strftime("%Y%m%d") for i in range((today - d7[0]).days + 1)]))
        _rn = one(d7, metrics=("totalUsers",), flt=_co)
        _ro = one(d7, metrics=("totalUsers",), flt=AND(_co, among("eventName", ["soft_provisional", "soft_authorized", "remind_allow"])))
        _rt = tile("Reminders on")
        C.same("Reminders on: new players (7 days)", n1(_rt[1], r"of ([\d,]+) new players"), _rn, max(1, wobble(_rn)))
        C.same("Reminders on: players with reminders (7 days)", n1(_rt[1], r"^([\d,]+) of"), _ro, max(1, wobble(_ro)))
        C.same("Reminders on %", n1(_rt[0], r"(\d+)%"), round(_ro / _rn * 100) if _rn else 0, 2)
        for _id in re.findall(r"id='(gst-[\w-]+)'", page):   # every Game stats view has the tile, and its % matches its own counts
            _t = parse(seg(_id)).get("Reminders on")
            if _t and "%" in _t[0]:
                _a, _b = n1(_t[1], r"^([\d,]+) of"), n1(_t[1], r"of ([\d,]+) new")
                C.true(f"Reminders on % adds up in {_id}", _b and abs(round(_a / _b * 100) - n1(_t[0], r"(\d+)%")) <= 1, f"{_t[0]} vs {_a} of {_b}")
        # Guy, Nov 22: Installed (est.) tile's 30-day line = GA4 devices active in the last 30 days (own pull)
        _m30 = re.search(r"([\d,]+) devices opened it in the last 30 days", page)
        C.true("Installed tile: 30-day devices line", bool(_m30) or "Installed (est.)" not in page, "missing")
        if _m30:
            C.same("Installed tile: devices opened in the last 30 days", int(_m30[1].replace(",", "")), one((today - dt.timedelta(days=29), today)), max(1, wobble(int(_m30[1].replace(",", "")))))
        # Guy, Nov 22: Day-1 return by version chart: "All" bar = that version's Day-1 tile; Google Ads + other = All
        _dv = page.find("Day-1 return by version")
        C.true("Day-1 by version chart on the page", _dv >= 0, "missing")
        for _lb in [x["label"] for x in (G.get("vx") or {}).values()] + list(G.get("vxnext") or []):   # Guy, Nov 24: "make a new section for 1.4.0" (also before it is live)
            C.true(f"Day-1 chart section {_lb}", page.count(f"<div class='dvh'>{html.escape(_lb)}</div>") == 1, "missing or twice")
        C.true("Google Analytics questions per refresh under 1,000", 0 < (G.get("calls") or 0) < 1000, f"{G.get('calls')} questions (785 on Nov 24; was 1,085): the refresh is slowing down again")   # Guy, Nov 24: refresh took almost 10 min
        C.true("Live version is in one version group", G.get("live") not in (G.get("versions") or []) or any(G.get("live") in (x or {}).get("vers", []) for x in [G.get("pre"), G.get("vf")] + list((G.get("vx") or {}).values())), f"live {G.get('live')} is in no group")
        for BB in [G.get("pre"), G.get("vf")] + list((G.get("vx") or {}).values()):
            if not BB or not BB.get("d1"):
                continue
            _sg = page[page.find(f"<div class='dvh'>{html.escape(BB['label'])}</div>", _dv):]
            _m = re.search(r"All new players</span>.*?<small>([\d,]+) of ([\d,]+)", _sg[:3000])
            C.true(f"Day-1 chart {BB['label']}: All = its tile ({BB['d1'][0]} of {BB['d1'][1]})", bool(_m) and (int(_m[1].replace(',', '')), int(_m[2].replace(',', ''))) == (BB["d1"][0], BB["d1"][1]), _m.group(0)[-40:] if _m else "missing")
            _sr = BB.get("d1src") or {}
            if _sr:
                C.same(f"Day-1 chart {BB['label']}: Google Ads + other new players = all", sum((_sr.get(k) or [0, 0])[1] for k in ("ads", "other")), BB["d1"][1], max(1, wobble(BB["d1"][1])))
                C.same(f"Day-1 chart {BB['label']}: Google Ads + other came back = all", sum((_sr.get(k) or [0, 0])[0] for k in ("ads", "other")), BB["d1"][0], max(1, wobble(BB["d1"][0])))
        # Guy, Nov 25: third drop-down (Today, Last 7 days, This month, Last month) + cards and data consistent
        _ids = re.findall(r"id='(gst-[\w-]+)'", page)
        C.true("Time drop-down: Today, Yesterday, Last 7 days, This month, Last month", re.findall(r"<option value='(\w+)'(?: selected)?>([^<]+)</option>", (re.findall(r"<select id='tsel'.*?</select>", page) or [""])[0]) == [("today", "Today"), ("yest", "Yesterday"), ("d7", "Last 7 days"), ("month", "This month"), ("last", "Last month")] and "bl_tsel_default" in page, "wrong or missing")
        C.true("Players filter on the page", "id='psel'" in page and "bl_psel_default" in page, "missing")
        _NM = ["Active players", "Day-1 return", "Day-7 return", "Win rate", "Typical furthest level", "Reached level 10 on day one", "Ad views per player", "+Moves videos watched", "Super Stir / Solve uses", "Shares", "Purchases", "Reminders on"]
        _VW = {"all": want, **({"pre": [v for v in want if _ver(v) < (1, 3, 11)]} if G.get("pre") else {}), **({"vf": [v for v in want if (1, 3, 11) <= _ver(v) <= (1, 3, 17)]} if G.get("vf") else {}), **{k: B["vers"] for k, B in (G.get("vx") or {}).items()}}
        C.true("A card set for every version, time and player choice", sorted(_ids) == sorted(f"gst-{v}-{t}-{w}" for v in _VW for t in ("today", "yest", "d7", "month", "last") for w in ("all", "new")), f"{len(_ids)} sets")

        def _own(a):   # own pulls for one view and period
            v, t = a
            r0, r1 = (dt.date.fromisoformat(x) for x in G["periods"][t])
            vs = [x for x in _VW[v] if rel[x] <= r1]
            if not vs:
                return a, (0, 0, {}, {})
            fl = released_only(r0, r1, vs)
            o = {r[0][0]: int(r[1][0]) for r in run((r0, r1), ["customEvent:outcome"], ["eventCount"], AND(fl, has("eventName", "level_end")))}
            kd = {r[0][0]: int(r[1][0]) for r in run((r0, r1), ["customEvent:kind"], ["eventCount"], AND(fl, has("eventName", "ad_shown")))}
            return a, (one((r0, r1), flt=fl), sum(int(r[1][0]) for r in run((r0, r1), ["firstSessionDate", "date"], flt=fl) if r[0][0] == r[0][1]), o, kd)
        with ThreadPoolExecutor(5) as _ex:
            _res = dict(_ex.map(_own, [(v, t) for v in _VW for t in (G.get("periods") or {})]))
        for (v, t), (na, nn, o, kd) in _res.items():
            A, N = parse(seg(f"gst-{v}-{t}-all")), parse(seg(f"gst-{v}-{t}-new")); nm = f"{v}/{t}"
            C.true(f"{nm}: the same 12 cards in the same order", list(A) == _NM and list(N) == ["New players"] + _NM[1:], f"{list(A)} / {list(N)}")
            g = lambda T, l: T.get(l, ("", ""))
            mvn = lambda x: max(3, wobble(x))
            n0 = lambda text, pat: 0 if re.search(r"no (level attempts|players) yet", text or "") else n1(text, pat)   # an empty card says so in words
            C.same(f"{nm}: active players", n1(g(A, "Active players")[0], r"([\d,]+)"), na, mvn(na)); C.same(f"{nm}: new players", n1(g(N, "New players")[0], r"([\d,]+)"), nn, mvn(nn))
            C.same(f"{nm}: wins", n0(g(A, "Win rate")[1], r"^([\d,]+) of"), o.get("win", 0), max(3, wobble(o.get("win", 0))))
            C.same(f"{nm}: attempts", n0(g(A, "Win rate")[1], r"of ([\d,]+) level"), sum(x for k, x in o.items() if k not in ("skip", "", "(not set)")), max(3, wobble(o.get("win", 0))))
            C.same(f"{nm}: rewarded ads", n0(g(A, "Ad views per player")[1], r"([\d,]+) rewarded"), kd.get("rewarded", 0), max(2, wobble(kd.get("rewarded", 0)))); C.same(f"{nm}: ads between levels", n0(g(A, "Ad views per player")[1], r"([\d,]+) between"), kd.get("interstitial", 0), max(2, wobble(kd.get("interstitial", 0))))
            nw = n1(g(N, "New players")[0], r"([\d,]+)")
            _nset = {x for x in (n1(g(A, "Active players")[1], r"([\d,]+) new"), n1(g(A, "Reached level 10 on day one")[1], r"of ([\d,]+) new"), n1(g(A, "Reminders on")[1], r"of ([\d,]+) new"), n1(g(N, "Reminders on")[1], r"of ([\d,]+) new")) if x is not None}
            C.true(f"{nm}: one number of new players on every card", _nset <= {nw}, f"{_nset} vs {nw}")
            if v == "vf" and t == "month" and _qd.get("Earlier"):   # Guy reads both: the card and Quiet start must say the same
                C.same("1.3.11 to 1.3.17 level 10 card = Quiet start Earlier row", n1(g(A, "Reached level 10 on day one")[1], r"of ([\d,]+) new"), n1(_qd["Earlier"][0], r"([\d,]+)"), 1)
            for T in (A, N):
                for l, (x, y) in T.items():   # every percentage equals its own "a of b"
                    q = re.match(r"([\d,]+) of ([\d,]+) ", y)
                    if q and "%" in x:
                        i, k = (int(z.replace(",", "")) for z in q.groups()); C.true(f"{nm}: {l} % = its own counts", k > 0 and (abs(round(i / k * 100) - int(re.sub(r"[^\d]", "", x) or 0)) <= 1) and i <= k, f"{x}, {y}")
                tp = n1(g(T, "Typical furthest level")[1], r"top player ([\d,]+)")
                if tp and t != "month" and v == "all":   # Guy, Nov 25: "top player 557" was the month's, not the 7 days'
                    C.true(f"{nm}: top player is from these days", tp <= max((int(r[0][0]) for r in run(tuple(dt.date.fromisoformat(z) for z in G["periods"][t]), ["customUser:max_level"], flt=released_only(*(dt.date.fromisoformat(z) for z in G["periods"][t]))) if r[0][0].isdigit()), default=0), f"top {tp}")
                P0 = n1(g(T, "Active players")[0] or g(T, "New players")[0], r"([\d,]+)"); av = g(T, "Ad views per player"); sm = sum(int(z.replace(",", "")) for z in re.findall(r"([\d,]+) (?:between levels|rewarded)", av[1]))
                C.true(f"{nm}: ad views per player = its ads / its players", (not P0 and av[0] == "—") or (P0 and abs(_num(r"([\d.]+)", av[0]) - sm / P0) <= 0.051), f"{av} {P0}")
        if _rcall and _rcall.get("RC Purchases Lite") is not None:   # purchases: RevenueCat, the days of each choice
            _tx = {r.date: r.tx for r in _rcall["RC Purchases Lite"][0].itertuples()}
            for t, (x, y) in (G.get("periods") or {}).items():
                C.same(f"Purchases, {t} (RevenueCat)", n1(parse(seg(f"gst-all-{t}-all")).get("Purchases", ("", ""))[0], r"([\d,]+)"), int(sum(v or 0 for k, v in _tx.items() if x <= k <= y and v == v)), 0)
    except Exception as _e2:
        C.fails.append(f"Reminders on check could not run: {type(_e2).__name__}: {_e2}"[:240])
    # levels
    everyone = released_only(START, today)
    levels = sorted(int(r[0][0]) for r in run((START, today), ["customUser:max_level"], flt=everyone) if r[0][0].isdigit())

    def reach_of(lv, flt, dates):
        return one(dates, flt=AND(flt, among("customUser:max_level", [str(x) for x in levels if x >= lv])))
    with ThreadPoolExecutor(5) as ex:
        by = dict(zip(levels, ex.map(lambda lv: reach_of(lv, everyone, (START, today)), levels)))
    top = by[levels[0]] if levels else 0
    avg = sum(lv * (by[lv] - (by[levels[i + 1]] if i + 1 < len(levels) else 0)) for i, lv in enumerate(levels)) / top if top else 0
    half = max((lv for lv in levels if by[lv] * 2 >= top), default=0)
    _l7 = sorted(int(r[0][0]) for r in run(d7, ["customUser:max_level"], flt=wk) if r[0][0].isdigit())
    with ThreadPoolExecutor(5) as ex:
        _b7l = dict(zip(_l7, ex.map(lambda lv: one(d7, flt=AND(wk, among("customUser:max_level", [str(x) for x in _l7 if x >= lv]))), _l7)))
    _t7l = _b7l[_l7[0]] if _l7 else 0; _tl = tile("Typical furthest level")
    C.same("Typical furthest level (7 days)", _num(r"([\d.]+)", _tl[0]), max((lv for lv in _l7 if _b7l[lv] * 2 >= _t7l), default=0), 0)   # Guy, Nov 8: middle player, not the average
    C.same("Typical furthest level: players", n1(_tl[1], r"half of ([\d,]+) player"), _t7l, 2)
    C.same("Typical furthest level: top player", n1(_tl[1], r"top player ([\d,]+)"), _l7[-1] if _l7 else 0, 0)
    m = re.search(r"window\.GAMECHART = \(\) => \{ const X = (\{.*?\}); if \(!window\.Chart\)", page, re.S)
    C.true("Level chart data found on the page", bool(m))
    if not m:
        return
    X = json.loads(m.group(1))
    recent = released_only(today - dt.timedelta(days=8), today)   # Guy, Nov 23: quit = 9+ days away
    for i, st in enumerate(X["steps"]):
        C.same(f"Reached level {st}", X["reach"][i], next((by[k] for k in levels if k >= st), 0), 1)
        C.same(f"Still playing at level {st}", X["playing"][i], min(reach_of(st, recent, (today - dt.timedelta(days=8), today)), X["reach"][i]), 1)
        C.true(f"Level {st} bar adds up", X["playing"][i] <= X["reach"][i] and (i == 0 or X["reach"][i] <= X["reach"][i - 1]))
    # players per day chart
    daily = {r[0][0]: int(r[1][0]) for r in run((START, today), ["date"])}
    newer = {r[0][0]: int(r[1][0]) for r in run((START, today), ["date"], flt=everyone)}
    day_ev = {(r[0][0], r[0][1]): int(r[1][0]) for r in run((START, today), ["date", "eventName"], ["eventCount"], AND(everyone, among("eventName", ["super_solve", "super_stir", "ad_shown", "level_up", "level_end"])))}
    for i, lab in enumerate(X["labels"]):
        d = dt.datetime.strptime(f"{lab} {today.year}", "%m/%d %Y" if "/" in lab else "%b %d %Y").date()
        k, gap, recent_day = d.strftime("%Y%m%d"), (1 if d >= today - dt.timedelta(days=1) else 0), d >= today - dt.timedelta(days=1)
        C.same(f"Players on {lab}", X["players"][i], daily.get(k, 0), gap)
        C.same(f"Players on released versions, {lab}", X["newer"][i], newer.get(k, 0), gap)
        C.same(f"App Store purchases on {lab}", X["purchase_ok"][i], C.iapn.get(d.isoformat(), 0))
        for e in ("super_solve", "super_stir", "ad_shown", "level_up", "level_end"):
            C.same(f"{e} on {lab}", X[e][i], day_ev.get((k, e), 0), wobble(day_ev.get((k, e), 0)) if recent_day else 0)
    # rewarded videos per day (AdMob), Guy Nov 9; recent days move as AdMob updates
    try:
        _, rw = money_lite._admob(keys, START - dt.timedelta(days=7), today)
    except Exception as ex:
        rw = None; C.true(f"AdMob rewarded counts readable ({ex})", False)
    if rw is not None:
        C.true("Rewarded videos found in AdMob (not all zero)", sum(rw.values()) > 0 and sum(v or 0 for v in X["rwd"]) > 0)
        for i, lab in enumerate(X["labels"]):
            d = dt.datetime.strptime(f"{lab} {today.year}", "%m/%d %Y" if "/" in lab else "%b %d %Y").date()
            gap = 3 if d >= today - dt.timedelta(days=1) else 0
            C.same(f"Rewarded videos on {lab}", X["rwd"][i] or 0, rw.get(d.isoformat(), 0), gap)
            C.same(f"Rewarded videos week before {lab}", X["rwp"][i] or 0, rw.get((d - dt.timedelta(days=7)).isoformat(), 0), gap if d - dt.timedelta(days=7) >= today - dt.timedelta(days=1) else 0)
    # new-version comparison
    if X.get("cver") and (G.get("compare") or {}).get("since"):
        since, ver = dt.date.fromisoformat(G["compare"]["since"]), _ver(X["cver"])
        dates = lambda a, b: [(a + dt.timedelta(days=i)).strftime("%Y%m%d") for i in range((b - a).days + 1)]
        new = AND(released_only(START, today, [v for v in want if _ver(v) >= ver]), among("firstSessionDate", dates(since, today)))
        bv = _ver(G["compare"].get("base") or "0.0.0"); b0 = dt.date.fromisoformat(G["compare"].get("bsince") or START.isoformat())   # Guy, Nov 20: reference = 1.3.11+
        old = AND(released_only(START, today, [v for v in want if bv <= _ver(v) < ver]), among("firstSessionDate", dates(b0, since - dt.timedelta(days=1))))
        C.same("New players on the new version", X["cn"], reach_of(1, new, (START, today)), 1)
        C.same("New players before the new version", X["co"], reach_of(1, old, (START, today)), 1)
    # retention (the same way Firebase's cohorts define it)
    a, b = today - dt.timedelta(days=8), today - dt.timedelta(days=2)
    body = {"dimensions": [{"name": "cohort"}, {"name": "cohortNthDay"}], "metrics": [{"name": "cohortActiveUsers"}], "cohortSpec": {"cohortsRange": {"granularity": "DAILY", "startOffset": 0, "endOffset": 1},
            "cohorts": [{"name": str(i), "dimension": "firstSessionDate", "dateRange": {"startDate": (a + dt.timedelta(days=i)).isoformat(), "endDate": (a + dt.timedelta(days=i)).isoformat()}} for i in range((b - a).days + 1)]}, "dimensionFilter": NO_CT}
    rows = s.post(f"https://analyticsdata.googleapis.com/v1beta/properties/{PROPERTY}:runReport", json=body, timeout=60).json().get("rows", [])
    base = sum(int(r["metricValues"][0]["value"]) for r in rows if int(r["dimensionValues"][1]["value"]) == 0)
    back = sum(int(r["metricValues"][0]["value"]) for r in rows if int(r["dimensionValues"][1]["value"]) == 1)
    C.same("Day-1 retention", _num(r"(\d+)% <small><span class='nf'>day-1 retention", page), round(back / base * 100) if base else 0, 1)
    # Guy, Nov 23: Day-1 return chart: last point = the badge's 7 start days (same cohorts), every start day since Nov 1 present
    _m = re.search(r"id='d1tc' data-last='([\d.]+)' data-lo='([\d.]+)'", page)
    C.true("Day-1 return chart on the page", bool(_m), "missing")
    if _m:
        C.same("Day-1 chart, last point = 7 start days (Google Analytics)", float(_m.group(1)), round(back / base * 100, 1) if base else 0, 1.0)
        C.true("Day-1 chart low is not above its last point", float(_m.group(2)) <= float(_m.group(1)), f"low {_m.group(2)} > last {_m.group(1)}")
        _dd = re.search(r"window.D1TCHART = \(\) => \{ const X = (\{.*?\}), cv = ", page)
        _X = json.loads(_dd.group(1)) if _dd else {}
        C.same("Day-1 chart start days (Nov 1 to 2 days ago)", len(_X.get("base", [])), (today - dt.timedelta(days=2) - dt.date(2026, 11, 1)).days + 1)
    # Guy, Nov 23: "Quit is 9+ days ago" in How far players get
    C.true("Levels chart says Quit (9+ days away)", "Quit (9+ days away)" in page and "3+ days away" not in page, "old 3-day wording or label missing")



def _check_social_split(C, page):
    """Guy, Nov 16: Search vs Social (est.) in the downloads + earnings chart. Recomputed here from the saved search history:
    base = lower quartile of daily search downloads / search impressions since Oct 5; expected = min(search, round(impressions x base))."""
    m = re.search(r"window\.SRCCHART = \(\) => \{ const X = (\{.*?\}), cv = ", page, re.S)
    if not m:
        C.fails.append("Social (est.) check: downloads chart data not found"); return
    X = json.loads(m.group(1))
    SS = json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "search-split-cache.json")))
    r = sorted(v["dl"] / v["imp"] for d, v in SS.items() if d >= "2026-10-05" and v.get("imp"))
    q = (len(r) - 1) * 0.25; lo = int(q); base = r[lo] + (r[min(lo + 1, len(r) - 1)] - r[lo]) * (q - lo) if r else 0.0   # same as pandas quantile(0.25)
    C.same("Social (est.) base rate x 100,000", round(X.get("base", 0) * 1e5), round(base * 1e5), 0)
    bad = 0
    for i, imp in enumerate(X.get("imp") or []):
        tot = X["dl_search"][i] + X.get("dl_social", [0] * len(X["imp"]))[i]
        want = min(tot, round(imp * base)) if imp and base else tot
        bad += X["dl_search"][i] != want
    C.same("Social (est.) days split wrong", bad, 0, 0)

def _check_sources(C):
    """Guy, Nov 24: Nov 22 counted twice in the download sources after the app was renamed. A day's downloads by source can differ a
    little from Apple's sales report, never by half: days over 1.5x (10+ downloads) fail."""
    here = os.path.dirname(os.path.abspath(__file__))
    src, ins = json.load(open(os.path.join(here, "sources-cache.json"))), json.load(open(os.path.join(here, "installs-cache.json")))
    bad = [f"{d}: {n} by source, {ins[d]} downloads" for d, r in src.items()
           for n in [sum(v for k, v in r.items() if k.startswith("dl_"))] if (ins.get(d) or 0) >= 10 and n > 1.5 * ins[d]]
    C.same("Download source days counted twice " + "; ".join(bad), len(bad), 0, 0)

def _check_search_chart(C, page):
    """Guy, Nov 17: App Store search chart: actual times shown match the saved search history, and the projected next Sunday
    is recomputed independently (same weekday last week x last week's growth, Mon-Sat and Sunday separately, clamped 1-3x)."""
    m = re.search(r"window\.SRCHCHART = \(\) => \{ const X = (\{.*?\}), cv = ", page, re.S)
    if not m:
        C.fails.append("App Store search check: chart data not found"); return
    X = json.loads(m.group(1))
    SS = json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "search-split-cache.json")))
    imp = {d: v["imp"] for d, v in SS.items() if v.get("imp")}
    days = sorted(imp)[-60:]
    C.same("Search days with wrong times shown", sum(a != b for a, b in zip(X["imp"][:X["n0"]], [imp[d] for d in days])) + abs(X["n0"] - len(days)), 0, 0)
    D = dt.date.fromisoformat; last = days[-1]
    w = lambda k, sun: sum(imp.get((D(last) - dt.timedelta(days=i + k)).isoformat(), 0) for i in range(7) if ((D(last) - dt.timedelta(days=i + k)).weekday() == 6) == sun)
    f = lambda sun: max(1.0, min(w(0, sun) / w(7, sun), 3.0)) if w(7, sun) else 1.0
    end = D(last) + dt.timedelta(days=(6 - D(last).weekday()) or 7)
    b = imp.get((end - dt.timedelta(days=7)).isoformat(), 0)
    C.same("Search projected Sunday (middle)", X["mid"][-1], round(b * (1 + f(True)) / 2), 0)
    C.same("Search projected Sunday (high)", X["hi"][-1], round(b * f(True)), 0)

def _check_views(C, page, snap, prev, stale, errors, plats):
    C.true("Every source pulled", not errors, "; ".join(errors)[:300])
    C.true("No site showing old numbers", not stale, ", ".join(stale))
    C.same("Total views", _num(r"([\d,]+) <small><span class='nf'>total views", page, int), sum((snap.get(p) or {}).get("views") or 0 for p in plats))
    for p in plats:
        now, was = (snap.get(p) or {}).get("views"), ((prev or {}).get(p) or {}).get("views")
        C.true(f"{p} views present", now is not None)
        if now is not None and was:
            C.true(f"{p} views didn't fall", now >= was * 0.99, f"{was:,} at the last check, {now:,} now")
    # Guy, Nov 21 ("this is something you should've caught"): a site total that isn't the sum of its own posts can jump with no post moving
    # (YouTube counted unlisted Google Ads videos: +1,202 in one check). Every site's total must equal its posts in this check's post history.
    try:
        _ph = json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "posts-history.json")))[-1]["posts"]
        for p in plats:
            if (snap.get(p) or {}).get("views") is not None:
                _sum = sum(v or 0 for k, v in _ph.items() if k.startswith(p + ":"))
                C.same(f"{p} total = sum of its posts (no ads or hidden videos)", snap[p]["views"], _sum, max(5, round(_sum * 0.002)))
    except Exception as _e:
        C.fails.append(f"Site totals vs posts check could not run: {type(_e).__name__}: {_e}"[:240])


def run(html_path, keys, G, snap, prev, stale, errors, plats, today=None):
    """Compares the finished page with the sources. Returns the Checks; the page is not changed."""
    today = today or dt.date.today()
    page = open(html_path, encoding="utf-8").read()
    C = Checks()
    for name, step in (("Views", lambda: _check_views(C, page, snap, prev, stale, errors, plats)), ("App Store, downloads and money", lambda: C.__setattr__("on_sale", _check_store(C, page, keys, today))),
                       ("Game stats", lambda: _check_game(C, page, keys, today, G, C.on_sale)), ("Social (est.)", lambda: _check_social_split(C, page)), ("App Store search", lambda: _check_search_chart(C, page)), ("Download sources", lambda: _check_sources(C))):
        try:
            step()
        except Exception as e:
            msg = re.sub(r"(token|key|secret)=[^&\s'\"]+", r"\1=***", f"{type(e).__name__}: {e}", flags=re.I)
            C.fails.append(f"{name} check could not run: {msg}"[:240])
    try:   # Guy, Nov 19: US rating count must match the most common of 5 fresh Apple lookups (Apple's servers disagreed 3 vs 2)
        import collections, time as _t, requests as _rq
        got = []
        for k in range(5):
            r = _rq.get("https://itunes.apple.com/lookup", params={"id": "6816478290", "country": "us", "t": f"{_t.time():.0f}v{k}"}, timeout=20)
            if r.ok:
                got.append(int((r.json().get("results") or [{}])[0].get("userRatingCount") or 0))
            _t.sleep(2)
        if got:
            cnt = collections.Counter(got); top = max(cnt.values()); want_n = min(n for n, c in cnt.items() if c == top)
            m = re.search(r"Star ratings by country: ([^.']*)", page)
            us = int((re.search(r"US (\d+)", m.group(1)) or [0, 0])[1]) if m else None
            C.same("US ratings (most common of 5 Apple lookups)", us, want_n, 0)
            tile = re.search(r"class='dayt rclick'[^>]*>([\d,]+)", page)   # Guy, Nov 26: the top card shows US ratings only
            C.same("Top card = US ratings", int(tile.group(1).replace(",", "")) if tile else None, want_n, 0)
            rows = re.findall(r"<tr data-c='(\w+)'><td class='cmnf'>[^<]*</td><td class='cmnm rcn'>\w+</td><td class='rsc'>.*?</td><td class='cmnn'>([\d,]+)</td>", page)
            C.true("Ratings list has rows", bool(rows), "no rows found")
            C.true("Ratings list: only countries with ratings, US row = US count", all(int(x.replace(",", "")) > 0 for _, x in rows) and dict(rows).get("US", "0").replace(",", "") == str(want_n), f"{rows}")
    except Exception as e:
        C.fails.append(f"Ratings check could not run: {type(e).__name__}"[:240])
    # Guy, Nov 19: every date pop-up header starts with the day ("Sun. 11/15")
    fulls = [x for arr in re.findall(r'"p?full": \[([^\]]*)\]', page) for x in re.findall(r'"([^"]*)"', arr)]
    C.true("Pop-up dates read 'Sun. 11/15'", bool(fulls) and all(re.fullmatch(r"(Sun|Mon|Tue|Wed|Thu|Fri|Sat)\. \d{1,2}/\d{1,2}", x) for x in fulls), f"{len(fulls)} dates, e.g. {[x for x in fulls if not re.fullmatch(r'(Sun|Mon|Tue|Wed|Thu|Fri|Sat)\. \d{1,2}/\d{1,2}', x)][:2]}")
    C.true("Views and earnings pop-ups add the day", "window.DDD = " in page and page.count("DDD(") >= 2, "DDD helper missing")
    try:   # Guy, Nov 20: "make captions consistent". A Videos card titled with a logged ad's raw caption missed its ad match
        import html as _h, json as _j, os as _o
        rows = _j.load(open(_o.path.join(_o.path.dirname(_o.path.abspath(__file__)), "ad-log.json")))
        caps = {(a.get(s) or "")[:90]: a["ad"] for a in rows for s in ("facebook", "instagram") if a.get(s) and (a.get(s) or "")[:90] != a["title"][:90]}
        cards = [_h.unescape(t) for t in re.findall(r"<div class='vct'>(.*?)</div>", page)]
        bad = [f"{caps[t]}: {t[:40]}" for t in cards if t in caps]
        C.true("Video cards use the ad-log title (no raw captions)", bool(cards) and not bad, "; ".join(bad[:3]))
    except Exception as e:
        C.fails.append(f"Video card title check could not run: {type(e).__name__}"[:240])
    # Guy, Nov 7: the data check is a build step, not part of the report; results go to the build log only, nothing on the page
    return C
