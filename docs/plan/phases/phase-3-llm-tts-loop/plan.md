# Phase 3 — The agent speaks

- **Parent plan:** [../../2026-08-19-ai-receptionist-phone-booking-agent.md](../../2026-08-19-ai-receptionist-phone-booking-agent.md)
- **Branch:** `feat/llm-tts-loop`
- **Status:** in progress
- **Depends on:** [Phase 2](../phase-2-speech-to-text/plan.md)
- **Unblocks:** [Phase 4](../phase-4-booking-slots/plan.md)

## Decisions taken at the start of the phase

| Decision | Choice |
| --- | --- |
| LLM client | The `openai` SDK. It owns SSE framing now and streaming tool-call delta accumulation in Phase 4, which is the genuinely error-prone part. Phase 2's argument for raw `ws` — that reconnection, batching, and backpressure had to be owned — does not transfer: these are one-shot HTTP requests. |
| TTS client | Raw `fetch`. The response is a raw byte stream, not SSE, so the SDK would only sit between `response.body` and the frame chunker. |
| Greeting | Pre-synthesised and cached as mu-law bytes, keyed on a hash of the text, voice, and model. Off the critical path for first impressions, and a cached greeting still plays when OpenAI is down — which Phase 6 relies on. |
| Outbound audio | The gateway passes an `OutboundAudioSink` down at `create()`. `CallSession` never calls back into the gateway. |
| Multiple finals per turn | Abort the in-flight completion and restart with the merged text, rather than debouncing. Zero added latency in the common single-final case. |
| Barge-in signal | **Corrected mid-phase.** `onSpeechStarted` was believed to fire; it does not. See below — endpointing is now ours, and barge-in is gated on the first decoded word. |

## Confirmed API shapes

Verified against the live API on 2026-08-21, before any code was written — the same discipline that
caught `gpt-live-transcribe` rejecting `turn_detection` in Phase 2. Do not substitute remembered
values.

**The brain streams from Chat Completions.** `gpt-5.6-terra` is present in `GET /v1/models`
(alongside `gpt-5.6-luna` and `gpt-5.6-sol`) and `POST /v1/chat/completions` with `stream: true`
returns the familiar chunk shape:

```json
{"object":"chat.completion.chunk","model":"gpt-5.6-terra",
 "choices":[{"index":0,"delta":{"content":" what"},"finish_reason":null}]}
```

So text deltas are `choices[0].delta.content` and the Responses API is not required. The first chunk
carries `delta.role` with empty content — skip it rather than feeding an empty string to the chunker.
Chunks also carry an `obfuscation` field, which is padding against compression side-channels and is
to be ignored.

**TTS returns headerless PCM, streamed.** `POST /v1/audio/speech` with `response_format: "pcm"`
responds `Content-Type: audio/pcm` and `Transfer-Encoding: chunked`. The body starts on sample data —
a `RIFF` header would be `52 49 46 46`, and the first bytes are `0500 0500 0400 …` — so there is
nothing to strip. `instructions` is accepted alongside `voice`.

Measured for one sentence, *"Of course, I can take a booking request for two."*:

| Stage | Size |
| --- | --- |
| PCM16 @ 24 kHz from OpenAI | 187,200 B (93,600 samples, 3.9 s) |
| After `Downsampler` ÷3 | 31,200 samples @ 8 kHz |
| After `encodeMulaw` | 31,200 B |
| After `FrameBuffer` | **195 frames** of 160 B |

Useful as a sanity check when the pipeline is wired: a frame count wildly off this ratio means the
resampler phase or the framing is wrong, not the model.

## The wrong STT model was chosen

This phase started on the belief that `input_audio_buffer.speech_started` fires. It does not for
`gpt-live-transcribe`, and neither does `speech_stopped` or `.completed`. Phase 2's plan flagged this
as open and listed it as outcome 3; it was closed on recollection rather than evidence, and the first
real call found it — the caller was transcribed perfectly and the agent never replied, because
`onFinal` never fired.

**The deeper mistake was narrower than it looked.** Phase 2 read
`Turn detection is not supported for this transcription model` and concluded turn detection was
unavailable. The message says *this model*. Probed on 2026-08-21, `gpt-4o-transcribe`,
`gpt-4o-mini-transcribe`, `gpt-transcribe`, and `whisper-1` all accept `server_vad`; only
`gpt-live-transcribe` and `gpt-realtime-whisper` reject it. `STT_MODEL` now defaults to
`gpt-4o-transcribe` and the original design works as written.

The transcript-activity gate below is kept as the fallback for a model without VAD, since `STT_MODEL`
is configuration. The session adopts whichever the model actually provides — see "Adaptive
endpointing".

Read off a live session on 2026-08-21 by streaming a synthesised sentence plus four seconds of
trailing silence. The **complete** event vocabulary:

```
  1 × session.created
  1 × session.updated
 16 × conversation.item.input_audio_transcription.delta
```

That is all. `gpt-live-transcribe` is a continuous transcriber with no concept of a turn, which is
also why it rejects `turn_detection`.

### Adaptive endpointing

The session does not trust its configuration about which signals it will get — it adopts whichever
arrives. The first `speech_started` or `speech_stopped` sets `vadDriven`, permanently disarms the
transcript gate (cancelling any timer it had already armed), and hands turns to the model. Without a
boundary event the gate runs exactly as before.

The two must never both fire: each would emit its own final for one utterance, and the conversation
layer would answer twice.

**Boundaries are tracked per `item_id`, not "most recent".** `.completed` for one utterance routinely
arrives *after* `speech_started` for the next, so reading the latest boundary at completion time
attributes one turn's timestamps to another — observed live, with two consecutive utterances both
reporting `startMs: 2476`.

**`silenceDurationMs` is the tuning knob, and 500 ms was too low.** It cut *"Hello, my name is Anna.
Can I book a table for two people?"* into three separate turns, because the pauses at the commas
cleared it — a caller gathering their thoughts mid-sentence would be cut off the same way. At 800 ms
the same input returns as one clean utterance. The cost is explicit:

| `silenceDurationMs` | Result | Caller falls silent → transcript |
| --- | --- | --- |
| 500 ms | split into three turns | +1360 ms |
| **800 ms** | one clean turn | **+1849 ms** |
| the gate, for comparison | one turn | +3700 ms |

Both figures come from synthesised speech, which pauses more evenly than a person. This is the first
thing to adjust on real calls: raise it if the agent talks over people, lower it if replies drag.

### The fallback: a transcript-activity gate

Exactly what Phase 2 prescribed for this outcome. A delta arriving into an empty buffer means the
caller started talking; the transcript going quiet for `ENDPOINT_SILENCE_MS` means they stopped. The
joined deltas are the transcript — verified lossless against a committed `.completed`, character for
character.

Two things were tried and rejected, both on measurements:

**`input_audio_buffer.commit` — rejected.** It is the documented way to delimit an utterance with VAD
off, and it does return a clean `.completed`. But it closes the item over whatever has been *decoded*
so far, and this model runs seconds behind the audio. Committing at each endpoint lost the back half
of a sentence outright on a live run: `"Hello, my name is Anna. Can I book a table for two people?"`
came back as `"Hello,"` and `"my name is"`, with the rest discarded. Without it, the same input
returns as one complete final. The commit also costs ~600 ms before `.completed` arrives, so it was
never on the critical path anyway.

**A 900 ms threshold — too tight.** Mid-speech delta gaps are roughly twice as wide over 8 kHz mu-law
as over direct 24 kHz PCM (~1200 ms against 660 ms): worse audio decodes in chunkier bursts. 900 ms
split one sentence into three finals. Now 1200 ms.

### Barge-in is narrower than planned

`handleSpeechStarted` acts only while `SPEAKING`, not while `THINKING`. The signal is a
transcript-activity gate rather than a VAD edge, so during `THINKING` it nearly always means the
caller's own sentence continuing past a pause the endpointer called early — and no audio is playing
to interrupt. Cancelling there would discard a turn the merge in `handleFinal` completes correctly.

The honest cost: barge-in now waits for the first *decoded word* rather than the first energy, so it
is roughly 700 ms later than a true VAD edge would be. The ~200 ms interruption target in the demo
criterion is not achievable on this signal.

## Measured latency — the budget is not met

Measured end to end against the live API on 2026-08-21, one turn, no telephony:

| Stage | Budget | Before the model switch | After |
| --- | --- | --- | --- |
| Caller stops → transcript | 500 ms | ~3700 ms | **~1850 ms** |
| LLM first token | 400 ms | ~900 ms | ~900 ms |
| TTS first audio | 300 ms | ~850 ms | ~850 ms |
| **Caller stops → first frame** | **1500 ms** | ~5500 ms | **~3600 ms** |

The model switch removed roughly 1.9 s. The target is still missed by about 2 s, and STT remains the
largest single term at ~1850 ms even with server VAD — of which 800 ms is the deliberate
`silenceDurationMs` choice above and the rest is decode time.

Our own code — chunker, resampler, framing — contributes nothing measurable in either column.

Recorded plainly rather than restated softly, because the parent plan makes < 1.5 s a project goal
and this is not yet there.

What was ruled out: `gpt-5.6-terra` is a reasoning model, and a first sample suggested
`reasoning_effort: "none"` cut first token threefold. **It does not.** Across three samples per
configuration, `terra` default, `terra` with `reasoning_effort: "none"`, and `gpt-5.6-luna` are
indistinguishable inside the noise. The parameter is deliberately *not* set: it would be cargo cult
based on one outlier.

Levers still untried, in order of expected value:

1. **Tune `silenceDurationMs` against real calls.** 800 ms of the ~1850 ms is this constant, chosen
   on synthesised speech that pauses more evenly than a person. Real callers may tolerate 600 ms,
   which would be an immediate 200 ms with no other change.
2. **Shorten the system prompt.** It is re-read every turn and sits in front of first token.
3. **A shorter first sentence.** Prompting for a brief opener means the chunker flushes sooner; time
   to *first audio* matters far more than time to the whole reply.
4. **`gpt-5.6-luna`.** Indistinguishable from `terra` in testing, but worth re-measuring under load —
   `LLM_MODEL` makes it a config change.
5. **The `gpt-realtime-2.1` speech-to-speech adapter** the parent plan holds in reserve behind the
   provider interfaces. Evaluated and deferred on 2026-08-21: it would remove the cascade entirely
   and get closest to the target, but Phase 4 requires the readback to be *generated from stored
   values rather than paraphrased by the model*, which an S2S model cannot guarantee. That is a
   safety property for a booking system, not a preference. Revisit if the levers above stall.

**A hand-rolled energy VAD is no longer on this list.** It was the leading candidate while the model
was believed to report no boundaries; with `server_vad` doing the job properly, writing our own would
be re-solving a solved problem — exactly what Phase 2 argued against twice.

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

### The outbound sink

`MediaStreamGateway` builds a sink closing over the socket and `streamSid`, and hands it to
`ConversationService.create()`. `CallSession` writes through it and never calls back into the
gateway — routing barge-in through `findByStreamSid` would make a cycle (gateway →
`ConversationService` → `CallSession` → gateway) and leak the gateway's private session type into the
conversation layer.

```ts
export interface OutboundAudioSink {
  playFrame(mulawFrame: Buffer): void;
  mark(name: string): void;
  clear(): void;
}
```

`findByStreamSid` stays, but its only caller is the dev controller; its comment claiming a Phase 3
purpose is corrected.

### One caller turn can produce several finals

`gpt-live-transcribe` chunks audio itself, so two spoken sentences may arrive as two `.completed`
events. Without a rule that is two replies talking over each other.

- Final in `LISTENING` → commit immediately, go `THINKING`. The common case, no cost.
- Final in `THINKING` → abort the in-flight completion, merge into the same user message, restart.
  No audio has played yet, so this costs one wasted partial completion and nothing else.
- Final in `SPEAKING` → mostly unreachable, because `speech_started` fires first and barge-in has
  already moved the session to `LISTENING`. Handle it as a fresh turn rather than asserting.

Deliberately **not** a debounce window: a window would add its full duration to *every* turn against
a 1.5 s budget, to fix a case that is the exception.

### `toolCalls` must always settle

`LlmProvider.respond` returns `{ sentences, toolCalls: Promise<ToolCall[]> }`. On barge-in the
consumer abandons `sentences` mid-iteration, which calls `.return()` on the generator and unwinds its
`finally`. Settle `toolCalls` there — resolving `[]` rather than rejecting.

A rejection nobody is awaiting becomes an unhandled rejection that ends the process and every other
live call with it, which is the failure `MediaStreamGateway` already guards against around frame
handling. Phase 4 is the phase that actually awaits this promise, and it must not be able to hang.

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
