#!/usr/bin/env python3
"""Daily Pulse. Usage:
  pulse.py fetch [--date D] [--refresh[=feeds]] [--offline]   fetch feeds -> cache/<date>/, write x_needed.json
  pulse.py build [--date D]                                   rank + render from cache (zero network)
X metrics/searches are filled by the Grok Bot agent into cache/<date>/x_metrics.json and x_search.json.
"""
import sys, os, json, re, hashlib, time, html, math, datetime as dt
from urllib.parse import urljoin, urlsplit, urlunsplit, parse_qsl, urlencode
import urllib.request
import yaml, feedparser
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import gnews
from zoneinfo import ZoneInfo

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CFG = yaml.safe_load(open(os.path.join(ROOT, "config.yaml")))
TZ = ZoneInfo(CFG["timezone"])
TRACK = re.compile(r"^(utm_.*|fbclid|gclid|ref|ref_src|s|t|cmpid|smid|mod|ito|taid)$")

def norm_url(u):
    u = (u or "").strip()
    p = urlsplit(u)
    host = p.netloc.lower()
    for pre in ("www.", "m.", "mobile.", "old."):
        if host.startswith(pre): host = host[len(pre):]
    if host == "twitter.com": host = "x.com"
    m = re.search(r"/status(?:es)?/(\d+)", p.path)
    if host == "x.com" and m: return "x.com/status/" + m.group(1)
    q = urlencode([(k, v) for k, v in parse_qsl(p.query) if not TRACK.match(k)])
    return urlunsplit(("https", host, p.path.rstrip("/"), q, ""))

def status_id(u):
    m = re.search(r"(?:x|twitter)\.com/[^/]+/status(?:es)?/(\d+)", u or "")
    return m.group(1) if m else None

def domain(u):
    h = urlsplit(u).netloc.lower()
    return h[4:] if h.startswith("www.") else h

SKIP = re.compile(r"(^|\.)(x\.com|twitter\.com|t\.co|pic\.twitter\.com|youtube\.com|youtu\.be|instagram\.com|tiktok\.com|imgur\.com|giphy\.com|vimeo\.com|twimg\.com|bit\.ly|linktr\.ee)$")
def article_for(it, xm):
    """Primary non-X article URL for an X-sourced item (post entities, then Scoble 'also' posts)."""
    for u in [it["url"]] + it.get("also", []):
        sid = status_id(u)
        if not sid and u != it["url"] and not SKIP.search(domain(u)): return u
        for l in (xm.get(sid) or {}).get("links", []) if sid else []:
            if l and not SKIP.search(domain(l)) and not re.search(r"\.(jpe?g|png|gif|mp4)(\?|$)", l): return l
    return None
def handle(u):
    m = re.match(r"https?://(?:www\.)?(?:x|twitter)\.com/([^/]+)/status/", u); return m and m.group(1)

def h(s): return hashlib.sha1(s.encode()).hexdigest()[:16]

def args():
    a = {"date": None, "refresh": None, "offline": False}
    for x in sys.argv[2:]:
        if x.startswith("--date="): a["date"] = x[7:]
        elif x in ("--refresh", "--no-cache"): a["refresh"] = "all"
        elif x.startswith("--refresh="): a["refresh"] = x[10:]
        elif x == "--offline": a["offline"] = True
        elif x == "--new-run": a["new_run"] = True
    a["date"] = a["date"] or dt.datetime.now(TZ).strftime("%Y-%m-%d")
    return a

def cdir(date, *p):
    d = os.path.join(ROOT, "cache", date, *p); os.makedirs(d, exist_ok=True); return d

def fetch_url(url, date, refresh, offline, stats):
    f = os.path.join(cdir(date, "feeds"), h(norm_url(url)) + ".json")
    if os.path.exists(f) and refresh not in ("all", "feeds"):
        stats["hit"] += 1; return json.load(open(f))["body"]
    if offline: stats["miss"] += 1; return None
    stats["miss"] += 1
    try:
        req = urllib.request.Request(url, headers={"User-Agent": CFG["user_agent"]})
        body = urllib.request.urlopen(req, timeout=20).read().decode("utf-8", "replace")
    except Exception as e:
        print(f"  ! fetch failed {url}: {e}"); return None
    json.dump({"url": url, "fetched_at": time.time(), "body": body}, open(f, "w"))
    return body

def parse(url, body):
    items = []
    if url.endswith(".json"):
        for it in json.loads(body).get("items", []):
            items.append({"title": it["title"], "url": it["url"], "published": it.get("publishedAt"),
                          "scoble_rank": it.get("rank"), "also": it.get("also") or [], "edition": it.get("editionAt"), "source": "scoble"})
        return items
    fp = feedparser.parse(body)
    for e in fp.entries:
        t = e.get("published_parsed") or e.get("updated_parsed")
        link = urljoin(url, e.get("link", ""))
        if not t:  # e.g. City of HB: "Posted Oct. 29, 2026" in the description
            mm = re.search(r"Posted (\w+)\.? (\d+), (\d{4})", e.get("summary", ""))
            if mm:
                try: t = time.strptime(f"{mm.group(1)[:3]} {mm.group(2)} {mm.group(3)} 12", "%b %d %Y %H")
                except ValueError: t = None
        title = html.unescape(re.sub(r"\s+", " ", e.get("title", ""))).strip()
        if "news.google.com" in url and " - " in title:  # "Headline - Publisher"
            title, pub = title.rsplit(" - ", 1)
        items.append({"title": title, "url": link,
                      "published": dt.datetime(*t[:6], tzinfo=dt.timezone.utc).isoformat() if t else None,
                      "source": "reddit" if "reddit.com" in url else "rss",
                      "srcdomain": (e.get("source", {}) or {}).get("href") and domain(e.source.href)})
    return items

def ts(s):
    if not s: return None
    try: return dt.datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()
    except Exception: return None

def cmd_fetch(a):
    stats = {"hit": 0, "miss": 0}; cands = {}
    now = time.time(); win = CFG["window_hours"] * 3600
    for t in CFG["topics"]:
        lst = []
        for url in t.get("feeds", []):
            body = fetch_url(url, a["date"], a["refresh"], a["offline"], stats)
            if not body: continue
            try: its = parse(url, body)
            except Exception as e: print(f"  ! parse failed {url}: {e}"); continue
            ex = t.get("exclude_title")
            for it in its:
                if ex and re.search(ex, it["title"]): continue
                if not it["published"] and it["source"] != "scoble": continue  # undated: skip
                p = ts(it["published"]) or ts(it.get("edition"))
                if p and now - p > win and it["source"] != "scoble": continue
                if it["source"] == "scoble" and ts(it.get("edition")) and now - ts(it["edition"]) > win: continue
                lst.append(it)
        cands[t["id"]] = lst
        print(f"  {t['id']}: {len(lst)} candidates")
    meta_f = os.path.join(cdir(a["date"]), "meta.json")
    meta = json.load(open(meta_f)) if os.path.exists(meta_f) and not a["refresh"] else {}
    meta.setdefault("fetched_at", dt.datetime.now(TZ).strftime("%Y-%m-%d %H:%M"))
    json.dump(meta, open(meta_f, "w"))
    json.dump(cands, open(os.path.join(cdir(a["date"]), "candidates.json"), "w"), indent=1)
    have = load(a["date"], "x_metrics.json", {})
    want = {status_id(u) for l in cands.values() for i in l for u in [i["url"]] + i.get("also", [])[:2]}
    ids = sorted({x for x in want if x and not (have.get(x) or {}).get("ent")})
    searches = [q for t in CFG["topics"] if t.get("use_x", True) for q in t.get("x_search", [])]
    have_s = load(a["date"], "x_search.json", {})
    need = {"metric_ids": ids, "searches": [q for q in searches if q not in have_s]}
    json.dump(need, open(os.path.join(cdir(a["date"]), "x_needed.json"), "w"), indent=1)
    print(f"feeds cache: {stats['hit']} hit / {stats['miss']} miss; X needed: {len(ids)} metric ids, {len(need['searches'])} searches")

def load(date, name, default):
    f = os.path.join(ROOT, "cache", date, name)
    return json.load(open(f)) if os.path.exists(f) else default

def score(it, xm, now):
    R = CFG["ranking"]; s = 0.0
    sid = status_id(it["url"])
    m = xm.get(sid) if sid else it.get("metrics")
    if m:
        w = R["x"]
        s = sum(w.get(k, 0) * m.get(k, 0) for k in w)
    elif it["source"] == "reddit" and it.get("reddit"):
        s = R["reddit"]["score"] * it["reddit"].get("score", 0) + R["reddit"]["comments"] * it["reddit"].get("comments", 0)
    if it.get("scoble_rank"):
        s += R["scoble_rank_weight"] / it["scoble_rank"]
    age_h = max(0, (now - (ts(it.get("published")) or ts(it.get("edition")) or now)) / 3600)
    decay = 0.5 ** (age_h / R["recency_half_life_hours"])
    return (s + 1) * decay  # +1 so signal-less items still rank by recency

def cmd_build(a):
    date = a["date"]; now = time.time()
    cands = load(date, "candidates.json", None)
    if cands is None: sys.exit("no candidates; run fetch first")
    xm = load(date, "x_metrics.json", {}); xs = load(date, "x_search.json", {})
    meta = load(date, "meta.json", {})
    seen_f = os.path.join(ROOT, "state", "seen.json")
    seen = json.load(open(seen_f)) if os.path.exists(seen_f) else {}
    stamp = dt.datetime.now(TZ).strftime("%Y-%m-%d %H:%M") if a.get("new_run") else meta.get("fetched_at", dt.datetime.now(TZ).strftime("%Y-%m-%d %H:%M"))
    run_id = stamp.replace(" ", "_").replace(":", "")
    out = []; used = set()
    for t in CFG["topics"]:
        pool = list(cands.get(t["id"], []))
        for q in t.get("x_search", []):
            for p in xs.get(q, []):
                pool.append({"title": p["title"], "url": p["url"], "published": p.get("created_at"),
                             "metrics": p.get("metrics"), "source": "x"})
        pool.sort(key=lambda i: -score(i, xm, now))
        picked = []
        gcache_f = os.path.join(cdir(date), "gnews.json")
        gcache = json.load(open(gcache_f)) if os.path.exists(gcache_f) else {}
        for it in pool:
            if "news.google.com" in it["url"]:
                if it["url"] not in gcache:
                    r = gnews.resolve(it["url"])
                    if r != it["url"]: gcache[it["url"]] = r  # cache successes only
                it = {**it, "url": gcache.get(it["url"], it["url"])}
            n = norm_url(it["url"])
            if n in used or (n in seen and seen[n][:10] < date): continue  # dedupe vs earlier days only
            if not it["title"]: continue
            rec = {"t": it["title"][:160], "u": it["url"], "d": it.get("srcdomain") or domain(it["url"])}
            hd = handle(it["url"])
            if hd:
                art = article_for(it, xm)
                rec.update({"x": it["url"], "h": hd})
                if art: rec["u"] = art; rec["d"] = domain(art)
                else: rec["d"] = "x.com"
                if art and norm_url(art) in used: continue
                if art: used.add(norm_url(art))
            used.add(n); picked.append(rec)
            if len(picked) >= t["count"]: break
        json.dump(gcache, open(gcache_f, "w"))
        if picked: out.append({"id": t["id"], "title": t["title"], "items": picked})
    for s in out:
        for i in s["items"]:
            seen[norm_url(i["u"])] = run_id
            if i.get("x"): seen[norm_url(i["x"])] = run_id
    json.dump(seen, open(seen_f, "w"), indent=0, sort_keys=True)
    runs = sorted(f[:-5] for f in os.listdir(os.path.join(ROOT, "runs")) if f.endswith(".json") and f != "index.json")
    if run_id not in runs: runs.append(run_id); runs.sort()
    data = {"run": run_id, "stamp": stamp, "date": date, "sections": out}
    json.dump(data, open(os.path.join(ROOT, "runs", run_id + ".json"), "w"), indent=1)
    for r in runs:  # refresh prev/next on all snapshots
        d = json.load(open(os.path.join(ROOT, "runs", r + ".json"))); write_html(d, runs)
    write_html(data, runs, latest=True)
    json.dump([{"run": r, "html": f"runs/{r}.html"} for r in reversed(runs)], open(os.path.join(ROOT, "runs", "index.json"), "w"), indent=1)
    open(os.path.join(ROOT, "archive.html"), "w").write(page("Daily Pulse · archive",
        '<header><b>Daily Pulse</b>archive · <a href="./">latest</a></header><ol>' +
        "".join(f'<li><a href="runs/{r}.html">{r[:10]} {r[11:13]}:{r[13:]} PT</a></li>' for r in reversed(runs)) + "</ol>", "./"))
    print(f"built {run_id}: " + ", ".join(f"{s['id']}={len(s['items'])}" for s in out))

CSS = """body{font:15px/1.35 -apple-system,Verdana,sans-serif;margin:0;background:#f6f6ef;color:#000}
header{background:#ff6600;padding:6px 10px;font-size:14px}header b{margin-right:8px}header a{color:#000}
h2{font-size:13px;margin:12px 10px 2px;color:#828282;text-transform:uppercase;letter-spacing:.04em}
ol{margin:0;padding:0 10px 0 34px}li{padding:7px 0;color:#828282}li a{color:#000;text-decoration:none;display:inline}
li a:visited{color:#828282}.d{font-size:12px;color:#828282}.d a{color:#828282;text-decoration:underline}footer{font-size:12px;color:#828282;padding:14px 10px}
@media(prefers-color-scheme:dark){body{background:#1b1b1b;color:#ddd}li a{color:#ddd}header{background:#c50}}"""

def page(title, body, base="./"):
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<meta name="apple-mobile-web-app-capable" content="yes"><meta name="mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-title" content="Pulse"><meta name="apple-mobile-web-app-status-bar-style" content="default">
<meta name="theme-color" content="#ff6600"><link rel="apple-touch-icon" href="{base}apple-touch-icon.png">
<link rel="icon" href="{base}apple-touch-icon.png">
<title>{html.escape(title)}</title><style>{CSS}</style></head><body>{body}</body></html>"""

def meta(x):
    v = f' · <a href="{html.escape(x["x"])}" target="_blank" rel="noopener">{"via " if x["d"] != "x.com" else ""}@{html.escape(x["h"])}</a>' if x.get("h") else ""
    return html.escape(x["d"]) + v

def write_html(d, runs, latest=False):
    i = runs.index(d["run"]); prev = runs[i-1] if i else None; nxt = runs[i+1] if i+1 < len(runs) else None
    pre = "runs/" if latest else ""; base = "./" if latest else "../"
    nav = []
    if prev: nav.append(f'<a href="{pre}{prev}.html">← prev</a>')
    if nxt and not latest: nav.append(f'<a href="{nxt}.html">next →</a>')
    if not latest: nav.append('<a href="../">latest</a>')
    nav.append(f'<a href="{base}archive.html">archive</a>')
    b = f'<header><b>Daily Pulse</b>{html.escape(d["stamp"])} PT · ' + " · ".join(nav) + '</header>'
    for s in d["sections"]:
        b += f'<h2>{html.escape(s["title"])}</h2><ol>' + "".join(
            f'<li><a href="{html.escape(x["u"])}" target="_blank" rel="noopener">{html.escape(x["t"])}</a> <span class="d">{meta(x)}</span></li>'
            for x in s["items"]) + "</ol>"
    b += '<footer>Top, World, AI, Markets, Tech, Cyber via <a href="https://presto-ferry-g7bz.here.now/" target="_blank" rel="noopener">Scobleizer News Pulse</a>. Ranked by X engagement.</footer>'
    out = os.path.join(ROOT, "index.html") if latest else os.path.join(ROOT, "runs", d["run"] + ".html")
    open(out, "w").write(page("Daily Pulse " + d["stamp"], b, base))

if __name__ == "__main__":
    a = args()
    {"fetch": cmd_fetch, "build": cmd_build}[sys.argv[1]](a)
