# Phase 1 — Browser dev client

- **Parent plan:** [plan.md](plan.md) (Phase 1 — Audio path)
- **Branch:** `feat/browser-dev-client`
- **Status:** implemented; verified without a microphone. The three checks that need one are listed
  as outstanding in the exit checklist below.
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
than a synthetic tone sweep, the 20 ms frame clock under live timing, session lifecycle, `Call` row
writes, and — because the page echoes marks the way Twilio does — the gateway's `mark` round trip,
which otherwise stays untested until the first real call.

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
          ◄── mark  → echo back once the audio queued before it has played
          ◄── clear → stop queued sources, reset cursor    (Phase 3 barge-in)
```

### `mark` is echoed, not logged

`mark` is the one place where "just log it" would quietly stop the browser being a Twilio stand-in.
Twilio does not consume a `mark` — it **sends it back** once the audio queued ahead of it has
finished playing, which is how the server learns an utterance actually reached the caller.
[media-stream.gateway.ts](../../../../src/telephony/media-stream.gateway.ts) already has the `mark`
case waiting for that echo, and `markMessage` in
[twilio-frames.ts](../../../../src/telephony/twilio-frames.ts) already exists to send it.

So the page holds the mark name against the last `AudioBufferSourceNode` scheduled before it and
sends `{ event: 'mark', streamSid, mark: { name } }` on that node's `onended`. Without this the
server's `mark` path stays unexercised right up until the first real phone call — which is exactly
the code this client exists to de-risk. `clear` must drop pending marks along with the queued audio,
the same way Twilio discards both.

### Sharing the codec

The browser must **not** carry its own mu-law implementation. A subtly different copy would let the
loopback appear to work while masking exactly the codec bug this is meant to catch — the encoder and
decoder would simply be wrong in agreement.

`esbuild` bundles `client/main.ts`, which imports
[mulaw.codec.ts](../../../../src/audio/mulaw.codec.ts) directly, so the page runs the same
`pcm16ToMulaw` and the same 256-entry decode table as the gateway and the harness.

One change is needed there: widen `decodeMulaw(mulaw: Buffer)` to `Uint8Array`. `Buffer` *is* a
`Uint8Array`, the body only uses `.length` and index access, and the widening is variance-safe — every
existing caller compiles untouched. It is worth doing on its own merits: from Phase 2 the server
decodes real Twilio audio with this exact function, so having the browser call it too means the
interactive session exercises the production path rather than a parallel copy of it.

**Encode cannot be shared, and the reason is the function body, not the return type.** `encodeMulaw`
allocates with `Buffer.allocUnsafe`, which does not exist in a browser bundle at all — changing the
signature to return `Uint8Array` would not unblock sharing, it would just move the failure to
runtime. So the browser loops the scalar `pcm16ToMulaw` itself. That is the right trade: the scalar
function is the part that could be subtly wrong, and a four-line loop around it cannot meaningfully
diverge. Say this in the code, because the return type looks like the obstacle and is not.

This also means the bundle stays clean only because esbuild tree-shakes `encodeMulaw` away when
`client/main.ts` imports just `pcm16ToMulaw` and `decodeMulaw`. That works, but nothing enforces it,
and if it ever regresses the page dies with `Buffer is not defined` at module load — before any of
our code runs, so the console gives no hint about audio at all. `build:client` therefore ends with a
`Buffer` grep over the output bundle.

The AudioWorklet is a second esbuild entry point. It only buffers 128-sample blocks into 160-sample
frames, so it needs no shared code — worklets run in their own global scope and cannot import from
the main bundle anyway.

### Sample rate

`new AudioContext({ sampleRate: 8000 })`, with `createMediaStreamSource` resampling the microphone
into it. This is why the page needs **no new resampling**: the existing `Downsampler` is fixed at 3:1
and cannot do the 48 kHz → 8 kHz a typical capture device would otherwise require.

If a browser refuses the rate, check `ctx.sampleRate !== 8000` and fail with a message that names the
problem. Silently sending wrong-rate audio would sound like a codec fault and waste an afternoon.

### Float32 ↔ Int16 — the one piece of unshared arithmetic

The Web Audio API works in Float32 in `[-1, 1]`; the codec works in Int16. So the page does add two
numeric conversions, on capture and on playback, and they are the only maths in the path that is
neither shared with the server nor covered by a test.

They deserve the same suspicion the codec gets, for the same reason. If the two directions disagree —
different scale factors, or a missing clamp on the way in — the loopback still *sounds* right,
because the second conversion undoes the first. The error only appears in Phase 2, when the audio
goes to STT instead of back to your ears, and it will look like a bad STT model. That is the
wrong-in-agreement failure the codec section exists to prevent, one layer further out.

Pin both directions to a single constant and write them next to each other:

```ts
const FULL_SCALE = 32768;

// capture: clamp first — Web Audio can hand back values outside [-1, 1]
const i16 = Math.max(-FULL_SCALE, Math.min(FULL_SCALE - 1, Math.round(f32 * FULL_SCALE)));

// playback
const f32 = i16 / FULL_SCALE;
```

The clamp is not optional. `Math.round(1.0 * 32768)` is `32768`, which overflows Int16 and wraps to
`-32768` — a full-scale positive sample becomes full-scale negative, and it crackles only on the
loudest peaks.

### Playback

Keep a scheduling cursor in `AudioContext` time and schedule each decoded frame at
`max(cursor, now + cushion)`, advancing the cursor by the buffer duration. Hold the live
`AudioBufferSourceNode`s in a set so `clear` can stop them — that set is what makes Phase 3's
barge-in testable here rather than only on a real call.

### Keeping the client out of the server build

**Do this before writing a line of `client/`.** Dropping browser TypeScript into the repo root
breaks `npm run build`, and the way it breaks is not obvious from the error.

[tsconfig.json](../../../../tsconfig.json) has no `include`, and
[tsconfig.build.json](../../../../tsconfig.build.json) excludes only `node_modules`, `test`, `dist`,
`prisma`, and specs. So `client/*.ts` becomes a **server** compile input, with two consequences:

- `tsc` infers `rootDir` from the longest common path of its inputs. Today that is `src/`, so the
  entry point lands at `dist/main.js`. Add `client/` and the common path becomes the repo root — the
  output moves to `dist/src/main.js`, and both `npm run start:prod` (`node dist/main`) and
  `nest start` stop finding it. This is a **production** break caused by a dev-only file, which is
  the opposite of what this client is for.
- The worklet's globals — `registerProcessor`, `AudioWorkletProcessor` — are not in `lib.dom` and
  the build fails on TS2304 before it gets that far.

The fix is three small files:

| File | Change |
| --- | --- |
| [tsconfig.build.json](../../../../tsconfig.build.json) | add `"client"` to `exclude`, and set `"rootDir": "src"` explicitly so the layout can never drift again |
| [tsconfig.json](../../../../tsconfig.json) | add `"exclude": ["client", "dist", "node_modules"]`, so the editor and eslint's `projectService` do not load browser files into the server project |
| `client/tsconfig.json` | new: `"lib": ["ES2023", "DOM", "DOM.Iterable"]`, `"types": ["audioworklet"]`, `"module": "esnext"`, `"moduleResolution": "bundler"`, `"noEmit": true` |

`module`/`moduleResolution` must be overridden there. The root config is `nodenext`, which requires
explicit `.js` extensions on relative ESM imports — so `import { ... } from '../src/audio/mulaw.codec'`
type-checks only under `bundler`. esbuild itself does not care, which is what makes this the sort of
error you meet later than you would like.

## Implementation steps

1. [x] **Fence `client/` off from the server build first** — the three tsconfig changes in *Keeping
   the client out of the server build* above. Prove it with `npm run build` and confirm the entry
   point is still `dist/main.js`, **not** `dist/src/main.js`. Doing this after writing the client
   means debugging a broken production build and a new audio path at the same time.
2. [x] `npm i -D esbuild @types/audioworklet`; add `build:client` and `build:client:watch` scripts,
   ending in a `Buffer` grep over the bundle (see *Sharing the codec*). Keep them out of
   `npm run build`, which stays server-only.
3. [x] Widen `decodeMulaw` to accept `Uint8Array` in
   [mulaw.codec.ts](../../../../src/audio/mulaw.codec.ts). No caller changes. Note in the comment
   there why `encodeMulaw` cannot follow — `Buffer.allocUnsafe`, not the return type.
4. [x] `client/capture-worklet.ts` — 128 → 160 sample framing on the audio thread.
5. [x] `client/main.ts`:
   - **SIDs.** Mint a fresh `CallSid` and `streamSid` per call, `CA`/`MZ` + 32 hex, exactly as
     [replay.ts](../../../../test/harness/replay.ts) does. A fixed `CallSid` makes the webhook's
     `upsert` reuse one `Call` row, and the gateway's `endedAt IS NULL` guard then silently skips
     the teardown write on every call after the first — the lifecycle checks below would pass
     against stale data.
   - `POST /twilio/voice` and the `DOMParser` read of `<Stream url>` and the `<Parameter>` values.
   - Capture, Float32 → Int16 with the clamp, `pcm16ToMulaw`, base64, `media` out.
   - Playback: decode, Int16 → Float32, scheduling cursor, live-source set.
   - `mark` echo on the `onended` of the node it was queued behind; `clear` stops queued sources,
     resets the cursor, and drops pending marks.
   - **Hang up** sends `stop` and closes the socket — that is what drives the `Call` row to
     `COMPLETED`, so it is part of the demo criterion, not a nicety.
6. [x] `public/dev-client.html` — the page itself. Committed; the bundle it loads is generated.
7. [x] `src/dev/dev-client.controller.ts` — `GET /dev` serves the HTML, `GET /dev/config` returns
   `{ storeNumber }` from `TWILIO_PHONE_NUMBER` so the page knows what to send as `To`.
8. [x] `src/dev/dev.module.ts`; import it from [app.module.ts](../../../../src/app.module.ts) **only
   when `NODE_ENV !== 'production'`**. Module registration runs before DI, so this reads the raw env
   rather than `ConfigService` — the standard Nest idiom, and worth a comment saying so.
9. [x] [main.ts](../../../../src/main.ts) — `NestFactory.create<NestExpressApplication>` and
   `useStaticAssets` for `public/assets` under the `/dev/assets` prefix. A distinct prefix from the
   controller routes, so static middleware and the router cannot shadow one another.
   **Put this behind the same `NODE_ENV !== 'production'` test as the module.** Gating the module
   alone leaves the bundle served in production: `/dev` would 404 while `/dev/assets/main.js` still
   answered. One environment check, not two that can drift.
10. [x] `.gitignore` — `public/assets/`.
11. [x] Update [plan.md](plan.md) and
    [the change doc](../../../features/phase-1-audio-path.md).

## Files created or changed

- `client/main.ts`, `client/capture-worklet.ts` — new, and deliberately outside both the server
  compile and the `{src,apps,libs,test}` eslint glob. Not for DOM types: `target: ES2023` with no
  explicit `lib` already resolves to `lib.es2023.full.d.ts`, which includes DOM. The reasons are the
  `rootDir` break and the AudioWorklet globals, both above.
- `client/tsconfig.json` — new; owns those two files so the editor and eslint have a project to
  resolve them against.
- [tsconfig.json](../../../../tsconfig.json), [tsconfig.build.json](../../../../tsconfig.build.json)
  — exclude `client`, pin `rootDir` to `src`.
- `public/dev-client.html` — new, committed. `public/assets/` — generated, gitignored.
- `src/dev/dev-client.controller.ts`, `src/dev/dev.module.ts` — new.
- [src/audio/mulaw.codec.ts](../../../../src/audio/mulaw.codec.ts) — `Uint8Array` widening.
- [src/main.ts](../../../../src/main.ts), [src/app.module.ts](../../../../src/app.module.ts) — static
  assets and the dev-only module import, behind one shared `NODE_ENV` check.
- [package.json](../../../../package.json) — `esbuild`, `@types/audioworklet`, `build:client`,
  `build:client:watch`.

## Testing

1. `npm run build && ls dist/main.js` — the server build is unmoved. Run this *before* the browser
   work and again at the end; it is the check that catches the `rootDir` break.
2. `npm run build:client && npm run start:dev`, open `http://localhost:3000/dev` — **`localhost`,
   not a LAN IP** — grant the microphone, click **Call**, and speak.
3. Server log matches the replay harness's sequence, frames in equal to frames out:
   ```
   [TwilioController]   Call cmt… from +1555… to store Placeholder Restaurant
   [MediaStreamGateway] Stream MZ… started for call cmt…
   [MediaStreamGateway] Stream MZ… ended after N frames in, N out
   ```
4. Two consecutive calls each produce their **own** `Call` row, both reaching `COMPLETED` — the SID
   minting check. One row updated twice, or a second row stuck at `IN_PROGRESS`, means the SIDs are
   not fresh per call.
5. `Call` row created by the webhook, `streamSid` filled on `start`, `COMPLETED` after hangup.
6. **`git diff src/telephony/` is empty** — the swap-in readiness check above.
7. Both dev routes are gone under `NODE_ENV=production`: `/dev` **and** `/dev/assets/main.js` return
   404. Checking only the first passes while the bundle is still being served.
8. Regressions: `npx jest` (66), `npm run test:e2e` (4), `npm run build`, `npm run lint`.
9. `npm run replay` still passes — the harness and the browser drive the same endpoint and must not
   have diverged.

## Risks & gotchas

- **Use headphones.** Without them the echo feeds straight back into the microphone and howls within
  a second or two. `echoCancellation: true` in the capture constraints helps and is not a substitute.
- **A dev-only file can break the production build.** The `rootDir` inference above is the whole
  reason step 1 comes first. If `npm run start:prod` ever reports it cannot find `dist/main`, this is
  why — check what `tsc` is including before anything else.
- **`/dev` must never reach production.** It exposes a microphone-capture page and the store number.
  The `NODE_ENV` gate is the control, and it must cover the static assets as well as the module;
  verify by booting with `NODE_ENV=production` and confirming both `/dev` and `/dev/assets/main.js`
  return 404.
- **Serve over `localhost`, not a LAN IP.** `getUserMedia` and `audioWorklet.addModule` both need a
  secure context. `http://localhost:3000` qualifies; `http://192.168.x.x:3000` does not, and the
  failure is `navigator.mediaDevices` being `undefined` — a `TypeError` that never mentions HTTPS.
  Reaching the page from a phone on the same network is the obvious thing to try, and this is what
  stops it.
- **Browser audio flatters Phase 2.** A laptop microphone at 8 kHz is far cleaner than a phone line.
  Do not judge STT accuracy on it — the parent plan already warns that real 8 kHz phone audio is
  genuinely hard, and this page will make it look easy.
- **AudioContext sample-rate support** varies by browser. Chrome, Edge, and Firefox honour 8000. This
  is the one thing that could stop the page working at all somewhere untested.

## Exit checklist

- [x] `git diff src/telephony/` empty — Twilio drops in unchanged.
- [x] `npm run build` still emits `dist/main.js`; `npm run start:prod` boots.
- [x] `/dev` **and** `/dev/assets/main.js` return 404 under `NODE_ENV=production`.
- [x] Unit, e2e, build, lint, and the replay harness all still clean — 66 unit, 4 e2e, 100 frames
      in and 100 out.
- [x] [plan.md](plan.md) and [the change doc](../../../features/phase-1-audio-path.md) updated, with
      Phase 1's real-call criterion still explicitly open.

Outstanding — these three need a microphone and cannot be confirmed from a terminal:

- [ ] Demo criterion demonstrated in the browser.
- [ ] The gateway's `mark` path was exercised by the browser's echo, not just by unit tests.
- [ ] Two calls in a row produce two distinct `Call` rows, both `COMPLETED`.
