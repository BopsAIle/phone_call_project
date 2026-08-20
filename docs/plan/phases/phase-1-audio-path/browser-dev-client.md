# Phase 1 — Browser dev client

- **Parent plan:** [plan.md](plan.md) (Phase 1 — Audio path)
- **Branch:** `feat/twilio-media-stream`
- **Status:** planned
- **Depends on:** the Phase 1 gateway and codec, both shipped
- **Unblocks:** interactive testing in Phases 2 and 3

## Why we need this

Phase 1's code is finished and verified offline — 66 unit tests, 4 e2e tests, and a replay harness
that drives the real webhook and gateway at 37.7 dB SNR with zero frame loss. What is missing is its
demo criterion: *call the number, hear yourself.*

That is blocked, and not by anything in the code. The Twilio trial does include a number
(`+17372508034`), but the console gates number **configuration** behind an account upgrade that is
not available right now. The trial number is also US while the developer is in Vietnam, so even
inbound testing would carry international call charges on a personal phone, repeatedly, for a test
meant to be run many times.

Waiting is the wrong response. The audio path is the riskiest part of the system and the whole point
of Phase 1 was to prove it before any AI is wired in. A browser that speaks Twilio's protocol proves
almost all of it today.

**This is not only a workaround.** From Phase 3 it becomes the fastest way to talk to the agent and
test barge-in — the same leverage the replay harness gives, but interactive. Iterating on a prompt by
redialling a phone is miserable; clicking *Call* in a tab is not.

## Objective

A page that captures the microphone, encodes to 8 kHz mu-law, and speaks **Twilio's exact Media
Streams protocol** to the existing `/media-stream` endpoint — so you click call, talk, and hear
yourself, live and full-duplex, through the production gateway.

## The governing constraint

**The browser is a Twilio stand-in, not a second code path.** Same WebSocket endpoint, same
`connected` / `start` / `media` / `stop` frames going out, same `media` / `mark` / `clear` coming
back. When Twilio becomes available you point the number at the webhook and nothing in
`src/telephony/` changes.

The acceptance test for this is literal: **`git diff src/telephony/` must be empty.** If the gateway
needed a special case for the browser, then the browser is not speaking Twilio's protocol and the
confidence this gives us is fake.

## Demo criterion

Open `http://localhost:3000/dev`, click **Call**, speak, and hear your own voice back without drift.
The server log shows the same lines the replay harness produces, with frames in and out equal, and a
`Call` row exists with the correct `streamSid`, reaching `COMPLETED` on hangup.

## What this proves, and what it does not

**Proves:** full-duplex audio through the production gateway, the mu-law codec on real speech rather
than a synthetic tone sweep, the 20 ms frame clock under live timing, session lifecycle, and `Call`
row writes.

**Does not prove:** Twilio's own TwiML execution, real PSTN audio (a laptop microphone downsampled to
8 kHz is markedly cleaner than a phone line), real network jitter and packet loss, or that the tunnel
and Twilio console configuration are correct.

So **Phase 1's real-call checkbox stays unticked**, with this recorded as how the phase was
demonstrated. Anyone reading [plan.md](plan.md) later must not conclude it was tested on a phone.

## Detailed design

```
Browser  public/dev-client.html + /dev/assets/main.js
   │
   ├─① POST /twilio/voice  (form-encoded: CallSid, From, To)
   │     → DOMParser reads <Stream url> and the <Parameter> values out of the TwiML
   │       Same approach as test/harness/replay.ts: drive the real webhook, so the
   │       store lookup and Call row creation are exercised rather than faked.
   │
   ├─② getUserMedia → AudioContext(8000) → AudioWorklet
   │     → 160-sample frames → Int16 → pcm16ToMulaw → base64
   │     → { event: 'media', streamSid, media: { payload } }
   │
   └─③ WS /media-stream ──── identical protocol ────► MediaStreamGateway  ← UNCHANGED
          ◄── media → decode → AudioBuffer → scheduled playback
          ◄── mark  → log
          ◄── clear → stop queued sources, reset cursor    (Phase 3 barge-in)
```

### Sharing the codec

The browser must **not** carry its own mu-law implementation. A subtly different copy would let the
loopback appear to work while masking exactly the codec bug this is meant to catch — the encoder and
decoder would simply be wrong in agreement.

`esbuild` bundles `client/main.ts`, which imports
[mulaw.codec.ts](../../../../src/audio/mulaw.codec.ts) directly, so the page runs the same
`pcm16ToMulaw` and the same 256-entry decode table as the gateway and the harness.

One change is needed there: widen `decodeMulaw(mulaw: Buffer)` to `Uint8Array`. `Buffer` *is* a
`Uint8Array`, so every existing caller is unaffected. `encodeMulaw` stays Buffer-returning —
[replay.ts](../../../../test/harness/replay.ts) calls `.toString('base64')` on its result — and the
browser loops the scalar `pcm16ToMulaw` itself. The scalar function is the part that could be subtly
wrong; a four-line loop around it cannot meaningfully diverge.

The AudioWorklet is a second esbuild entry point. It only buffers 128-sample blocks into 160-sample
frames, so it needs no shared code — worklets run in their own global scope and cannot import from
the main bundle anyway.

### Sample rate

`new AudioContext({ sampleRate: 8000 })`, with `createMediaStreamSource` resampling the microphone
into it. This is why the page needs no new DSP: the existing `Downsampler` is fixed at 3:1 and cannot
do the 48 kHz → 8 kHz a typical capture device would otherwise require.

If a browser refuses the rate, check `ctx.sampleRate !== 8000` and fail with a message that names the
problem. Silently sending wrong-rate audio would sound like a codec fault and waste an afternoon.

### Playback

Keep a scheduling cursor in `AudioContext` time and schedule each decoded frame at
`max(cursor, now + cushion)`, advancing the cursor by the buffer duration. Hold the live
`AudioBufferSourceNode`s in a set so `clear` can stop them — that set is what makes Phase 3's
barge-in testable here rather than only on a real call.

## Implementation steps

1. [ ] `npm i -D esbuild`; add `build:client` and `build:client:watch` scripts. Keep them out of
   `npm run build`, which stays server-only.
2. [ ] Widen `decodeMulaw` to accept `Uint8Array` in
   [mulaw.codec.ts](../../../../src/audio/mulaw.codec.ts). No caller changes.
3. [ ] `client/capture-worklet.ts` — 128 → 160 sample framing on the audio thread.
4. [ ] `client/main.ts` — webhook call and TwiML parse, capture, protocol, playback, `clear` handling.
5. [ ] `public/dev-client.html` — the page itself. Committed; the bundle it loads is generated.
6. [ ] `src/dev/dev-client.controller.ts` — `GET /dev` serves the HTML, `GET /dev/config` returns
   `{ storeNumber }` from `TWILIO_PHONE_NUMBER` so the page knows what to send as `To`.
7. [ ] `src/dev/dev.module.ts`; import it from [app.module.ts](../../../../src/app.module.ts) **only
   when `NODE_ENV !== 'production'`**. Module registration runs before DI, so this reads the raw env
   rather than `ConfigService` — the standard Nest idiom, and worth a comment saying so.
8. [ ] [main.ts](../../../../src/main.ts) — `NestFactory.create<NestExpressApplication>` and
   `useStaticAssets` for `public/assets` under the `/dev/assets` prefix. A distinct prefix from the
   controller routes, so static middleware and the router cannot shadow one another.
9. [ ] `.gitignore` — `public/assets/`.
10. [ ] Update [plan.md](plan.md) and
    [the change doc](../../../features/phase-1-audio-path.md).

## Files created or changed

- `client/main.ts`, `client/capture-worklet.ts` — new. Deliberately outside the
  `{src,apps,libs,test}` eslint glob: this code needs DOM types the server tsconfig does not load.
- `public/dev-client.html` — new, committed. `public/assets/` — generated, gitignored.
- `src/dev/dev-client.controller.ts`, `src/dev/dev.module.ts` — new.
- [src/audio/mulaw.codec.ts](../../../../src/audio/mulaw.codec.ts) — `Uint8Array` widening.
- [src/main.ts](../../../../src/main.ts), [src/app.module.ts](../../../../src/app.module.ts) — static
  assets and the dev-only module import.
- [package.json](../../../../package.json) — `esbuild`, `build:client`, `build:client:watch`.

## Testing

1. `npm run build:client && npm run start:dev`, open `http://localhost:3000/dev`, grant the
   microphone, click **Call**, and speak.
2. Server log matches the replay harness's sequence, frames in equal to frames out:
   ```
   [TwilioController]   Call cmt… from +1555… to store Placeholder Restaurant
   [MediaStreamGateway] Stream MZ… started for call cmt…
   [MediaStreamGateway] Stream MZ… ended after N frames in, N out
   ```
3. `Call` row created by the webhook, `streamSid` filled on `start`, `COMPLETED` after hangup.
4. **`git diff src/telephony/` is empty** — the swap-in readiness check above.
5. Regressions: `npx jest` (66), `npm run test:e2e` (4), `npm run build`, `npm run lint`.
6. `npm run replay` still passes — the harness and the browser drive the same endpoint and must not
   have diverged.

## Risks & gotchas

- **Use headphones.** Without them the echo feeds straight back into the microphone and howls within
  a second or two. `echoCancellation: true` in the capture constraints helps and is not a substitute.
- **`/dev` must never reach production.** It exposes a microphone-capture page and the store number.
  The `NODE_ENV` gate is the control; verify it by booting with `NODE_ENV=production` and confirming
  `/dev` returns 404.
- **Browser audio flatters Phase 2.** A laptop microphone at 8 kHz is far cleaner than a phone line.
  Do not judge STT accuracy on it — the parent plan already warns that real 8 kHz phone audio is
  genuinely hard, and this page will make it look easy.
- **AudioContext sample-rate support** varies by browser. Chrome, Edge, and Firefox honour 8000. This
  is the one thing that could stop the page working at all somewhere untested.

## Exit checklist

- [ ] Demo criterion demonstrated in the browser.
- [ ] `git diff src/telephony/` empty — Twilio drops in unchanged.
- [ ] `/dev` returns 404 under `NODE_ENV=production`.
- [ ] Unit, e2e, build, lint, and the replay harness all still clean.
- [ ] [plan.md](plan.md) and [the change doc](../../../features/phase-1-audio-path.md) updated, with
      Phase 1's real-call criterion still explicitly open.
