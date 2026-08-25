# Documentation

## Layout

- [plan/](plan/) — planning documents written **before** implementation, named
  `YYYY-MM-DD-<feature-slug>.md`.
- [features/](features/) — change documents written **after** implementation, named
  `<feature-slug>.md`. Each explains why the change was needed, what changed, how it
  works, and its impact.
- [integrations/](integrations/) — contracts with external services and teams. These
  are shared with the other side and are the source of truth for the wire protocol,
  so they are corrected before the code is.

Both are required for every new feature. See
[.claude/skills/feature-docs/SKILL.md](../.claude/skills/feature-docs/SKILL.md) for the
workflow, or run `/feature-doc <feature-name>` to scaffold them.

## Features

<!-- Add one line per feature: - [Feature name](features/<feature-slug>.md) — one-line summary -->

- [Phase 0 — Foundation](features/phase-0-foundation.md) — validated configuration, Postgres and the
  full Prisma schema, `GET /health`, and the STT/LLM/TTS provider interfaces.
- [Phase 1 — Audio path](features/phase-1-audio-path.md) — Twilio voice webhook and Media Streams
  gateway, the mu-law codec and anti-aliased resampler, `Call` persistence, the offline replay
  harness, and a browser dev client that speaks Twilio's protocol while the real number is blocked.
- [Phase 3 — The agent speaks](features/phase-3-llm-tts-loop.md) — the LLM and TTS loop, sentence
  chunking, the turn state machine, barge-in, and the greeting with its automated-assistant
  disclosure. Phase 2's change doc was deliberately skipped; its plan is the record.

## Integrations

<!-- Add one line per integration: - [Service name](integrations/<slug>.md) — one-line summary -->

- [AI Bridge](integrations/ai-bridge-contract.md) — wire protocol between this backend and
  the AI team's voice service, which takes over STT, LLM, TTS, turn-taking, and the
  greeting. Covers the WebSocket transport, the 16 kHz PCM16 audio format, the
  `interrupt` barge-in event, and the latency budget measured on the pipeline it
  replaces. **Draft — pending agreement.**

## Plans

<!-- Add one line per plan: - [Feature name](plan/YYYY-MM-DD-<feature-slug>.md) — status -->

- [AI Receptionist — Phone Booking Agent](plan/2026-08-19-ai-receptionist-phone-booking-agent.md) — draft
  (built in 7 stages; detailed per-phase plans in [plan/phases/](plan/phases/README.md))
