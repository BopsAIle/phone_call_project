# Phase 0 — Foundation

- **Parent plan:** [../../2026-08-19-ai-receptionist-phone-booking-agent.md](../../2026-08-19-ai-receptionist-phone-booking-agent.md)
- **Branch:** `feat/foundation`
- **Status:** not started
- **Depends on:** nothing
- **Unblocks:** every later phase

## Objective

Turn the NestJS scaffold into a project that can hold the receptionist: validated configuration, a
real database with the full schema, and the three provider interfaces that later phases implement.

No AI, no telephony, no audio. The point of this phase is that when Phase 1 starts, nothing about
config or persistence is still in flux.

## Demo criterion

`npm run start:dev` boots, `GET /health` returns `{ status: "ok", database: "up" }`, the seed script
creates one `Store` row, and deleting a required variable from `.env` makes the app refuse to start
with a message naming the missing key.

## Scope

**In:** env validation, Prisma + schema + migration + seed, Postgres via Docker, health endpoint,
provider interfaces, scaffold cleanup.

**Out:** anything that makes a network call to Twilio or OpenAI.

## Detailed design

### Configuration

Use `@nestjs/config` with a zod `validate` function so the process dies at boot, not at 2am on the
first call. A missing `OPENAI_API_KEY` must be a startup crash, never a runtime 500.

`src/config/env.schema.ts`:

```ts
export const envSchema = z.object({
  NODE_ENV: z.enum(['development', 'test', 'production']).default('development'),
  PORT: z.coerce.number().default(3000),
  DATABASE_URL: z.string().url(),
  OPENAI_API_KEY: z.string().min(1),
  TWILIO_ACCOUNT_SID: z.string().startsWith('AC'),
  TWILIO_AUTH_TOKEN: z.string().min(1),
  TWILIO_PHONE_NUMBER: z.string().regex(/^\+[1-9]\d{6,14}$/), // E.164
  PUBLIC_BASE_URL: z.string().url(),   // tunnel or deployed host; builds the wss:// stream URL
  STORE_TIMEZONE: z.string().default('Europe/Berlin'),
  DEFAULT_LOCALE: z.enum(['en', 'de']).default('en'),
  LLM_MODEL: z.string().default('gpt-5.6-terra'),
  STT_MODEL: z.string().default('gpt-live-transcribe'),
  TTS_MODEL: z.string().default('gpt-4o-mini-tts'),
  TTS_VOICE: z.string().default('marin'),
});
export type Env = z.infer<typeof envSchema>;
```

Register globally with `ConfigModule.forRoot({ isGlobal: true, validate })`, and expose a typed
`ConfigService<Env, true>` so `configService.get('OPENAI_API_KEY')` is type-safe.

Commit a `.env.example` with every key and no values. `.env` is already gitignored — keep it that way.

### Database

`docker-compose.yml` with `postgres:16-alpine`, a named volume, and port `5432`. This is the only
infrastructure the project needs locally.

`prisma/schema.prisma` holds the full schema from the parent plan (`Store`, `Call`, `Utterance`,
`Booking` and the three enums). Create it all now even though Phases 1–4 fill it in gradually — one
migration is easier to reason about than five, and the schema is already designed.

`src/prisma/prisma.service.ts` extends `PrismaClient` and implements `OnModuleInit` to `$connect()`.
Register `enableShutdownHooks` in `main.ts` so Prisma disconnects cleanly on SIGTERM.

`prisma/seed.ts` creates the single `Store` row from env values. Bilingual greeting text is a
**placeholder** until the user supplies the real wording — see Open questions in the parent plan.

### Provider interfaces

These three interfaces are the reason later phases can be worked (and swapped) independently. Define
them now, implement them later. Note that `TtsProvider` yields **Twilio-ready mu-law**, so all
resampling stays hidden inside the implementation.

```ts
// src/stt/stt.provider.ts
export interface SttSession {
  pushAudio(mulaw8k: Buffer): void;              // straight from Twilio
  onPartial(cb: (text: string) => void): void;
  onFinal(cb: (text: string, meta: { startMs: number; endMs: number }) => void): void;
  onSpeechStarted(cb: () => void): void;         // the barge-in trigger
  onSpeechStopped(cb: () => void): void;
  setLocale(locale: 'en' | 'de'): void;
  close(): Promise<void>;
}
export interface SttProvider {
  createSession(opts: { locale?: 'en' | 'de' }): Promise<SttSession>;
}

// src/llm/llm.provider.ts
export interface LlmProvider {
  respond(opts: {
    messages: ChatMessage[];
    tools: ToolDefinition[];
    signal: AbortSignal;
  }): {
    sentences: AsyncIterable<string>;   // flushed at sentence boundaries, for incremental TTS
    toolCalls: Promise<ToolCall[]>;
  };
}

// src/tts/tts.provider.ts
export interface TtsProvider {
  synthesize(opts: {
    text: string;
    locale: 'en' | 'de';
    signal: AbortSignal;
  }): AsyncIterable<Buffer>;            // 160-byte, 20 ms, 8 kHz mu-law frames
}
```

`AbortSignal` on both `respond` and `synthesize` is not decoration — it is how Phase 3 implements
barge-in. Designing it in now avoids a refactor later.

### Scaffold cleanup

Delete `src/app.controller.ts`, `src/app.service.ts`, and `src/app.controller.spec.ts`. Replace with
`src/health/health.controller.ts`, which pings the DB with `SELECT 1`.

## Implementation steps

1. [ ] `npm i @nestjs/config zod @prisma/client` and `npm i -D prisma`.
2. [ ] Write `docker-compose.yml`; `docker compose up -d`; confirm Postgres accepts connections.
3. [ ] `npx prisma init`; write the full `schema.prisma`; `npx prisma migrate dev --name init`.
4. [ ] Add `src/config/env.schema.ts` and wire `ConfigModule.forRoot({ isGlobal: true, validate })`.
5. [ ] Add `.env.example`; create a local `.env`.
6. [ ] Add `src/prisma/prisma.module.ts` + `prisma.service.ts`; enable shutdown hooks in `main.ts`.
7. [ ] Write `prisma/seed.ts`; add the `prisma.seed` key to `package.json`; run `npx prisma db seed`.
8. [ ] Add `src/health/health.controller.ts` and remove the scaffold controller/service/spec.
9. [ ] Add the three provider interface files (types only, no implementations).
10. [ ] Type-check, lint, verify the demo criterion.
11. [ ] **Admin, in parallel:** request the German +49 Twilio number. It needs a verified local
    address bundle and takes days — starting it now means it is ready when Phase 5 needs it. Buy a
    US or UK number immediately for Phases 1–4.

## Files created or changed

- `docker-compose.yml`, `.env.example` — new.
- `prisma/schema.prisma`, `prisma/migrations/*`, `prisma/seed.ts` — new.
- `src/config/env.schema.ts`, `src/config/config.module.ts` — new.
- `src/prisma/prisma.module.ts`, `src/prisma/prisma.service.ts` — new.
- `src/health/health.controller.ts` — new.
- `src/stt/stt.provider.ts`, `src/llm/llm.provider.ts`, `src/tts/tts.provider.ts` — new, types only.
- [src/app.module.ts](../../../../src/app.module.ts) — import Config, Prisma, Health.
- [src/main.ts](../../../../src/main.ts) — shutdown hooks, port from `ConfigService`.
- [package.json](../../../../package.json) — dependencies and the `prisma.seed` entry.
- `src/app.controller.ts`, `src/app.service.ts`, `src/app.controller.spec.ts` — deleted.

## Testing

- Unit: `envSchema` accepts a complete env and rejects a missing/malformed `TWILIO_PHONE_NUMBER`
  and a non-URL `DATABASE_URL`.
- Manual: boot with a key removed and confirm the crash message names it.
- Manual: `GET /health` with Postgres up returns `database: "up"`; stop the container and confirm it
  reports down rather than hanging.
- `npx prisma migrate reset` followed by seed reproduces a clean database from scratch.

## Risks & gotchas

- **Do not let the seed contain real customer data or credentials.** It runs in every environment.
- The greeting text in the seed is a placeholder. Phase 3 will speak it aloud — make sure the real
  wording (including the AI and recording disclosure) lands before that phase ships.
- `DATABASE_URL` inside Docker differs from the host URL. Use `localhost:5432` from the host and
  document it in `.env.example` to avoid an hour of confusion.
- Prisma's generated client must be regenerated after every schema edit (`prisma generate`); the
  `migrate dev` command does it for you, a hand-edited schema does not.

## Exit checklist

- [ ] Demo criterion demonstrated.
- [ ] `npm run build` and `npm run lint` clean.
- [ ] `.env` not committed; `.env.example` is.
- [ ] Migration committed and reproducible from an empty database.
- [ ] Development phone number purchased; German number requested.
