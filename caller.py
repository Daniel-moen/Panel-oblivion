"""AI caller agent: phones owners with captured contact details and pitches
for a meeting — the step between `contact_found` and a mandate.

The engine finds the property, erf.py pins the parcel, a human captures the
owner's number (owners.py / panel contacts). This module works that output:
it dials the owner, an AI voice agent introduces itself, references their
property being on the market, pitches Oblivion's film-led marketing, and
tries to book a meeting or callback for the human agent. Every call lands in
the panel as an `interactions` row (channel 'call', actor 'ai-caller'), so
stages advance exactly as if a person had made the call.

The agent's job is deliberately capped at BOOKING — it never claims to sign
a mandate, quote commission, or invent buyers. Mandates are won by the human
in the meeting the agent secures.

Architecture
------------
Everything of value lives here: the persona prompt, the per-property
briefing, the outcome schema, call policy, and logging. Actual telephony
(PSTN, realtime STT/TTS, barge-in) is rented as a dumb pipe — the same way
httpclient.py rents the network. Two interchangeable providers
(CALLER_PROVIDER):

  * elevenlabs (default) — ElevenLabs Agents. One persistent agent is
    provisioned via API (id kept in panel_meta) with per-call prompt/first-
    message overrides, so the full briefing still comes from this file on
    every dial. Their post-call webhook returns transcript + the
    data-collection fields mapped from OUTCOME_SCHEMA.
  * vapi — Vapi.ai, transient assistant per call.

The LLM behind the voice is Claude on either platform.

A zero-cost SIMULATOR is built in: /caller has a chat box that runs the
exact same system prompt through the scoring backends (Kimi/OpenAI/Claude,
whichever key is present), with you role-playing the owner. Tune the pitch
there before pointing it at a real phone number.

Compliance (this is not decorative — see owners.py's POPIA note)
----------------------------------------------------------------
* CPA direct-marketing hours are enforced at dial time (SAST): Mon–Fri
  08:00–20:00, Sat 09:00–13:00, never on Sunday. Override only for testing
  with CALLER_IGNORE_HOURS=1.
* The agent DISCLOSES it is an AI assistant in its opening sentence, and
  confirms it plainly if asked. No pretending to be human, ever.
* Identity first: the property is not mentioned until the agent has
  confirmed it is speaking with the owner (POPIA — no personal/property
  details to third parties or voicemail).
* "Don't call me again" is honoured immediately: the number goes onto the
  `do_not_call` table (a minimal suppression list — number, reason, date)
  and the queue skips it forever. Pair with owners.delete() / panel contact
  deletion to purge the rest of their data.
* CALLER_MAX_ATTEMPTS (default 3) caps dial attempts per property; any
  terminal outcome (not_interested, do_not_call, meeting_set) stops
  redialling regardless of attempt count.

Setup (ElevenLabs, the default — full walk-through in docs/CALLER.md)
-----
    ELEVENLABS_API_KEY         from elevenlabs.io
    ELEVENLABS_PHONE_NUMBER_ID a number imported into ElevenLabs (Twilio or
                               SIP trunk). NOTE: a US +1 caller ID gets
                               ignored in SA — BYO a ZA number via a local
                               SIP trunk for real use.
    ELEVENLABS_WEBHOOK_SECRET  HMAC secret from the post-call webhook you
                               register in their dashboard, pointing at
                               <CALLER_PUBLIC_URL>/api/caller/webhook
    ELEVENLABS_VOICE_ID        voice from their Voice Library
                               (default EXAVITQu4vr4xnSDxMaL, "Sarah")
    ELEVENLABS_AGENT_ID        optional: pin an existing agent; otherwise one
                               is created automatically on first dial

    CALLER_PROVIDER            elevenlabs (default) | vapi
    CALLER_PUBLIC_URL          where webhooks reach this app (falls back to
                               https://$RAILWAY_PUBLIC_DOMAIN)
    CALLER_AGENT_NAME          voice persona name          (default "Mia")
    CALLER_HUMAN_NAME          the human agent it books for (default "Duane")
    CALLER_AGENCY_NAME         agency it represents         (default "Oblivion")
    CALLER_CALLBACK_NUMBER     number left on voicemails
    CALLER_LLM_MODEL           Claude model id as the platform names it
                               (default claude-sonnet-4-5 on ElevenLabs)
    CALLER_MAX_ATTEMPTS        dial attempts per property (default 3)
    CALLER_AUTOPILOT=1         auto-dial the queue every 15 min inside calling
                               hours (run single-worker!); default is manual
                               per-property dialling from /caller.

    Vapi fallback: VAPI_API_KEY, VAPI_PHONE_NUMBER_ID, CALLER_WEBHOOK_SECRET,
    CALLER_VOICE_PROVIDER/CALLER_VOICE_ID.
"""

from __future__ import annotations

import hmac
import json
import os
import re
import sqlite3
import threading
import time
from datetime import datetime, timedelta, timezone

import requests
from flask import Blueprint, Response, jsonify, request

import config
import db
import panel

bp = Blueprint("caller", __name__)

# ------------------------------------------------------------------ config

AGENT_NAME = os.environ.get("CALLER_AGENT_NAME", "Mia")
HUMAN_NAME = os.environ.get("CALLER_HUMAN_NAME", "Duane")
AGENCY_NAME = os.environ.get("CALLER_AGENCY_NAME", "Oblivion")
CALLBACK_NUMBER = os.environ.get("CALLER_CALLBACK_NUMBER", "")

CALL_PROVIDER = os.environ.get("CALLER_PROVIDER", "elevenlabs")  # elevenlabs | vapi

ELEVEN_BASE = "https://api.elevenlabs.io"
ELEVEN_API_KEY = os.environ.get("ELEVENLABS_API_KEY", "")
ELEVEN_PHONE_NUMBER_ID = os.environ.get("ELEVENLABS_PHONE_NUMBER_ID", "")
ELEVEN_AGENT_ID = os.environ.get("ELEVENLABS_AGENT_ID", "")
ELEVEN_WEBHOOK_SECRET = os.environ.get("ELEVENLABS_WEBHOOK_SECRET", "")
ELEVEN_VOICE_ID = os.environ.get("ELEVENLABS_VOICE_ID", "EXAVITQu4vr4xnSDxMaL")
ELEVEN_TTS_MODEL = os.environ.get("ELEVENLABS_TTS_MODEL", "eleven_turbo_v2_5")

VAPI_API_KEY = os.environ.get("VAPI_API_KEY", "")
VAPI_PHONE_NUMBER_ID = os.environ.get("VAPI_PHONE_NUMBER_ID", "")
VAPI_BASE = "https://api.vapi.ai"
LLM_PROVIDER = os.environ.get("CALLER_LLM_PROVIDER", "anthropic")
# Each platform names Claude its own way; override to whatever your account's
# model list shows.
LLM_MODEL = os.environ.get("CALLER_LLM_MODEL") or (
    "claude-sonnet-4-5" if CALL_PROVIDER == "elevenlabs"
    else "claude-sonnet-4-20250514")
VOICE_PROVIDER = os.environ.get("CALLER_VOICE_PROVIDER", "vapi")
VOICE_ID = os.environ.get("CALLER_VOICE_ID", "Paige")

WEBHOOK_SECRET = (os.environ.get("CALLER_WEBHOOK_SECRET")
                  or os.environ.get("DASHBOARD_PASSWORD", ""))
PUBLIC_URL = (os.environ.get("CALLER_PUBLIC_URL")
              or (f"https://{os.environ['RAILWAY_PUBLIC_DOMAIN']}"
                  if os.environ.get("RAILWAY_PUBLIC_DOMAIN") else "")).rstrip("/")

MAX_ATTEMPTS = int(os.environ.get("CALLER_MAX_ATTEMPTS", "3"))
IGNORE_HOURS = os.environ.get("CALLER_IGNORE_HOURS") == "1"
AUTOPILOT = os.environ.get("CALLER_AUTOPILOT") == "1"
AUTOPILOT_BATCH = int(os.environ.get("CALLER_AUTOPILOT_BATCH", "5"))

SAST = timezone(timedelta(hours=2))

# ----------------------------------------------------------------- storage

DDL = """
CREATE TABLE IF NOT EXISTS calls (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    group_id         TEXT NOT NULL,
    contact_id       INTEGER,
    phone            TEXT NOT NULL,          -- E.164
    provider         TEXT NOT NULL DEFAULT 'vapi',   -- vapi | sim
    provider_call_id TEXT,
    status           TEXT NOT NULL DEFAULT 'queued', -- queued|dialing|in_progress|ended|failed
    ended_reason     TEXT,
    outcome          TEXT,                   -- caller outcome enum, see OUTCOME_SCHEMA
    summary          TEXT,
    transcript       TEXT,                   -- JSON [{role, text}] or raw string
    analysis         TEXT,                   -- JSON structured outcome
    recording_url    TEXT,
    cost_usd         REAL,
    created_at       TEXT DEFAULT (datetime('now')),
    ended_at         TEXT
);
CREATE INDEX IF NOT EXISTS idx_calls_group ON calls(group_id);
CREATE INDEX IF NOT EXISTS idx_calls_provider_id ON calls(provider_call_id);

-- Minimal suppression list. Deliberately number-only: honouring "never call
-- me again" REQUIRES remembering the number, and nothing else (POPIA
-- minimality). Everything else about the person is purged separately.
CREATE TABLE IF NOT EXISTS do_not_call (
    phone    TEXT PRIMARY KEY,
    reason   TEXT,
    added_at TEXT DEFAULT (datetime('now'))
);
"""

_schema_done = False


def ensure_schema(conn: sqlite3.Connection) -> None:
    global _schema_done
    if not _schema_done:
        conn.executescript(DDL)
        panel.ensure_schema(conn)
        _schema_done = True


def _rows(cur) -> list[dict]:
    return [dict(r) for r in cur.fetchall()]


# ------------------------------------------------------------ phone / hours

def normalize_phone(raw: str | None) -> str | None:
    """SA-centric E.164: '082 000 0000' -> '+27820000000'. None if hopeless."""
    if not raw:
        return None
    digits = re.sub(r"[^\d+]", "", raw)
    if digits.startswith("+"):
        return digits if len(digits) >= 10 else None
    if digits.startswith("00"):
        return "+" + digits[2:]
    if digits.startswith("27") and len(digits) == 11:
        return "+" + digits
    if digits.startswith("0") and len(digits) == 10:
        return "+27" + digits[1:]
    return None


def within_calling_hours(now: datetime | None = None) -> bool:
    """CPA direct-marketing windows, SAST. Public holidays are on the human:
    autopilot stays coarse-grained, the queue page shows the clock state."""
    if IGNORE_HOURS:
        return True
    now = now or datetime.now(SAST)
    wd, hhmm = now.weekday(), now.hour * 60 + now.minute
    if wd == 6:                       # Sunday
        return False
    if wd == 5:                       # Saturday
        return 9 * 60 <= hhmm < 13 * 60
    return 8 * 60 <= hhmm < 20 * 60   # weekdays


def is_dnc(conn, phone: str) -> bool:
    return conn.execute("SELECT 1 FROM do_not_call WHERE phone=?",
                        (phone,)).fetchone() is not None


# ---------------------------------------------------------------- briefing

def build_briefing(conn, gid: str) -> dict | None:
    """Everything the agent may truthfully say about this property."""
    gid = str(gid)
    summ = panel._summaries(conn).get(gid)
    if not summ:
        return None
    b = dict(summ)

    keys = [r["listing_key"] for r in conn.execute(
        "SELECT listing_key FROM property_groups WHERE CAST(group_id AS TEXT)=?",
        (gid,))] or ([gid[5:]] if gid.startswith("solo-") else [])
    if keys:
        q = ",".join("?" * len(keys))
        # listing_date is portal prose ("04 March 2026"), first_seen is ISO;
        # parse both in Python and take the earliest sighting.
        dates = []
        for r in conn.execute(f"SELECT listing_date, first_seen FROM listings "
                              f"WHERE listing_key IN ({q})", keys):
            for raw, fmt in ((r["listing_date"], "%d %B %Y"),
                             (r["first_seen"], None)):
                if not raw:
                    continue
                try:
                    dates.append(datetime.strptime(raw, fmt) if fmt
                                 else datetime.fromisoformat(raw[:10]))
                except ValueError:
                    pass
        if dates:
            b["days_on_market"] = max((datetime.now() - min(dates)).days, 0)
        cuts = conn.execute(
            f"""SELECT COUNT(*) AS n FROM (
                    SELECT price_zar, LAG(price_zar) OVER (ORDER BY observed_at) AS prev
                    FROM price_history WHERE listing_key = ?)
                WHERE prev IS NOT NULL AND price_zar < prev""",
            (b.get("listing_key"),)).fetchone()
        b["price_cuts"] = cuts["n"] if cuts else 0

    s = conn.execute("SELECT pitch_angle, reasoning, mandate_verdict FROM scores "
                     "WHERE listing_key=?", (b.get("listing_key"),)).fetchone()
    if s:
        b.update({k: s[k] for k in s.keys()})

    b["history"] = [dict(r) for r in conn.execute(
        "SELECT occurred_at, channel, outcome, summary FROM interactions "
        "WHERE group_id=? ORDER BY id DESC LIMIT 3", (gid,))]
    return b


def _fmt_price(zar) -> str:
    if not zar:
        return "an undisclosed price"
    m = zar / 1_000_000
    return f"R{m:.2f} million".replace(".00 ", " ").replace(".50 ", ".5 ")


def _greeting(now: datetime | None = None) -> str:
    h = (now or datetime.now(SAST)).hour
    return "Good morning" if h < 12 else ("Good afternoon" if h < 18 else "Good evening")


def first_message(owner_name: str | None) -> str:
    who = (owner_name or "").split()[0] if owner_name else None
    ask = f"Am I speaking with {who}?" if who else "Am I speaking with the owner of the property?"
    return (f"{_greeting()}! My name is {AGENT_NAME} — I'm the AI assistant for "
            f"{HUMAN_NAME} at {AGENCY_NAME}, the property film specialists. {ask}")


def system_prompt(b: dict, owner_name: str | None) -> str:
    address = b.get("official_address") or b.get("street_address_raw")
    suburb = b.get("suburb") or ""
    place = (f"{address}, {suburb}".rstrip(", ") if address
             else f"a property in {suburb or 'the area'}")
    facts = [f"Property: {place}",
             f"Asking price: {_fmt_price(b.get('price_zar'))}"]
    if b.get("bedrooms"):
        facts.append(f"{int(b['bedrooms'])} bed / {int(b['bathrooms'] or 0)} bath "
                     f"{b.get('property_type') or 'home'}")
    if b.get("days_on_market"):
        facts.append(f"On the market roughly {b['days_on_market']} days")
    if (b.get("agency_count") or 0) > 1:
        facts.append(f"Marketed by {b['agency_count']} agencies (open mandate — "
                     "adding us costs the owner nothing)")
    if b.get("price_cuts"):
        facts.append(f"Price reduced {b['price_cuts']} time(s) — the current "
                     "marketing isn't converting")
    if b.get("pitch_angle"):
        facts.append(f"Pitch angle from research: {b['pitch_angle']}")
    if owner_name:
        facts.append(f"Registered owner: {owner_name} (public deeds record)")
    for h in b.get("history", []):
        facts.append(f"Previous contact {h['occurred_at'][:10]} ({h['channel']}): "
                     f"{h.get('outcome') or '?'} — {h.get('summary') or ''}")

    return f"""You are {AGENT_NAME}, the AI calling assistant for {HUMAN_NAME} at {AGENCY_NAME}, a Cape Town / West Coast agency that markets luxury homes with cinematic property films. You are on a live phone call with a homeowner whose property is currently listed for sale.

WHAT YOU KNOW (say nothing beyond this — never invent buyers, offers, statistics, or promises):
{chr(10).join('- ' + f for f in facts)}

YOUR ONE GOAL, in order of preference:
1. Book a specific day/time for {HUMAN_NAME} to visit — a free, no-obligation property film consultation and market valuation.
2. Failing that, a specific day/time for {HUMAN_NAME} to phone them back.
3. Failing that, leave a warm impression and end politely. A future yes beats a pressured no.

HARD RULES:
- You are an AI and you already said so in your greeting. If asked, confirm it plainly and without apology, then carry on.
- Do NOT mention the property, its price, or the owner's name to anyone until they confirm they are the owner. If it's someone else, just ask for a good time for {HUMAN_NAME} to reach the owner. If it's voicemail, leave only: your name, {AGENCY_NAME}, and {CALLBACK_NUMBER or 'a callback request'} — no property details.
- You cannot sign mandates, discuss commission, or agree terms. That is {HUMAN_NAME}'s meeting. If pushed: "That's exactly what {HUMAN_NAME} would cover with you — can I set that up?"
- If they say they're not interested, accept it first time, thank them, end the call.
- If they ask not to be called again, apologise once, confirm their number is being removed immediately, and end the call.
- Never argue, never pressure, never call their current agent bad at their job.

THE PITCH (one idea per turn, not a monologue): their home is already on the market, so they clearly want it sold. {AGENCY_NAME} does what portal photos can't — a cinematic film of the home that reaches buyers on film and social platforms other agencies don't touch. Since the mandate is open, adding {AGENCY_NAME} costs nothing and adds a second engine to the sale. The consultation is free either way and includes an up-to-date market valuation.

OBJECTIONS:
- "I already have an agent" → "Keep them! With an open mandate we simply market alongside — more reach, same asking price, you pay only whoever actually sells it."
- "I have a sole mandate" → ask when it expires, ask if {HUMAN_NAME} may call closer to the time, thank them.
- "Price/market frustration" → empathise; the free valuation gives them a current number with no strings.
- "Is this a scam?" → they can look up {AGENCY_NAME}, and {HUMAN_NAME} will confirm everything in person; you're only offering a free consultation.

STYLE: natural spoken South African English. Short turns — one or two sentences, one question at a time. Say numbers the way people speak ("nineteen and a half million rand"). Warm, unhurried, a little wry; never salesy-breathless. This call should feel like a favour, not a pitch. Aim to be done within three minutes."""


# The end-of-call analysis Vapi's model fills in; the sim grader uses it too.
OUTCOME_SCHEMA = {
    "type": "object",
    "properties": {
        "reached": {"type": "string",
                    "enum": ["owner", "other_person", "voicemail", "nobody"]},
        "outcome": {"type": "string",
                    "enum": ["meeting_set", "callback_requested", "interested",
                             "not_interested", "do_not_call", "wrong_number",
                             "left_message", "no_answer"]},
        "meeting_at": {"type": "string",
                       "description": "ISO date/time agreed for the meeting, if any"},
        "callback_at": {"type": "string",
                        "description": "ISO date/time to call back, if agreed"},
        "summary": {"type": "string",
                    "description": "2-3 sentences: who answered, how it went, what was agreed"},
        "objections": {"type": "string"},
        "selling_situation": {"type": "string",
                              "description": "anything learned: motivation, timeline, other agencies, mandate status"},
    },
    "required": ["reached", "outcome", "summary"],
}

# caller outcome -> panel interactions.outcome (see panel.OUTCOMES)
PANEL_OUTCOME = {"meeting_set": "meeting_set", "callback_requested": "callback_requested",
                 "interested": "interested", "not_interested": "not_interested",
                 "do_not_call": "not_interested", "wrong_number": "spoke",
                 "left_message": "left_message", "no_answer": "no_answer"}

TERMINAL_OUTCOMES = ("meeting_set", "not_interested", "do_not_call", "wrong_number")


# ------------------------------------------------------------------- queue

def call_queue(conn) -> list[dict]:
    """Properties ready for the agent: tracked, right stage, phone on file,
    not suppressed, not exhausted, no terminal outcome yet."""
    ensure_schema(conn)
    cands = _rows(conn.execute("""
        SELECT tp.group_id AS gid, tp.stage, c.id AS contact_id, c.name, c.phone, c.role
        FROM tracked_property tp
        JOIN contacts c ON c.group_id = tp.group_id
        WHERE tp.archived_at IS NULL
          AND tp.stage IN ('contact_found', 'contacted')
          AND c.phone IS NOT NULL AND c.phone != ''
        ORDER BY tp.group_id, c.role != 'owner', c.id"""))
    stats = {r["group_id"]: r for r in _rows(conn.execute(
        "SELECT group_id, COUNT(*) AS attempts, MAX(created_at) AS last_call, "
        "MAX(outcome IN {}) AS terminal FROM calls WHERE provider != 'sim' "
        "GROUP BY group_id".format(str(TERMINAL_OUTCOMES))))}
    summ = panel._summaries(conn)

    out, seen = [], set()
    for c in cands:
        gid = c["gid"]
        if gid in seen:
            continue                       # first (owner-preferred) contact wins
        seen.add(gid)
        phone = normalize_phone(c["phone"])
        st = stats.get(gid) or {}
        if not phone or is_dnc(conn, phone):
            continue
        if st.get("terminal") or (st.get("attempts") or 0) >= MAX_ATTEMPTS:
            continue
        row = {"group_id": gid, "stage": c["stage"], "contact_id": c["contact_id"],
               "owner_name": c["name"], "phone": phone,
               "attempts": st.get("attempts") or 0, "last_call": st.get("last_call")}
        s = summ.get(gid) or {}
        row.update({k: s.get(k) for k in ("title", "suburb", "price_zar",
                                          "street_address_raw", "official_address",
                                          "agency_count", "tier")})
        out.append(row)
    out.sort(key=lambda r: (r["attempts"], -(r["price_zar"] or 0)))
    return out


# -------------------------------------------------------- provider adapters

def provider_ready() -> str | None:
    """None if calls can be placed, else what's missing."""
    if CALL_PROVIDER == "elevenlabs":
        # The webhook secret doesn't gate dialling, but without it no outcome
        # ever lands, so a call would be money down the drain — require it.
        need = (("ELEVENLABS_API_KEY", ELEVEN_API_KEY),
                ("ELEVENLABS_PHONE_NUMBER_ID", ELEVEN_PHONE_NUMBER_ID),
                ("ELEVENLABS_WEBHOOK_SECRET", ELEVEN_WEBHOOK_SECRET))
    else:
        need = (("VAPI_API_KEY", VAPI_API_KEY),
                ("VAPI_PHONE_NUMBER_ID", VAPI_PHONE_NUMBER_ID),
                ("CALLER_PUBLIC_URL", PUBLIC_URL),
                ("CALLER_WEBHOOK_SECRET", WEBHOOK_SECRET))
    missing = [n for n, v in need if not v]
    return ("set " + ", ".join(missing)) if missing else None


def _eleven_headers() -> dict:
    return {"xi-api-key": ELEVEN_API_KEY}


def _eleven_agent_config() -> dict:
    """Base agent: voice, LLM, and OUTCOME_SCHEMA mapped onto their post-call
    data-collection fields. The prompt/first message here are placeholders —
    every dial overrides them with the live briefing from this file."""
    data_collection = {}
    for name, spec in OUTCOME_SCHEMA["properties"].items():
        desc = spec.get("description", "")
        if "enum" in spec:
            desc = (desc + " " if desc else "") + \
                "Exactly one of: " + ", ".join(spec["enum"]) + "."
        data_collection[name] = {"type": "string", "description": desc or name}
    return {
        "name": f"{AGENT_NAME} ({AGENCY_NAME} caller)",
        "conversation_config": {
            "agent": {
                "language": "en",
                "first_message": "Hello?",
                "prompt": {"prompt": "Placeholder — overridden on every call.",
                           "llm": LLM_MODEL, "temperature": 0.6},
            },
            "tts": {"voice_id": ELEVEN_VOICE_ID, "model_id": ELEVEN_TTS_MODEL},
            "conversation": {"max_duration_seconds": 480},
        },
        "platform_settings": {
            "overrides": {"conversation_config_override": {
                "agent": {"prompt": {"prompt": True}, "first_message": True}}},
            "data_collection": data_collection,
        },
    }


def eleven_agent_id(conn, sync: bool = False) -> str:
    """The provisioned ElevenLabs agent id — created via API on first use and
    remembered in panel_meta; ELEVENLABS_AGENT_ID pins an existing one.
    sync=True pushes the current base config to an already-created agent
    (after changing voice, model, or the outcome schema)."""
    agent_id = ELEVEN_AGENT_ID
    if not agent_id:
        row = conn.execute("SELECT value FROM panel_meta "
                           "WHERE key='elevenlabs_agent_id'").fetchone()
        agent_id = row[0] if row else None
    if agent_id and not sync:
        return agent_id
    if agent_id:
        r = requests.patch(f"{ELEVEN_BASE}/v1/convai/agents/{agent_id}",
                           headers=_eleven_headers(),
                           json=_eleven_agent_config(), timeout=30)
        if r.status_code >= 300:
            raise ValueError(f"ElevenLabs agent update failed "
                             f"({r.status_code}): {r.text[:300]}")
        return agent_id
    r = requests.post(f"{ELEVEN_BASE}/v1/convai/agents/create",
                      headers=_eleven_headers(),
                      json=_eleven_agent_config(), timeout=30)
    if r.status_code >= 300:
        raise ValueError(f"ElevenLabs agent create failed "
                         f"({r.status_code}): {r.text[:300]}")
    agent_id = r.json().get("agent_id")
    conn.execute("INSERT OR REPLACE INTO panel_meta(key, value) "
                 "VALUES ('elevenlabs_agent_id', ?)", (agent_id,))
    conn.commit()
    return agent_id


def _eleven_start(conn, phone: str, sys_prompt: str, opening: str) -> str:
    """Dial via ElevenLabs Agents; returns their conversation_id."""
    agent_id = eleven_agent_id(conn)
    # The outbound endpoint depends on how the number was imported.
    info = requests.get(
        f"{ELEVEN_BASE}/v1/convai/phone-numbers/{ELEVEN_PHONE_NUMBER_ID}",
        headers=_eleven_headers(), timeout=30)
    number_provider = ((info.json().get("provider") or "")
                       if info.status_code < 300 else "")
    endpoint = ("/v1/convai/sip-trunk/outbound-call"
                if number_provider == "sip_trunk"
                else "/v1/convai/twilio/outbound-call")
    r = requests.post(f"{ELEVEN_BASE}{endpoint}", headers=_eleven_headers(),
                      json={
                          "agent_id": agent_id,
                          "agent_phone_number_id": ELEVEN_PHONE_NUMBER_ID,
                          "to_number": phone,
                          "conversation_initiation_client_data": {
                              "conversation_config_override": {"agent": {
                                  "prompt": {"prompt": sys_prompt},
                                  "first_message": opening}}},
                      }, timeout=30)
    ok = r.status_code < 300 and (r.json().get("success", True) if r.text else True)
    if not ok:
        raise ValueError(f"ElevenLabs refused the call ({r.status_code}): "
                         f"{r.text[:300]}")
    cid = r.json().get("conversation_id")
    if not cid:
        raise ValueError("ElevenLabs accepted the call but returned no "
                         f"conversation_id: {r.text[:200]}")
    return cid


def _vapi_start(phone: str, sys_prompt: str, opening: str) -> str:
    """Dial via Vapi with a transient assistant; returns their call id."""
    assistant = {
        "name": f"{AGENT_NAME} ({AGENCY_NAME})",
        "firstMessage": opening,
        "model": {"provider": LLM_PROVIDER, "model": LLM_MODEL,
                  "temperature": 0.6,
                  "messages": [{"role": "system", "content": sys_prompt}]},
        "voice": {"provider": VOICE_PROVIDER, "voiceId": VOICE_ID},
        "transcriber": {"provider": "deepgram", "model": "nova-3",
                        "language": "en"},
        "maxDurationSeconds": 480,
        "analysisPlan": {
            "summaryPlan": {"enabled": True},
            "structuredDataPlan": {"enabled": True, "schema": OUTCOME_SCHEMA},
        },
        "server": {"url": f"{PUBLIC_URL}/api/caller/webhook",
                   "secret": WEBHOOK_SECRET},
    }
    resp = requests.post(
        f"{VAPI_BASE}/call",
        headers={"Authorization": f"Bearer {VAPI_API_KEY}"},
        json={"phoneNumberId": VAPI_PHONE_NUMBER_ID,
              "customer": {"number": phone}, "assistant": assistant},
        timeout=30)
    if resp.status_code >= 300:
        raise ValueError(f"Vapi refused the call ({resp.status_code}): "
                         f"{resp.text[:300]}")
    return resp.json().get("id")


def start_call(conn, gid: str, contact_id: int | None = None) -> dict:
    """Dial one property. Returns the stored calls row, or raises ValueError
    with a human-readable reason."""
    ensure_schema(conn)
    reason = provider_ready()
    if reason:
        raise ValueError(f"caller not configured: {reason}")
    if not within_calling_hours():
        raise ValueError("outside CPA calling hours (Mon-Fri 08:00-20:00, "
                         "Sat 09:00-13:00 SAST). CALLER_IGNORE_HOURS=1 to test.")

    gid = str(gid)
    where, params = "group_id=? AND phone IS NOT NULL AND phone != ''", [gid]
    if contact_id:
        where += " AND id=?"
        params.append(contact_id)
    contact = conn.execute(
        f"SELECT * FROM contacts WHERE {where} ORDER BY role != 'owner', id",
        params).fetchone()
    if not contact:
        raise ValueError("no contact with a phone number for this property")
    phone = normalize_phone(contact["phone"])
    if not phone:
        raise ValueError(f"cannot normalise {contact['phone']!r} to E.164")
    if is_dnc(conn, phone):
        raise ValueError(f"{phone} is on the do-not-call list")
    active = conn.execute(
        "SELECT 1 FROM calls WHERE group_id=? AND status IN ('queued','dialing',"
        "'in_progress') AND created_at > datetime('now', '-30 minutes')",
        (gid,)).fetchone()
    if active:
        raise ValueError("a call for this property is already in flight")

    briefing = build_briefing(conn, gid)
    if not briefing:
        raise ValueError(f"no property data for group {gid}")

    sys_prompt = system_prompt(briefing, contact["name"])
    opening = first_message(contact["name"])
    if CALL_PROVIDER == "elevenlabs":
        call_id = _eleven_start(conn, phone, sys_prompt, opening)
    else:
        call_id = _vapi_start(phone, sys_prompt, opening)

    cur = conn.execute(
        "INSERT INTO calls (group_id, contact_id, phone, provider, "
        "provider_call_id, status) VALUES (?,?,?,?,?, 'dialing')",
        (gid, contact["id"], phone, CALL_PROVIDER, call_id))
    panel._log(conn, gid, "ai_call_started",
               {"call_id": cur.lastrowid, "phone": phone}, actor="ai-caller")
    conn.commit()
    return dict(conn.execute("SELECT * FROM calls WHERE id=?",
                             (cur.lastrowid,)).fetchone())


def _record_outcome(conn, call: dict, analysis: dict, summary: str | None):
    """Land a finished call in the panel: interaction row, DNC, stage moves."""
    gid = call["group_id"]
    outcome = analysis.get("outcome") or "no_answer"
    panel_outcome = PANEL_OUTCOME.get(outcome, "spoke")
    follow_up = analysis.get("meeting_at") or analysis.get("callback_at")
    text = summary or analysis.get("summary") or ""
    if outcome == "wrong_number":
        text = f"[wrong number] {text}"
    if analysis.get("selling_situation"):
        text += f" · Learned: {analysis['selling_situation']}"
    if analysis.get("objections"):
        text += f" · Objections: {analysis['objections']}"

    cur = conn.execute(
        "INSERT INTO interactions (group_id, contact_id, channel, direction, "
        "outcome, summary, next_follow_up_at, actor) "
        "VALUES (?,?, 'call', 'outbound', ?,?,?, 'ai-caller')",
        (gid, call["contact_id"], panel_outcome, text.strip(), follow_up))
    panel._after_interaction(conn, gid, {
        "id": cur.lastrowid, "channel": "call", "outcome": panel_outcome,
        "summary": text.strip(), "next_follow_up_at": follow_up}, {})

    if outcome == "do_not_call":
        conn.execute("INSERT OR IGNORE INTO do_not_call (phone, reason) "
                     "VALUES (?, 'asked during AI call')", (call["phone"],))
        panel._log(conn, gid, "dnc_added", {"phone": call["phone"]},
                   actor="ai-caller")


def _eleven_sig_ok(body: bytes, header: str) -> bool:
    """ElevenLabs-Signature: 't=<unix>,v0=<hmac_sha256(secret, "t.body")>'."""
    if not ELEVEN_WEBHOOK_SECRET or not header:
        return False
    try:
        parts = dict(p.split("=", 1) for p in header.split(","))
        t, v0 = parts["t"], parts["v0"]
        if abs(time.time() - int(t)) > 1800:
            return False
        mac = hmac.new(ELEVEN_WEBHOOK_SECRET.encode(),
                       f"{t}.{body.decode('utf-8')}".encode(),
                       "sha256").hexdigest()
        return hmac.compare_digest(mac, v0)
    except (ValueError, KeyError, UnicodeDecodeError):
        return False


@bp.post("/api/caller/webhook")
def api_webhook():
    """Provider server events. Authenticated by each provider's own scheme,
    not dashboard auth (webapp exempts this path); bad/absent auth = 401."""
    payload = request.get_json(silent=True) or {}
    if "message" in payload:                              # Vapi shape
        given = request.headers.get("x-vapi-secret", "")
        if not WEBHOOK_SECRET or not hmac.compare_digest(given, WEBHOOK_SECRET):
            return Response("bad secret", 401)
        return _vapi_webhook(payload.get("message") or {})
    if not _eleven_sig_ok(request.get_data(),
                          request.headers.get("elevenlabs-signature", "")):
        return Response("bad signature", 401)
    return _eleven_webhook(payload)


def _eleven_webhook(payload: dict):
    """ElevenLabs post-call webhook: transcript + data-collection results."""
    if payload.get("type") != "post_call_transcription":
        return jsonify({})                                # e.g. post_call_audio
    data = payload.get("data") or {}
    cid = data.get("conversation_id")
    if not cid:
        return jsonify({})
    with db.connect() as conn:
        ensure_schema(conn)
        row = conn.execute("SELECT * FROM calls WHERE provider_call_id=?",
                           (cid,)).fetchone()
        if not row:
            return jsonify({})
        call = dict(row)
        analysis = data.get("analysis") or {}
        structured = {}
        for k, v in (analysis.get("data_collection_results") or {}).items():
            val = v.get("value") if isinstance(v, dict) else v
            if val not in (None, "", "null", "None", "unknown"):
                structured[k] = val
        summary = analysis.get("transcript_summary") or structured.get("summary")
        meta = data.get("metadata") or {}
        conn.execute(
            """UPDATE calls SET status='ended', ended_at=datetime('now'),
               ended_reason=?, outcome=?, summary=?, transcript=?,
               analysis=?, cost_usd=? WHERE id=?""",
            (meta.get("termination_reason"),
             structured.get("outcome"), summary,
             json.dumps(data.get("transcript"), ensure_ascii=False)
             if data.get("transcript") is not None else None,
             json.dumps(structured, ensure_ascii=False),
             meta.get("cost"),   # NB: ElevenLabs reports credits, not USD
             call["id"]))
        if call["status"] != "ended":       # process each report once
            _record_outcome(conn, call, structured, summary)
        conn.commit()
    return jsonify({})


def _vapi_webhook(msg: dict):
    mtype = msg.get("type")
    call_id = ((msg.get("call") or {}).get("id")) or ""
    if not call_id:
        return jsonify({})

    with db.connect() as conn:
        ensure_schema(conn)
        row = conn.execute("SELECT * FROM calls WHERE provider_call_id=?",
                           (call_id,)).fetchone()
        if not row:
            return jsonify({})
        call = dict(row)

        if mtype == "status-update":
            status = {"ringing": "dialing", "in-progress": "in_progress",
                      "ended": "ended"}.get(msg.get("status"), msg.get("status"))
            if status and call["status"] != "ended":
                conn.execute("UPDATE calls SET status=? WHERE id=?",
                             (status, call["id"]))

        elif mtype == "end-of-call-report":
            analysis = (msg.get("analysis") or {})
            structured = analysis.get("structuredData") or {}
            summary = analysis.get("summary")
            artifact = msg.get("artifact") or {}
            transcript = (artifact.get("messages") or msg.get("messages")
                          or artifact.get("transcript") or msg.get("transcript"))
            cost = msg.get("cost")
            if isinstance(cost, dict):
                cost = cost.get("total")
            conn.execute(
                """UPDATE calls SET status='ended', ended_at=datetime('now'),
                   ended_reason=?, outcome=?, summary=?, transcript=?,
                   analysis=?, recording_url=?, cost_usd=? WHERE id=?""",
                (msg.get("endedReason"),
                 structured.get("outcome"),
                 summary or structured.get("summary"),
                 json.dumps(transcript, ensure_ascii=False)
                 if not isinstance(transcript, (str, type(None))) else transcript,
                 json.dumps(structured, ensure_ascii=False),
                 (artifact.get("recordingUrl") or msg.get("recordingUrl")),
                 cost, call["id"]))
            if call["status"] != "ended":       # process each report once
                _record_outcome(conn, call, structured, summary)
        conn.commit()
    return jsonify({})


# --------------------------------------------------------------- simulator

def _sim_reply(system: str, messages: list[dict]) -> tuple[str, str]:
    """One agent turn through whichever scoring backend has credentials.
    messages: [{'role': 'assistant'|'user', 'content': str}] — user = owner."""
    last_err = None
    for name in config.AI_BACKEND_ORDER:
        try:
            if name == "anthropic":
                if not os.environ.get("ANTHROPIC_API_KEY"):
                    continue
                import anthropic
                # Claude requires the first turn to be the user's; the phone
                # picking up is that turn.
                msgs = messages
                if not msgs or msgs[0]["role"] != "user":
                    msgs = [{"role": "user",
                             "content": "(the phone is answered)"}] + msgs
                r = anthropic.Anthropic().messages.create(
                    model=config.AI_MODEL, max_tokens=1024,
                    system=system, messages=msgs)
                text = "".join(blk.text for blk in r.content
                               if blk.type == "text")
                return text, f"anthropic:{config.AI_MODEL}"
            if name == "kimi":
                key = (os.environ.get("MOONSHOT_API_KEY")
                       or os.environ.get("KIMI_API_KEY"))
                if not key:
                    continue
                from openai import OpenAI
                client, model = (OpenAI(api_key=key, base_url=config.KIMI_BASE_URL),
                                 config.KIMI_MODEL)
            elif name == "openai":
                if not os.environ.get("OPENAI_API_KEY"):
                    continue
                from openai import OpenAI
                client, model = OpenAI(), config.OPENAI_MODEL
            else:
                continue
            r = client.chat.completions.create(
                model=model,
                messages=[{"role": "system", "content": system}] + messages,
                max_tokens=1024)
            return r.choices[0].message.content or "", f"{name}:{model}"
        except Exception as e:          # try the next provider
            last_err = e
    raise RuntimeError(f"no AI backend usable for the simulator "
                       f"({type(last_err).__name__ if last_err else 'no keys set'}) — "
                       "set MOONSHOT_API_KEY, OPENAI_API_KEY or ANTHROPIC_API_KEY")


@bp.post("/api/caller/simulate")
def api_simulate():
    """Text dry-run of the live call. Body: {group_id, messages:[{role,content}]}
    where role 'user' is you playing the owner. Empty messages -> the scripted
    opening line, no model call."""
    body = request.get_json(silent=True) or {}
    gid = str(body.get("group_id") or "")
    messages = body.get("messages") or []
    with db.connect() as conn:
        ensure_schema(conn)
        briefing = build_briefing(conn, gid)
        if not briefing:
            return jsonify({"error": f"no property data for group {gid!r}"}), 404
        contact = conn.execute(
            "SELECT * FROM contacts WHERE group_id=? ORDER BY role != 'owner', id",
            (gid,)).fetchone()
        owner = contact["name"] if contact else None
        if not messages:
            return jsonify({"reply": first_message(owner), "backend": "script"})
        try:
            reply, backend = _sim_reply(system_prompt(briefing, owner), messages)
        except RuntimeError as e:
            return jsonify({"error": str(e)}), 503
    return jsonify({"reply": reply, "backend": backend})


# ------------------------------------------------------------------ routes

@bp.get("/api/caller/status")
def api_status():
    with db.connect() as conn:
        ensure_schema(conn)
        queue = call_queue(conn)
        recent = _rows(conn.execute(
            "SELECT COUNT(*) AS n, SUM(outcome='meeting_set') AS meetings "
            "FROM calls WHERE provider != 'sim'"))[0]
    return jsonify({
        "provider": CALL_PROVIDER,
        "configured": provider_ready() is None,
        "missing": provider_ready(),
        "hours_open": within_calling_hours(),
        "autopilot": AUTOPILOT,
        "agent": {"name": AGENT_NAME, "human": HUMAN_NAME, "agency": AGENCY_NAME,
                  "model": f"{CALL_PROVIDER}/{LLM_MODEL}"},
        "queue_size": len(queue),
        "calls_made": recent["n"] or 0,
        "meetings_set": recent["meetings"] or 0,
    })


@bp.get("/api/caller/queue")
def api_queue():
    with db.connect() as conn:
        return jsonify(call_queue(conn))


@bp.post("/api/caller/call")
def api_call():
    body = request.get_json(silent=True) or {}
    gid = body.get("group_id")
    if not gid:
        return jsonify({"error": "group_id required"}), 400
    with db.connect() as conn:
        try:
            row = start_call(conn, gid, body.get("contact_id"))
        except ValueError as e:
            return jsonify({"error": str(e)}), 400
    return jsonify(row)


@bp.get("/api/caller/calls")
def api_calls():
    gid = request.args.get("group_id")
    where, params = ("WHERE group_id=?", [gid]) if gid else ("", [])
    with db.connect() as conn:
        ensure_schema(conn)
        rows = _rows(conn.execute(
            f"SELECT * FROM calls {where} ORDER BY id DESC LIMIT 100", params))
        summ = panel._summaries(conn)
    for r in rows:
        s = summ.get(r["group_id"]) or {}
        r["property"] = (s.get("official_address") or s.get("street_address_raw")
                         or s.get("title") or r["group_id"])
    return jsonify(rows)


@bp.post("/api/caller/sync-agent")
def api_sync_agent():
    """Push the current base config (voice, LLM, outcome schema) to the
    provisioned ElevenLabs agent — run after changing those env vars."""
    if CALL_PROVIDER != "elevenlabs":
        return jsonify({"error": "CALLER_PROVIDER is not elevenlabs"}), 400
    if not ELEVEN_API_KEY:
        return jsonify({"error": "set ELEVENLABS_API_KEY"}), 400
    with db.connect() as conn:
        ensure_schema(conn)
        try:
            agent_id = eleven_agent_id(conn, sync=True)
        except ValueError as e:
            return jsonify({"error": str(e)}), 502
    return jsonify({"ok": True, "agent_id": agent_id})


@bp.route("/api/caller/dnc", methods=["GET", "POST", "DELETE"])
def api_dnc():
    with db.connect() as conn:
        ensure_schema(conn)
        if request.method == "GET":
            return jsonify(_rows(conn.execute(
                "SELECT * FROM do_not_call ORDER BY added_at DESC")))
        phone = normalize_phone((request.get_json(silent=True) or {}).get("phone"))
        if not phone:
            return jsonify({"error": "valid phone required"}), 400
        if request.method == "POST":
            conn.execute("INSERT OR REPLACE INTO do_not_call (phone, reason) "
                         "VALUES (?, 'added manually')", (phone,))
        else:
            conn.execute("DELETE FROM do_not_call WHERE phone=?", (phone,))
        conn.commit()
    return jsonify({"ok": True, "phone": phone})


# --------------------------------------------------------------- autopilot

_autopilot_started = False


def _autopilot_loop():
    while True:
        try:
            if within_calling_hours() and provider_ready() is None:
                with db.connect() as conn:
                    for item in call_queue(conn)[:AUTOPILOT_BATCH]:
                        try:
                            start_call(conn, item["group_id"], item["contact_id"])
                            print(f"[caller] autopilot dialing {item['group_id']} "
                                  f"({item['phone']})", flush=True)
                        except ValueError as e:
                            print(f"[caller] autopilot skip {item['group_id']}: {e}",
                                  flush=True)
        except Exception as e:
            print(f"[caller] autopilot error: {type(e).__name__}: {e}", flush=True)
        threading.Event().wait(900)


def start_autopilot() -> None:
    """Opt-in background dialler (CALLER_AUTOPILOT=1). Run a SINGLE gunicorn
    worker with this on, or every worker dials the queue."""
    global _autopilot_started
    if not AUTOPILOT or _autopilot_started:
        return
    _autopilot_started = True
    threading.Thread(target=_autopilot_loop, daemon=True).start()
    print("[caller] autopilot on: dialling the queue every 15 min in-hours",
          flush=True)


# -------------------------------------------------------------------- page

@bp.get("/caller")
def caller_page():
    return Response(PAGE, 200, {"Content-Type": "text/html; charset=utf-8"})


PAGE = """<!doctype html>
<html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>AI Caller — Oblivion</title>
<style>
  :root { --bg:#0d1117; --card:#161b22; --line:#30363d; --fg:#e6edf3;
          --dim:#8b949e; --acc:#3fb950; --warn:#d29922; --bad:#f85149; }
  * { box-sizing:border-box; }
  body { margin:0; background:var(--bg); color:var(--fg);
         font:14px/1.5 -apple-system, "Segoe UI", Roboto, sans-serif; }
  .wrap { max-width:1100px; margin:0 auto; padding:24px 16px 80px; }
  h1 { font-size:20px; } h2 { font-size:15px; margin:28px 0 8px; }
  .pill { display:inline-block; padding:2px 10px; border-radius:999px;
          border:1px solid var(--line); color:var(--dim); font-size:12px;
          margin-right:6px; }
  .pill.ok { color:var(--acc); border-color:var(--acc); }
  .pill.warn { color:var(--warn); border-color:var(--warn); }
  .pill.bad { color:var(--bad); border-color:var(--bad); }
  table { width:100%; border-collapse:collapse; background:var(--card);
          border:1px solid var(--line); border-radius:8px; overflow:hidden; }
  th, td { text-align:left; padding:8px 10px; border-top:1px solid var(--line);
           vertical-align:top; }
  th { border-top:none; color:var(--dim); font-weight:600; font-size:12px; }
  button { background:#21262d; color:var(--fg); border:1px solid var(--line);
           border-radius:6px; padding:5px 12px; cursor:pointer; }
  button:hover { border-color:var(--dim); }
  button.primary { background:#238636; border-color:#2ea043; }
  .dim { color:var(--dim); } .small { font-size:12px; }
  details summary { cursor:pointer; color:var(--dim); }
  pre { white-space:pre-wrap; font-size:12px; background:var(--bg);
        padding:8px; border-radius:6px; }
  #chat { background:var(--card); border:1px solid var(--line); border-radius:8px;
          padding:12px; max-height:420px; overflow-y:auto; }
  .msg { margin:6px 0; max-width:85%; padding:6px 10px; border-radius:10px; }
  .msg.agent { background:#1f6feb33; }
  .msg.owner { background:#30363d; margin-left:auto; }
  .simrow { display:flex; gap:8px; margin-top:8px; }
  .simrow input { flex:1; background:var(--bg); border:1px solid var(--line);
                  color:var(--fg); border-radius:6px; padding:8px; }
  .err { color:var(--bad); }
</style></head><body><div class="wrap">
  <h1>AI Caller</h1>
  <div id="status" class="small dim">loading…</div>

  <h2>Call queue</h2>
  <div class="small dim">Tracked properties in contact_found / contacted with a
  phone number, minus do-not-call, exhausted attempts and settled outcomes.</div>
  <table id="queue"><thead><tr><th>Property</th><th>Owner</th><th>Phone</th>
  <th>Asking</th><th>Attempts</th><th></th></tr></thead><tbody></tbody></table>

  <h2>Recent calls</h2>
  <table id="calls"><thead><tr><th>When</th><th>Property</th><th>Status</th>
  <th>Outcome</th><th>Summary</th></tr></thead><tbody></tbody></table>

  <h2>Simulator</h2>
  <div class="small dim">Dry-run the exact live-call prompt by playing the owner —
  costs one text completion per turn, no phone involved.
  Group id: <input id="simgid" size="10" style="background:var(--bg);
  border:1px solid var(--line);color:var(--fg);border-radius:6px;padding:3px 6px">
  <button onclick="simStart()">Start sim</button></div>
  <div id="chat" style="margin-top:8px"></div>
  <div class="simrow"><input id="simsay" placeholder="say something as the owner…"
  onkeydown="if(event.key==='Enter')simSend()"><button class="primary"
  onclick="simSend()">Send</button></div>

<script>
const $ = s => document.querySelector(s);
const esc = t => (t ?? '').toString().replace(/[&<>"]/g,
  c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
const R = v => v ? 'R' + (v/1e6).toFixed(2).replace(/\\.?0+$/,'') + 'm' : '—';

async function refresh() {
  const st = await (await fetch('/api/caller/status')).json();
  $('#status').innerHTML =
    `<span class="pill ${st.configured ? 'ok' : 'bad'}">${st.configured
       ? 'Vapi configured' : 'not configured: ' + esc(st.missing)}</span>` +
    `<span class="pill ${st.hours_open ? 'ok' : 'warn'}">${st.hours_open
       ? 'calling hours open' : 'outside calling hours'}</span>` +
    `<span class="pill">${st.autopilot ? 'autopilot ON' : 'manual dialling'}</span>` +
    `<span class="pill">agent ${esc(st.agent.name)} → ${esc(st.agent.human)}</span>` +
    `<span class="pill">${st.calls_made} calls · ${st.meetings_set} meetings</span>`;

  const q = await (await fetch('/api/caller/queue')).json();
  $('#queue tbody').innerHTML = q.map(r => `<tr>
    <td>${esc(r.official_address || r.street_address_raw || r.title)}<br>
        <span class="small dim">${esc(r.suburb || '')} · ${esc(r.group_id)}</span></td>
    <td>${esc(r.owner_name || '?')}</td><td>${esc(r.phone)}</td>
    <td>${R(r.price_zar)}</td><td>${r.attempts}</td>
    <td><button class="primary" onclick="dial('${esc(r.group_id)}', ${r.contact_id})">
        Call</button></td></tr>`).join('')
    || '<tr><td colspan="6" class="dim">queue is empty</td></tr>';

  const calls = await (await fetch('/api/caller/calls')).json();
  $('#calls tbody').innerHTML = calls.map(c => `<tr>
    <td class="small">${esc((c.created_at || '').slice(0, 16))}<br>
        <span class="dim">${esc(c.provider)}</span></td>
    <td>${esc(c.property)}</td><td>${esc(c.status)}</td>
    <td>${esc(c.outcome || '—')}</td>
    <td>${esc(c.summary || '')}
        ${c.transcript ? `<details><summary>transcript</summary>
          <pre>${esc(fmtTranscript(c.transcript))}</pre></details>` : ''}
        ${c.recording_url ? `<a href="${esc(c.recording_url)}" class="small"
          target="_blank">recording</a>` : ''}</td></tr>`).join('')
    || '<tr><td colspan="5" class="dim">no calls yet</td></tr>';
}

function fmtTranscript(t) {
  try { const m = JSON.parse(t);
    if (Array.isArray(m)) return m.filter(x => x.role !== 'system')
      .map(x => `${x.role}: ${x.message || x.content || ''}`).join('\\n');
  } catch (e) {}
  return t;
}

async function dial(gid, cid) {
  if (!confirm('Place a real AI call for property ' + gid + '?')) return;
  const r = await fetch('/api/caller/call', {method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({group_id: gid, contact_id: cid})});
  const j = await r.json();
  if (j.error) alert(j.error); else refresh();
}

let simMsgs = [];
function bubble(role, text) {
  $('#chat').insertAdjacentHTML('beforeend',
    `<div class="msg ${role === 'assistant' ? 'agent' : 'owner'}">${esc(text)}</div>`);
  $('#chat').scrollTop = 1e9;
}
async function simTurn() {
  const r = await fetch('/api/caller/simulate', {method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({group_id: $('#simgid').value.trim(), messages: simMsgs})});
  const j = await r.json();
  if (j.error) { bubble('assistant', '⚠ ' + j.error); return; }
  simMsgs.push({role: 'assistant', content: j.reply});
  bubble('assistant', j.reply);
}
function simStart() {
  if (!$('#simgid').value.trim()) { alert('enter a group id from the queue'); return; }
  simMsgs = []; $('#chat').innerHTML = ''; simTurn();
}
function simSend() {
  const t = $('#simsay').value.trim();
  if (!t || !$('#simgid').value.trim()) return;
  $('#simsay').value = '';
  simMsgs.push({role: 'user', content: t});
  bubble('user', t); simTurn();
}

refresh(); setInterval(refresh, 20000);
</script></div></body></html>
"""
