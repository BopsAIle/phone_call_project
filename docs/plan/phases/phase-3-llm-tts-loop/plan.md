# Phase 3 — The agent speaks

- **Parent plan:** [../../2026-08-19-ai-receptionist-phone-booking-agent.md](../../2026-08-19-ai-receptionist-phone-booking-agent.md)
- **Branch:** `feat/llm-tts-loop`
- **Status:** not started
- **Depends on:** [Phase 2](../phase-2-speech-to-text/plan.md)
- **Unblocks:** [Phase 4](../phase-4-booking-slots/plan.md)

## Objective

Close the loop. Feed transcripts to the LLM, stream its reply into TTS sentence by sentence, convert
the audio to Twilio's format, and play it back — interruptibly.

After this phase the agent holds a real conversation. It does not yet collect bookings; that is
Phase 4. The goal here is that the *mechanics* of talking feel right: fast enough, and interruptible.

## Demo criterion

Call in and have a genuine back-and-forth conversation. Interrupt the agent mid-sentence and it stops
speaking within ~200 ms and listens. Time from you finishing a sentence to hearing the first word of
the reply is under 1.5 s.

## Scope

**In:** `OpenAiLlmService`, `OpenAiTtsService`, the sentence chunker, the outbound audio pipeline,
the turn state machine, barge-in, the greeting with disclosure, latency instrumentation.

**Out:** booking tools and slot tracking (Phase 4), German (Phase 5). English only, chatting only.

## Detailed design

### Turn state machine

`CallSession` owns one state:

```
GREETING ──► LISTENING ──► THINKING ──► SPEAKING ──► LISTENING
                  ▲                         │
                  └──────── barge-in ───────┘
```

Every transition is triggered by an STT event or a stream completing. Keeping this explicit is what
stops the classic voice-agent failure where two replies play over each other because a late tool
result arrived after the caller already moved on.

### Sentence chunking — the latency trick that matters most

Do **not** wait for the full LLM completion before starting TTS. Accumulate token deltas and flush a
chunk as soon as you hit a sentence boundary (`.`, `?`, `!`, newline) or ~80 characters, whichever
comes first. The first sentence goes to TTS while the model is still writing the second.

This alone turns a ~2.5 s wait into ~0.8 s, and it is the difference between an agent that feels
responsive and one that feels broken.

Guard the boundary regex against decimals and abbreviations ("7.30", "Dr.") with a minimum chunk
length. Spoken replies are short, so a simple rule is sufficient — do not import a sentence
tokeniser for this.

### Outbound audio pipeline

```
LLM sentence
  → POST /v1/audio/speech  (model gpt-4o-mini-tts, response_format "pcm", streamed)
  → Int16 PCM, 24 kHz mono, headerless, little-endian
  → resampler.downsample(3x)   ← LOW-PASS FIRST (Phase 1)
  → mulaw.encode               → 8 kHz mu-law
  → slice into 160-byte frames
  → base64 → { event: "media", streamSid, media: { payload } }
  → { event: "mark", streamSid, mark: { name } } after each chunk
```

Request `response_format: "pcm"` — it is raw and headerless, so there is no WAV header to strip and
no MP3 decode step. It is also the format OpenAI recommends for lowest latency.

Set `instructions` to shape delivery: for English, something like *"Speak in a warm, professional,
unhurried tone, like a friendly restaurant host."* Phase 5 swaps this per locale. Voice: `marin`.

### Barge-in

The behaviour that separates a usable phone agent from a demo. On `onSpeechStarted` from STT while
in `SPEAKING`:

1. `abortController.abort()` — cancels both the in-flight LLM stream and the TTS HTTP request.
2. Send `{ event: 'clear', streamSid }` — flushes audio Twilio has buffered but not yet played.
3. Drop any queued sentences that have not been synthesised.
4. Clear `pendingMarks` and transition to `LISTENING`.

Step 2 is essential and easy to forget: aborting your own streams does nothing about the seconds of
audio already handed to Twilio. Without `clear`, the agent keeps talking over the caller from
Twilio's buffer while your logs insist it stopped.

Track `pendingMarks: Set<string>`; each outbound chunk sends a `mark`, and Twilio echoes it when that
audio finishes playing. When the set empties, the agent has genuinely stopped speaking — this is the
only reliable signal, since "I sent the last frame" is not the same as "the caller heard it".

The `AbortSignal` threaded through `LlmProvider.respond` and `TtsProvider.synthesize` in Phase 0 is
what makes all of this a few lines instead of a refactor.

### Greeting and disclosure

On Twilio's `start`, synthesise and play the greeting immediately — silence at pickup makes callers
hang up or say "hello?" repeatedly.

The greeting **must state that the caller is speaking to an automated assistant and that the call is
transcribed**, before anything is collected. This is a GDPR/TTDSG requirement for German callers and
simple courtesy for everyone. Building it in now is trivial; retrofitting consent onto transcripts
already stored is not. Phase 5 makes it bilingual.

Consider pre-synthesising the greeting once and caching the mu-law bytes on disk. It never changes,
it is on the critical path for first impressions, and a cached greeting still plays when OpenAI is
down — which Phase 6 relies on.

### System prompt (conversational baseline)

Short, because every token is latency. It should establish: the role and store name; **replies of one
or two sentences, because this is a phone call**; no invented menu items, prices, or opening hours;
and — even before booking exists — that the agent cannot see the reservation book and must never
confirm a table.

That last constraint goes in now rather than in Phase 4. If the agent learns to say "yes, 8pm works"
during casual testing, that behaviour is exactly what Phase 4 has to unlearn.

### Latency instrumentation

Record per turn, all relative to `speech_stopped` (`t0` from Phase 2): first LLM token, first TTS
byte, first frame written to Twilio. Store the total in `Utterance.latencyMs` for the agent turn and
log the breakdown. Budget: VAD ~500 ms, LLM first token ~400 ms, TTS first audio ~300 ms.

Without this you will not know which of the three stages to attack when the agent feels slow, and
guessing wastes days.

## Implementation steps

1. [ ] `src/llm/openai-llm.service.ts` implementing `LlmProvider` — streaming, `AbortSignal`, no
   tools yet.
2. [ ] `src/llm/sentence-chunker.ts` + unit tests.
3. [ ] `src/llm/prompts/receptionist.en.ts` — the baseline system prompt.
4. [ ] `src/tts/openai-tts.service.ts` implementing `TtsProvider` — streamed PCM in, mu-law frames
   out, abortable.
5. [ ] `src/conversation/call-session.ts` — state machine, conversation history, turn orchestration.
6. [ ] `src/conversation/conversation.service.ts` — session registry keyed by `streamSid`.
7. [ ] Wire `MediaStreamGateway` → `ConversationService` (replacing the Phase 1 echo).
8. [ ] Outbound frame writer with `mark` tracking.
9. [ ] Barge-in: abort, `clear`, queue drop, `pendingMarks` reset.
10. [ ] Greeting with disclosure, played on `start`; optional pre-synthesis cache.
11. [ ] Latency instrumentation and `Utterance` rows for `role = AGENT`.
12. [ ] Extend the replay harness to inject a mid-reply interruption so barge-in is testable offline.
13. [ ] Real call; confirm both halves of the demo criterion.

## Files created or changed

- `src/llm/openai-llm.service.ts`, `sentence-chunker.ts`, `prompts/receptionist.en.ts`,
  `llm.module.ts` — new.
- `src/tts/openai-tts.service.ts`, `tts.module.ts` — new.
- `src/conversation/call-session.ts`, `conversation.service.ts`, `conversation.module.ts` — new.
- `src/telephony/media-stream.gateway.ts` — hand audio to `ConversationService`; write outbound
  frames, marks, and clears.
- `test/harness/replay.ts` — interruption injection.

## Testing

- **Unit — sentence chunker:** flushes on `.`/`?`/`!`/newline; does not split "7.30" or "Dr."; flushes
  the remainder at stream end; respects the character cap on a run-on sentence.
- **Unit — state machine:** every transition, including the illegal ones (a reply arriving while
  already `SPEAKING` must be dropped, not queued into an overlap).
- **Unit — barge-in:** given a `speechStarted` during `SPEAKING`, the abort fires, a `clear` is
  written, and the pending queue empties.
- **Unit — TTS pipeline:** a known PCM buffer produces the expected number of 160-byte mu-law frames,
  with a partial trailing frame padded rather than dropped.
- **Integration (harness):** full turn from fixture WAV to output WAV; and an interruption injected
  mid-reply, asserting output stops promptly.
- **E2E:** real call — conversation quality, interruption responsiveness, and measured latency under
  1.5 s at the median.
- **Listen to the output.** Automated tests cannot hear aliasing, clipping, or clicks at chunk
  boundaries. Play the harness WAV every time you touch the audio path.

## Risks & gotchas

- **Forgetting `clear` on barge-in** — the single most common bug in this design. Symptom: logs show
  the agent stopped, the caller still hears it talking.
- **Chunk-boundary clicks** mean the resampler's filter state is not carried across TTS chunks. Same
  root cause as the Phase 1 block-boundary test.
- **Over-long replies.** LLMs write paragraphs; phone callers need one or two sentences. Enforce it
  in the prompt and watch for it in transcripts — a 20-second monologue is unusable on a call.
- **Abort leaks.** An aborted TTS fetch whose body is not drained or destroyed leaks sockets. Verify
  with repeated interruptions over a long call.
- **Cost during development.** Every test call bills STT + LLM + TTS. Use the replay harness for
  iteration and save real calls for verification.
- **Double replies** if a final transcript arrives while `THINKING`. The state machine must swallow
  or coalesce it.

## Exit checklist

- [ ] Demo criterion demonstrated: real conversation, and interruption works.
- [ ] Median reply latency under 1.5 s, with the per-stage breakdown logged.
- [ ] Greeting includes the automated-assistant and transcription disclosure.
- [ ] Harness reproduces a full turn and an interruption offline.
- [ ] No socket or session leaks after 20 consecutive interruptions.
- [ ] `npm run build` and `npm run lint` clean.
