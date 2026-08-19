# Phase 6 — Hardening

- **Parent plan:** [../../2026-08-19-ai-receptionist-phone-booking-agent.md](../../2026-08-19-ai-receptionist-phone-booking-agent.md)
- **Branch:** `feat/hardening`
- **Status:** not started
- **Depends on:** [Phase 5](../phase-5-bilingual-staff-api/plan.md)
- **Unblocks:** production launch

## Objective

Make the agent behave well when things go wrong — and things go wrong on live phone lines constantly.
Silence, confused callers, OpenAI outages, callers who want a human, calls that never end.

Phases 1–5 build the happy path. This phase is what makes it safe to point a real restaurant's number
at the system, plus the observability to run it and the retention policy to keep it lawful.

## Demo criterion

Kill OpenAI connectivity mid-call (block the host in `/etc/hosts` or a proxy) and the agent
apologises audibly, takes a callback number, and ends the call cleanly. No dead air, no hung
WebSocket. A structured log line for the call records duration, per-stage latencies, token counts,
and an estimated cost.

## Scope

**In:** silence and duration timeouts, graceful degradation, human escalation, structured logging,
cost tracking, transcript retention, concurrency check, the mu-law passthrough spike.

**Out:** new conversational features. This phase adds no capability the caller asked for — it makes
the existing ones survive contact with reality.

## Detailed design

### Timeouts

Three independent timers on `CallSession`:

| Timer | Trigger | Action |
| --- | --- | --- |
| No-input | 8 s with no caller speech while `LISTENING` | prompt *"Are you still there?"* in the call locale |
| No-input, second strike | another 8 s | read back whatever was collected, say a colleague will call back, hang up |
| Max duration | 5 min total | wrap up politely and hang up |

Silence is ambiguous on a phone line — the caller may have put you down, lost signal, or be thinking.
Two prompts then a graceful exit is the right balance; hanging up on the first silence loses
bookings, and never hanging up leaks sessions and money.

Always persist whatever slots were collected before hanging up. A partial booking from an abandoned
call is still worth a callback.

### Graceful degradation

The rule: **never leave dead air.** A silent line makes the caller hang up and the restaurant loses
the booking outright.

Wrap each stage with its own fallback:

- **TTS fails** → play a **pre-synthesised, disk-cached** apology in the call locale. Cache these at
  build or boot time: an apology that itself needs a working TTS is useless exactly when needed. The
  Phase 3 greeting cache is the same mechanism.
- **LLM fails** → cached line: *"Sorry, I'm having trouble. Let me take your number and a colleague
  will call you right back."* Then collect the number via the still-working STT, or fall back to the
  caller ID already on the `Call` row.
- **STT fails after reconnection attempts** → cached line, then `<Dial>` to the fallback human number
  if configured, otherwise hang up having saved the caller ID as a callback lead.
- **Database fails** → keep the call going. Buffer slots in memory and write on recovery. A booking
  read back to the caller but lost to a transient DB blip is worse than a slow write.

Every degraded path must still produce a row a human can act on. A failed call that leaves a phone
number is a recoverable booking; one that leaves nothing is a lost customer.

### Human escalation

Add a `transfer_to_human` tool. The agent calls it when the caller asks for a person, gets frustrated,
or raises something outside booking (complaint, large party, allergy the agent should not adjudicate).

Implementation: Twilio REST call update redirecting to TwiML with `<Dial>{FALLBACK_HUMAN_NUMBER}</Dial>`.
If unset or out of hours, apologise, take a callback number, and set `Call.endReason = 'escalated'`.

Prompt guidance matters here: escalate readily. A caller who has asked twice for a human and been
refused by a bot is a worse outcome than any booking is worth.

### Structured logging and cost

Adopt `nestjs-pino`. One JSON summary line per call: `callId`, locale, duration, turn count,
per-stage latency percentiles, LLM prompt/completion tokens, STT seconds, TTS characters, estimated
cost, `endReason`.

Per-call cost is the number that decides whether this is viable at volume, and per-stage latency is
what tells you which stage to attack when the agent feels slow. Both were instrumented in Phase 3 —
this phase aggregates and persists them.

Add a `CallMetrics` table or a JSON column on `Call`; a column is sufficient at this scale.

**Redaction:** never log transcript text, audio payloads, or API keys at `info` or above. Transcripts
are personal data. Add a pino redaction config and a test asserting the key never appears in output.

### Retention

Bookings are business records; **transcripts are personal data with no reason to live forever.**

Add a scheduled job (`@nestjs/schedule`) that deletes `Utterance` rows older than
`TRANSCRIPT_RETENTION_DAYS` (default 30), keeping `Call` and `Booking`. Retention length is an open
question for the user in the parent plan — 30 days is a defensible default, not a decision.

No raw audio is stored anywhere, which is the simplest way to stay clean. Keep it that way; if audio
storage is ever added it needs its own consent and retention story.

### Concurrency

Each call holds two WebSockets, an audio pipeline, and a resampler. Verify behaviour under
concurrency before launch, since the restaurant's busiest hour is exactly when several calls arrive
at once.

Drive 10 concurrent replay-harness calls and watch event-loop lag and RSS. Resampling is the only
CPU-bound work; if lag climbs, move it to a worker thread — but **measure first**, because at this
scale it is very likely fine and worker threads would be premature.

Add a `MAX_CONCURRENT_CALLS` cap. Over the cap, return TwiML that apologises and takes a voicemail
rather than accepting a call the process cannot serve.

### mu-law passthrough spike

Timeboxed to half a day. Try `audio/pcmu` and `g711_ulaw_8khz` as the transcription session's input
format (see the parent plan's "Known unknown"). If either is accepted, the upsample on the input path
disappears — less CPU per call and slightly lower latency.

If neither works, record the negative result here and move on. The current path is documented and
correct; this is an optimisation, not a fix.

## Implementation steps

1. [ ] `npm i nestjs-pino pino-http @nestjs/schedule`.
2. [ ] Three timers on `CallSession` with locale-aware prompts.
3. [ ] Pre-synthesise and cache greeting and fallback lines per locale at boot.
4. [ ] Per-stage fallback wrappers for TTS, LLM, STT, and the database.
5. [ ] `transfer_to_human` tool and the Twilio `<Dial>` redirect.
6. [ ] `FALLBACK_HUMAN_NUMBER`, `MAX_CONCURRENT_CALLS`, `TRANSCRIPT_RETENTION_DAYS` in the env schema.
7. [ ] Structured logging with redaction; per-call summary line.
8. [ ] Cost estimation and persistence of call metrics.
9. [ ] Retention cron job.
10. [ ] Concurrency cap plus the overflow TwiML.
11. [ ] Load test with 10 concurrent harness calls.
12. [ ] mu-law passthrough spike; record the outcome in this file.
13. [ ] Write the change doc at `docs/features/ai-receptionist-phone-booking-agent.md` and link it
    from [docs/README.md](../../../README.md).

## Files created or changed

- `src/conversation/call-timers.ts`, `src/conversation/fallback-audio.service.ts` — new.
- `src/llm/tools/escalation.tools.ts` — new.
- `src/telephony/twilio.controller.ts` — escalation redirect, overflow TwiML.
- `src/observability/` — logging config, redaction, cost estimation — new.
- `src/retention/retention.service.ts` — new.
- `src/config/env.schema.ts` — new variables.
- `prisma/schema.prisma` + migration — call metrics column.
- `test/load/concurrent-calls.ts` — new.

## Testing

- **Unit — timers:** no-input fires at 8 s; the second strike wraps up; max duration hangs up;
  any caller speech resets them.
- **Unit — fallbacks:** each stage's failure produces the cached line rather than an exception
  reaching the gateway.
- **Unit — redaction:** API keys and transcript text never appear in log output. Assert on the
  serialised line, not on the logger config.
- **Unit — cost estimation:** known token counts produce the expected figure.
- **Integration — outage simulation:** block the OpenAI host mid-call via the harness; the agent
  apologises, collects a callback number, and ends cleanly with a usable row.
- **Integration — retention:** utterances older than the window are deleted; `Call` and `Booking`
  survive.
- **Load:** 10 concurrent harness calls — no session leaks, event-loop lag within bounds, memory flat
  after completion.
- **E2E:** real call where you stay silent; real call where you ask for a human.

## Risks & gotchas

- **A fallback that depends on the failed service** is the classic mistake here. The apology audio
  must be on disk before it is needed.
- **Timers that outlive the call** leak sessions. Clear all three on `stop`, on socket close, and on
  error — the same cleanup paths Phase 1 established.
- **Hanging up too eagerly** loses bookings. Two prompts before exit.
- **Redaction is easy to regress.** A `logger.debug(transcript)` added later during debugging can
  quietly ship. The assertion test is the guard.
- **Escalation loops** if the fallback number routes back into the Twilio number. Verify the fallback
  is a genuinely external line.
- **Cost estimates drift** as prices change. Put the rates in config, not in code, and date-stamp
  them.

## Exit checklist

- [ ] Demo criterion demonstrated: simulated outage handled with no dead air.
- [ ] All three timeouts verified on real calls.
- [ ] Escalation to a human works end to end.
- [ ] Redaction test passes; no secrets or transcripts in logs.
- [ ] Retention job verified against seeded old data.
- [ ] 10 concurrent calls with no leaks.
- [ ] mu-law spike outcome recorded here either way.
- [ ] Change doc written and linked from `docs/README.md`.
- [ ] `npm run build` and `npm run lint` clean.
