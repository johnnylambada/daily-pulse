# Daily Pulse — 5 AM PT routine runbook

Repo: `/workspace/daily-pulse` (GitHub `johnnylambada/daily-pulse`). Python: `.venv/bin/python`
(if missing: `python3 -m venv .venv && .venv/bin/pip install feedparser pyyaml`).
`D` = today's date in America/Los_Angeles (`date +%F`).

## Steps
1. **Fetch feeds** (fresh, scheduled run only):
   `cd /workspace/daily-pulse && git pull -q && .venv/bin/python src/pulse.py fetch --date=$D --refresh`
   Writes `cache/$D/candidates.json` and `cache/$D/x_needed.json` (`metric_ids`, `searches`).
   Manual reruns the same day: omit `--refresh` → zero new fetches.
2. **X metrics** (agent-only; scripts can't call X): read `cache/$D/x_needed.json`. For each chunk of ≤100 `metric_ids`, call
   `x.get_posts_by_ids` with `ids=<comma list>` and `post.fields=public_metrics,created_at`, `write_to_file: true`
   (pass ids inline; `$file:` isn't supported). Then:
   `.venv/bin/python src/ingest_x.py metrics $D <raw file 1> <raw file 2> ...`
   Typical: ~450 ids → 5 calls. Stay under 30 calls/min, 1000/day. If X fails or quota runs out, skip; ranking falls back to Scoble rank + recency.
3. **X searches** (only if `searches` non-empty; v1 has none): `x.search_posts_all` with `query`, `max_results=25`,
   `sort_order=relevancy`, `start_time=<24h ago UTC>`, `post.fields=public_metrics,created_at`, then
   `.venv/bin/python src/ingest_x.py search $D "<query>" <raw file>`.
4. **Build**: `.venv/bin/python src/pulse.py build --date=$D` → `runs/<RUN>.json` + `.html`, `runs/index.html`, updates `state/seen.json`.
   Print `runs/<RUN>.json` sections.
5. **Publish snapshot Page**: `WriteCanvas` (new page, title `Daily Pulse · <RUN with space, e.g. 2026-11-02 05:00>`) using the same
   source as the latest Page (`ReadCanvas` canvas `c00a1773-0b3d-426d-8bb8-285d51193045` for the template) with:
   `RUN` = stamp, `S` = sections from `runs/<RUN>.json` as `[title, [[t,u,d],...]]`,
   `NAV` = `[{label:"← prev", href:<previous run url from state/pages.json>}, {label:"latest", href:<latest url>}]`.
   Record its canvas_id/url under `runs` in `state/pages.json`.
6. **Update the previous snapshot Page**: `EditCanvas` its `NAV` to add `{label:"next →", href:<new snapshot url>}`.
7. **Update latest Page in place** (stable URL — never create a new one): `WriteCanvas` with
   `canvas_id=c00a1773-0b3d-426d-8bb8-285d51193045`, same content as the snapshot, `NAV` =
   `[{label:"this edition", href:<new snapshot url>}, {label:"← prev", href:<previous snapshot url>}]`.
8. **Commit & push**: `git add -A && git commit -m "Run <RUN>" && git push`.
9. Log in the commit message / reply: run id, item counts per topic, feed cache hits, X calls used.

## Rules
- Never create a new "latest" Page; always overwrite `c00a1773-…`.
- Don't message John unless the run failed (then one short note with what broke).
- Adjust topics/counts/sources only in `config.yaml`.
