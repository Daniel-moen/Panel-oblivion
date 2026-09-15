# Management Panel — Plan

Goal: one app where the Prospecting Engine (find/score listings) sits under a Management Panel
that tracks chosen properties through a pipeline — every contact attempt logged, mandate outcomes
recorded — "the ultimate property prospecting and management tool".

## Current state (Aug 2026)
- Flask (`webapp.py`, no blueprints) + SQLite raw sqlite3 (`db.py`), SvelteKit 5 SPA (`ui/`), Basic auth, single user.
- Property entity = `property_groups.group_id`. Contacts only in `owner_details` (1 row/group, manual|loom).
- No tracked/stage/tag/task/activity model. Jobs are in-process threads (1 gunicorn worker). Virtual Agent not integrated yet.

## Data model (new, keyed on group_id TEXT; solo listings use `solo-<listing_key>`)
- tracked_property(group_id PK, stage, priority, assigned_to, tracked_at, archived_at, source)
- contacts(id, group_id, role owner|agent|attorney|other, name, phone, email, id_number, company,
  provider manual|loom|virtualagent, consent_basis, created_at)
- interactions(id, group_id, contact_id, channel call|whatsapp|sms|email|visit|letter, direction outbound|inbound,
  outcome no_answer|spoke|left_message|callback_requested|not_interested|interested|meeting_set,
  summary, occurred_at, next_follow_up_at, actor)  — logging with next_follow_up_at auto-creates a task
- mandates(id, group_id, type sole|open|dual|joint|sole_with_exclusion|none_lost, signed_at, expires_at,
  duration_days, listing_price, commission_pct, competing_agencies, lost_reason, lost_to, notes, document_path)
  — recording one sets stage=mandate_signed; task auto-created 14d before expiry; expired/lost re-enter engine
- notes(id, group_id, body, created_at, pinned)
- activities(id, group_id, kind stage_change|price_cut|delisted|relisted|cma_sent|deed_lookup|note|interaction|mandate,
  payload JSON, occurred_at, actor)
- tasks(id, group_id, title, due_at, done_at, kind follow_up|valuation|send_cma|mandate_renewal|other)
- tags, property_tags; saved_views(name, filters JSON); users(id, name)
- Stages: new → researching → contact_found → contacted → meeting → valuation_sent → mandate_signed → listed → sold | lost | parked
- Migration: owner_details → contacts(role=owner)+notes; tracker.prospected=1 → tracked_property(stage=parked, source=tracker_import)

## API (blueprint panel.py)
- GET/POST /api/tracked; GET/PATCH/DELETE /api/tracked/<gid> (GET = full dossier)
- CRUD /api/tracked/<gid>/{contacts,interactions,mandates,notes,activities,tasks}; GET /api/tasks?due=today|overdue
- POST /api/tracked/<gid>/lookup/{loom,virtualagent}
- GET /api/panel/stats (funnel, overdue follow-ups, mandates by type, conversion by suburb/portal/channel)
- GET /api/panel/events (SSE). Engine hook: lifecycle.py + price history emit activities for tracked groups.

## UI routes
/ dashboard (funnel, today's follow-ups, expiring mandates, hot untracked) · /prospects (existing list + Track button) ·
/map (tracked layer) · /pipeline kanban (cards: last-contact age, mandate badge) · /properties table ·
/properties/[id] workspace: header (address, price, tier, stage, MANDATE badge) + tabs Overview · Contacts ·
Contact Log (interactions, "Log call" quick form) · Mandate · Timeline · Notes · Tasks · Listings & prices · ERF/Valuation · CMA ·
/contacts directory · /tasks · /settings (stages, tags, auto-track rules, integration health)
Sidebar nav: Engine / Management sections; JobStrip stays global.

## Cross-cutting
Basic auth kept, users table added now. POPIA: consent_basis, hard delete per contact/property, audited.
Indices on (stage, archived_at), interactions(group_id, occurred_at), tasks(due_at, done_at). CSV export.

## Phases
1. Foundation: all tables + migration, panel.py blueprint (tracked CRUD, contacts, interactions, mandates, notes, tasks),
   Track button on prospect cards, /properties table with stage/last-contact/mandate columns
2. Property workspace: contacts, contact log, mandate panel, notes, timeline; LOOM → contacts
3. Pipeline & tasks: kanban, stage log, tasks, dashboard, engine events on timeline, mandate expiry reminders
4. Contacts directory + Virtual Agent client (credit budget, dedupe by phone/ID)
5. Polish: saved views, tags, auto-track rules, SSE, settings, reports, nav refactor, new / dashboard

## Defaults unless overridden
SQLite stays; stages fixed in code for v1; tracking explicit, auto-track opt-in.
