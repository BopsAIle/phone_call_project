# Phase 2 — The agent hears

- **Parent plan:** [../../2026-08-19-ai-receptionist-phone-booking-agent.md](../../2026-08-19-ai-receptionist-phone-booking-agent.md)
- **Branch:** `feat/stt-streaming`
- **Status:** not started
- **Depends on:** [Phase 1](../phase-1-audio-path/plan.md)
- **Unblocks:** [Phase 3](../phase-3-llm-tts-loop/plan.md)

## Objective

Turn the caller's audio into live text. Open an OpenAI realtime transcription session per call, feed
it the Twilio audio, handle partial and final transcripts, detect when the caller starts and stops
speaking, and persist every final utterance.

This phase also produces the **speech-started** signal that Phase 3 needs for barge-in. That signal
matters as much as the transcript itself — design for it now rather than bolting it on.

## Demo criterion

Place a real call, talk, and watch final transcripts appear in the server log within roughly a second
of finishing each sentence, with matching `Utterance` rows (`role = CALLER`) in Postgres.

## Scope

**In:** `OpenAiRealtimeSttService` implementing `SttProvider`, audio format conversion into the STT
session, transcript event handling, `Utterance` persistence, reconnection.

**Out:** the LLM, any spoken response, language detection (Phase 5 — pass a fixed locale for now).

## Detailed design

### Session lifecycle

One OpenAI WebSocket per call, opened on Twilio's `start` and closed on `stop`. Do not pool or share
sessions across calls: transcription sessions carry per-conversation audio state, and crossing
callers would be both wrong and a privacy breach.

Connect with `Authorization: Bearer ${OPENAI_API_KEY}`.

> **Confirm at implementation time.** The exact realtime WebSocket URL and the GA `turn_detection`
> shape were not pinned down during planning. Resolve both against the current API reference in the
> first hour of this phase and record the answer here — do not copy a beta-era snippet from a blog
> post, since the GA API rejects the old flat parameter names outright.

### Session configuration

```json
{
  "type": "session.update",
  "session": {
    "type": "transcription",
    "audio": {
      "input": {
        "format": { "type": "audio/pcm", "rate": 24000 },
        "transcription": { "model": "gpt-live-transcribe" },
        "turn_detection": { "type": "server_vad" }
      }
    }
  }
}
```

Two things to note. The GA API requires this **nested** `session.audio.input` object and rejects the
older flat `input_audio_format` / `input_audio_transcription` keys. And `audio/pcm` @ 24000 is the
documented, verified format — we deliberately convert rather than gamble on the undocumented mu-law
enum string (see the parent plan's "Known unknown"). We already own the codec, so the conversion is
nearly free.

Let **server-side VAD** do turn detection. Writing our own energy-gate endpointing means tuning
thresholds against phone noise, hold music, and background chatter — a solved problem we should not
re-solve.

### Audio path into the session

```
Twilio media frame (base64)
  → base64 decode           → 160 bytes mu-law, 8 kHz
  → mulaw.decode            → Int16 PCM,  8 kHz
  → resampler.upsample(3x)  → Int16 PCM, 24 kHz
  → base64 encode           → input_audio_buffer.append
```

Every step reuses Phase 1 code; this phase adds no new DSP.

**Batch before sending.** A 20 ms frame is a tiny WebSocket message, and sending 50 per second per
call is needless overhead. Accumulate ~100 ms (five frames) per `append`. That adds at most 100 ms
of latency against a ~500 ms VAD endpointing window — a good trade. Do not batch much beyond that,
or barge-in starts to feel sluggish.

### Events consumed

| Event | Use |
| --- | --- |
| `conversation.item.input_audio_transcription.delta` | partial text → `onPartial`, log only |
| `conversation.item.input_audio_transcription.completed` | final text → `onFinal`, persist `Utterance` |
| `input_audio_buffer.speech_started` | → `onSpeechStarted`; **the barge-in trigger for Phase 3** |
| `input_audio_buffer.speech_stopped` | → `onSpeechStopped`; starts the latency clock for the reply |
| `error` | log with the call id, then apply the reconnection policy |

Confirm the two `speech_*` names against the GA reference alongside the URL above.

Persist only **final** transcripts as `Utterance` rows. Partials revise themselves several times per
sentence and would turn the table into noise.

### Timing and latency

Record `speech_stopped` as `t0` on the session. Phase 3 measures first-token and first-audio against
it, and the difference lands in `Utterance.latencyMs`. Capturing `t0` here means Phase 3 does not
have to reach back into STT internals.

Compute `startMs` / `endMs` relative to the call's `startedAt` so a transcript can be replayed
against recorded audio later.

### Reconnection

If the OpenAI socket drops mid-call, **do not drop the phone call.** Reconnect with a short backoff
(200 ms, 500 ms, 1 s; three attempts), replay the session config, and continue. Buffer inbound
Twilio audio during the gap up to a small cap (~2 s) and discard beyond that — stale audio
transcribed late is worse than a missing word.

If all attempts fail, surface it to the session so Phase 6 can speak a graceful apology rather than
leaving dead air.

## Implementation steps

1. [ ] `npm i openai` (also used in Phase 3; the raw `ws` client may be simpler for the realtime
   socket — decide once the URL is confirmed).
2. [ ] Confirm the realtime WebSocket URL, `turn_detection` shape, and `speech_*` event names
   against the current API reference. **Update this document with what you find.**
3. [ ] `src/stt/openai-realtime-stt.service.ts` implementing `SttProvider` from Phase 0.
4. [ ] Connection setup, `session.update`, and a typed event dispatcher.
5. [ ] Audio conversion + 100 ms batching feeding `input_audio_buffer.append`.
6. [ ] Wire `SttSession` into `MediaStreamGateway`: create on `start`, `pushAudio` on `media`,
   `close` on `stop`.
7. [ ] Persist `Utterance` rows on final transcripts; log partials at `debug` only.
8. [ ] Reconnection with backoff and the bounded audio buffer.
9. [ ] Extend the replay harness to print the transcript it produced, so a WAV fixture becomes a
   repeatable accuracy check.
10. [ ] Real call; confirm the demo criterion.

## Files created or changed

- `src/stt/openai-realtime-stt.service.ts`, `src/stt/stt.module.ts`,
  `src/stt/realtime-events.types.ts` — new.
- `src/telephony/media-stream.gateway.ts` — create, feed, and close the STT session.
- `test/harness/replay.ts` — print transcripts.
- `src/stt/*.spec.ts` — new.

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

- **Copying beta-era snippets.** The GA API rejects flat `input_audio_format`. Most blog posts and
  tutorials online predate the change. Trust the current reference only.
- **8 kHz phone audio is genuinely hard.** Accuracy will be lower than your microphone tests suggest.
  Judge quality on real calls, not on studio-quality fixtures.
- **Partial transcripts are not stable.** Never persist them and never feed them to the LLM; they
  revise mid-sentence.
- **Backpressure.** If the OpenAI socket stalls, the `append` queue grows unboundedly. Cap it and
  drop the oldest audio rather than letting memory climb across concurrent calls.
- **Privacy.** Transcripts are personal data from this phase onward. Do not log full text at `info`
  in production, and note that Phase 6 adds the retention policy.

## Exit checklist

- [ ] Demo criterion demonstrated on a real call.
- [ ] The confirmed WebSocket URL, `turn_detection` shape, and event names are recorded in this file.
- [ ] `onSpeechStarted` fires reliably — Phase 3's barge-in depends entirely on it.
- [ ] Reconnection verified by killing the socket mid-call.
- [ ] `npm run build` and `npm run lint` clean.
