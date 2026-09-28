# Build plan: engine upgrade, property page, Mia + Claude Code agents

Three workstreams run in parallel in this one working tree. Each owns its files;
touch another stream's files only where this plan says so, and re-read a file
right before editing it (another stream may have changed it).

Deploy target: Debian 13 VPS, code in /opt/prospecting, DATA_DIR=/var/lib/prospecting,
systemd unit `prospecting` (gunicorn, 1 worker, 8 threads, 127.0.0.1:5051) running as
the non-root user `prospect`, Caddy HTTPS at https://209-159-148-182.sslip.io.
Claude Code is installed for `prospect` at /var/lib/prospecting/.local/bin/claude.
Google Chrome runs under Xvfb (display :99) with remote debugging on 127.0.0.1:9222 and a
persistent profile, so a session logged into LOOM / Virtual Agent survives. People
watch/drive it through noVNC at /browser/ (behind the dashboard login).

## Stream A — engine: filters, server-side querying, crawl cadence
Owns: webapp.py prospects section (PROSPECT_QUERY, _build_prospects, /api/prospects,
/api/prospect/*), the auto-crawl scheduler section, config.py crawl settings,
ui/src/lib/filters.svelte.js, ui/src/lib/components/FilterBar.svelte,
ui/src/routes/prospects/+page.svelte, ui/src/lib/state.svelte.js, ProspectList/ProspectCard
(except their click target — see stream B).

## Stream B — property page
Owns: new route ui/src/routes/property/[key]/ (full page for one prospect), new
components under ui/src/lib/components/property/, Drawer.svelte (retire or slim),
the click target in ProspectCard/ProspectList (navigate to /property/<listing_key>),
webapp.py route that serves the prerendered/fallback page for /property/*.
Calls stream C's API for "Get deed info" (contract below).

## Stream C — agents (Mia port) + reports
Owns: new agents.py (Flask blueprint), new agent_tools/ dir (CLI + CLAUDE.md the
agents read), new routes ui/src/routes/mia/ and ui/src/routes/reports/, new
components under ui/src/lib/components/mia/, dock entries for Mia + Reports,
registering the blueprint in webapp.py (one import + register line).

### Contract (C implements, B and A may call)
All under the normal dashboard auth; mutating calls need the `leads` privilege.
- `POST /api/agent/tasks` body `{kind: "deed"|"prospect"|"report"|"custom", group_id?, listing_key?, prompt?}` → 201 task
- `GET /api/agent/tasks?group_id=&limit=` → `{tasks: [task]}`
- `GET /api/agent/tasks/<id>` → task incl. `events` (recent progress lines)
- `POST /api/agent/tasks/<id>/cancel`
- task = `{id, kind, title, status: queued|running|done|failed|cancelled, group_id, listing_key, created_by, created_at, started_at, finished_at, summary, report_id, result}`
  For kind `deed`, `result` = `{owner_name, owner_type, id_number?, phone, email, deed_number, purchase_price, purchase_date, bond_holder, source}` (any may be null).
- `GET /api/reports` → `{reports: [{id, title, kind, group_id, created_by, created_at}]}`; `GET /api/reports/<id>` → `{..., markdown}`
- Mia chat: `GET /api/mia/thread?after=<msg id>`, `POST /api/mia/message {text}` → messages `{id, at, from: <username>|"mia"|"system", text, task_id?, report_id?}`
