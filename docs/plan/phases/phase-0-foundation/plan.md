# Phase 0 — Foundation

- **Parent plan:** [../../2026-08-19-ai-receptionist-phone-booking-agent.md](../../2026-08-19-ai-receptionist-phone-booking-agent.md)
- **Branch:** `feat/foundation`
- **Status:** shipped (2026-08-19)
- **Change doc:** [../../../features/phase-0-foundation.md](../../../features/phase-0-foundation.md)
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

Written against **zod 4** (`npm i zod` installs 4.x). In v4 the string formats are top-level
functions — `z.url()`, not the deprecated `z.string().url()`.

`src/config/env.schema.ts`:

```ts
export const envSchema = z.object({
  NODE_ENV: z.enum(['development', 'test', 'production']).default('development'),
  PORT: z.coerce.number().default(3000),
  DATABASE_URL: z.url(),
  OPENAI_API_KEY: z.string().min(1),
  TWILIO_ACCOUNT_SID: z.string().startsWith('AC').length(34),
  TWILIO_AUTH_TOKEN: z.string().min(1),
  TWILIO_PHONE_NUMBER: z.string().regex(/^\+[1-9]\d{6,14}$/), // E.164
  PUBLIC_BASE_URL: z.url(),            // tunnel or deployed host; builds the wss:// stream URL
  STORE_NAME: z.string().min(1),       // seed only — see "Source of truth" below
  STORE_TIMEZONE: z.string().default('Europe/Berlin'),
  DEFAULT_LOCALE: z.enum(['en', 'de']).default('en'),
  LLM_MODEL: z.string().default('gpt-5.6-terra'),
  STT_MODEL: z.string().default('gpt-live-transcribe'),
  TTS_MODEL: z.string().default('gpt-4o-mini-tts'),
  TTS_VOICE: z.string().default('marin'),
});
export type Env = z.infer<typeof envSchema>;
```

`z.url()` accepts `postgresql://user:pass@localhost:5432/db?schema=public` and the Docker-internal
`postgresql://…@db:5432/…` form — verified against zod 4.4.

Register globally with `ConfigModule.forRoot({ isGlobal: true, validate })`, and expose a typed
`ConfigService<Env, true>` so `configService.get('OPENAI_API_KEY')` is type-safe.

**Format the validation failure.** A raw `ZodError` thrown out of `validate` prints as a wall of
JSON and does not satisfy the demo criterion. Catch it and rethrow a readable message:

```ts
const parsed = envSchema.safeParse(config);
if (!parsed.success) {
  const detail = parsed.error.issues
    .map((i) => `${i.path.join('.')}: ${i.message}`)
    .join('\n  ');
  throw new Error(`Invalid environment configuration:\n  ${detail}`);
}
return parsed.data;
```

**Do not name the wrapper module `ConfigModule`** — it collides with `@nestjs/config`'s export and
every import site becomes ambiguous. Either call it `AppConfigModule` or skip the wrapper entirely
and call `ConfigModule.forRoot()` directly in `app.module.ts`. This plan assumes `AppConfigModule`.

**Source of truth.** `STORE_NAME`, `STORE_TIMEZONE`, and `DEFAULT_LOCALE` exist only to seed the
`Store` row. From Phase 3 onward, runtime code reads timezone, locale, and greeting from the `Store`
record — never from env. Otherwise the two drift and nobody can tell which one the agent used.

Commit a `.env.example` with every key and no values. `.env` is already gitignored — keep it that way.

### Database

#### Docker

`docker-compose.yml` with `postgres:16-alpine`, a named volume, port `5432`, explicit
`POSTGRES_USER` / `POSTGRES_PASSWORD` / `POSTGRES_DB`, and a **healthcheck** (`pg_isready`). Without
the healthcheck, `prisma migrate dev` run immediately after `docker compose up -d` races the
container's first-boot initialisation and fails with a connection error that looks like a config
problem. This is the only infrastructure the project needs locally.

#### Prisma 7

`npm i -D prisma` installs **7.x** (7.9.1 at time of writing). Prisma 7 differs from the 5/6-era
setup in four ways that all land in this phase. Everything below was verified against a real
`prisma@7.9.1` install, not recalled:

1. **`prisma.config.ts` replaces the `prisma` key in `package.json`.** That key no longer exists.
   `prisma init` generates the config file; the seed command goes in it as `migrations.seed`.
   It needs `dotenv` as a devDependency:

   ```ts
   import 'dotenv/config';
   import { defineConfig } from 'prisma/config';

   export default defineConfig({
     schema: 'prisma/schema.prisma',
     migrations: {
       path: 'prisma/migrations',
       seed: 'tsx prisma/seed.ts',
     },
     datasource: { url: process.env['DATABASE_URL'] },
   });
   ```

2. **The `datasource` block in `schema.prisma` no longer carries `url`.** It is just
   `provider = "postgresql"`; the CLI reads the URL from `prisma.config.ts`.

3. **A driver adapter is mandatory at runtime.** `PrismaClientOptions` requires either `adapter` or
   an Accelerate URL — there is no implicit `DATABASE_URL` pickup any more. Install
   `@prisma/adapter-pg` (it brings `pg`) and construct the client explicitly:

   ```ts
   const adapter = new PrismaPg({ connectionString: process.env.DATABASE_URL });
   super({ adapter });
   ```

4. **The generator must be configured for CommonJS.** The default `prisma-client` generator emits
   ESM using `import.meta.url` and `.ts`-extension imports, which will not compile in this project
   ([tsconfig.json](../../../../tsconfig.json) is `module: nodenext` with no `"type": "module"`).
   Set the module format explicitly and put the output **inside `src/`**:

   ```prisma
   generator client {
     provider            = "prisma-client"
     output              = "../src/generated/prisma"
     runtime             = "nodejs"
     moduleFormat        = "cjs"
     importFileExtension = "js"
   }
   ```

   `moduleFormat = "cjs"` removes the `import.meta.url` preamble. The output path matters: see
   "Build layout" below.

Consequences of the generated client living under `src/generated/prisma`:

- Add `/src/generated` to `.gitignore` (`prisma init` gitignores its default location; ours differs).
- **Add `"postinstall": "prisma generate"` to `package.json`.** Because the client is gitignored, a
  fresh clone has no client at all, and `npm run build` fails with four `TS2339`/`TS2307` errors in
  `prisma.service.ts` that look like a broken import rather than a missing codegen step. Verified by
  deleting `src/generated` and rebuilding.
- Add an ignore for it in [eslint.config.mjs](../../../../eslint.config.mjs) — the `lint` glob is
  `{src,apps,libs,test}/**/*.ts` and would otherwise type-lint thousands of generated lines.
- Add `"!**/generated/**"` to jest's `collectCoverageFrom` in [package.json](../../../../package.json).

#### Build layout

`nest build` uses [tsconfig.build.json](../../../../tsconfig.build.json), which excludes only
`node_modules`, `test`, `dist`, and `**/*spec.ts`. [tsconfig.json](../../../../tsconfig.json) sets no
`rootDir`, so TypeScript infers the output root from the common ancestor of all compiled files.
Today that is `src/`, and the build emits `dist/main.js` — which is what `start:prod`
(`node dist/main`) expects.

Adding `prisma/seed.ts` at the repo root changes that common ancestor to the repo root, silently
moving the entry point to `dist/src/main.js` and breaking `npm run start:prod`. **Add both
`"prisma"` and `"prisma.config.ts"` to the `exclude` array in `tsconfig.build.json`.** A bare
`"prisma"` entry only excludes the *directory* — `prisma.config.ts` is a sibling file at the repo
root and would keep the output root anchored there on its own.

Keeping the generated client under `src/` (above) is the other half of this fix — if it lived at the
repo root it would be pulled into the program by `prisma.service.ts`'s import, and `exclude` cannot
prevent that (it governs which files *start* the program, not which are reached through imports).

#### Schema and service

`prisma/schema.prisma` holds the full schema from the parent plan (`Store`, `Call`, `Utterance`,
`Booking` and the three enums). Create it all now even though Phases 1–4 fill it in gradually — one
migration is easier to reason about than five, and the schema is already designed.

`src/prisma/prisma.service.ts` extends `PrismaClient` and implements **both** `OnModuleInit`
(`$connect()`) and `OnModuleDestroy` (`$disconnect()`). `app.enableShutdownHooks()` in `main.ts`
triggers the lifecycle hook on SIGTERM; on its own it does not disconnect Prisma.

**Connect strategy — decide here, because it conflicts with the health check.** If `$connect()`
throws in `OnModuleInit` the process never finishes booting, so there is no server to answer
`GET /health` and report the database as down. Pick fail-fast: `await $connect()` at boot, so a
missing database is a startup crash consistent with the config philosophy. The health endpoint then
covers the database *going away after* a successful boot, which is the case worth monitoring.

#### Migration workflow

Nothing applies migrations automatically — they run explicitly, and the two commands are not
interchangeable:

| Command | Script | When |
| --- | --- | --- |
| `prisma migrate dev` | `npm run db:migrate` | Development. Diffs the schema, writes a new migration folder, applies it, regenerates the client. Also applies migrations a teammate committed. |
| `prisma migrate deploy` | `npm run db:deploy` | CI and production. Applies committed migrations only — never creates one, never resets. |
| `prisma migrate reset` | `npm run db:reset` | Drop, re-apply everything, re-seed. Destroys data; development only. |

The loop for a schema change in any later phase: edit `schema.prisma` → `npm run db:migrate` →
**commit the generated `prisma/migrations/<timestamp>_<name>/` folder** → `npm run db:deploy` on
deploy. A migration that is not committed does not exist for anyone else.

#### Seed

`prisma/seed.ts` creates the single `Store` row from env values. **Use `upsert` keyed on
`phoneNumber`**, not `create` — `Store.phoneNumber` is `@unique`, so a plain `create` throws on the
second run and makes `migrate reset` + seed non-repeatable.

Run it with `tsx`, not `ts-node`. The generated client's imports carry `.js` extensions that
TypeScript resolves back to `.ts`; `ts-node` does not do that remapping at require time and fails
with `MODULE_NOT_FOUND`. `tsx` handles it.

Bilingual greeting text is a **placeholder** until the user supplies the real wording — see Open
questions in the parent plan.

### Provider interfaces

These three interfaces are the reason later phases can be worked (and swapped) independently. Define
them now, implement them later. Note that `TtsProvider` yields **Twilio-ready mu-law**, so all
resampling stays hidden inside the implementation.

`LlmProvider` below references `ChatMessage`, `ToolDefinition`, and `ToolCall`. Those are not
defined anywhere else in this plan and the file will not compile without them, so define them in
`src/llm/llm.types.ts` in the same step — provider-neutral shapes, not OpenAI SDK types (the point
of the interface is that the SDK stays behind it):

```ts
// src/llm/llm.types.ts
export type ChatRole = 'system' | 'user' | 'assistant' | 'tool';

export interface ChatMessage {
  role: ChatRole;
  content: string;
  toolCallId?: string;                 // set when role === 'tool'
}

export interface ToolDefinition {
  name: string;
  description: string;
  parameters: Record<string, unknown>; // JSON Schema
}

export interface ToolCall {
  id: string;
  name: string;
  arguments: Record<string, unknown>;  // parsed, not the raw JSON string
}
```

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

### Health endpoint

`src/health/health.controller.ts` pings the database with `SELECT 1`. Two details the demo criterion
depends on:

- **Wrap the query in a timeout.** A stopped Postgres container does not refuse connections quickly
  — the socket hangs until the OS TCP timeout, and `GET /health` hangs with it. Race the
  `$queryRaw` against a ~2 s timer and treat the timeout as down. (Setting `connect_timeout=2` in
  `DATABASE_URL` helps the driver but does not bound an already-established-then-severed
  connection; the race is the reliable guard.)
- **Return 503 when the database is down**, not 200 with a "down" body — a monitor that only reads
  the status code must still see the failure.

Shape: `{ status: 'ok', database: 'up' }` with 200, or `{ status: 'error', database: 'down' }` with
503.

### Scaffold cleanup

Delete `src/app.controller.ts`, `src/app.service.ts`, and `src/app.controller.spec.ts`.

**Also update [test/app.e2e-spec.ts](../../../../test/app.e2e-spec.ts).** It currently asserts that
`GET /` returns `"Hello World!"`, which is served by the controller being deleted — leaving it in
place breaks `npm run test:e2e`. Repoint it at `GET /health` (it boots the full `AppModule`, so it
needs a reachable database and a valid `.env`) or delete it.

## Implementation steps

Ordering matters in two places: `.env` must exist before any Prisma CLI command reads it, and the
`tsconfig.build.json` fix must land before the first build that includes `prisma/`.

1. [ ] `npm i @nestjs/config zod @prisma/client @prisma/adapter-pg` and
   `npm i -D prisma dotenv tsx`.
2. [ ] Write `docker-compose.yml` (with healthcheck); `docker compose up -d`; confirm
   `pg_isready` passes.
3. [ ] Add `src/config/env.schema.ts` with the formatted-error `validate`; wire
   `ConfigModule.forRoot({ isGlobal: true, validate })` via `AppConfigModule`.
4. [ ] Add `.env.example`; create a local `.env` with a real `DATABASE_URL`. **Before step 5** —
   `prisma init` writes its own `.env` if none exists and the CLI needs `DATABASE_URL` present.
5. [ ] `npx prisma init`; reconcile the generated `prisma.config.ts` with the version in this plan;
   set the CJS generator block; write the full `schema.prisma`.
6. [ ] Add `"prisma"` and `"prisma.config.ts"` to `exclude` in `tsconfig.build.json`; add
   `/src/generated` to `.gitignore`; add the eslint ignore and the jest `collectCoverageFrom`
   exclusion.
7. [ ] `npx prisma migrate dev --name init` (generates the client as a side effect).
8. [ ] Add `src/prisma/prisma.module.ts` + `prisma.service.ts` (adapter, `OnModuleInit`,
   `OnModuleDestroy`); `app.enableShutdownHooks()` and `PORT` from `ConfigService` in `main.ts`.
9. [ ] Write `prisma/seed.ts` as an `upsert`; set `migrations.seed` in `prisma.config.ts`; run
   `npx prisma db seed`.
10. [ ] Add `src/health/health.controller.ts` (timeout + 503); delete the scaffold
    controller/service/spec; repoint `test/app.e2e-spec.ts`.
11. [ ] Add `src/llm/llm.types.ts` and the three provider interface files (types only, no
    implementations).
12. [ ] Add `src/config/env.schema.spec.ts`.
13. [ ] `npm run build`, `npm run lint`, `npm test`, `npm run test:e2e`; verify the demo criterion
    and confirm `dist/main.js` still exists at that path.
14. [ ] **Admin, in parallel:** request the German +49 Twilio number. It needs a verified local
    address bundle and takes days — starting it now means it is ready when Phase 5 needs it. Buy a
    US or UK number immediately for Phases 1–4.

## Files created or changed

- `docker-compose.yml`, `.env.example` — new.
- `prisma.config.ts` — new (Prisma 7; replaces the old `package.json` `prisma` key).
- `prisma/schema.prisma`, `prisma/migrations/*`, `prisma/seed.ts` — new.
- `src/generated/prisma/**` — generated, gitignored, never edited.
- `src/config/env.schema.ts`, `src/config/app-config.module.ts` — new.
- `src/config/env.schema.spec.ts` — new.
- `src/prisma/prisma.module.ts`, `src/prisma/prisma.service.ts` — new.
- `src/health/health.controller.ts`, `src/health/health.module.ts` — new.
- `src/llm/llm.types.ts` — new, types only.
- `src/stt/stt.provider.ts`, `src/llm/llm.provider.ts`, `src/tts/tts.provider.ts` — new, types only.
- [src/app.module.ts](../../../../src/app.module.ts) — import Config, Prisma, Health.
- [src/main.ts](../../../../src/main.ts) — shutdown hooks, port from `ConfigService`.
- [package.json](../../../../package.json) — dependencies; jest `collectCoverageFrom` exclusion;
  `postinstall` and the `db:*` scripts.
- [tsconfig.build.json](../../../../tsconfig.build.json) — add `"prisma"` and `"prisma.config.ts"`
  to `exclude`.
- [eslint.config.mjs](../../../../eslint.config.mjs) — ignore `src/generated/`.
- [.gitignore](../../../../.gitignore) — add `src/generated/`.
- [test/app.e2e-spec.ts](../../../../test/app.e2e-spec.ts) — repointed at `/health`, or deleted.
- `src/app.controller.ts`, `src/app.service.ts`, `src/app.controller.spec.ts` — deleted.

## Testing

- Unit (`src/config/env.schema.spec.ts`): `envSchema` accepts a complete env and rejects a
  missing/malformed `TWILIO_PHONE_NUMBER` and a non-URL `DATABASE_URL`; the formatted error message
  contains the offending key name.
- Manual: boot with a key removed and confirm the crash message names it.
- Manual: `GET /health` with Postgres up returns 200 / `database: "up"`; stop the container and
  confirm it returns 503 within the timeout rather than hanging.
- `npx prisma migrate reset` followed by seed reproduces a clean database from scratch, and seeding
  **twice** in a row succeeds (proves the `upsert`).
- `npm run build` then confirm `dist/main.js` exists (not `dist/src/main.js`) and
  `npm run start:prod` boots.
- `npm run test:e2e` passes against the updated spec.

## Risks & gotchas

- **Do not let the seed contain real customer data or credentials.** It runs in every environment.
- The greeting text in the seed is a placeholder. Phase 3 will speak it aloud — make sure the real
  wording (including the AI and recording disclosure) lands before that phase ships.
- `DATABASE_URL` inside Docker differs from the host URL. Use `localhost:5432` from the host and
  document it in `.env.example` to avoid an hour of confusion.
- Prisma's generated client must be regenerated after every schema edit (`prisma generate`); the
  `migrate dev` command does it for you, a hand-edited schema does not.
- **The build-output move is the nastiest failure here** because it is silent: `npm run build`
  succeeds, `npm run start:dev` keeps working, and only `start:prod` breaks — probably in CI, not on
  your machine. Check for `dist/main.js` in the exit checklist.
- **Prisma 7 defaults are ESM.** If you skip `moduleFormat = "cjs"`, the generated client emits
  `import.meta.url`, which cannot compile to CommonJS. The failure appears as a TypeScript error in
  a `// @ts-nocheck` generated file, which is confusing enough to lose an hour to.
- **`ts-node` cannot run the seed** — the generated client's `.js`-extension imports resolve to
  `.ts` files, which `ts-node` does not remap. Use `tsx`. Symptom is `MODULE_NOT_FOUND` on a path
  that visibly exists.
- If you would rather follow the older, more heavily documented Prisma workflow, pinning
  `prisma@^6` / `@prisma/client@^6` removes items 1–4 of the Prisma 7 section (no config file, no
  adapter, `url = env("DATABASE_URL")` in the schema, CJS client by default). It is a legitimate
  choice, but it starts a greenfield project one major version behind.

## Exit checklist

- [x] Demo criterion demonstrated — `/health` returns `{ status: "ok", database: "up" }`; removing
      `OPENAI_API_KEY` from `.env` refuses boot with `Invalid environment configuration:
      OPENAI_API_KEY: Invalid input: expected string, received undefined`.
- [x] `npm run build` and `npm run lint` clean; 13 unit tests and 1 e2e test pass.
- [x] `dist/main.js` exists at that path.
- [x] `GET /health` returns 503 in ~134 ms when Postgres is stopped — no hang.
- [x] Boot fails fast when Postgres is stopped, with an actionable message.
- [x] Seed runs twice in a row without error, returning the same store id.
- [x] `.env` not committed; `.env.example` is. `src/generated/` not committed.
- [x] Migration committed and reproducible from an empty database.
- [ ] Development phone number purchased; German number requested. **Outstanding — admin task,
      blocks Phase 1.**
