# Plan: AI Receptionist — Phone Booking Agent

- **Date:** 2026-08-19
- **Slug:** `ai-receptionist-phone-booking-agent`
- **Branch:** `feat/ai-receptionist`
- **Status:** draft
- **Change doc:** [../features/ai-receptionist-phone-booking-agent.md](../features/ai-receptionist-phone-booking-agent.md)

## Why we need this change

A restaurant's phone goes unanswered during service. Staff are on the floor, the line rings out,
and the caller hangs up and books somewhere else. Every missed call is a lost table, and the loss is
invisible — nobody records the bookings that never happened. Voicemail does not fix it: callers
rarely leave one, and when they do the message lacks half the details needed to act on it.

This feature puts an AI receptionist on the store's number. It answers every call immediately, holds
a natural spoken conversation in English or German, collects the details required to book a table,
reads them back for confirmation, and stores a structured booking record. A staff member later works
a queue of complete, pre-qualified callbacks instead of an empty voicemail box.

Crucially, **the agent never checks or promises availability.** A human calls back to confirm the
table. That constraint is what makes the system safe to ship: the agent cannot double-book, cannot
promise a table that does not exist, and needs no integration with the reservation book.

## Goals

- Answer 100% of inbound calls to the store number with no human involvement.
- Hold a natural, interruptible spoken conversation in **English and German**.
- Collect and persist: customer name, party size, requested date/time, callback phone, and notes.
- Read the details back and get explicit verbal confirmation before ending the call.
- Produce a staff-facing queue of bookings with status `PENDING_CALLBACK`.
- Keep the full transcript of every call, with per-stage latency recorded for tuning.
- Target under 1.5 s from the caller finishing speaking to the agent starting to reply.

## Non-goals

- **Checking or confirming table availability.** Out of scope by design — a human does this.
- Modifying or cancelling an existing booking over the phone.
- Taking payment, deposits, or card details.
- Outbound calling (the confirmation callback is placed manually by staff).
- Languages beyond English and German.
- A customer-facing web booking UI. This is a backend and phone channel only.
- Multi-tenant SaaS. The schema allows for multiple stores, but the first release serves one.

## Current behaviour

There is no receptionist functionality. The repository is an unmodified NestJS 11 scaffold:

- [src/main.ts](../../src/main.ts) — bootstraps and listens on `PORT ?? 3000`.
- [src/app.module.ts](../../src/app.module.ts) — empty `imports`, default controller and service.
- [src/app.controller.ts](../../src/app.controller.ts) — returns "Hello World!".
- [package.json](../../package.json) — only `@nestjs/*`, `reflect-metadata`, `rxjs`. No telephony,
  AI, WebSocket, or database dependencies.

There is no database, no configuration module, and no environment validation. The `data/` directory
at the repo root is unrelated local tooling state and is already gitignored.

## Proposed approach

A cascaded **STT → LLM → TTS** pipeline orchestrated inside NestJS, with one WebSocket per live call.
OpenAI supplies all three stages; Twilio supplies the phone line and the audio transport.

```
PSTN caller
   │
   ▼
Twilio number ──POST──► /twilio/voice ──► TwiML: <Connect><Stream url="wss://…/media-stream">
   │
   └──── bidirectional WS (8 kHz mu-law, 20 ms frames, base64) ────┐
                                                                   ▼
                                                     MediaStreamGateway (NestJS)
                                                                   │
                     ┌─────────────────────────────────────────────┼─────────────────────────┐
                     ▼                                             ▼                         ▼
            AudioCodec (mu-law <-> PCM,                    CallSession (per-call          TtsService
             8k <-> 24k resample)                          orchestrator + state)        gpt-4o-mini-tts
                     │                                             │                         │
                     ▼                                             ▼                         │
            SttService (OpenAI realtime               LlmService (gpt-5.6-terra              │
            transcription, gpt-live-transcribe,        + tool calling for slots)             │
            server VAD, delta/completed)                           │                         │
                     │                                             ▼                         │
                     └──── transcript ──────────────► Prisma (Call, Utterance, Booking) ◄─────┘
                                                                   │
                                                                   ▼
                                                        Staff REST API + callback queue
```

### Conversation design

**Slots collected:** `customerName`, `partySize`, `requestedAt` (date + time), `phone` (pre-filled
from the Twilio `From` header and confirmed aloud), `notes` (allergies, high chair, occasion).

**Extraction happens via tool calling, not a second parsing pass.** The brain is given two tools:

- `update_booking(fields)` — called whenever the model learns any slot; partial updates allowed and
  merged into `Booking.slots` immediately, so a mid-call hangup still leaves usable data.
- `finalize_booking()` — called only after the details have been read back and the caller agreed.
  Sets `Booking.status = PENDING_CALLBACK` and fires the staff notification.

Keeping extraction in the same model turn as the spoken reply avoids a second round trip and the
latency it would add.

**Availability guard.** The system prompt states that the agent cannot see the reservation book and
must never confirm a table, only promise a callback. This is the single most important prompt
constraint — an agent that hallucinates "yes, 8pm is free" creates real-world double bookings.

**Date and time.** The current datetime and store timezone are injected into the system prompt so
"next Friday at seven" resolves correctly. The model's ISO output is validated with `luxon` against
the store timezone, and the caller's original phrasing is always persisted in `requestedRaw` so the
staff member calling back sees what was actually said rather than a wrong guess.

**Bilingual EN/DE.** Greet bilingually, detect the language from the first final transcript, then
lock it on `Call.locale` for the rest of the call and pass it to STT (language hint) and TTS (via
`instructions`, e.g. *"Speak natural German at a calm, clear pace"*). Locking beats per-utterance
auto-detection, which flips on short utterances like "ja" or "okay" over 8 kHz phone audio. An
explicit mid-call switch is allowed if the caller asks.

**Barge-in.** When STT reports speech started while the agent is mid-utterance, send Twilio a
`clear` message, abort the in-flight TTS stream, and drop the queued sentence. Without this the
agent talks over interruptions and the call feels broken.

**Latency budget** (target < 1.5 s): VAD endpointing ~500 ms, LLM first token ~400 ms, TTS first
audio ~300 ms. Mitigated by streaming LLM output into TTS **sentence by sentence** rather than
awaiting the full completion, and by keeping the system prompt short. Per-stage timings are recorded
in `Utterance.latencyMs` from Phase 1 — we cannot tune what we do not measure.

### Verified vendor facts

Confirmed against current provider documentation on 2026-08-19. These drive the design; do not
substitute remembered values.

- **Twilio Media Streams** — 8 kHz G.711 mu-law, mono, base64, 20 ms frames (160 bytes). Inbound
  events `connected` / `start` / `media` / `stop` / `mark`. The only messages Twilio accepts *from*
  us are `media`, `mark`, and `clear`. `clear` flushes Twilio's buffered outbound audio and is the
  barge-in primitive; `mark` echoes back when a chunk finishes playing, which is how we know the
  agent actually stopped talking. Requires `<Connect><Stream>`, not `<Start><Stream>`.
- **OpenAI TTS** (`gpt-4o-mini-tts`) — `response_format: "pcm"` is raw **24 kHz, 16-bit signed,
  little-endian, headerless, mono**. `wav`/`pcm` are the lowest-latency formats. Chunked streaming
  is supported. The `instructions` parameter controls accent, tone, and speed. Voices `marin` and
  `cedar` are the current quality recommendations.
- **OpenAI realtime transcription** — the GA API uses a **nested** `session.audio.input.format`
  object (`{"type": "audio/pcm", "rate": 24000}`); the old flat `input_audio_format: "g711_ulaw"`
  is rejected. Server emits `conversation.item.input_audio_transcription.delta` (partial) and
  `.completed` (final). Model: `gpt-live-transcribe`.
- **Model IDs** — brain `gpt-5.6-terra` (balanced) with `gpt-5.6-luna` as the cheap fallback; STT
  `gpt-live-transcribe`; TTS `gpt-4o-mini-tts`; future speech-to-speech `gpt-realtime-2.1`.

> **Known unknown, deliberately routed around.** The GA enum string for direct G.711 mu-law input
> (`audio/pcmu` vs `g711_ulaw_8khz`) is not enumerated in public documentation, and the community
> thread asking exactly this is unanswered. We sidestep it: we already must own a mu-law codec and
> a resampler for the TTS output path, so we run the same code inverted on the input path and send
> the documented `audio/pcm` @ 24000. Direct mu-law passthrough becomes a later optimisation
> (Phase 6 spike), never a blocker.

### Alternatives considered

| Option | Pros | Cons | Verdict |
| --- | --- | --- | --- |
| **Cascaded STT → LLM → TTS** (chosen) | Full transcript; slot extraction via tool calls; per-stage cost and latency visibility; swappable stages | ~1.5–2.5 s to first audio; we own resampling and VAD wiring | **Chosen** — matches the requested design and gives the observability a booking system needs |
| OpenAI Realtime speech-to-speech (`gpt-realtime-2.1`) | ~500 ms latency; native mu-law in/out, no resampling; built-in VAD and interruption | Black box — weaker transcript and extraction story; harder to debug and cost-attribute | Rejected for v1. Stages sit behind `SttProvider`/`LlmProvider`/`TtsProvider` interfaces so an S2S adapter can replace all three later without touching the gateway or booking logic |
| Managed platform (Vapi, Retell) | Fastest to production; voice loop maintained by vendor | We do not build or control the pipeline; per-minute vendor lock-in | Rejected — the point of this project is to own the pipeline |
| Deepgram STT + ElevenLabs TTS | Best-in-class latency and voice quality | Two more vendors, two more keys and bills | Rejected — user has OpenAI only; revisit if voice quality disappoints |
| Whisper file transcription per turn | Simple request/response, no WebSocket | No streaming, no VAD, seconds of added latency per turn | Rejected — unusable for live conversation |
| MongoDB instead of Postgres | Flexible transcript blobs | Bookings are relational and reporting matters | Rejected — Postgres + Prisma chosen |

## Implementation steps

Each phase is independently demoable and lands on its own branch off `feat/ai-receptionist`. Every
phase has its own detailed execution plan under [phases/](phases/README.md) — the summaries below
are the index, not the instructions.

1. [ ] **[Phase 0 — Foundation](phases/phase-0-foundation/plan.md).** `@nestjs/config` with a zod-validated env schema (fail fast on
   missing keys), Prisma + the schema below, `docker-compose.yml` for Postgres, `PrismaService`,
   health endpoint, and the three provider interfaces. No AI yet. Request the German phone number
   now — provisioning takes days.
2. [ ] **[Phase 1 — Audio path](phases/phase-1-audio-path/plan.md).** Twilio webhook returns `<Connect><Stream>`; the gateway accepts the
   WS, parses `start`/`media`/`stop`, and persists a `Call` row. Ship the mu-law codec and resampler
   **with unit tests**. Build the offline replay harness here. *Demo: call the number and hear your
   own voice echoed back.* This phase de-risks the project — if audio is clean here, the rest is
   application logic.
3. [ ] **[Phase 2 — The agent hears](phases/phase-2-speech-to-text/plan.md).** OpenAI realtime transcription session over WebSocket, server
   VAD, `delta`/`completed` handling, `Utterance` rows written live. *Demo: transcripts stream into
   the server log during a real call.*
4. [ ] **[Phase 3 — The agent speaks](phases/phase-3-llm-tts-loop/plan.md).** `gpt-5.6-terra` with the receptionist prompt;
   `gpt-4o-mini-tts` → PCM 24k → resample → mu-law → Twilio frames, streamed per sentence. Barge-in
   via `clear` + `mark`. Include the AI-and-recording disclosure in the greeting. *Demo: a real, if
   aimless, spoken conversation.*
5. [ ] **[Phase 4 — It actually books](phases/phase-4-booking-slots/plan.md).** `update_booking` / `finalize_booking` tools, slot tracking,
   datetime resolution, spoken readback and confirmation, `Booking` persisted. *Demo: call in, book
   a table, see the row in Postgres.*
6. [ ] **[Phase 5 — Production shape](phases/phase-5-bilingual-staff-api/plan.md).** Locale detection and locking, German prompt and voice tuning,
   staff REST API (list pending callbacks, mark confirmed/unreachable), new-booking notification,
   Twilio request signature validation.
7. [ ] **[Phase 6 — Hardening](phases/phase-6-hardening/plan.md).** Silence and no-input timeouts, max call duration, graceful
   degradation when OpenAI errors mid-call (apologise and take a callback number — never dead air),
   `<Dial>` escalation to a human, structured logging with cost and latency per call, transcript
   retention policy, and the mu-law passthrough spike.
8. [ ] Write the change doc at `docs/features/ai-receptionist-phone-booking-agent.md` and link it
   from [docs/README.md](../README.md).

## Files expected to change

New modules under `src/`:

- `src/config/` — `@nestjs/config` registration and the zod env schema.
- `src/prisma/` — `PrismaService`, `PrismaModule`.
- `src/telephony/twilio.controller.ts` — `POST /twilio/voice`, `POST /twilio/status`, with Twilio
  signature validation.
- `src/telephony/twiml.service.ts` — builds the `<Connect><Stream>` response.
- `src/telephony/media-stream.gateway.ts` — raw `ws` server on `/media-stream`; the audio entry point.
- `src/telephony/twilio-frames.ts` — encode/decode `media` | `mark` | `clear` messages.
- `src/audio/mulaw.codec.ts`, `resampler.ts`, `frame-buffer.ts` — mu-law ↔ PCM16, 8 kHz ↔ 24 kHz,
  and 20 ms framing/pacing.
- `src/stt/` — `stt.provider.ts` interface, `openai-realtime-stt.service.ts`.
- `src/llm/` — `llm.provider.ts`, `openai-llm.service.ts`, `prompts/receptionist.prompt.ts`,
  `tools/booking.tools.ts`.
- `src/tts/` — `tts.provider.ts`, `openai-tts.service.ts`.
- `src/conversation/call-session.ts` — **the core of the system**: one call's lifetime, STT/LLM/TTS
  handles, slot state, who is speaking, barge-in, timers. Everything else is plumbing.
- `src/conversation/conversation.service.ts` — session registry keyed by `streamSid`.
- `src/conversation/slot-filler.ts`, `locale-detector.ts`.
- `src/bookings/` — staff-facing REST controller and service.
- `src/notifications/` — new-booking alert to staff.

Modified:

- [src/app.module.ts](../../src/app.module.ts) — wire up every new module.
- [src/main.ts](../../src/main.ts) — WebSocket server setup, graceful shutdown hooks.
- [package.json](../../package.json) — new dependencies below.
- [src/app.controller.ts](../../src/app.controller.ts) and
  [src/app.service.ts](../../src/app.service.ts) — remove the scaffold or replace with the health check.

## Data & configuration

### New dependencies

`@nestjs/config`, `zod`, `@prisma/client`, `prisma` (dev), `openai`, `twilio`, `ws`, `@types/ws`
(dev), `luxon`, `@types/luxon` (dev).

### Environment variables

`DATABASE_URL`, `OPENAI_API_KEY`, `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, `TWILIO_PHONE_NUMBER`,
`PUBLIC_BASE_URL` (tunnel or deployed host, used to build the `wss://` stream URL), `STORE_TIMEZONE`
(default `Europe/Berlin`), `DEFAULT_LOCALE`, `LLM_MODEL`, `STT_MODEL`, `TTS_MODEL`, `TTS_VOICE`.

All are validated by the zod schema at boot. `.env` stays gitignored; no key is ever committed or
logged.

### Prisma schema

```prisma
model Store {
  id            String @id @default(cuid())
  name          String
  phoneNumber   String @unique          // Twilio number, E.164
  timezone      String @default("Europe/Berlin")
  defaultLocale String @default("en")
  greetingEn    String
  greetingDe    String
  calls         Call[]
}

model Call {
  id            String @id @default(cuid())
  storeId       String
  twilioCallSid String @unique
  streamSid     String?
  fromNumber    String
  toNumber      String
  locale        String?                 // detected: "en" | "de"
  status        CallStatus @default(IN_PROGRESS)
  startedAt     DateTime @default(now())
  endedAt       DateTime?
  durationSec   Int?
  endReason     String?                 // completed | caller_hangup | timeout | error | escalated
  store         Store @relation(fields: [storeId], references: [id])
  utterances    Utterance[]
  booking       Booking?
}

model Utterance {
  id        String @id @default(cuid())
  callId    String
  role      Role                        // CALLER | AGENT
  text      String
  startMs   Int
  latencyMs Int?                        // per-stage timing, for tuning
  createdAt DateTime @default(now())
  call      Call @relation(fields: [callId], references: [id], onDelete: Cascade)
}

model Booking {
  id           String @id @default(cuid())
  callId       String @unique
  customerName String?
  phone        String?                  // defaults to the Twilio `From` number
  partySize    Int?
  requestedAt  DateTime?                // resolved absolute local datetime
  requestedRaw String?                  // "next Friday around seven" — kept for the human caller
  notes        String?
  locale       String?
  status       BookingStatus @default(PENDING_CALLBACK)
  slots        Json                     // raw accumulated tool-call state
  createdAt    DateTime @default(now())
  call         Call @relation(fields: [callId], references: [id], onDelete: Cascade)
}

enum CallStatus    { IN_PROGRESS COMPLETED FAILED ABANDONED }
enum BookingStatus { PENDING_CALLBACK CONFIRMED CANCELLED UNREACHABLE }
enum Role          { CALLER AGENT }
```

Migrations are additive and created per phase (`prisma migrate dev`). A seed script creates the
single `Store` row.

## Testing

- **Unit** — mu-law codec round-trip and resampler SNR against a generated sine wave (Phase 1);
  Twilio frame encode/decode (Phase 1); slot-filler state transitions and datetime resolution across
  timezones and DST boundaries (Phase 4); locale detection (Phase 5).
- **Offline replay harness** — the highest-value test to build. A script that replays a WAV file
  into `MediaStreamGateway` as synthetic Twilio `media` frames and writes the agent's outbound audio
  to a WAV file. It exercises the entire pipeline, including barge-in, with no phone call, no
  tunnel, and no Twilio spend. Build it in Phase 1 and extend it every phase.
- **E2E per phase** — place a real call to the Twilio number and confirm that phase's demo criterion.
- **Data assertions** — after a booking call, verify the `Call`, `Utterance[]`, and `Booking` rows
  are coherent and the booking is `PENDING_CALLBACK`.
- **Adversarial call scripts** (Phase 5) — caller changes their mind mid-booking; caller starts in
  German and switches to English; caller interrupts constantly; caller asks "is 8pm free?" (the
  agent must decline to confirm); caller hangs up mid-slot (partial booking must still persist).
- Per repository convention, run type-check and lint before every commit.

## Risks & rollback

| Risk | Detection | Mitigation / rollback |
| --- | --- | --- |
| **Resampling artefacts** — naive 24k→8k decimation without a low-pass filter aliases and makes the agent sound tinny and robotic. The hidden failure mode; easy to misattribute to the TTS model. | Listen to harness WAV output; codec unit tests | Proper filtered resampling, verified in Phase 1 before any AI is wired in |
| **Latency above ~2 s** makes the agent feel broken | `Utterance.latencyMs` percentiles | Sentence-level TTS streaming, shorter prompt, `gpt-5.6-luna`; escalation path is the `gpt-realtime-2.1` S2S adapter behind the existing interfaces |
| **Agent confirms availability** despite the prompt | Adversarial call scripts; transcript review | Hard prompt constraint plus a check that `finalize_booking` never sets a confirmed status; the human callback is the backstop |
| **German +49 number requires a verified local address bundle**, days to provision | Twilio console | Develop on a US/UK number; request the DE number in Phase 0 so it is ready by Phase 5 |
| **Twilio needs a public `wss://`** — local tunnels change host on restart | Webhook 502s | ngrok/cloudflared with a reserved domain; `PUBLIC_BASE_URL` is env-driven |
| **OpenAI outage or error mid-call** leaves dead air | Error rate per call; `Call.endReason` | Phase 6: apologise, take a callback number, `<Dial>` escalation to a human |
| **Cost per call** scales with STT + LLM + TTS minutes | Per-call cost logging (Phase 6) | Switch the brain to `gpt-5.6-luna`; cap max call duration |
| **Privacy** — German callers are covered by GDPR/TTDSG | Doc and prompt review | The greeting must state that the caller is speaking to an automated assistant and that the call is transcribed, **before** anything is collected. Built into Phase 3, not retrofitted — adding consent to already-stored transcripts is painful. Never log full audio or transcripts at `debug` in production; retention policy in Phase 6 |

**Rollback:** the feature is entirely additive. Repointing the Twilio number's voice webhook away
from `/twilio/voice` disables the receptionist instantly without a deploy. Each phase is a separate
branch and can be reverted independently; Prisma migrations are additive and non-destructive.

## Open questions

- Store name, timezone, opening hours, and exact greeting wording in both languages — **owner: user**
  (needed for the Phase 0 seed).
- Who receives the new-booking notification, and over which channel (SMS, email, Slack, or dashboard
  only)? — **owner: user** (needed for Phase 5).
- Retention period for call transcripts, and whether raw audio is stored at all — **owner: user**
  (needed for Phase 6; the safe default is to store no audio).
- Is a single store sufficient for the first release, or is multi-store needed sooner? — **owner: user**
  (the schema already allows for it).
