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
   `x.get_posts_by_ids` with `ids=<comma list>` and `post.fields=public_metrics,created_at,entities`, `write_to_file: true`
   (pass ids inline; `$file:` isn't supported). Then:
   `.venv/bin/python src/ingest_x.py metrics $D <raw file 1> <raw file 2> ...`
   Ids include each item's post plus up to 2 Scoble `also` posts; posts already cached with entities are skipped. Typical: ~450–770 ids → 5–8 calls  Stay under 30 calls/min, 1000/day. If X fails or quota runs out, skip; ranking falls back to Scoble rank + recency.
3. **X searches** (only if `searches` non-empty; v1 has none): `x.search_posts_all` with `query`, `max_results=25`,
   `sort_order=relevancy`, `start_time=<24h ago UTC>`, `post.fields=public_metrics,created_at`, then
   `.venv/bin/python src/ingest_x.py search $D "<query>" <raw file>`.
4. **Build**: `.venv/bin/python src/pulse.py build --date=$D` → `index.html` (latest), `runs/<RUN>.json` + `.html`, `archive.html`, updates `state/seen.json`. Also resolves Google News links to publisher URLs (network, cached per date).
   Print `runs/<RUN>.json` sections.
5. **Commit & push**: `git add -A && git commit -m "Run <RUN>" && git push`.
6. Log in the commit message / reply: run id, item counts per topic, feed cache hits, X calls used.

## Manual rerun the same day
`pulse.py build --date=$D --new-run` writes a new timestamped run and keeps the earlier one. Dedupe only applies against previous days, so the rerun can reuse today's stories.

## Rules
- Site: https://johnnylambada.github.io/daily-pulse/ redeploys automatically ~1 min after push. Optionally verify with `curl -s https://johnnylambada.github.io/daily-pulse/ | grep <RUN stamp>`.
- Never use Grok Bot Pages (WriteCanvas/EditCanvas) for this.
- Don't message John unless the run failed (then one short note with what broke).
- Adjust topics/counts/sources only in `config.yaml`.
