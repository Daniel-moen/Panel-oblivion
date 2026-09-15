# AI caller agent (`caller.py`, `/caller`)

The step between *contact found* and *mandate won*: once a property in the
panel has an owner phone number, an AI voice agent ("Mia") can phone the
owner, disclose that it's an AI calling for Duane at Oblivion, reference the
property already being on the market, pitch the film-marketing angle, and try
to book a **meeting or callback for the human agent**. It never claims to
sign mandates, quote commission, or invent buyers — its entire job is
getting Duane in the door.

Every finished call lands in the panel as an `interactions` row (channel
`call`, actor `ai-caller`), so stages advance exactly as if a person had made
the call: `meeting_set` → stage **meeting** + a task at the agreed time,
`callback_requested` → follow-up task, `not_interested` / `do_not_call` →
terminal, number suppressed.

## Where the intelligence lives

Everything that matters is in this repo: the persona prompt
(`caller.system_prompt`), the per-property briefing (`build_briefing` — price,
days on market, price cuts, agency count, the scorer's `pitch_angle`, prior
contact history), the outcome schema, calling policy, and logging. Telephony
(PSTN + realtime STT/TTS + barge-in) is rented as a dumb pipe, the same way
`httpclient.py` rents the network. The default pipe is **ElevenLabs Agents**
(their voices are the best available, ASR and turn-taking are built in, and
the brain is Claude); `CALLER_PROVIDER=vapi` switches to the Vapi adapter.
Either way this is *infrastructure*, not a proptech data provider — no owner
data ever leaves beyond the number being dialled and the briefing spoken on
the call.

One persistent ElevenLabs agent is provisioned automatically over their API
on the first dial (its id is kept in `panel_meta`); every call then overrides
the agent's prompt and opening line with the live per-property briefing, so
the script in `caller.py` is always what gets spoken. After changing voice,
model, or the outcome schema, push the new base config with
`POST /api/caller/sync-agent`.

## Try it for free first: the simulator

`/caller` has a **Simulator**: enter a group id, hit *Start sim*, and
role-play the owner in a text chat. It runs the *exact* system prompt a live
call would use, through whichever scoring backend has credentials
(`MOONSHOT_API_KEY` / `OPENAI_API_KEY` / `ANTHROPIC_API_KEY`). Tune the pitch
here before spending anything on real calls.

## Going live (ElevenLabs)

1. Create an ElevenLabs account (a paid tier — Agents minutes are billed in
   credits) → API key from the dashboard → `ELEVENLABS_API_KEY`.
2. Get a phone number into ElevenLabs (Agents → Phone numbers): either
   connect a **Twilio** number with your Twilio SID/token, or attach a **SIP
   trunk**. Copy its id → `ELEVENLABS_PHONE_NUMBER_ID`.
   **Caller ID matters:** a US `+1` number gets ignored by SA owners. For
   real use, get a South African number (021/087) from a local VoIP provider
   and bring it in as a SIP trunk.
3. Register the post-call webhook (Settings → Webhooks): URL
   `<your app URL>/api/caller/webhook`, type *post-call transcription*. Copy
   the HMAC secret it generates → `ELEVENLABS_WEBHOOK_SECRET`. Without this,
   calls happen but outcomes never land — dialling refuses until it's set.
4. Pick a voice in the Voice Library (there are South African English voices
   — search "South African") → `ELEVENLABS_VOICE_ID`
   (default `EXAVITQu4vr4xnSDxMaL`, "Sarah").
5. Set on Railway (or `.env` locally):

   | Variable | What |
   |---|---|
   | `ELEVENLABS_API_KEY` | dashboard key |
   | `ELEVENLABS_PHONE_NUMBER_ID` | the imported number's id |
   | `ELEVENLABS_WEBHOOK_SECRET` | HMAC secret from step 3 |
   | `ELEVENLABS_VOICE_ID` | voice from step 4 |
   | `CALLER_CALLBACK_NUMBER` | number spoken on voicemails |
   | `CALLER_AGENT_NAME` / `CALLER_HUMAN_NAME` / `CALLER_AGENCY_NAME` | persona (default Mia / Duane / Oblivion) |
   | `CALLER_LLM_MODEL` | Claude model id as ElevenLabs names it (default `claude-sonnet-4-5`) |
   | `ELEVENLABS_AGENT_ID` | optional — pin a hand-made agent instead of auto-provisioning |

6. Open `/caller` — the status pills confirm configuration — and hit **Call**
   on a queue row. The first dial auto-creates the agent. The queue is every
   tracked property in stage `contact_found`/`contacted` with a phone number,
   minus do-not-call numbers, exhausted attempts (`CALLER_MAX_ATTEMPTS`,
   default 3) and settled outcomes.

<details><summary>Vapi fallback</summary>

`CALLER_PROVIDER=vapi` plus `VAPI_API_KEY`, `VAPI_PHONE_NUMBER_ID`,
`CALLER_WEBHOOK_SECRET` (falls back to `DASHBOARD_PASSWORD`),
`CALLER_PUBLIC_URL` (auto-detected on Railway), and optionally
`CALLER_VOICE_PROVIDER`/`CALLER_VOICE_ID` and `CALLER_LLM_MODEL`
(default `claude-sonnet-4-20250514`). Vapi posts to the same webhook,
authenticated by `x-vapi-secret` instead of an HMAC signature.
</details>

`CALLER_AUTOPILOT=1` dials the queue automatically every 15 minutes inside
calling hours (batch of `CALLER_AUTOPILOT_BATCH`, default 5). Run a **single**
gunicorn worker with autopilot on, or every worker dials. Default is manual
per-property dialling.

## Compliance (built in, not optional)

- **CPA calling hours**, enforced at dial time in SAST: Mon–Fri 08:00–20:00,
  Sat 09:00–13:00, never Sunday. `CALLER_IGNORE_HOURS=1` only for testing.
- **AI disclosure** in the opening sentence, confirmed plainly if asked.
- **POPIA identity gate**: no property or personal details until the person
  confirms they're the owner; voicemails get name + agency + callback number
  only.
- **"Don't call me again"** goes onto the `do_not_call` suppression table
  immediately (number only — POPIA minimality) and the queue skips it
  forever. Purge the rest of the person's data via the panel / `owners.delete`.

## Debugging

- `calls` table stores status, ended reason, outcome, transcript, structured
  analysis and per-call cost (for ElevenLabs the cost column holds **credits**,
  not USD); `/api/caller/calls` and the Recent-calls table on `/caller` show
  it all. Audio stays in the ElevenLabs dashboard per conversation.
- Webhook not firing → check the webhook registration URL is reachable from
  outside and the secret matches; the route answers 401 on a bad
  `ElevenLabs-Signature` (or `x-vapi-secret` for Vapi).
- Provider refusing calls → the dial error surfaces verbatim in the Call
  button's alert (`ElevenLabs refused the call (…)`), usually a model/voice
  id not enabled on the account, or an unimported phone number.
- Changed voice/model/schema env vars but calls sound the same →
  `POST /api/caller/sync-agent` pushes the new base config to the agent.
