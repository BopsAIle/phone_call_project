# Phase 1 — Audio path

- **Plan:** [../plan/phases/phase-1-audio-path/plan.md](../plan/phases/phase-1-audio-path/plan.md)
- **Branch:** `feat/twilio-media-stream`
- **Status:** code complete and verified offline; the real-call demo criterion is blocked on the
  Twilio number purchase carried over from Phase 0.

## Why we need this change

Phase 0 produced a project that could hold the receptionist but could not hear or say anything. This
phase connects a real phone call to the process.

It is deliberately the second thing built, before any AI, because audio is the riskiest part of the
system and the least forgiving to debug later. Sample-rate conversion, mu-law encoding, and frame
framing fail *silently* — nothing throws, the agent just sounds wrong, and by Phase 3 the obvious
suspect is the TTS voice rather than a decimation filter written weeks earlier. Proving a clean
full-duplex path with an echo, and unit-testing the DSP against known signals, means every later
phase is ordinary application logic on a known-good transport.

Doing nothing is not an option — every phase from here moves audio.

## What changed

### New modules

**`src/audio/`** — pure functions and stateful DSP objects, no Nest, no network:

- [mulaw.codec.ts](../../src/audio/mulaw.codec.ts) — G.711 mu-law encode/decode with a 256-entry
  decode lookup table, plus the shared sample-rate and frame-size constants.
- [resampler.ts](../../src/audio/resampler.ts) — `Downsampler` (24k→8k) and `Upsampler` (8k→24k),
  both stateful across frames.
- [frame-buffer.ts](../../src/audio/frame-buffer.ts) — cuts an arbitrary byte stream into exact
  160-byte, 20 ms Twilio frames, carrying the remainder across chunks.

**`src/telephony/`**:

- [twilio.controller.ts](../../src/telephony/twilio.controller.ts) — `POST /twilio/voice` and
  `POST /twilio/status`.
- [twiml.service.ts](../../src/telephony/twiml.service.ts) — builds the `<Connect><Stream>` document
  and derives the `wss://` URL.
- [twilio-frames.ts](../../src/telephony/twilio-frames.ts) — zod-validated parsing of the six inbound
  message types and serialisers for the three outbound ones.
- [media-stream.gateway.ts](../../src/telephony/media-stream.gateway.ts) — the raw `ws` server.
- [telephony.module.ts](../../src/telephony/telephony.module.ts).

**`test/harness/`** — [replay.ts](../../test/harness/replay.ts) and a minimal
[wav.ts](../../test/harness/wav.ts) reader/writer, plus `test/fixtures/tone-sweep.wav`.

### Endpoints

| Endpoint | Purpose |
| --- | --- |
| `POST /twilio/voice` | Resolves the store from the dialled number, creates the `Call` row, returns `<Connect><Stream>` TwiML |
| `POST /twilio/status` | Records the ending: `endedAt`, `durationSec`, `status`, `endReason` |
| `WS /media-stream` | Twilio Media Streams; echoes audio in this phase |

### Database

No schema change — Phase 0 created the full schema. This phase is the first writer of `Call`.

### Dependencies

`twilio` and `ws` added as dependencies, `@types/ws` as a dev dependency. New `npm run replay` script.

## How it works

A caller reaches the number and Twilio opens **three separate connections** to us, not one:

```
① POST /twilio/voice     — has CallSid, From, To.  Creates the Call row.
② WS  /media-stream      — has streamSid + custom parameters. Carries the audio.
③ POST /twilio/status    — has CallSid, CallStatus, CallDuration. Closes the row out.
```

### Why the `Call` row is created at the webhook

Twilio's WebSocket `start` event carries `streamSid`, `accountSid`, `callSid`, `tracks`,
`mediaFormat`, and `customParameters` — but **not `From` or `To`**, both of which are non-null
columns on `Call`. The row therefore cannot originate at the socket. The webhook has all three
fields, creates the row, and passes its id down as a `<Parameter>`; the gateway only writes
`streamSid` on `start`.

This was the plan's one blocking error, found during review before implementation. It also turned out
to have a second benefit, observed in practice during development: when a stream fails to connect
(a wrong tunnel host), the row still exists with a null `streamSid` and status `IN_PROGRESS`, which
is a diagnosable trace instead of no record at all.

The store lookup does not disappear by using `<Parameter>` — it moves to the webhook, keyed on the
unique `Store.phoneNumber`. An unmatched number returns `<Say>` + `<Hangup>`, never a 500, so the
caller hears an explanation rather than Twilio's generic failure tone.

### Ownership of the ending

`stop` and the status callback race, and Twilio does not always send `stop` at all. The status
callback owns the ending and writes unconditionally; the gateway's teardown writes the same fields
only when `endedAt` is still null. Either order produces the same row. Non-terminal statuses
(`ringing`, `in-progress`) are ignored rather than being written as an ending.

### The DSP decisions that matter

**Downsampling 24k→8k low-passes before decimating.** Decimating without an anti-alias filter folds
everything above 4 kHz back into the audible band, which sounds tinny and harsh and gets
misattributed to the TTS model. A 48-tap Hamming windowed-sinc at 3.4 kHz is the filter; the test
that proves it exists feeds in a 6 kHz tone and asserts the 2 kHz bin of the output is more than
40 dB down — 6 kHz being unmeasurable in an 8 kHz signal, the alias is what you measure.

**Upsampling 8k→24k applies an explicit ×3 gain.** Zero-stuffing by L and filtering divides amplitude
by L. Without the compensation, Phase 2 would feed STT audio 9.5 dB down — nothing throws,
transcription mostly still works, and the accuracy lost on quiet callers reads as a weak model.

**Both carry filter state across frames.** A 20 ms frame is far shorter than a 48-tap filter, so a
filter that restarted each frame would ring at every boundary — a click 50 times a second.

### Echo, deliberately without the codec

The Phase 1 pipeline copies the base64 payload from an inbound `media` frame into an outbound one.
Nothing in the echo path decodes audio, so a bad echo means a transport bug and never a codec one.
The codec's proof is its unit tests and the replay harness. Phase 2 forks the `media` handler into
decode → upsample → STT.

## Impact

**Breaking changes:** none. Entirely additive; `GET /health` and Phase 0 behaviour are unchanged.

**Migrations:** none.

**Environment:** no new variables. `PUBLIC_BASE_URL` gains a second consumer — it now builds the
`wss://` stream URL as well as being validated at boot.

**Twilio configuration (manual, required):** the number needs **both** its voice webhook pointed at
`https://<host>/twilio/voice` **and** its status callback at `https://<host>/twilio/status`. The
second is easy to miss because nothing fails visibly without it — calls simply stay `IN_PROGRESS`
forever, and that would not surface until Phase 5's staff API reads the field.

**Rollback:** repoint the Twilio number's voice webhook away from `/twilio/voice`. No deploy needed
and no data to unwind.

## Verification

Offline, all green:

- 66 unit tests, including the 6 kHz anti-alias test, the ×3 upsample gain test, and the mu-law
  round trip.
- 4 e2e tests against a booted `AppModule`.
- Replay harness: 100 frames in, 100 frames out, **37.7 dB SNR** against the source WAV with **0
  samples of lag** — exactly mu-law's quantisation floor and nothing else lost.
- `Call` rows verified in Postgres across all four paths: creation at the webhook, `streamSid` on
  `start`, finalisation by the gateway's `stop`, and finalisation by the status callback.
- Unknown dialled number returns `<Say>` + `<Hangup>` and creates no row.

**Not yet verified: the demo criterion.** Calling the number and hearing your own voice needs a
purchased Twilio number and a tunnel. Phase 0's exit checklist still carries
`Development phone number purchased` as outstanding, and `TWILIO_PHONE_NUMBER` is currently a Twilio
magic test number. The code path is exercised end to end by the replay harness, but a real call has
not been placed.

## Notes for later phases

- **`beforeApplicationShutdown`, not `onApplicationShutdown`.** Nest closes the HTTP server *between*
  those two hooks, and an open WebSocket keeps that close pending — cleaning up in the later hook
  deadlocks the process until it is SIGKILLed. Written the wrong way first; the e2e shutdown case
  caught it.
- **mu-law is not a bijection on its code space.** `0x7F` (negative zero) and `0xFF` both decode to
  0, and 0 encodes to `0xFF`. The plan asserted all 256 codes round-trip; 255 of them do.
- **Twilio silently discards malformed outbound messages** — no NACK, nothing in the console. The
  `media`/`mark`/`clear` shapes are asserted in unit tests because the runtime gives no signal.
- `mark` and `clear` are implemented and tested but unused until Phase 3's barge-in.
- `Upsampler` and `FrameBuffer` are built and tested here but have no caller until Phases 2 and 3.
