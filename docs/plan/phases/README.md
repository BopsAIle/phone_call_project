# Phase plans — AI Receptionist

Detailed execution plans for each phase of
[AI Receptionist — Phone Booking Agent](../2026-08-19-ai-receptionist-phone-booking-agent.md).

Read the parent plan first for the *why*, the architecture, and the verified vendor facts. Each
document below covers the *how* for one phase and assumes that context.

| Phase | Plan | Objective | Demo criterion |
| --- | --- | --- | --- |
| 0 | [phase-0-foundation](phase-0-foundation/plan.md) | Config, Prisma, Postgres, provider interfaces | App boots, `/health` reports a live DB, seed store exists |
| 1 | [phase-1-audio-path](phase-1-audio-path/plan.md) | Twilio Media Streams, mu-law codec, resampler | Call the number and hear your own voice echoed back |
| 2 | [phase-2-speech-to-text](phase-2-speech-to-text/plan.md) | OpenAI realtime STT | Transcripts stream into the log and `Utterance` rows mid-call |
| 3 | [phase-3-llm-tts-loop](phase-3-llm-tts-loop/plan.md) | The agent speaks — LLM + TTS + barge-in | A real spoken conversation you can interrupt |
| 4 | [phase-4-booking-slots](phase-4-booking-slots/plan.md) | Slot filling, readback, persistence | Call in, book a table, see the `Booking` row |
| 5 | [phase-5-bilingual-staff-api](phase-5-bilingual-staff-api/plan.md) | German support, staff API, webhook auth | A German call books correctly; staff work the callback queue |
| 6 | [phase-6-hardening](phase-6-hardening/plan.md) | Timeouts, failure handling, cost, retention | Agent survives an OpenAI outage mid-call without dead air |

## Rules for working these phases

- **Phases are strictly ordered.** Each depends on the one before it. Do not start Phase 3 because
  Phase 2 is "nearly done" — the demo criterion is the gate.
- **Each phase gets its own branch**, named in its plan document, cut from the previous phase's
  branch (or from `master` once that branch has merged). Phase 0 shipped on `feat/foundation` off
  `master`; Phase 1 cuts `feat/twilio-media-stream` from there.
- **The demo criterion is the definition of done**, not "the code is written". If you cannot
  demonstrate it, the phase is not finished.
- **These are living documents.** When the implementation deviates, update the phase plan and the
  parent plan in the same commit so the two never contradict each other.
- Run type-check and lint before every commit, per repository convention.

## Why the order is what it is

The riskiest unknown is not the AI — it is the audio. Sample-rate conversion, mu-law encoding, and
frame timing either work or produce something that sounds broken in ways that are easy to
misattribute to the TTS model. Phase 1 therefore proves a clean full-duplex audio path with an echo
before a single AI call is made. Everything after that is application logic against a known-good
transport.

Phase 0 is numbered zero deliberately: it contains no receptionist behaviour at all, only the
scaffolding every later phase depends on.
