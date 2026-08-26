# AI Receptionist — telephony backend

A phone receptionist for restaurants. A customer dials the restaurant's number,
Twilio answers it and streams the audio here, and this service bridges that audio
to the AI team's voice service, which does the talking.

**This repo owns telephony**: the Twilio webhook, the media-stream socket, codec
conversion, 20 ms framing, and Twilio's playback buffer. **The AI team owns the
conversation**: speech-to-text, voice activity detection, the language model,
text-to-speech, turn-taking, and the greeting.

```mermaid
flowchart LR
    Caller["PSTN caller"] <--> Twilio
    Twilio <-->|"8 kHz mu-law, 20 ms frames"| BE["This backend"]
    BE <-->|"16 kHz PCM16, WebSocket"| AI["AI service"]
```

The wire protocol between the two halves is
[docs/integrations/ai-bridge-contract.md](docs/integrations/ai-bridge-contract.md).

---

## Getting started

You do **not** need a phone, a Twilio account, or a public tunnel to run this.
A browser dev client speaks Twilio's protocol using your microphone.

### Prerequisites

- Node.js 20+
- Docker (for Postgres)
- The AI team's service, running locally or reachable over the network

### 1. Install

```bash
npm install
```

### 2. Start Postgres

```bash
npm run db:up
```

> **Note the port: 5433, not 5432.** The compose file publishes the container's
> 5432 on host port **5433**, because a locally-installed PostgreSQL usually
> already owns 5432 — on Windows both can bind it and connections silently reach
> the wrong server. If migrations behave strangely, check which one you are
> actually talking to.

### 3. Configure `.env`

Copy the template and fill it in:

```bash
cp .env.example .env
```

A minimal configuration that works for local browser testing:

```ini
NODE_ENV=development
PORT=3000

DATABASE_URL=postgresql://receptionist:receptionist@localhost:5433/ai_receptionist?schema=public

# The AI team's service. Locally this is plain ws:// — their process serves
# plain WebSocket and TLS is terminated at ingress in production.
AI_BRIDGE_URL=ws://localhost:8000/v1/bridge
AI_BRIDGE_TOKEN=<whatever their local config expects>

# Identifies the restaurant. Must be E.164. For browser testing it does not
# have to be a real Twilio number — it only has to match the seeded store.
TWILIO_PHONE_NUMBER=+15551234567
TWILIO_ACCOUNT_SID=AC00000000000000000000000000000000
TWILIO_AUTH_TOKEN=placeholder

# Only used to build the wss:// URL Twilio would dial. The browser client keeps
# its own origin and takes just the path, so a placeholder is fine locally.
PUBLIC_BASE_URL=https://example.invalid

# Seed values. After `db:seed` the Store row is the source of truth.
STORE_NAME=Bella Vista
STORE_TIMEZONE=Europe/Berlin
DEFAULT_LOCALE=en

# Still validated at boot but unused on the bridge path — see Known warts.
OPENAI_API_KEY=placeholder
```

Every key is validated at boot by [env.schema.ts](src/config/env.schema.ts).
A missing or malformed value crashes the process on startup rather than failing
in the middle of a call.

### 4. Migrate and seed

```bash
npm run db:migrate
npm run db:seed
```

Seeding creates a `Store` keyed on `TWILIO_PHONE_NUMBER`, with placeholder
greetings in English and German. **Without it every call is rejected** — the
voice webhook resolves the store by the number that was dialled.

The greeting text carries a legally required automated-assistant and
transcription disclosure. Edit the wording directly in the database; a re-seed
deliberately leaves it alone.

### 5. Start the AI team's service

Follow their repo's own instructions. Two things to check:

- **It must not use port 3000**, which this backend takes by default.
- `curl http://localhost:<their-port>/health` should return `{"status":"ok"}`.
  Note that their health check does not touch speech services, so a healthy
  response means their process is up, not that it can transcribe.

Then set `AI_BRIDGE_URL` to `ws://localhost:<their-port>/v1/bridge`.

### 6. Build the browser client and start

```bash
npm run build:client
npm run start:dev
```

The dev client is a separate esbuild bundle, so `build:client` is needed after a
fresh clone and whenever `client/` changes. Use `npm run build:client:watch`
while working on it.

### 7. Make a call

Open **<http://localhost:3000/dev>** and start a call. Grant microphone access.

The page is registered only when `NODE_ENV !== 'production'`.

---

## What a working call looks like

```
[TwilioController]      Call <id> from +15550000001 to store Bella Vista
[AiBridgeSession[<id>]] AI bridge connected as Bella Vista (en)
[ConversationService]   Conversation open for call <id>
[AiBridgeSession[<id>]] First agent audio: 6400 bytes from the AI service
```

Those middle two lines are the ones that matter:

- **`AI bridge connected`** — the socket is up, authentication passed, and
  `session.init` went over. It names the store and locale so you can see the
  session context arrived intact.
- **`First agent audio`** — they are actually speaking. This separates
  *connected but silent* (their side) from *connected and speaking but you hear
  nothing* (our conversion or the Twilio path).

You should then hear the greeting in the browser. Talking over the agent should
stop it within about one frame.

---

## Troubleshooting

| What you see | What it means |
|---|---|
| `AI bridge rejected our credentials (1008)` | Wrong `AI_BRIDGE_TOKEN`. Deliberately not retried — the next attempt would present the same token. |
| `AI bridge socket error: …` then `reconnecting in 200ms` | Wrong URL, unreachable host, or a TLS mismatch. Three attempts, then the call continues without an agent. |
| `Could not open a conversation for call …` | `AI_BRIDGE_URL` is empty. The call connects but is silent. |
| `AI bridge connected` but never `First agent audio` | Their side is not sending the greeting. Their problem, not ours. |
| `Malformed message: …` | They are sending something we cannot parse — contract drift. |
| `No <Stream> in the TwiML — is +… seeded as a store?` | Run `npm run db:seed`, or `TWILIO_PHONE_NUMBER` does not match the seeded row. |
| `Cannot reach the database. Is it running?` | `npm run db:up`, and check you are on port **5433**. |
| Browser asks for a microphone and nothing happens | `npm run build:client` — the bundle is not built on install. |

---

## Commands

| | |
|---|---|
| `npm run start:dev` | Watch-mode server |
| `npm run build:client` | Build the browser dev client bundle |
| `npm test` | Unit tests |
| `npm run test:e2e` | End-to-end tests (needs a migrated database) |
| `npm run lint` | ESLint with `--fix` |
| `npm run build` | Production build |
| `npm run db:up` / `db:down` | Postgres container |
| `npm run db:migrate` / `db:seed` / `db:reset` | Schema and fixtures |
| `npm run db:studio` | Prisma Studio |
| `npm run replay -- in.wav out.wav` | Drive a call from a WAV file, no microphone |

### Replaying a fixture

```bash
npm run replay -- test/fixtures/tone-sweep.wav out.wav --interrupt 4000
```

Needs the server already running. Frames are paced at 20 ms like real Twilio;
`--fast` skips the pacing when only the audio path is in question. `--interrupt`
fires a barge-in that far into the call, and the frame count at the end shows how
quickly playback stopped.

> The transcript it prints reads `Utterance` rows, which are no longer written —
> the AI service returns no transcripts. Audio and frame counts still work.

---

## Known warts

These are tracked and deliberate, not oversights.

- **`OPENAI_API_KEY` is still required at boot** but unused on the bridge path.
  It goes away with `src/stt/`, `src/llm/`, and `src/tts/`, which are still on
  disk but no longer wired into the module graph.
- **A mid-call reconnect re-greets the caller** and loses conversation history.
  The handshake carries a `resumed` flag for exactly this, but the AI service
  does not honour it yet. Raised with them as a v2 item.
- **Nothing captures a booking.** The AI service does no tool calls and no
  database access, and the tool-calling work that was planned here is being
  removed. Ownership is an open question in
  [the contract](docs/integrations/ai-bridge-contract.md).

---

## Documentation

- [docs/README.md](docs/README.md) — index
- [docs/integrations/ai-bridge-contract.md](docs/integrations/ai-bridge-contract.md)
  — the wire protocol between this backend and the AI service
- [docs/integrations/ai-bridge-plan.md](docs/integrations/ai-bridge-plan.md) —
  how this repo became a media bridge, and why
- [docs/features/](docs/features/) — what each change did and why it was needed
- [CLAUDE.md](CLAUDE.md) — conventions, and the documentation workflow every
  feature must follow
