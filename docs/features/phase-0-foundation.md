# Phase 0 — Foundation

- **Slug:** `phase-0-foundation`
- **Status:** shipped
- **Plan:** [../plan/phases/phase-0-foundation/plan.md](../plan/phases/phase-0-foundation/plan.md)
- **Parent plan:** [../plan/2026-08-19-ai-receptionist-phone-booking-agent.md](../plan/2026-08-19-ai-receptionist-phone-booking-agent.md)

## Summary

Turns the NestJS scaffold into a project that can hold the receptionist: environment variables are
validated at boot, Postgres runs in Docker with the full schema applied, and the three provider
interfaces later phases implement are defined. There is no AI, telephony, or audio yet — the point
is that when Phase 1 starts, nothing about configuration or persistence is still in flux.

## Why we need this change

The repository was an unmodified NestJS 11 scaffold: a "Hello World!" controller, no database, no
configuration module, no environment validation. Every later phase needs somewhere to persist a
call and a validated way to read credentials, so building any of them first would have meant
building this badly and in a hurry.

The specific cost of skipping it is a class of failure that only shows up in production. Without
boot-time validation, a missing `OPENAI_API_KEY` is not an error until the first phone call, at
which point a real caller hears dead air. Fail-fast configuration converts that into a deployment
that refuses to start — visible immediately, to the person who caused it.

## What changed

| Area | Change |
| --- | --- |
| Modules | `src/config/` (env schema + `AppConfigModule`), `src/prisma/` (`PrismaService`, global `PrismaModule`), `src/health/`, `src/common/with-timeout.ts` — added. `src/app.controller.ts`, `src/app.service.ts` and their spec — deleted |
| Endpoints | `GET /health` — added. `GET /` ("Hello World!") — removed |
| Data | `Store`, `Call`, `Utterance`, `Booking` tables and the `CallStatus` / `BookingStatus` / `Role` enums, created by migration `20260819083920_init`. Seed inserts one `Store` row |
| Config | 16 variables validated by [env.schema.ts](../../src/config/env.schema.ts); see [.env.example](../../.env.example). `STORE_NAME` added beyond the parent plan's list — the `Store` row cannot be seeded without it |
| Interfaces | `SttProvider`, `LlmProvider`, `TtsProvider` and `llm.types.ts` — types only, no implementations |
| Dependencies | `@nestjs/config`, `zod`, `@prisma/client`, `@prisma/adapter-pg`; dev: `prisma`, `dotenv`, `tsx`, `cross-env` |
| Scripts | `postinstall`, `db:up`, `db:down`, `db:migrate`, `db:deploy`, `db:seed`, `db:reset`, `db:studio`, `prisma:generate` |

## How it works

**Boot.** [main.ts](../../src/main.ts) creates the app from [app.module.ts](../../src/app.module.ts),
which imports three modules. `AppConfigModule` runs `validateEnv` over `process.env` before anything
else; a failure throws with one line per problem, each naming its key, and the process exits.
`PrismaService` then connects and runs a `SELECT 1` probe — if the database is unreachable, boot
fails with `Cannot reach the database. Is it running? Try npm run db:up.`

**Health.** [health.controller.ts](../../src/health/health.controller.ts) races a `SELECT 1` against
a 2 s timer. Up: `200 {"status":"ok","database":"up"}`. Down: `503 {"status":"error","database":"down"}`.

**Shutdown.** `app.enableShutdownHooks()` triggers `PrismaService.onModuleDestroy`, which disconnects.

### Key decisions

- **Fail-fast at boot, for both config and database.** Rejected booting into a permanently unhealthy
  state. `$connect()` alone does not achieve this — the pg driver adapter pools lazily and resolves
  happily with no database running, so an explicit probe query is what makes boot actually fail.
  Found by testing with the container stopped, not by reading documentation.
- **Prisma 7 over pinning to 6.** Greenfield project; being one major behind on day one is a debt
  that only grows. The cost is four setup differences: `prisma.config.ts` instead of the removed
  `package.json` `prisma` key, no `url` in the datasource block, a mandatory driver adapter, and a
  generator that must be told to emit CommonJS.
- **Generated client under `src/generated/prisma`, not the repo root.** `prisma.service.ts` imports
  it, so TypeScript pulls it into the build program regardless of `tsconfig.build.json` excludes.
  At the repo root it would move the inferred output root there, silently relocating the entry point
  to `dist/src/main.js` and breaking `start:prod`.
- **Extensionless imports in the generated client** (`importFileExtension = ""`). The default
  `.js`-extension imports resolve to `.ts` files, which neither `ts-node` nor `ts-jest` remaps —
  the seed and the e2e suite both failed on it.
- **Host port 5433 for Postgres.** A locally-installed PostgreSQL service usually owns 5432, and on
  Windows both can bind it without an error — connections then silently reach the wrong server.
- **The `Store` row owns greetings, timezone, and locale at runtime.** The matching env vars seed it
  and are never read again. Greeting text carries the legal AI-and-recording disclosure and must be
  editable without a deploy.

## Impact

- **Breaking changes:** `GET /` is gone. Nothing consumed it.
- **Migrations / setup:** `npm install` (runs `prisma generate` via `postinstall`) → copy
  [.env.example](../../.env.example) to `.env` and fill it in → `npm run db:up` → `npm run db:migrate`
  → `npm run db:seed`.
- **Performance & cost:** none. No external API calls in this phase.
- **Security & privacy:** `.env` is gitignored and uncommitted; `src/generated/` likewise. No
  credentials are logged. The seed contains only placeholder data and is safe to run anywhere.

## How to verify

1. `npm run db:up && npm run db:migrate && npm run db:seed`
2. `npm run start:dev`, then `GET /health` → `200 {"status":"ok","database":"up"}`
3. `docker compose stop db`, hit `/health` again → `503` within ~2 s, no hang.
4. Delete a line from `.env` and start → refuses to boot, naming the key.
5. `npm test` (13 unit tests over the env schema) and `npm run test:e2e` (boots the app, hits `/health`).
6. `npm run db:reset` reproduces the database from an empty state; `npm run db:seed` twice in a row
   succeeds, proving the upsert.

All six were run and passed on 2026-08-19.

## Follow-ups

- **Greeting text is a placeholder.** Phase 3 speaks it aloud. The real bilingual wording, including
  the AI-and-recording disclosure, must land before that phase ships.
- **Twilio credentials in `.env` are placeholders.** Phase 1 needs real ones, plus a development
  US/UK number. The German +49 number needs a verified address bundle and takes days — request it
  now so it is ready for Phase 5.
- **`npm run test:e2e` requires a running database.** It boots the real `AppModule`. Worth revisiting
  if it becomes awkward in CI.
- **Transcript retention** is deferred to Phase 6, but `Utterance` starts accumulating personal data
  in Phase 2. Worth deciding the window earlier than planned.

## Change log

| Date | Change | Author |
| --- | --- | --- |
| 2026-08-19 | Initial implementation | XuanVietK67 |
