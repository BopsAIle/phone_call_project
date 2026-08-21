# Phase 3 — The agent speaks

- **Plan:** [../plan/phases/phase-3-llm-tts-loop/plan.md](../plan/phases/phase-3-llm-tts-loop/plan.md)
- **Branch:** `feat/llm-tts-loop`
- **Status:** code complete, unit-verified, and smoke-tested against the live OpenAI API. The
  conversational demo criterion is **not** yet demonstrated end to end — see
  [What is not verified](#what-is-not-verified). The measured reply latency **misses the 1.5 s
  target**, and that is a real finding rather than a rounding error.

## Why we need this change

After Phase 2 the agent could hear and could write down what it heard, but it could not answer. The
only audio a caller received was Phase 1's echo of their own voice. That is a transcription service,
not a receptionist.

This phase closes the loop: transcript → LLM → speech → back down the phone line, and — just as
importantly — stops all of that the moment the caller talks over it. Without barge-in the agent
monologues at people who are trying to correct it, which is the single behaviour that makes a voice
agent feel broken rather than slow.

It is also where the **GDPR/TTDSG disclosure** finally gets spoken. Callers now hear that they are
talking to an automated assistant and that the call is transcribed, before anything is collected from
them. Retrofitting consent onto transcripts already stored is painful; this is the cheap moment.

Doing nothing leaves a system that records callers and never replies.

## What changed

### New modules

**`src/llm/`**

- [sentence-chunker.ts](../../src/llm/sentence-chunker.ts) — cuts token deltas into speakable
  sentences. Deliberately the same shape as
  [FrameBuffer](../../src/audio/frame-buffer.ts): `push()` returns whole units, `flush()` returns the
  tail.
- [openai-llm.service.ts](../../src/llm/openai-llm.service.ts) — `LlmProvider` over Chat Completions,
  streaming and abortable, running the chunker so `sentences` yields sentences rather than tokens.
- [prompts/receptionist.en.ts](../../src/llm/prompts/receptionist.en.ts) — the baseline system
  prompt, including the availability guard.

**`src/tts/`**

- [openai-tts.service.ts](../../src/tts/openai-tts.service.ts) — `TtsProvider`: streamed PCM in,
  Twilio-ready mu-law frames out, abortable, with the response body cancelled on every exit path.
- [greeting-cache.ts](../../src/tts/greeting-cache.ts) — the greeting pre-rendered to mu-law frames
  on disk, keyed on a hash of text, voice, and model.

**`src/conversation/`**

- [audio-sink.ts](../../src/conversation/audio-sink.ts) — the three messages Twilio accepts from us,
  as the conversation layer sees them.
- [call-session.ts](../../src/conversation/call-session.ts) — grown from Phase 2's thin listener into
  the turn state machine, conversation history, barge-in, mark tracking, and latency instrumentation.

### Changed

- [media-stream.gateway.ts](../../src/telephony/media-stream.gateway.ts) — builds the outbound sink,
  routes Twilio's `mark` echo into the conversation, loads the `Store` alongside the `Call` for the
  greeting, and **deletes Phase 1's echo**.
- [conversation.service.ts](../../src/conversation/conversation.service.ts) — takes the sink, the
  greeting, and the store context; resolves the locale from config.
- [dev-client.controller.ts](../../src/dev/dev-client.controller.ts) and
  [client/main.ts](../../client/main.ts) — a `POST /dev/barge-in/:streamSid` endpoint and an
  **Interrupt** button.
- [test/harness/replay.ts](../../test/harness/replay.ts) — `--interrupt <ms>`, and it now reports how
  many frames arrived *after* the interruption.
- [media-stream.e2e-spec.ts](../../test/media-stream.e2e-spec.ts) — the two echo assertions became
  liveness assertions, since there is no echo any more.

### Dependencies and configuration

`openai` (6.49.0) is added, for the LLM only. No new environment variables — `LLM_MODEL`,
`TTS_MODEL`, and `TTS_VOICE` were already in the Phase 0 schema. No migration:
`Utterance.latencyMs` and the nullable `endMs` were already in the schema.

`.cache/` is gitignored; it holds pre-rendered greeting audio.

## How it works

```
STT final transcript
  → CallSession                      LISTENING → THINKING
  → LlmProvider.respond()            streamed deltas → SentenceChunker
  → per sentence: TtsProvider        PCM 24 kHz → Downsampler → mu-law → 160-byte frames
  → OutboundAudioSink.playFrame()    THINKING → SPEAKING on the first frame
  → OutboundAudioSink.mark()         one mark per sentence
  → Twilio echoes the mark back      SPEAKING → LISTENING when pendingMarks empties
```

### Key decisions

**The chunker is the latency mechanism.** Sentence one goes to TTS while the model is still writing
sentence two. Awaiting each `speak()` looks like it serialises, but it does not: the SSE stream keeps
receiving in the background, and because frames are written as fast as TTS produces them rather than
paced at 20 ms, Twilio already holds seconds of sentence one while sentence two synthesises.

**A `.` is held for one more delta.** `7.30` and `Dr. Weber` are only distinguishable from a sentence
end by what follows, and a delta often ends exactly on the dot. `?` and `!` are unambiguous and flush
at once. A missed abbreviation costs one extra TTS request and a pause in an odd place — never a
wrong reply — so this is a short list, not a tokeniser.

**The gateway passes a sink down; the conversation never calls back.** Routing barge-in through
`findByStreamSid` would have made a cycle (gateway → ConversationService → CallSession → gateway) and
leaked the gateway's private session type across the seam. `findByStreamSid` survives, but its only
caller is now the dev controller.

**Barge-in sends `clear`, and that is the whole point.** Aborting our own streams does nothing about
audio Twilio has already buffered. Without `clear` the logs say the agent stopped while the caller
still hears it talking.

**A turn is identified by its `AbortController`.** An aborted turn's async loops do not stop
synchronously, so every step re-checks that it is still the current turn before touching shared
state. That is what prevents the classic overlapping-replies failure.

**Several finals in one caller turn are merged by abort-and-restart**, not by a debounce window. A
window would add its full duration to *every* turn against an already-missed budget, to fix a case
that is the exception. Restarting costs one wasted partial completion, and only when it happens.

**Endpointing is adaptive, because turn detection depends on the model.** `STT_MODEL` defaults to
`gpt-4o-transcribe`, which reports `speech_started` / `speech_stopped` / `.completed` and endpoints
turns for us. `gpt-live-transcribe` reports none of those, so the session falls back to ending a turn
when the transcript goes quiet, joining the deltas itself. It adopts whichever the model actually
sends rather than trusting its config, and the two paths can never both fire — that would be two
replies per turn. VAD boundaries are tracked per `item_id`, because `.completed` for one utterance
routinely arrives after `speech_started` for the next.

**Barge-in only fires while `SPEAKING`.** Because the signal is transcript activity rather than a VAD
edge, "speech started" during `THINKING` nearly always means the caller's own sentence continuing
past a pause the endpointer called early — and no audio is playing to interrupt.

**`toolCalls` always settles, never rejects.** Breaking out of the `for await` on barge-in calls
`.return()` on the generator, which unwinds its `finally`. A rejection nobody is awaiting is an
unhandled rejection, and that ends the process along with every other live call. Phase 4 is the phase
that actually awaits this promise.

## Impact

**Breaking:** the echo is gone. Anything that assumed inbound audio comes straight back — including
the old e2e assertions — no longer holds.

**Cost:** every call now bills LLM and TTS on top of STT. The replay harness and the dev client exist
so iteration does not go through real calls.

**Rollback:** entirely additive at the module level. Repointing the Twilio voice webhook away from
`/twilio/voice` disables the receptionist without a deploy.

## Verified

- 185 unit tests and 4 e2e tests pass; `npm run lint` and `npm run build` are clean.
- **The full LLM → TTS → mu-law path was run against the live OpenAI API**, producing an 8 kHz WAV of
  the agent answering "May I book a table for two?" with *"Certainly. What date and time would you
  like to book for?"* — 178 frames, 3.5 s of speech, correct duration for the text.
- **The endpointing gate was verified against a live transcription session**, streaming synthesised
  speech converted to 8 kHz mu-law and paced at 20 ms, i.e. exactly what a call delivers. It produced
  one clean final: *"Hello, my name is Anna. Can I book a table for two people?"*
- The API shapes in the plan were confirmed against the live API before the code was written.
- Chunker guards verified on real replies: `7.30` and `Dr. Weber` do not split.

## The bug this phase shipped and then fixed

Worth recording, because the lesson is not about the code.

The first real call transcribed the caller perfectly and the agent never answered. This phase was
built on the belief that `input_audio_buffer.speech_started` fires. It does not for
`gpt-live-transcribe` — and neither does `speech_stopped` or `.completed`, so `onFinal` never fired
and no turn ever started. Phase 2's plan had flagged exactly this as an open question and listed "no
boundary events at all" as a possible outcome; it was closed on recollection instead of evidence.

Every unit test passed throughout, because they drove a fake socket that emitted events the real API
never sends. A fake built from the same wrong assumption as the code confirms the assumption rather
than testing it. The fix was found in one live probe that printed the session's actual event
vocabulary — the step Phase 2's plan had specified and that was skipped.

**The root cause was one step further back.** Phase 2 read `Turn detection is not supported for this
transcription model` and concluded turn detection was unavailable. The message says *this model*.
Four other transcription models in the same account accept `server_vad`; only `gpt-live-transcribe`
and `gpt-realtime-whisper` reject it. Switching `STT_MODEL` to `gpt-4o-transcribe` restored the
original design and removed ~1.9 s from every reply. A vendor error naming *this model* is a prompt
to try another one.

## What is not verified

- **The demo criterion is not demonstrated.** A genuine back-and-forth through the dev client, and an
  interruption on a live stream, still need doing by hand.
- **Latency still misses the target** — roughly 3.6 s from the caller stopping to the first frame,
  against 1.5 s. The model switch removed ~1.9 s of the original ~5.5 s. STT remains the largest term
  at ~1850 ms, of which 800 ms is the deliberate `silenceDurationMs` choice. The plan ranks the
  remaining levers.
- **`silenceDurationMs` is tuned on synthesised speech.** 500 ms split a sentence at its commas;
  800 ms did not. Real callers pause less evenly, so this is the first constant to revisit on real
  calls — in either direction.
- **Barge-in timing has not been re-measured** since server VAD replaced the transcript gate. It
  should now be far closer to the ~200 ms target, because `speech_started` fires on audio energy
  rather than on the first decoded word, but that is inference rather than measurement.
- **No leak test.** The 20-consecutive-interruptions check has not been run.
- **Phase 2's change doc was deliberately skipped**, so `docs/features/` has no
  `phase-2-speech-to-text.md`. Known debt, not an oversight.
