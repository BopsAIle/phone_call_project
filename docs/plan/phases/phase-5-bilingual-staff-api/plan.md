# Phase 5 — Production shape

- **Parent plan:** [../../2026-08-19-ai-receptionist-phone-booking-agent.md](../../2026-08-19-ai-receptionist-phone-booking-agent.md)
- **Branch:** `feat/bilingual-and-staff-api`
- **Status:** not started
- **Depends on:** [Phase 4](../phase-4-booking-slots/plan.md)
- **Unblocks:** [Phase 6](../phase-6-hardening/plan.md)

## Objective

Make the agent usable by real German and English callers, and give staff a way to actually work the
callback queue. Close the security hole that the Twilio webhooks have been running with since
Phase 1.

Up to now the system has been a demo one person places calls to. This phase turns it into something a
restaurant could put on its phone line.

## Demo criterion

A caller speaking German is greeted bilingually, the agent switches fully to German after the first
sentence, and a booking is completed in German. A staff member lists pending callbacks over the API,
reads the transcript, and marks one confirmed. Unsigned requests to `/twilio/voice` are rejected.

## Scope

**In:** locale detection and locking, German prompt and voice, bilingual greeting, staff REST API
with auth, Twilio signature validation, new-booking notification.

**Out:** timeouts, failure handling, cost tracking, retention (all Phase 6).

## Detailed design

### Locale detection

Greet bilingually — a short English line followed by a short German one — then detect from the
caller's **first final transcript** and lock the result on `Call.locale` for the rest of the call.

Detection: send the first final transcript to `gpt-5.6-luna` with a one-token classification prompt
(`en` or `de`). It costs almost nothing, adds ~150 ms once per call, and is far more robust on 8 kHz
phone audio than stopword or umlaut heuristics — Germans say "okay" and "hi" constantly.

**Lock it.** Per-utterance auto-detection flips on short confirmations: "ja", "okay", "gut", "nein",
and "acht" are all plausible in either language, and an agent that changes language mid-booking is
unusable. Allow an explicit switch only when the caller asks for one, via a `switch_language` tool.

Fall back to `DEFAULT_LOCALE` if the first utterance is too short to classify.

### German is not a translation

Write `receptionist.de.ts` natively rather than translating the English prompt. Specifically:

- Use **"Sie"** throughout. A restaurant receptionist using "du" reads as wrong or rude to most
  callers.
- German date and time speech differs structurally: "halb acht" is 7:30, not 8:30 — a mistake that
  produces a confidently wrong booking. State the 24-hour convention explicitly in the prompt and
  cover it with a resolver test.
- Numbers are spoken units-first ("vierundzwanzig"). Worth an explicit instruction to read party
  size and phone digits back slowly.
- The readback strings in `slot-filler.ts` need German variants — including correct date formatting
  (`Freitag, 22. August um 19:30`).

TTS: pass locale-specific `instructions`, e.g. *"Sprechen Sie ruhiges, natürliches Hochdeutsch in
einem freundlichen, professionellen Ton."* Keep `marin` unless German output sounds off, then A/B
against `cedar`.

STT: pass the locked locale as a language hint to the transcription session after detection.

### Twilio signature validation

The webhooks have been unauthenticated since Phase 1. Anyone who learns the URL can POST fake calls,
create `Call` rows, and burn OpenAI credit.

Add a `TwilioSignatureGuard` using `twilio.validateRequest(authToken, signature, fullUrl, params)` on
both webhook routes. Two things routinely break it:

- The URL must be the **externally visible** one (`PUBLIC_BASE_URL` + path), not what Express sees
  behind a tunnel or proxy. Behind a proxy, enable `trust proxy`.
- Validation needs the raw, correctly-parsed form body. Verify against a real Twilio request, not
  only a hand-rolled test.

The WebSocket endpoint cannot be signed. Protect it by validating that the `streamSid` and `callSid`
in the `start` event correspond to a `Call` row this process created from a *signed* webhook within
the last few minutes, and reject otherwise.

### Staff API

Minimal REST, JSON, intended for a thin dashboard or curl:

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/api/bookings?status=&from=&to=&page=` | callback queue, newest first, paginated |
| `GET` | `/api/bookings/:id` | one booking with its call and full transcript |
| `PATCH` | `/api/bookings/:id` | set `status` (`CONFIRMED`, `CANCELLED`, `UNREACHABLE`), append staff notes |
| `GET` | `/api/calls/:id/transcript` | ordered utterances |

Default listing is `PENDING_CALLBACK` sorted by `requestedAt` — the thing staff need most is "who do
I ring next, and when is their table for".

**Auth: a static API key in `X-Api-Key`, checked by a guard, from a new `STAFF_API_KEY` env var.**
This endpoint exposes customer names, phone numbers, and call transcripts; it must not ship
unauthenticated even briefly. A static key is deliberately minimal — it is enough for one restaurant
and a small dashboard, and it can be replaced when there is a real user model. Note the limitation in
the change doc so it is a known trade-off rather than an oversight.

### Notification

On `finalize_booking`, emit an internal event that a `NotificationService` turns into a staff alert.
Implement one channel behind an interface; the parent plan lists the channel choice as an open
question for the user.

Default to a configurable outbound webhook (`STAFF_WEBHOOK_URL`) — it is trivial and adapts to Slack,
Teams, or a dashboard. SMS via Twilio is a small addition once the channel is decided.

Notification failure must **never** fail the call. Fire and forget, log the error, retry once.

## Implementation steps

1. [ ] `src/conversation/locale-detector.ts` + one-token classification call.
2. [ ] Lock `Call.locale`; pass it to STT, LLM, and TTS; add the `switch_language` tool.
3. [ ] Bilingual greeting including the disclosure **in both languages**.
4. [ ] `src/llm/prompts/receptionist.de.ts`, written natively.
5. [ ] German readback strings and date formatting in `slot-filler.ts`.
6. [ ] Locale-specific TTS `instructions`; A/B the voice on German.
7. [ ] `src/telephony/twilio-signature.guard.ts` on both webhook routes; `trust proxy` if needed.
8. [ ] `start`-event provenance check on the WebSocket.
9. [ ] `STAFF_API_KEY` in the env schema; `src/common/api-key.guard.ts`.
10. [ ] `src/bookings/bookings.controller.ts` with the four endpoints, DTOs, and pagination.
11. [ ] `src/notifications/` — interface, webhook implementation, wired to finalisation.
12. [ ] German harness fixtures; a full German booking conversation.
13. [ ] Real calls in both languages; confirm the demo criterion.

## Files created or changed

- `src/conversation/locale-detector.ts` — new.
- `src/llm/prompts/receptionist.de.ts` — new.
- `src/telephony/twilio-signature.guard.ts`, `src/common/api-key.guard.ts` — new.
- `src/bookings/bookings.controller.ts`, `src/bookings/dto/*` — new.
- `src/notifications/notifications.module.ts`, `notification.provider.ts`,
  `webhook-notification.service.ts` — new.
- `src/conversation/slot-filler.ts` — localised readback.
- `src/tts/openai-tts.service.ts`, `src/stt/openai-realtime-stt.service.ts` — locale plumbing.
- `src/config/env.schema.ts` — `STAFF_API_KEY`, `STAFF_WEBHOOK_URL`.
- `test/fixtures/` — German audio fixtures.

## Testing

- **Unit — locale detector:** German and English samples classify correctly; a two-word utterance
  falls back to the default; the locale locks and is not revisited on later utterances.
- **Unit — German readback:** "halb acht" resolves to 19:30, not 20:30. The highest-value single
  assertion in this phase.
- **Unit — German dates:** `Freitag, 22. August um 19:30` formatting.
- **Unit — signature guard:** a valid Twilio signature passes; a tampered body, a wrong URL, and a
  missing header are each rejected.
- **Unit — API key guard:** missing and wrong keys give 401; the key is never logged.
- **Integration:** full German booking through the harness, asserting the persisted `Booking`.
- **Integration:** unsigned `POST /twilio/voice` is rejected; a `start` event for an unknown
  `callSid` is refused.
- **E2E:** a real German call and a real English call, each completing a booking.
- **Manual:** a native or fluent German speaker listens to the agent. Grammatically correct German
  can still sound robotic, and no test catches tone.

## Risks & gotchas

- **"halb acht" means 7:30.** Getting this wrong books every German caller an hour late, and the
  readback will not save you because the agent will read back the wrong time confidently.
- **Locale flapping** if the lock is missed — the agent answering "ja" in English then switching back
  is jarring and makes the whole system feel broken.
- **Signature validation behind a tunnel** fails on URL mismatch far more often than on a genuinely
  bad signature. Debug the URL first.
- **The staff API leaks personal data** if shipped unauthenticated. The guard is not optional, and
  the static key is a documented interim measure.
- **Disclosure must be in both languages.** An English-only disclosure does not satisfy the
  requirement for a German caller who never hears it in a language they speak.
- **German TTS quality is worth verifying early.** If it disappoints, the fallback is a dedicated
  German voice vendor — a change of scope worth surfacing before Phase 6, not after launch.

## Exit checklist

- [ ] Demo criterion demonstrated in both languages.
- [ ] "halb acht" test passes.
- [ ] Both webhooks reject unsigned requests; the WebSocket rejects unknown calls.
- [ ] Staff API requires a key and never logs it.
- [ ] Notification fires on finalisation and cannot fail a call.
- [ ] A German speaker has listened to and approved the agent's German.
- [ ] `npm run build` and `npm run lint` clean.
