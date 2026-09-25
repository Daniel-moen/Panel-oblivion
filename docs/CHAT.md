# Team chat — channels, attachments, @mentions

The team chat on every page, opened from the round chat button in the header
(the strip on every route, the top-right row on Home): the team talking to each other (Agent Z is
`/api/agent`, a different thing). Polling, not sockets — the Procfile runs one
gunicorn worker with several threads, and a held-open socket per browser
would eat a thread each. Server: `chat.py` (a blueprint, registered like
`team.py`). Client: `ui/src/lib/chat.svelte.js` + `ChatWidget.svelte` +
`ui/src/lib/components/chat/`.

This file is the contract between the three: server, widget and the
Playwright harness (`tests/chat_e2e.py`).

## Tables (created by `chat.ensure_schema`, once per process, at boot)

```
chat_channels(id PK, slug UNIQUE, name, kind 'general'|'topic'|'property',
              property_gid NULL, created_by NULL, created_at, updated_at,
              archived_at NULL)
              -- UNIQUE index on property_gid WHERE kind='property'
              -- UNIQUE index on lower(name) WHERE kind != 'property' (skipped,
              --   not fatal, if existing rows already clash)
chat_messages(id PK AUTOINCREMENT, channel_id, user_id NULL, legacy_sender NULL,
              body, attachments JSON '[]', mentions JSON '[]',
              client_id NULL, rev INTEGER NOT NULL,
              created_at, edited_at NULL, deleted_at NULL)
              -- INDEX (channel_id, id); INDEX (rev);
              -- UNIQUE (user_id, client_id) WHERE client_id IS NOT NULL
chat_mentions(message_id, user_id, channel_id, PRIMARY KEY(user_id, message_id))
              -- one row per (message, mentioned user): unread-mention counts
              -- and the Mentions view without scanning JSON
              -- INDEX (user_id, channel_id, message_id): the unread-mention
              --   count is one range per live channel (message_id > last read)
              -- INDEX (message_id): delete clears a message's rows
chat_reads(user_id, channel_id, last_read_id, PRIMARY KEY(user_id, channel_id))
              -- channel_id 0 is the user's BASELINE: the newest message id
              -- when they first opened the chat. A channel with no row reads
              -- as last_read_id = baseline, so a new account does not start
              -- with the whole history unread, but a channel created later
              -- does count everything in it.
```

`rev` is a global, strictly increasing change counter: every insert, edit and
delete sets `rev = (SELECT COALESCE(MAX(rev),0)+1 FROM chat_messages)` in the
same write statement. SQLite has one writer at a time, so revs are assigned and
committed in the same order — a client holding cursor N can never miss a
change that commits later with a rev ≤ N. That is why the sync cursor is `rev`
and not `id` (an edit or delete keeps its id but must still reach every client).

Migration (idempotent, at boot, under `BEGIN IMMEDIATE`): create the tables,
seed `#general` (slug `general`, kind `general`), and copy `team_chat` into
`#general` with `user_id` NULL, `legacy_sender = sender`. The copy is recorded
by a marker in `app_state`: `chat.legacy_migrated_upto` = the highest
`team_chat` id copied.

- **First time** (no marker) and `chat_messages` empty: every row is copied
  **keeping its id**, `rev = id` (a cached old client's `?after=<id>` lines up).
- **First time** but `chat_messages` already has rows (a build from before the
  marker existed): only `team_chat` rows not already present as the same
  legacy row (same id, sender, created_at) are copied, with fresh ids.
- **Later boots**: `team_chat` rows with id > marker — they can only come from
  an old container still serving an old client during a deploy overlap — are
  copied with **fresh ids** and `rev = MAX(rev)+1` each, so every syncing
  client picks them up; then the marker advances, in the same transaction.

`team_chat` itself is left in place, untouched.

## Endpoints (JSON; all behind the session gate; the actor is `team._actor()`)

Message object (everything the client renders):

```
{id, rev, channel_id,
 user: {id, username, display_name, initials} | null,   -- null on legacy rows
 sender,            -- display name, or legacy_sender on old rows
 body,              -- '' when deleted
 attachments: [...],-- enriched snapshots, see below ([] when deleted)
 mentions: [user ids], mentions_me: bool,
 created_at, edited_at, deleted: bool, mine: bool, client_id}
```

Attachments are validated and **enriched at post time** and stored as that
snapshot, so reads never join the listings tables:

```
{type:'property', gid, label, suburb, price_zar, tier, photo_url}
{type:'media', id, name, kind:'photo'|'video'|..., thumb, caption}   -- thumb is a
                                          -- Zerko path; the client prefixes /zerko
{type:'link', url, title, domain}
```

| Method | Path | Notes |
|---|---|---|
| GET | `/api/chat/channels` | `{channels:[{id, slug, name, kind, property_gid, property:{label,suburb,photo_url,price_zar,tier}\|null, archived_at, last_read_id, unread, mentions, last:{id, sender, preview, at}\|null}], me:{id, username, display_name, is_admin}, cursor}` — order: general, topics by name, properties by last activity. `?archived=1` adds archived ones (admin). |
| POST | `/api/chat/channels` | `{name}` → topic (admin/owner only, else 403), 201. `{property_gid}` → property channel, anyone; 201 new / 200 existing (idempotent per gid); unknown gid 400. Name clash 409. |
| PATCH | `/api/chat/channels/<id>` | `{name?, archived?: bool}` admin only; `#general` cannot be archived (400). |
| GET | `/api/chat/channels/<id>/messages?before=&after=&limit=` | ascending; default limit 50, max 200; neither → the tail. `{messages, has_more}` (`has_more` = older exist, for `before`/tail; for `after` alone it means newer ones exist past this page). Deleted messages are included (as `deleted: true`). |
| POST | `/api/chat/channels/<id>/messages` | `{body, attachments, mentions, client_id?}` → 201 `{message}`; same `client_id` from the same user again → 200 with the original (safe retry — looked up before the archived check, so a retry after an archive still answers); the same `client_id` in a different channel → 409 `client_id_reused`. Archived channel → 409. |
| PATCH | `/api/chat/messages/<id>` | `{body}` own message within 15 min, admins any time. 403 / 409 (`edit_window`, `deleted`, `archived`). |
| DELETE | `/api/chat/messages/<id>` | soft delete; own or admin. Already deleted → 409 `deleted`. Archived channel → 409 `archived`. |
| POST | `/api/chat/channels/<id>/read` | `{last_read_id}` — only ever advances. → `{last_read_id, unread, mentions}` (`mentions` = caller's total unread mentions). |
| GET | `/api/chat/sync?since=<rev>` | the ONLY polled call. `{cursor, messages:[changed since, all live channels, ascending rev, ≤200], more, unread:{channel_id:n}, mentions, channels_stamp}`. No `since` → no messages, just the current cursor. The client refetches `/channels` when `channels_stamp` changes or a message arrives for a channel it does not know. |
| GET | `/api/chat/mentions?limit=` | the caller's recent mentions, newest first, each message with `channel:{id,name,slug,kind}`. |
| GET | `/api/chat/people` | `{people:[{id, username, display_name, initials, online, is_me}]}` active users. |
| GET/POST | `/api/chat` | compatibility shim onto `#general` for a cached old client: `{messages:[{id,sender,body,at}], latest}`; POST ignores the typed sender and posts as the signed-in user. |

Validation on post (400 `{error, message}`, the message naming the bad item):
body sanitised like the old `_chat_body` (C0 controls except tab/newline and
DEL stripped, CRLF→LF, trimmed) plus invisible characters (below), ≤ 2000
chars (over → 400, not truncated); empty body allowed only with ≥ 1
attachment; ≤ 6 attachments; property gid must exist in `property_groups`;
media needs the sender's `media` privilege (else 403 `media_forbidden`, before
any library lookup, so it says nothing about which ids exist) and the id must
exist in the Zerko library; links as below, ≤ 2048 chars, title ≤ 200;
`mentions` ≤ 20 active user ids. The body is also scanned for `@username` and
`@Display Name` (case-insensitive, longest name first, must end at a non-word
char) and those users are added. Explicit `mentions` ids from a non-admin are
kept only when that user's `@username` or `@Display Name` token is in the body
(the @ picker always inserts one) — no silent pings; an admin's list is taken
as sent. `@everyone` / `@here` mention every active user — only when the
sender is an admin; from anyone else they are plain text. You are never
recorded as mentioning yourself.

Links: `http`/`https` with a hostname; refused if the URL contains a backslash
(browsers read `\` as `/`: `http://evil.com\@good.com/` would show good.com and
open evil.com), whitespace, any control character or any non-ASCII character
(the message asks for the encoded form — percent-encoding / punycode, as the
address bar copies it), a `user:password@` part, or a bad port. `domain` is
the lower-cased hostname without a leading `www.`.

Invisible characters: bidi controls (U+202A–202E, U+2066–2069, U+200E/200F,
U+061C), zero-width characters (U+200B, U+200C, U+2060, U+FEFF), C1 controls
(U+0080–009F) are stripped from bodies, channel names, link titles and media
captions/names. U+2028/2029 become a newline in bodies, a space in one-line
fields. ZWJ (U+200D) is kept in bodies (emoji sequences need it) and stripped
from one-line fields; a body of only ZWJ/whitespace is empty.

Admin, everywhere in chat, means the account holds the `admin` privilege —
the rule `team._actor` applies to the caller, and `chat.is_admin_account`
applies to stored authors (edit re-scans). Owner/admin roles always hold it;
auth refuses to let a `member` carry it (invites and `PATCH /api/users`).

### Server details the table leaves open (chat.py)

- Response bodies: `POST /api/chat/channels` and `PATCH /api/chat/channels/<id>`
  → `{channel:{id, slug, name, kind, property_gid, property, archived_at}}`.
  `PATCH` and `DELETE /api/chat/messages/<id>` → `{message}` (the updated
  object; a delete returns it with `deleted: true`).
- Errors are `{error, message}` with `error` one of `bad_request`,
  `bad_attachment`, `bad_mention`, `media_unavailable`, `body_too_long`,
  `empty_message`, `archived` (409), `edit_window` (409), `deleted` (409, edit
  or delete of a deleted message), `name_taken` (409), `not_found` (404),
  `forbidden` (403), `media_forbidden` (403), `client_id_reused` (409).
  Any path id or `?before/?after/?since/last_read_id` outside 0..2^63-1: a
  path id → 404, a parameter → 400 (never a 500). Admin-only routes answer auth's `{error:'forbidden',
  need:'admin'}`. Unauthenticated → 401 `{error:'auth_required'}`.
- Media: looked up read-only in Zerko's own catalogue
  (`DATA_DIR/media-data/zerko.db`, table `videos`; a trashed item counts as
  missing) through `chat.media_lookup(ids)`. No catalogue → 400 "media library
  unavailable". Zerko has no per-item caption, so `caption` is whatever the
  client sent with the attachment (one line, ≤ 200), else null.
- Link `title` is optional (null when not given); over 200 chars is a 400.
- Edit and delete take the write lock first and re-check everything
  (author/admin, deleted, archived channel, edit window) on the row as read
  under it; the `UPDATE` is `WHERE id=? AND deleted_at IS NULL` and rolls back
  to 409 `deleted` if it matched nothing. A delete racing an edit always wins:
  the edit cannot resurrect the text. Messages in an archived channel cannot
  be edited or deleted (409 `archived`) — unarchive first.
- Delete is soft: the row, id, author and time stay (so the delete reaches
  every client via sync), but body, attachments and mentions are cleared in
  storage too, and its `chat_mentions` rows go.
- Edit re-scans the new body for @mentions and ADDS them; earlier mentions are
  kept. Rows migrated from `team_chat` belong to nobody: only an admin may
  edit or delete them.
- `POST .../read` clamps `last_read_id` to the channel's newest id (a client
  cannot mark the future read) and never below the baseline.
- `sync.unread` has a key (the channel id as a string, as JSON requires) for
  every live channel, zeros included. `channels_stamp` is an opaque string
  (a counter in `app_state`, bumped on every channel create/rename/archive).
- The baseline row is written the first time the user calls `/channels`,
  `/sync` or `/read`: one `INSERT OR IGNORE`, committed at once.
- Channel names: must be a string (else 400); topic ≤ 40 chars (a leading `#`
  is dropped), unique case-insensitively (Unicode case-fold) among `general` +
  topics, archived included, checked under the write lock; the UNIQUE
  `lower(name)` index is the backstop, and its IntegrityError is a 409
  `name_taken`. The slug is derived from the name and never changes on
  rename; when it is already taken by a different name (all non-Latin names
  slug to `channel`) it gets `-2`, `-3`… Property channels are named after the
  property label (names may repeat), slug `p-<gid>`. An archived channel stays
  readable through `/messages`; posting to it is 409.
- **Discuss reopens an archived property channel, for anyone** (intended —
  the lead's call): `POST /api/chat/channels {property_gid}` on a property
  whose channel an admin archived unarchives it and answers 200 with it. A
  property being talked about again is live again; topic channels have no
  such path (only an admin unarchives them).

## Client polling

Only `/api/chat/sync`: every 4 s while the sheet is open and the tab visible,
30 s while closed, stopped while the tab is hidden (one catch-up on return).
One timer, self-scheduling, never overlapping requests.

## Selectors (data-testid) the Playwright harness relies on

```
chat-launcher            the header chat button       chat-badge  (data-kind="mention"|"plain")
chat-sheet               the open sheet               chat-close
chat-channel             a channel row, data-slug, data-id; inside it chat-channel-unread
chat-new-channel         "+" (admins)                 chat-mentions-tab
chat-thread              the scroller                 chat-unread-divider
chat-msg                 a message, data-id, data-mine="true|false"
chat-msg-body            its text                     chat-mention (a highlighted @, data-me="true|false")
chat-att-property / chat-att-media / chat-att-link    rendered attachments
chat-msg-actions         the ⋯ button on a message   chat-msg-edit / chat-msg-delete
chat-edit-input / chat-edit-save
chat-input               the composer textarea        chat-send
chat-attach              "+" in the composer          chat-attach-opt-property / -media / -link
chat-link-url / chat-link-title / chat-link-add
chat-draft-chip          an attachment waiting to send (with a remove button inside)
chat-people              the @ picker                 chat-person (data-username)
chat-failed / chat-retry a message that failed to send
discuss-property         "Discuss" on the property drawer and property page
```
