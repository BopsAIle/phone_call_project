# Phase 1 — Audio path

- **Parent plan:** [../../2026-08-19-ai-receptionist-phone-booking-agent.md](../../2026-08-19-ai-receptionist-phone-booking-agent.md)
- **Branch:** `feat/twilio-media-stream`
- **Status:** not started
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
A `Call` row exists with the correct `twilioCallSid`, `fromNumber`, and `streamSid`.

## Scope

**In:** Twilio voice webhook and TwiML, raw WebSocket server, Twilio frame parsing, mu-law codec,
8 kHz ↔ 24 kHz resampling, `Call` persistence, the replay harness, codec unit tests.

**Out:** any OpenAI call. The echo is a `media` frame sent straight back.

## Detailed design

### TwiML

`POST /twilio/voice` returns:

```xml
<Response>
  <Connect>
    <Stream url="wss://{PUBLIC_BASE_URL}/media-stream">
      <Parameter name="storeId" value="{storeId}"/>
    </Stream>
  </Connect>
</Response>
```

`<Connect>` is **blocking** — the call stays alive for the life of the stream, which is what we
want. `<Start><Stream>` is the fork-and-continue variant and is the wrong verb here; it is
unidirectional and cannot play audio back.

Custom `<Parameter>` values arrive in the `start` event's `customParameters`, which is how the
session learns which store it is serving without a database lookup keyed on the dialled number.

### WebSocket server

**Do not use `@nestjs/websockets` with the socket.io adapter.** Twilio sends plain JSON text frames.
`@nestjs/platform-ws`'s `WsAdapter` is closer but expects a `{ event, data }` envelope, while Twilio
sends `{ event, media: {...} }` — the payload is a sibling of `event`, not nested under `data`.
Fighting the adapter costs more than skipping it.

Attach a raw `ws` server to the existing HTTP server instead:

```ts
const wss = new WebSocketServer({ server: app.getHttpServer(), path: '/media-stream' });
```

Wrap it in an injectable `MediaStreamGateway` so it can reach `PrismaService` and, later,
`ConversationService`.

### Twilio message protocol

Inbound (Twilio → us):

| Event | Contents | Action |
| --- | --- | --- |
| `connected` | protocol version | log only |
| `start` | `streamSid`, `callSid`, `customParameters`, media format | create/att­ach the `Call` row, open the session |
| `media` | `media.payload` — base64 mu-law, 20 ms, 160 bytes | feed the pipeline |
| `mark` | `mark.name` echoed back | playback of that chunk finished |
| `stop` | — | close the session, finalise the `Call` row |

Outbound (us → Twilio) — **only these three are accepted**:

```ts
{ event: 'media', streamSid, media: { payload: base64Mulaw } }
{ event: 'mark',  streamSid, mark: { name: 'utt-7-chunk-3' } }
{ event: 'clear', streamSid }                     // flush buffered audio — the barge-in primitive
```

`clear` and `mark` are not needed for the echo, but implement and unit-test the encoders now;
Phase 3 depends on them and they are trivial to get subtly wrong.

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

- **Upsample 8k → 24k** (caller audio heading to STT in Phase 2): insert two zeros between samples
  and low-pass, or interpolate. Quality matters less here — STT is robust, and the source is already
  band-limited to 4 kHz by the phone network.
- **Downsample 24k → 8k** (TTS audio heading to Twilio in Phase 3): **low-pass first, then take
  every third sample.** This is the one that must be right. Decimating without an anti-alias filter
  folds everything above 4 kHz back into the audible band, and the result sounds tinny, harsh, and
  "robotic" — exactly the artefact people misdiagnose as a bad TTS voice. Use a windowed-sinc FIR
  (≈48 taps, Hamming window, cutoff ~3.4 kHz) and carry the filter state across frames so block
  boundaries do not click.

### Frame pacing

Twilio buffers whatever you send, so you may write faster than real time. Do not add artificial
`setTimeout` pacing — it only adds latency and jitter. Send frames as they are produced, track
completion with `mark`, and interrupt with `clear`. For the echo, write each inbound frame straight
back out.

### Replay harness

`test/harness/replay.ts` — build this now and extend it in every later phase. It:

1. reads a 16-bit PCM WAV file,
2. resamples to 8 kHz and mu-law encodes it,
3. connects to `ws://localhost:3000/media-stream` and sends a synthetic `start`, then 160-byte
   `media` frames, then `stop`,
4. collects outbound `media` payloads, decodes them, and writes a WAV file to listen to.

This exercises the entire pipeline with no phone call, no tunnel, and no Twilio charges. It is the
single highest-leverage piece of test infrastructure in the project — by Phase 3 it lets you iterate
on prompts and barge-in in seconds instead of by redialling.

### Local tunnel

Twilio needs a public `wss://`. Use ngrok or cloudflared, put the host in `PUBLIC_BASE_URL`, and
point the number's voice webhook at `https://<host>/twilio/voice`. A **reserved** domain is worth it
— the free rotating host changes on every restart and you will re-edit the Twilio console each time.

## Implementation steps

1. [ ] `npm i twilio ws` and `npm i -D @types/ws`.
2. [ ] `src/telephony/twiml.service.ts` — build the `<Connect><Stream>` document.
3. [ ] `src/telephony/twilio.controller.ts` — `POST /twilio/voice` and `POST /twilio/status`
   (`status` writes `endedAt`, `durationSec`, `endReason`). Signature validation lands in Phase 5.
4. [ ] `src/audio/mulaw.codec.ts` — decode LUT, encode function, buffer-level helpers.
5. [ ] `src/audio/resampler.ts` — filtered 3:1 down, 1:3 up, both stateful across frames.
6. [ ] Unit-test the codec and resampler **before** wiring the gateway. They are pure functions;
   debugging them through a phone call is miserable.
7. [ ] `src/telephony/twilio-frames.ts` — typed parse/serialise for all five inbound and three
   outbound message types.
8. [ ] `src/telephony/media-stream.gateway.ts` — raw `ws` server, per-connection state keyed by
   `streamSid`, `Call` row on `start`, echo on `media`, cleanup on `stop` and on socket close.
9. [ ] `test/harness/replay.ts` plus a short sample WAV committed under `test/fixtures/`.
10. [ ] Tunnel, point the Twilio number at it, place a real call, confirm the echo.

## Files created or changed

- `src/telephony/twilio.controller.ts`, `twiml.service.ts`, `twilio-frames.ts`,
  `media-stream.gateway.ts`, `telephony.module.ts` — new.
- `src/audio/mulaw.codec.ts`, `resampler.ts`, `frame-buffer.ts` — new.
- `src/audio/*.spec.ts` — new.
- `test/harness/replay.ts`, `test/fixtures/*.wav` — new.
- [src/main.ts](../../../../src/main.ts) — attach the WebSocket server to the HTTP server.
- [src/app.module.ts](../../../../src/app.module.ts) — import `TelephonyModule`.

## Testing

**Codec (the invariants that actually catch bugs):**

- For all 256 mu-law byte values, `encode(decode(b)) === b`. Exact equality — mu-law decode/encode
  is a bijection on the code space. If this fails, the encoder is wrong.
- PCM → mu-law → PCM error stays within mu-law quantisation bounds across the full int16 range.
- Clipping: `+32767` and `-32768` encode without wrapping to the opposite sign. Sign-handling bugs
  produce loud noise and are obvious on a real call but easy to miss in code review.

**Resampler (the test worth writing carefully):**

- A 1 kHz sine at 24 kHz, downsampled to 8 kHz, still has its energy at 1 kHz.
- **A 6 kHz sine at 24 kHz, downsampled to 8 kHz, is attenuated by at least 40 dB.** 6 kHz is above
  the 4 kHz Nyquist limit of the output rate, so without the anti-alias filter it folds down to
  2 kHz and appears as a loud spurious tone. This single test is what proves the filter exists and
  works, and it is the difference between an agent that sounds human and one that sounds like a
  drive-through speaker.
- Round-trip 8k → 24k → 8k preserves a 500 Hz tone within tolerance.
- Filter state carries across block boundaries: resampling one 4800-sample block gives the same
  output as resampling thirty 160-sample blocks.

**Integration:** the replay harness produces an output WAV audibly identical to the input.

**E2E:** a real call echoes cleanly, and `Call` rows are correct on both `start` and `stop`.

## Risks & gotchas

- **Aliasing on the downsample** — covered above. The 6 kHz test is not optional.
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

- [ ] Demo criterion demonstrated on a real call.
- [ ] Codec and resampler unit tests pass, including the 6 kHz anti-alias test.
- [ ] Replay harness runs end-to-end and its output WAV sounds correct.
- [ ] Sessions clean up on `stop`, on socket close, and on error.
- [ ] `npm run build` and `npm run lint` clean.
