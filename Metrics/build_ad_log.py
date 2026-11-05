"""Writes ad-log.json from Claude Handoff/social-posts-log.json + the posting kits: which ad each post is (Guy, Nov 4: cards group by ad number).
The report builds on GitHub and can't see iCloud, so run this after logging posts:  python3 build_ad_log.py --push"""
import json, os, re, subprocess, sys

HERE = os.path.dirname(os.path.abspath(__file__))
BASE = os.path.expanduser("~/Library/Mobile Documents/com~apple~CloudDocs/[Projects]/Game Development/Beaker Lab")
OUT = os.path.join(HERE, "ad-log.json")
URL_ID = {"facebook": r"(?:reel|videos)/(\d+)", "instagram": r"(?:reel|p)/([\w-]+)", "youtube": r"shorts/([\w-]+)", "tiktok": r"video/(\d+)"}


def kit_section(txt, heads):
    """First line of the caption under the first of these kit headings."""
    for head in heads:
        m = re.search(rf"^{re.escape(head)}\s*(?:\(.*\))?\s*$\n+(.+)", txt, re.M)
        if m:
            return m.group(1).strip()
    return ""


rows = []
for p in json.load(open(os.path.join(BASE, "Claude Handoff", "social-posts-log.json")))["posts"]:
    kit = os.path.join(BASE, p.get("kit") or "")
    txt = open(kit).read() if p.get("kit") and os.path.exists(kit) else ""
    ids = {}
    for site, rx in URL_ID.items():
        m = re.search(rx, (p["platforms"].get(site) or {}).get("url") or "")
        if m:
            ids[site] = m.group(1)
    rows.append({"ad": p["id"], "title": p["title"], "date": p["post_time"][:10], "ids": ids,
                 "facebook": kit_section(txt, ["FACEBOOK + INSTAGRAM", "FACEBOOK"]),
                 "instagram": kit_section(txt, ["FACEBOOK + INSTAGRAM", "INSTAGRAM"])})
with open(OUT, "w") as f:
    json.dump(rows, f, ensure_ascii=False, indent=0)
print(f"{len(rows)} ads, {sum(1 for r in rows if not r['facebook'])} without a Facebook caption")
if "--push" in sys.argv:
    subprocess.run(["git", "add", OUT], cwd=HERE, check=True)
    if subprocess.run(["git", "diff", "--cached", "--quiet"], cwd=HERE).returncode:
        subprocess.run(["git", "commit", "-qm", "Update ad-log.json"], cwd=HERE, check=True)
        subprocess.run(["git", "pull", "-q", "--rebase"], cwd=HERE, check=True)
        subprocess.run(["git", "push", "-q"], cwd=HERE, check=True)
