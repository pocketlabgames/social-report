"""TikTok: Login Kit (Desktop, PKCE) + user/info + video/list. Sandbox app, target user = Beaker Lab.

Keys: Private Keys/tiktok-app.json {"client_key": "...", "client_secret": "..."}
Token: Private Keys/tiktok-token.json (refresh token lasts ~1 year; first run opens a TikTok login).
"""
import base64
import hashlib
import http.server
import json
import os
import secrets
import time
import urllib.parse
import webbrowser

import pandas as pd
import requests

API = "https://open.tiktokapis.com/v2/"
REDIRECT = "http://localhost:8765/callback"
SCOPES = "user.info.basic,user.info.profile,user.info.stats,video.list"
USER_FIELDS = ("open_id,union_id,username,display_name,avatar_url,bio_description,profile_deep_link,"
               "profile_web_link,is_verified,follower_count,following_count,likes_count,video_count")
VIDEO_FIELDS = ("id,title,video_description,create_time,duration,cover_image_url,share_url,embed_link,"
                "view_count,like_count,comment_count,share_count")


def _login(app):
    verifier = secrets.token_urlsafe(64)[:64]
    # TikTok's desktop flow documents a hex SHA-256 challenge; fall back to base64url if refused
    challenge = hashlib.sha256(verifier.encode()).hexdigest()
    state = secrets.token_urlsafe(16)
    url = "https://www.tiktok.com/v2/auth/authorize/?" + urllib.parse.urlencode({
        "client_key": app["client_key"], "scope": SCOPES, "response_type": "code",
        "redirect_uri": REDIRECT, "state": state, "code_challenge": challenge, "code_challenge_method": "S256"})
    got = {}

    class H(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            got.update({k: v[0] for k, v in q.items()})
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(b"<h2>TikTok connected. You can close this tab.</h2>" if "code" in got
                             else b"<h2>TikTok login failed. Check the terminal.</h2>")

        def log_message(self, *a):
            pass

    srv = http.server.HTTPServer(("localhost", 8765), H)
    print("Opening TikTok login in your browser...")
    webbrowser.open(url)
    while "code" not in got and "error" not in got:
        srv.handle_request()
    srv.server_close()
    if got.get("state") != state or "code" not in got:
        raise RuntimeError(f"TikTok login failed: {got.get('error')} {got.get('error_description', '')}")
    return _token(app, grant_type="authorization_code", code=got["code"], redirect_uri=REDIRECT,
                  code_verifier=verifier)


def _token(app, **data):
    r = requests.post(API + "oauth/token/", data={"client_key": app["client_key"],
                                                  "client_secret": app["client_secret"], **data}, timeout=60).json()
    if "access_token" not in r:
        raise RuntimeError(f"TikTok token error: {r.get('error')} {r.get('error_description', '')}")
    r["obtained_at"] = int(time.time())
    return r


def _access_token(keys_dir):
    app = json.load(open(os.path.join(keys_dir, "tiktok-app.json")))
    path = os.path.join(keys_dir, "tiktok-token.json")
    tok = json.load(open(path)) if os.path.exists(path) else None
    if tok and time.time() > tok["obtained_at"] + tok["expires_in"] - 300:
        try:
            tok = _token(app, grant_type="refresh_token", refresh_token=tok["refresh_token"])
        except RuntimeError:
            tok = None
    if not tok:
        if os.environ.get("CI"):   # GitHub Actions: no browser for a login
            raise RuntimeError("TikTok login needed: run the report once on the Mac")
        tok = _login(app)
    with open(path, "w") as f:
        json.dump(tok, f)
    os.chmod(path, 0o600)
    return tok["access_token"]


def _call(method, path, token, **kw):
    r = requests.request(method, API + path, headers={"Authorization": "Bearer " + token}, timeout=60, **kw).json()
    err = r.get("error", {})
    if err.get("code") not in (None, "ok"):
        raise RuntimeError(f"TikTok {path}: {err.get('code')} {err.get('message', '')}")
    return r["data"]


def fetch(keys_dir, today):
    token = _access_token(keys_dir)
    snap = today.isoformat()
    try:
        u = _call("GET", "user/info/", token, params={"fields": USER_FIELDS})["user"]
    except RuntimeError:   # Oct 29, 2026: TikTok's user/info fails with internal_error for the full field list; the counts alone still work
        u = _call("GET", "user/info/", token, params={"fields": "open_id,display_name,follower_count,following_count,likes_count,video_count"})["user"]

    vids, cursor = [], None
    while True:
        body = {"max_count": 20, **({"cursor": cursor} if cursor else {})}
        d = _call("POST", "video/list/", token, params={"fields": VIDEO_FIELDS}, json=body)
        vids += d.get("videos", [])
        if not d.get("has_more"):
            break
        cursor = d.get("cursor")

    rows = [{
        "snapshot_date": snap, "video_id": str(v["id"]),
        "created": pd.Timestamp(v["create_time"], unit="s", tz="UTC").tz_convert("America/New_York").strftime("%Y-%m-%d %H:%M"),
        "caption": (v.get("video_description") or v.get("title") or "").split("\n")[0][:120],
        "length_s": v.get("duration"), "views": v.get("view_count"), "likes": v.get("like_count"),
        "comments": v.get("comment_count"), "shares": v.get("share_count"), "url": (v.get("share_url") or "").split("?")[0],
    } for v in vids]

    account = pd.DataFrame([{"snapshot_date": snap, "followers": u.get("follower_count"),
                             "following": u.get("following_count"), "likes": u.get("likes_count"),
                             "videos": u.get("video_count")}])
    profile = pd.DataFrame([{"snapshot_date": snap, "platform": "TikTok", "handle": u.get("username"),
                             "name": u.get("display_name"), "bio": u.get("bio_description"),
                             "website": u.get("profile_web_link"), "profile_url": u.get("profile_deep_link"),
                             "picture_url": u.get("avatar_url"), "verified": u.get("is_verified")}])
    return {
        "TikTok Videos": (pd.DataFrame(rows), ["snapshot_date", "video_id"]),
        "TikTok Account": (account, ["snapshot_date"]),
        "Profiles": (profile, ["snapshot_date", "platform"]),
    }
