# Phase 1 — Audio path

- **Parent plan:** [../../2026-08-19-ai-receptionist-phone-booking-agent.md](../../2026-08-19-ai-receptionist-phone-booking-agent.md)
- **Branch:** `feat/twilio-media-stream`, cut from `feat/foundation` (or `master` once Phase 0 merges)
- **Status:** code complete, verified offline (2026-08-20); real-call demo criterion blocked on the
  Twilio number purchase carried over from Phase 0
- **Change doc:** [../../../features/phase-1-audio-path.md](../../../features/phase-1-audio-path.md)
- **Depends on:** [Phase 0](../phase-0-foundation/plan.md)
- **Unblocks:** every phase that moves audio (2, 3)

## Objective

Get clean, full-duplex audio between a real phone call and this process, and prove it with an echo.
Build the mu-law codec and the resampler that every later phase depends on, and the offline replay
harness that lets you test the whole pipeline without spending a cent on Twilio.

**This is the highest-risk phase.** Audio bugs are silent: they do not throw, they just make the
agent sound wrong, and in Phase 3 you will blame the TTS model for them. Finish this phase properly
and everything after it is ordinary application logic.

## Demo criterion

Call the Twilio number, speak, and hear your own voice played back clearly and without delay drift.
The webhook wrote a `Call` row with the correct `twilioCallSid`, `fromNumber`, and `toNumber`; the
gateway filled in `streamSid`; and after hanging up the row is `COMPLETED` with a plausible
`durationSec`.

## Scope

**In:** Twilio voice webhook and TwiML, raw WebSocket server, Twilio frame parsing, mu-law codec,
8 kHz ↔ 24 kHz resampling, `Call` persistence, the replay harness, codec unit tests.

**Out:** any OpenAI call. The echo is a `media` frame sent straight back.

## Detailed design

### TwiML

`POST /twilio/voice` receives Twilio's form-encoded call parameters — `CallSid`, `From`, `To` —
resolves the store, creates the `Call` row (see *Call lifecycle* below), and returns:

```xml
<Response>
  <Connect>
    <Stream url="wss://{host}/media-stream">
      <Parameter name="callId" value="{call.id}"/>
      <Parameter name="storeId" value="{store.id}"/>
    </Stream>
  </Connect>
</Response>
```

`<Connect>` is **blocking** — the call stays alive for the life of the stream, which is what we
want. `<Start><Stream>` is the fork-and-continue variant and is the wrong verb here; it is
unidirectional and cannot play audio back.

Custom `<Parameter>` values arrive in the `start` event's `customParameters`, always as strings.

**Resolving the store.** `Store.phoneNumber` is `@unique`, so the dialled `To` number resolves it in
a single `findUnique`. Note that `<Parameter>` does not remove that lookup — it moves it from the
gateway to the webhook, where the row it produces is passed down to the socket instead of being
re-fetched per stream. If no `Store` matches the dialled number, return `<Say>` + `<Hangup>` TwiML,
**not** a 500: an error response gives the caller Twilio's generic failure tone with no explanation
and leaves no `Call` row behind to diagnose from.

**Response mechanics.** Set `Content-Type: text/xml` explicitly — Nest defaults to JSON and Twilio
will not parse the body. The inbound body is `application/x-www-form-urlencoded`, which Nest's
Express adapter already parses. Twilio times this webhook out at **15 s**, so the store lookup and
the row insert are the only work this handler may do.

**`{host}`** derives from `PUBLIC_BASE_URL`, which [the env schema](../../../../src/config/env.schema.ts)
validates as an `https://` URL while the stream needs `wss://`. Swap the scheme and strip any
trailing slash in `twiml.service.ts`, and unit-test it — an `https://` URL in `<Stream url>` fails at
connect time with an error that never mentions the scheme.

### Call lifecycle — who writes what

Twilio's `start` event carries `streamSid`, `accountSid`, `callSid`, `tracks`, `mediaFormat`, and
`customParameters`. It **does not carry `From` or `To`**, and `Call.fromNumber` / `Call.toNumber` are
non-null in the schema — so the row cannot originate at the socket. It originates at the webhook,
which has all three, and three writers then touch it in order:

| Writer | Fields | Notes |
| --- | --- | --- |
| `POST /twilio/voice` | `storeId`, `twilioCallSid`, `fromNumber`, `toNumber` | `upsert` on `twilioCallSid`, not `create` — Twilio retries webhooks, and the `@unique` constraint turns a retry into a 500 |
| gateway `start` | `streamSid` | update by the `callId` custom parameter |
| gateway `stop` / socket close | — | tears the session down; writes ending fields **only if `endedAt` is still null** |
| `POST /twilio/status` | `endedAt`, `durationSec`, `status`, `endReason` | owns the ending |

Creating the row at the webhook also captures calls where the media stream never connects. A tunnel
misconfiguration currently leaves no trace at all, which is the hardest version of that bug to chase.

**`status` must actually be written.** `Call.status` defaults to `IN_PROGRESS` and nothing else moves
it, so a call that ends without this write stays in progress forever — and Phase 5's staff API and
Phase 6's metrics both read the field. Map Twilio's `CallStatus` parameter:

| Twilio `CallStatus` | `Call.status` | `Call.endReason` |
| --- | --- | --- |
| `completed` | `COMPLETED` | `completed` |
| `busy`, `no-answer`, `canceled` | `ABANDONED` | `caller_hangup` |
| `failed` | `FAILED` | `error` |

`CallDuration` arrives as a string of seconds; coerce it into `durationSec`.

**The two finalisers race.** The `stop` frame and the status callback arrive in either order, and
Twilio does not always send `stop` at all (dropped call, network loss). Making the status callback
the owner and gating the `stop` path on `endedAt IS NULL` produces the same row whichever wins.

### WebSocket server

**Do not use `@nestjs/websockets` with the socket.io adapter.** Twilio sends plain JSON text frames.
`@nestjs/platform-ws`'s `WsAdapter` is closer but expects a `{ event, data }` envelope, while Twilio
sends `{ event, media: {...} }` — the payload is a sibling of `event`, not nested under `data`.
Fighting the adapter costs more than skipping it.

Attach a raw `ws` server to the existing HTTP server instead. It has to live inside an injectable
`MediaStreamGateway` to reach `PrismaService` and, later, `ConversationService` — but only `main.ts`
holds the HTTP server, so the gateway exposes `attach` and `main.ts` calls it:

```ts
// media-stream.gateway.ts
attach(server: Server) {
  this.wss = new WebSocketServer({ server, path: '/media-stream' });
  this.wss.on('connection', (ws) => this.handleConnection(ws));
}

// main.ts, after await app.listen(...)
app.get(MediaStreamGateway).attach(app.getHttpServer());
```

Close every live socket in **`beforeApplicationShutdown`**, and not in `onApplicationShutdown` as an
earlier draft of this plan said. Nest's shutdown order is `onModuleDestroy` →
`beforeApplicationShutdown` → **close the HTTP server** → `onApplicationShutdown`. An open WebSocket
keeps that HTTP close pending forever, so cleaning up in the later hook deadlocks: the hook that
would close the sockets sits behind a close that is waiting on those same sockets, and the process
hangs until the orchestrator SIGKILLs it — taking every other live call with it.

This is not theoretical; it was written the wrong way first and the e2e shutdown case caught it.
[src/main.ts](../../../../src/main.ts) already calls `app.enableShutdownHooks()`, which is what
invokes the hook at all.

**Key per-connection state off the socket, not off `streamSid`.** A socket that closes before `start`
arrives has no `streamSid` at all, and a `Map<WebSocket, Session>` cleans up correctly in every case.
Keep a `streamSid → session` index beside it for the barge-in lookups Phase 3 needs.

Guard every write with `ws.readyState === WebSocket.OPEN`. Sends to a socket Twilio has already torn
down surface as an asynchronous `error` event, so in the echo path the failure shows up one frame
after the frame that caused it.

### Twilio message protocol

Inbound (Twilio → us):

| Event | Contents | Action |
| --- | --- | --- |
| `connected` | protocol version | log only |
| `start` | `streamSid`, `callSid`, `customParameters`, `mediaFormat` | open the session, write `streamSid` onto the `Call` row the webhook already created |
| `media` | `media.payload` — base64 mu-law, 20 ms, 160 bytes | feed the pipeline |
| `mark` | `mark.name` echoed back | playback of that chunk finished |
| `dtmf` | `dtmf.digit` | log only in this phase; Phase 6's escalation may want it |
| `stop` | — | close the session, finalise the `Call` row |

An **unknown `event` must be logged and ignored, never thrown from**. Twilio adds message types over
time, and an exception inside the socket's `message` handler kills a live phone call. Phase 2 applies
the same rule to OpenAI's event stream.

Assert `start.mediaFormat` once per session — it announces
`{ encoding: 'audio/x-mulaw', sampleRate: 8000, channels: 1 }`, which is the assumption the entire
codec is built on. Log loudly on any mismatch rather than decoding garbage.

Outbound (us → Twilio) — **only these three are accepted**:

```ts
{ event: 'media', streamSid, media: { payload: base64Mulaw } }
{ event: 'mark',  streamSid, mark: { name: 'utt-7-chunk-3' } }
{ event: 'clear', streamSid }                     // flush buffered audio — the barge-in primitive
```

`clear` and `mark` are not needed for the echo, but implement and unit-test the encoders now;
Phase 3 depends on them and they are trivial to get subtly wrong.

**Twilio discards malformed outbound messages silently** — no NACK, no error frame, nothing in the
console. A `mark` with the payload one level too deep simply never happens. Assert the exact JSON
shape of all three messages in unit tests, because the runtime gives you no signal at all.

### mu-law codec

G.711 mu-law: 8-bit companded, 8 kHz, one byte per sample, 160 bytes per 20 ms frame.

**Decode** with a precomputed 256-entry `Int16Array` lookup table built once at module load. There
are only 256 possible inputs; there is no reason to compute this per sample.

**Encode** with the canonical Sun algorithm (`BIAS = 0x84`, `CLIP = 32635`) plus the standard
128-entry exponent table:

```ts
function pcm16ToMulaw(sample: number): number {
  let sign = (sample >> 8) & 0x80;
  if (sign) sample = -sample;
  if (sample > CLIP) sample = CLIP;
  sample += BIAS;
  const exponent = EXP_LUT[(sample >> 7) & 0xff];
  const mantissa = (sample >> (exponent + 3)) & 0x0f;
  return ~(sign | (exponent << 4) | mantissa) & 0xff;
}
```

Do not trust this sketch — the round-trip test below is what proves it correct.

### Resampling

The ratio is exactly **1:3** (8 kHz ↔ 24 kHz), which is the one genuinely pleasant fact in this
phase: no fractional resampling, no drift accumulation, no phase bookkeeping across frames.

- **Upsample 8k → 24k** (caller audio heading to STT in Phase 2): insert two zeros between samples,
  low-pass, then **multiply by 3**. The gain step is not cosmetic. Zero-stuffing by L and filtering
  divides amplitude by L, so omitting it hands STT audio at a third of full scale — about 9.5 dB
  down. Nothing throws, transcription mostly still works, and the accuracy you lose on quiet callers
  looks exactly like a weak STT model. Do not substitute linear interpolation: it is a different and
  worse filter, not a shortcut to the same result.
- **Downsample 24k → 8k** (TTS audio heading to Twilio in Phase 3): **low-pass first, then take
  every third sample.** This is the one that must be right. Decimating without an anti-alias filter
  folds everything above 4 kHz back into the audible band, and the result sounds tinny, harsh, and
  "robotic" — exactly the artefact people misdiagnose as a bad TTS voice. Use a windowed-sinc FIR
  (≈48 taps, Hamming window, cutoff ~3.4 kHz) and carry the filter state across frames so block
  boundaries do not click.

48 taps is deliberately modest. A Hamming window gives roughly −53 dB of stopband attenuation, which
clears the 6 kHz test below comfortably, but the transition band at 24 kHz is ~1.6 kHz wide — so
content between 3.4 and 4 kHz is only partly attenuated. That is correct for telephony (the phone
band ends at 3.4 kHz anyway) and it is written down here so nobody later reads the soft roll-off as a
bug and "fixes" it by adding latency.

### Frame pacing

Twilio buffers whatever you send, so you may write faster than real time. Do not add artificial
`setTimeout` pacing — it only adds latency and jitter. Send frames as they are produced, track
completion with `mark`, and interrupt with `clear`. For the echo, write each inbound frame straight
back out.

### Replay harness

`test/harness/replay.ts` — build this now and extend it in every later phase. It:

1. reads a 16-bit PCM WAV file,
2. resamples to 8 kHz and mu-law encodes it,
3. `POST`s a synthetic form body (`CallSid`, `From`, `To`) to `/twilio/voice` and reads the stream
   URL and `<Parameter>` values back out of the returned TwiML,
4. connects to that URL and sends a synthetic `start` carrying those parameters, then 160-byte
   `media` frames, then `stop`,
5. collects outbound `media` payloads, decodes them, and writes a WAV file to listen to.

Step 3 exists because the `Call` row is created by the webhook: a synthetic `start` inventing its own
`callId` would reference a row that does not exist. Driving the real webhook is both more faithful
and cheaper than adding a test-only branch to the gateway. Expose it as `npm run replay`
(`tsx test/harness/replay.ts`) and keep the committed fixture WAV to a couple of seconds.

This exercises the entire pipeline with no phone call, no tunnel, and no Twilio charges. It is the
single highest-leverage piece of test infrastructure in the project — by Phase 3 it lets you iterate
on prompts and barge-in in seconds instead of by redialling.

### Browser dev client

The harness replays a file; it cannot tell you how the agent feels to talk to. A companion browser
page does that — microphone in, 8 kHz mu-law out, speaking Twilio's exact protocol to the same
`/media-stream` endpoint, so the gateway cannot tell the difference and Twilio drops in later
unchanged.

It is planned separately in **[browser-dev-client.md](browser-dev-client.md)**, which also records
why it exists: the Twilio trial gates number configuration behind an upgrade, so the real-call demo
criterion below is currently unreachable. The browser client substitutes for it without pretending to
replace it — it proves the audio path, not TwiML execution or real phone-line audio.

### Local tunnel

Twilio needs a public `wss://`. Use ngrok or cloudflared, put the host in `PUBLIC_BASE_URL`, and
point the number's voice webhook at `https://<host>/twilio/voice` **and its status callback at
`https://<host>/twilio/status`** — both live on the number's configuration, and the second is easy to
forget because nothing fails visibly without it. A **reserved** domain is worth it — the free
rotating host changes on every restart and you will re-edit the Twilio console each time.

## Implementation steps

1. [x] `npm i twilio ws` and `npm i -D @types/ws`.
2. [x] `src/audio/mulaw.codec.ts` — decode LUT, encode function, buffer-level helpers.
3. [x] `src/audio/resampler.ts` — filtered 3:1 down, 1:3 up with the ×3 gain, both stateful across
   frames.
4. [x] `src/audio/frame-buffer.ts` — accumulate a byte stream and emit exact 160-byte frames,
   carrying the remainder across calls, with an explicit flush.
5. [x] Unit-test the codec, resampler, and frame buffer **before** wiring anything else. They are
   pure functions; debugging them through a phone call is miserable.
6. [x] `src/telephony/twiml.service.ts` — build the `<Connect><Stream>` document, including the
   `PUBLIC_BASE_URL` → `wss://` conversion.
7. [x] `src/telephony/twilio.controller.ts` — `POST /twilio/voice` (store lookup, `Call` upsert,
   `text/xml` TwiML, `<Say>`+`<Hangup>` when no store matches) and `POST /twilio/status` (the status
   mapping table above). Signature validation lands in Phase 5.
8. [x] `src/telephony/twilio-frames.ts` — typed parse/serialise for the six inbound and three
   outbound message types, with log-and-ignore on anything unrecognised.
9. [x] `src/telephony/media-stream.gateway.ts` — raw `ws` server, `attach` called from `main.ts`,
   per-connection state keyed by the socket, `streamSid` written on `start`, echo on `media`,
   cleanup on `stop`, on socket close, and on error, plus `beforeApplicationShutdown`.
10. [x] `test/harness/replay.ts` plus a short sample WAV committed under `test/fixtures/`, and the
    `replay` script in `package.json`.
11. [ ] Tunnel; point the Twilio number's **voice webhook** at `https://<host>/twilio/voice` **and
    its status callback** at `https://<host>/twilio/status` — the status endpoint never fires
    otherwise, and the omission stays invisible until Phase 5 reads `Call.status`.
    **Blocked: no number purchased yet.**
12. [ ] Place a real call, confirm the echo, and check the `Call` row before and after hanging up.
    **Blocked on step 11.**

## Files created or changed

- `src/telephony/twilio.controller.ts`, `twiml.service.ts`, `twilio-frames.ts`,
  `media-stream.gateway.ts`, `telephony.module.ts` — new.
- `src/audio/mulaw.codec.ts`, `resampler.ts`, `frame-buffer.ts` — new.
- `src/audio/*.spec.ts` — new.
- `test/harness/replay.ts`, `test/fixtures/*.wav` — new.
- [src/main.ts](../../../../src/main.ts) — attach the WebSocket server to the HTTP server after
  `listen`.
- [src/app.module.ts](../../../../src/app.module.ts) — import `TelephonyModule` and `AudioModule`.
- [package.json](../../../../package.json) — `twilio`, `ws`, `@types/ws`, and the `replay` script.

## Testing

**Codec (the invariants that actually catch bugs):**

- `encode(decode(b)) === b` for all 256 codes **except `0x7F`**. mu-law has a negative zero: `0x7F`
  and `0xFF` both decode to 0, and 0 encodes back to `0xFF`. That one collapse is inherent to the
  codec, not a bug — assert the exception explicitly (`expect(changed).toEqual([0x7f])`) so the test
  still fails if anything *else* stops round-tripping. Verified against the implementation.
- PCM → mu-law → PCM error stays within half a quantisation step (≤ 512) across the **representable**
  range, `|sample| ≤ 32635`. Do not assert this over the full int16 range: mu-law saturates at
  ±32124, so `±32768` is off by 644 by design. Test that separately as saturation.
- Polarity: `0x00` is the loudest **negative** code and `0x80` the loudest positive one. Inverting
  this is silent on its own and wrong everywhere the audio is mixed or compared.
- Clipping: `+32767` and `-32768` saturate to ±32124 rather than wrapping to the opposite sign.
  JavaScript's number type is what saves us here — the C original overflows on `-(-32768)`.

**Resampler (the test worth writing carefully):**

Write a ten-line Goertzel helper in the spec file first and measure energy at a named frequency with
it. Every assertion below is then one line, and none of them require eyeballing an FFT.

- A 1 kHz sine at 24 kHz, downsampled to 8 kHz, still has its energy at 1 kHz.
- **A 6 kHz sine at 24 kHz, downsampled to 8 kHz, is attenuated by at least 40 dB.** 6 kHz is above
  the 4 kHz Nyquist limit of the output rate, so without the anti-alias filter it folds down to
  2 kHz and appears as a loud spurious tone. Measure the **2 kHz** bin of the output — 6 kHz does not
  exist in an 8 kHz signal, so there is nothing to measure at 6 kHz. This single test is what proves
  the filter exists and works, and it is the difference between an agent that sounds human and one
  that sounds like a drive-through speaker.
- Round-trip 8k → 24k → 8k preserves a 500 Hz tone within tolerance **and preserves its amplitude** —
  the second half is what catches a missing ×3 upsample gain.
- Filter state carries across block boundaries: resampling one 4800-sample block gives the same
  output as resampling ten 480-sample blocks. 480 samples is 20 ms at 24 kHz, which is the block size
  Phase 3 will actually feed it.

**Frame buffer:** a byte stream that is not a multiple of 160 emits only whole frames and carries the
remainder into the next call; the flush emits the tail. This is where chunk-boundary clicks come
from in Phase 3.

**TwiML:** an `https://host` value for `PUBLIC_BASE_URL`, with and without a trailing slash, produces
exactly `wss://host/media-stream`.

**Integration:** the replay harness produces an output WAV audibly identical to the input.

**E2E:** a real call echoes cleanly; the `Call` row is correct after the webhook, gains its
`streamSid` on `start`, and reaches `COMPLETED` with a `durationSec` after hangup.

## Risks & gotchas

- **Aliasing on the downsample** — covered above. The 6 kHz test is not optional.
- **The missing ×3 upsample gain** is the quietest bug in this phase: no error, no artefact, just
  9.5 dB of lost level that Phase 2 will read as poor STT accuracy.
- **Malformed outbound JSON is dropped without a word** by Twilio. If `mark` or `clear` appears not
  to work in Phase 3, check the message shape before anything else.
- **A status callback that was never configured** on the Twilio number means `/twilio/status` never
  fires, every `Call` stays `IN_PROGRESS`, and nothing surfaces until Phase 5's staff API reads the
  field. Configure it in the same sitting as the voice webhook.
- **`<Start>` instead of `<Connect>`** gives you a unidirectional stream; you will receive audio and
  wonder why nothing plays back.
- **Base64 per frame** — Twilio's payload is base64 and must be decoded before the codec and
  re-encoded after. Forgetting one side yields loud static, which at least fails loudly.
- **Socket cleanup.** Twilio does not always send `stop` (dropped calls, network loss). Clean up on
  the raw `close` and `error` events too, or sessions leak for the process lifetime.
- **Tunnel host mismatch** between `PUBLIC_BASE_URL` and the Twilio console produces a 502 with no
  audio and no obvious error. Check it first when a call fails silently.
- **Do not log audio payloads.** They are voluminous and, from Phase 2 onward, personal data.

## Exit checklist

- [ ] **Demo criterion demonstrated on a real call. Outstanding — blocked on Twilio.** The trial
      account does have a number (`+17372508034`), but the console gates *configuring* it behind an
      account upgrade, and the number is US while development is in Vietnam. Substituted for by the
      [browser dev client](browser-dev-client.md), which proves the audio path but not TwiML
      execution or real phone-line audio — so this stays unticked. Everything below was verified
      without a phone call.
- [x] Codec, resampler, and frame-buffer unit tests pass — 66 unit tests, including the 6 kHz
      anti-alias test and the ×3 upsample gain test.
- [x] Replay harness runs end-to-end: 100 frames in, 100 out, 37.7 dB SNR against the source WAV
      (mu-law's own quantisation floor) at 0 samples of lag.
- [x] Sessions clean up on `stop`, on socket close, and on error.
- [x] Shutdown completes with a socket still open, covered by an e2e case. Note this is `app.close()`
      rather than a real SIGTERM — Windows has no true signals, so the *hook* is proven and the
      *signal* delivery is not.
- [x] A hung-up call reaches `COMPLETED`, by both routes: the gateway's `stop` teardown and the
      status callback. Non-terminal statuses are ignored.
- [ ] The status callback is **configured on the Twilio number** — part of the blocked real-call step.
- [x] `npm run build` and `npm run lint` clean; 66 unit and 4 e2e tests pass.
- [x] Change doc written at [../../../features/phase-1-audio-path.md](../../../features/phase-1-audio-path.md)
      and linked from [docs/README.md](../../../README.md).
