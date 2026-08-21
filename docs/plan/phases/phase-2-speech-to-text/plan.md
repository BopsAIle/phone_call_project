# Phase 2 — The agent hears

- **Parent plan:** [../../2026-08-19-ai-receptionist-phone-booking-agent.md](../../2026-08-19-ai-receptionist-phone-booking-agent.md)
- **Branch:** `feat/stt-streaming`
- **Status:** in progress
- **Depends on:** [Phase 1](../phase-1-audio-path/plan.md)
- **Unblocks:** [Phase 3](../phase-3-llm-tts-loop/plan.md)

## Objective

Turn the caller's audio into live text. Open an OpenAI realtime transcription session per call, feed
it the Twilio audio, handle partial and final transcripts, detect when the caller starts and stops
speaking, and persist every final utterance.

This phase also produces the **speech-started** signal that Phase 3 needs for barge-in. That signal
matters as much as the transcript itself — design for it now rather than bolting it on.

## Demo criterion

Talk, and watch final transcripts appear in the server log within roughly a second of finishing each
sentence, with matching `Utterance` rows (`role = CALLER`) in Postgres.

**The gate for this phase is the browser dev client**, not a real call — the Twilio number is still
blocked, exactly as it was at the end of Phase 1, and gating on something outside our control would
stall the project rather than protect it. A real call remains the honest final proof and is carried
forward as an open item alongside Phase 1's.

Keep Phase 1's warning in view when judging the result: **a laptop microphone flatters STT.** It is
far cleaner than an 8 kHz phone line. The dev client proves the *wiring* — session opens, audio
converts, events dispatch, rows land. It does not prove accuracy for a real caller.

## Scope

**In:** `OpenAiRealtimeSttService` implementing `SttProvider`, audio format conversion into the STT
session, transcript event handling, `Utterance` persistence, reconnection.

**Out:** the LLM, any spoken response, language detection (Phase 5 — pass a fixed locale for now).

## Decisions taken at the start of the phase

| Decision | Choice |
| --- | --- |
| Done gate | Replay harness transcript + browser dev client. Real-call E2E carried forward as an open item, exactly as in Phase 1 — the Twilio number is still blocked. |
| STT session ownership | `src/conversation/` is introduced **now**, not in Phase 3. `CallSession` owns the STT session; the gateway stays pure transport. Phase 3 then extends a layer that exists rather than re-wiring the gateway a second time. |
| The Phase 1 echo | **Kept.** The `media` handler *forks* to STT rather than being replaced. The echo is the only outbound audio until Phase 3, and removing it now makes the dev client and the harness output silent — deleting the feedback signal in the middle of the phase that needs it. Phase 3 removes it when TTS takes over. |
| Realtime client | Raw `ws`, already a dependency, with our own zod-typed event union. No `openai` dependency this phase: reconnection, batching, and backpressure are precisely what this phase must own, and an SDK wrapping them would have to be unwrapped. |
| `Utterance.endMs` | Additive nullable migration. `SttSession.onFinal` already promises `{ startMs, endMs }` but the Phase 0 schema has `startMs` only. |

## Detailed design

### Session lifecycle

One OpenAI WebSocket per call, opened on Twilio's `start` and closed on `stop`. Do not pool or share
sessions across calls: transcription sessions carry per-conversation audio state, and crossing
callers would be both wrong and a privacy breach.

### Confirmed API shape

Verified against the current OpenAI reference on 2026-08-21, resolving the "confirm at implementation
time" block this document previously carried. Do not substitute remembered or blog-post values — the
GA API rejects the beta-era flat keys outright.

**Connect:** `wss://api.openai.com/v1/realtime?intent=transcription`, with a single required header,
`Authorization: Bearer ${OPENAI_API_KEY}`. **No `OpenAI-Beta` header** — it was a beta requirement
and is not sent on GA. `OpenAI-Safety-Identifier` is optional.

**Session configuration:**

```json
{
  "type": "session.update",
  "session": {
    "type": "transcription",
    "audio": {
      "input": {
        "format": { "type": "audio/pcm", "rate": 24000 },
        "transcription": {
          "model": "gpt-live-transcribe",
          "languages": ["en"],
          "delay": "low"
        },
        "turn_detection": {
          "type": "server_vad",
          "threshold": 0.5,
          "prefix_padding_ms": 300,
          "silence_duration_ms": 500
        }
      }
    }
  }
}
```

The GA API requires this **nested** `session.audio.input` object and rejects the older flat
`input_audio_format` / `input_audio_transcription` keys. `audio/pcm` @ 24000 is the documented,
verified format — we deliberately convert rather than gamble on the undocumented mu-law enum string
(see the parent plan's "Known unknown"). We already own the codec, so the conversion is nearly free.

Three fields the original draft of this plan did not know about:

- **`languages`** — an *array* of ISO 639-1 codes. `gpt-live-transcribe` uses this rather than the
  singular `language` of older models. It is the Phase 5 locale hook; `setLocale()` re-sends
  `session.update`.
- **`delay`** — trades latency against word error rate. Start at `"low"`. It is a real tuning knob
  for the 1.5 s budget, and 8 kHz phone audio may well want it raised.
- **`keywords`** and **`prompt`** — vocabulary biasing. Not used in Phase 2, but noted for Phase 4,
  where the store name and menu terms are exactly what they exist for.

`create_response` / `interrupt_response` are conversation-mode only. Omit them here.

**Appending audio:** `{ "type": "input_audio_buffer.append", "audio": "<base64 PCM16LE>" }`.

Let **server-side VAD** do turn detection. Writing our own energy-gate endpointing means tuning
thresholds against phone noise, hold music, and background chatter — a solved problem we should not
re-solve. Note that in a transcription session VAD only controls how audio is *chunked*; it does not
trigger a response the way it does in a speech-to-speech session.

**Two claims to verify by logging the first raw frames of the first live session**, rather than by
trusting this document: the `?intent=transcription` query form, and the presence of
`audio_start_ms` / `audio_end_ms` on the VAD events. Both have a graceful fallback — the session type
is also set by `session.update`, and timing falls back to the local audio clock below. If either
differs in practice, fix the code *and* this file in the same commit.

### Audio path into the session

```
Twilio media frame (base64)
  → base64 decode           → 160 bytes mu-law, 8 kHz
  → decodeMulaw()           → Int16 PCM,  8 kHz   (480 samples once upsampled)
  → upsampler.process()     → Int16 PCM, 24 kHz
  → int16ToLe()             → 960 bytes, little-endian
  → accumulate to ~100 ms
  → base64 encode           → input_audio_buffer.append
```

Every DSP step reuses Phase 1 code; this phase adds no new DSP. The one genuinely new piece is
`int16ToLe`, which is byte layout rather than signal processing.

**One `Upsampler` per call**, with `process()` called per 20 ms frame — not per batch, and never a
fresh instance. The filter is 48 taps, far longer than a frame, so its history has to survive across
frames; a filter that restarts each frame rings at every boundary, which is a click 50 times a
second. The resampler's own header comment says this; it is repeated here because this phase is its
first caller.

**Batch before sending.** A 20 ms frame is a tiny WebSocket message, and sending 50 per second per
call is needless overhead. Accumulate ~100 ms (five frames, 4800 bytes) per `append`. That adds at
most 100 ms of latency against a ~500 ms VAD endpointing window — a good trade. Do not batch much
beyond that, or barge-in starts to feel sluggish.

Do **not** reuse `FrameBuffer` for that batching, despite the shape fitting. It is documented as one
instance per *outbound* stream, and its `flush()` pads with `MULAW_SILENCE` (`0xFF`) — correct for a
short Twilio frame, meaningless for PCM16. A `Buffer[]` accumulator with a byte counter is ten lines
and says what it means.

### Events consumed

| Event | Payload field | Use |
| --- | --- | --- |
| `conversation.item.input_audio_transcription.delta` | `delta` | partial text → `onPartial`, `debug` log only |
| `conversation.item.input_audio_transcription.completed` | `transcript` | final text → `onFinal`, persist `Utterance` |
| `input_audio_buffer.speech_started` | `audio_start_ms` | → `onSpeechStarted`; **the barge-in trigger for Phase 3** |
| `input_audio_buffer.speech_stopped` | `audio_end_ms` | → `onSpeechStopped`; starts the latency clock for the reply |
| `session.created` / `session.updated` | — | confirms the session was accepted; log once |
| `error` | `error.message` | log with the call id, then apply the reconnection policy |

Persist only **final** transcripts as `Utterance` rows. Partials revise themselves several times per
sentence and would turn the table into noise.

### Timing and latency

Record `speech_stopped` as `t0` on the session. Phase 3 measures first-token and first-audio against
it, and the difference lands in `Utterance.latencyMs`. Capturing `t0` here means Phase 3 does not
have to reach back into STT internals.

`startMs` / `endMs` come from `audio_start_ms` / `audio_end_ms` on the VAD events. Those are the
model's view of its own buffer and are the only accurate boundary available: by the time we *receive*
`speech_stopped`, at least `silence_duration_ms` of wall clock has already elapsed, so timestamping
on arrival would be systematically late by half a second.

If those fields turn out to be absent, fall back to a local **audio clock** — `framesReceived × 20 ms`,
anchored at the Twilio `start` frame. Use that rather than `Date.now()`: it is monotonic in the
medium being measured, and it is what aligns with recorded audio on replay.

> **Deviation from the parent plan, deliberate.** The parent says "relative to the call's
> `startedAt`". `Call.startedAt` is written by the voice webhook, before the WebSocket exists, so it
> sits an unknown gap ahead of the first audio sample. Anchoring at the `start` frame is what makes
> `startMs` mean "offset into the audio". The offset between the two is logged once per call.

### Reconnection

If the OpenAI socket drops mid-call, **do not drop the phone call.** Reconnect with a short backoff
(200 ms, 500 ms, 1 s; three attempts), replay the session config, and continue. Buffer inbound
Twilio audio during the gap up to a small cap (~2 s) and discard beyond that — stale audio
transcribed late is worse than a missing word.

If all attempts fail, surface it to the session so Phase 6 can speak a graceful apology rather than
leaving dead air. In this phase that is a loud `error` log and a flag on the session.

Apply the same bounded-queue rule when the socket is open but **stalled**: check `bufferedAmount`
before appending, and drop the oldest audio past the cap. Unbounded growth across concurrent calls
is the memory leak this phase could most plausibly ship.

### Locale

Pass `DEFAULT_LOCALE` from config as `languages: [locale]`. `setLocale()` re-sends `session.update`.
Phase 5 owns detection and locking; nothing here should try to be clever about it.

## Implementation steps

1. [x] Confirm the realtime WebSocket URL, `turn_detection` shape, and `speech_*` event names
   against the current API reference. **Update this document with what you find.**
2. [ ] `src/audio/pcm.ts` — `int16ToLe` / `leToInt16`, with explicit `writeInt16LE` rather than a
   `Buffer.from(view.buffer)` cast, which silently depends on host endianness. Same discipline as
   `test/harness/wav.ts`. `leToInt16` has no caller until Phase 3 reads OpenAI's PCM back; write and
   test both directions now.
3. [ ] `endMs Int?` on `Utterance`; `prisma migrate dev --name utterance_end_ms`.
4. [ ] `src/stt/realtime-events.types.ts` — zod discriminated union of the server events plus the two
   outbound builders. Model it directly on `src/telephony/twilio-frames.ts`: `parseServerEvent()`
   returns `null` for anything unrecognised and **never throws**, for the same reason as Twilio —
   OpenAI adds event types, and an exception inside a socket `message` handler ends a live call.
5. [ ] `src/stt/openai-realtime-stt.service.ts` implementing `SttProvider` from Phase 0: connection
   setup, `session.update`, typed event dispatch.
6. [ ] Audio conversion + 100 ms batching feeding `input_audio_buffer.append`.
7. [ ] `src/conversation/` — `CallSession` (upsampler, STT session, audio clock, `Utterance` writes)
   and `ConversationService` (registry keyed by `streamSid`).
8. [ ] Wire `MediaStreamGateway` → `ConversationService`: create on `start`, `pushAudio` on `media`
   **alongside the existing echo**, close on `stop` and in `teardown`.
9. [ ] Persist `Utterance` rows on final transcripts; log partials at `debug` only.
10. [ ] Reconnection with backoff and the bounded audio buffer.
11. [ ] Extend the replay harness to print the transcript it produced, so a WAV fixture becomes a
    repeatable accuracy check.
12. [ ] Record a fixture WAV of a spoken booking request and assert its keywords.
13. [ ] Browser dev client run — the done gate for this phase. Real call when the number unblocks.

## Files created or changed

- `src/stt/openai-realtime-stt.service.ts`, `src/stt/stt.module.ts`,
  `src/stt/realtime-events.types.ts` — new.
- `src/audio/pcm.ts` — new.
- `src/conversation/call-session.ts`, `conversation.service.ts`, `conversation.module.ts` — new.
  Deliberately introduced this phase rather than Phase 3; see the decisions table above.
- `src/telephony/media-stream.gateway.ts` — hand audio to `ConversationService`; keep the echo.
- `prisma/schema.prisma` + a migration — `Utterance.endMs`.
- `test/harness/replay.ts` — print transcripts.
- `src/stt/*.spec.ts`, `src/audio/pcm.spec.ts`, `src/conversation/*.spec.ts` — new.

## Testing

- **Unit:** the event dispatcher maps each server event to the right callback, including an unknown
  event type (log and ignore, never throw — an unhandled event must not kill a live call).
- **Unit:** the batcher emits at the configured interval and flushes any remainder on `close`.
- **Unit:** reconnection backoff fires the expected number of attempts and re-sends `session.update`.
- **Integration (harness):** replay a fixture WAV of a spoken booking request and assert the final
  transcript contains the expected keywords. Cheap, repeatable, no phone call.
- **Integration:** replay with the OpenAI socket forcibly closed mid-stream; the session reconnects
  and the call survives.
- **E2E:** real call, transcripts in the log and in `Utterance`.

## Risks & gotchas

- **Copying beta-era snippets.** The GA API rejects flat `input_audio_format`, and the
  `OpenAI-Beta: realtime=v1` header is no longer sent. Most blog posts and tutorials online predate
  both changes. Trust the current reference only — that is why the confirmed shape is written out
  above in full rather than linked.
- **`languages`, not `language`.** `gpt-live-transcribe` takes an array. The singular form belongs to
  older models and is the kind of near-miss that fails as a validation error at connect time, on a
  live call, rather than in a test.
- **8 kHz phone audio is genuinely hard.** Accuracy will be lower than your microphone tests suggest.
  Judge quality on real calls, not on studio-quality fixtures.
- **Partial transcripts are not stable.** Never persist them and never feed them to the LLM; they
  revise mid-sentence.
- **Backpressure.** If the OpenAI socket stalls, the `append` queue grows unboundedly. Cap it and
  drop the oldest audio rather than letting memory climb across concurrent calls.
- **Privacy.** Transcripts are personal data from this phase onward. Do not log full text at `info`
  in production, and note that Phase 6 adds the retention policy.

## Exit checklist

- [ ] Demo criterion demonstrated through the browser dev client.
- [x] The confirmed WebSocket URL, `turn_detection` shape, and event names are recorded in this file.
- [ ] `?intent=transcription` and `audio_start_ms` / `audio_end_ms` confirmed against a real session's
      raw frames, and this file corrected if they differ.
- [ ] `onSpeechStarted` fires reliably — Phase 3's barge-in depends entirely on it.
- [ ] Reconnection verified by killing the socket mid-call.
- [ ] Replay harness prints a transcript from a spoken fixture.
- [ ] Change doc at `docs/features/phase-2-speech-to-text.md`, linked from `docs/README.md`.
- [ ] `npm run build` and `npm run lint` clean.
- [ ] **Carried forward:** real-call E2E, still blocked on a purchased Twilio number.
