#!/usr/bin/env python3
"""Merge raw Grok Bot X tool outputs into cache/<date>/x_metrics.json / x_search.json.
  ingest_x.py metrics <date> <raw.json>...         (get_posts_by_ids results)
  ingest_x.py search  <date> "<query>" <raw.json>  (search_posts_all result)
Raw files may contain wrapper text; the first JSON object is used."""
import sys, json, os, re
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

def raw(f):
    s = open(f).read(); return json.JSONDecoder().raw_decode(s[s.index("{"):])[0]

def m(pm):
    return {"likes": pm.get("like_count", 0), "reposts": pm.get("repost_count", pm.get("retweet_count", 0)),
            "replies": pm.get("reply_count", 0), "quotes": pm.get("quote_count", 0), "views": pm.get("impression_count", 0)}

kind, date = sys.argv[1], sys.argv[2]
d = os.path.join(ROOT, "cache", date); os.makedirs(d, exist_ok=True)
if kind == "metrics":
    f = os.path.join(d, "x_metrics.json"); out = json.load(open(f)) if os.path.exists(f) else {}
    for r in sys.argv[3:]:
        for p in raw(r).get("data", []):
            e = m(p.get("public_metrics", {}))
            e["links"] = [u.get("unwound_url") or u.get("expanded_url") or u.get("url")
                          for u in (p.get("entities") or {}).get("urls", [])]
            e["ent"] = True; out[p["id"]] = e
    json.dump(out, open(f, "w")); print(f"x_metrics: {len(out)} posts")
else:
    q = sys.argv[3]; f = os.path.join(d, "x_search.json"); out = json.load(open(f)) if os.path.exists(f) else {}
    posts = []
    for p in raw(sys.argv[4]).get("data", []):
        t = re.sub(r"\s*https://t\.co/\S+", "", p.get("text", "")).strip().split("\n")[0]
        posts.append({"title": t, "url": p["url"], "created_at": p.get("created_at"), "metrics": m(p.get("public_metrics", {}))})
    out[q] = posts; json.dump(out, open(f, "w")); print(f"x_search[{q[:40]}]: {len(posts)} posts")
