# Documentation

## Layout

- [plan/](plan/) — planning documents written **before** implementation, named
  `YYYY-MM-DD-<feature-slug>.md`.
- [features/](features/) — change documents written **after** implementation, named
  `<feature-slug>.md`. Each explains why the change was needed, what changed, how it
  works, and its impact.

Both are required for every new feature. See
[.claude/skills/feature-docs/SKILL.md](../.claude/skills/feature-docs/SKILL.md) for the
workflow, or run `/feature-doc <feature-name>` to scaffold them.

## Features

<!-- Add one line per feature: - [Feature name](features/<feature-slug>.md) — one-line summary -->

- [Phase 0 — Foundation](features/phase-0-foundation.md) — validated configuration, Postgres and the
  full Prisma schema, `GET /health`, and the STT/LLM/TTS provider interfaces.
- [Phase 1 — Audio path](features/phase-1-audio-path.md) — Twilio voice webhook and Media Streams
  gateway, the mu-law codec and anti-aliased resampler, `Call` persistence, and the offline replay
  harness.

## Plans

<!-- Add one line per plan: - [Feature name](plan/YYYY-MM-DD-<feature-slug>.md) — status -->

- [AI Receptionist — Phone Booking Agent](plan/2026-08-19-ai-receptionist-phone-booking-agent.md) — draft
  (built in 7 stages; detailed per-phase plans in [plan/phases/](plan/phases/README.md))
