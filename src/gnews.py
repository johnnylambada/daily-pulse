"""Resolve news.google.com/rss/articles/... redirect URLs to the publisher URL (best effort)."""
import re, json, urllib.request, urllib.parse
UA = {"User-Agent": "Mozilla/5.0"}

def resolve(url, timeout=15):
    m = re.search(r"news\.google\.com/(?:rss/)?articles/([^?]+)", url)
    if not m: return url
    gid = m.group(1)
    try:
        page = urllib.request.urlopen(urllib.request.Request(f"https://news.google.com/articles/{gid}", headers=UA), timeout=timeout).read().decode()
        sg = re.search(r'data-n-a-sg="([^"]+)"', page).group(1); ts = re.search(r'data-n-a-ts="([^"]+)"', page).group(1)
        inner = ["garturlreq", [["X", "X", ["X", "X"], None, None, 1, 1, "US:en", None, 1, None, None, None, None, None, 0, 1], "X", "X", 1, [1, 1, 1], 1, 1, None, 0, 0, None, 0], gid, int(ts), sg]
        body = "f.req=" + urllib.parse.quote(json.dumps([[["Fbv4je", json.dumps(inner), None, "generic"]]]))
        r = urllib.request.urlopen(urllib.request.Request("https://news.google.com/_/DotsSplashUi/data/batchexecute", data=body.encode(),
            headers={**UA, "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8"}), timeout=timeout).read().decode()
        arr = json.loads(r.split("\n\n", 1)[1])
        return json.loads(arr[0][2])[1]
    except Exception:
        return url
