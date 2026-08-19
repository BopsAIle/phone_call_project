# Phase 4 — It actually books

- **Parent plan:** [../../2026-08-19-ai-receptionist-phone-booking-agent.md](../../2026-08-19-ai-receptionist-phone-booking-agent.md)
- **Branch:** `feat/booking-slots`
- **Status:** not started
- **Depends on:** [Phase 3](../phase-3-llm-tts-loop/plan.md)
- **Unblocks:** [Phase 5](../phase-5-bilingual-staff-api/plan.md)

## Objective

Turn a conversation into a booking record. Give the LLM tools to report what it learns, track which
details are still missing, resolve spoken dates and times into real timestamps, read everything back
for confirmation, and persist it.

This is the phase where the product becomes the product.

## Demo criterion

Call in, say *"Hi, I'd like a table for four next Friday at half seven, name's Sam"*, answer the
agent's follow-ups, hear it read the details back, say yes — and find a complete `Booking` row with
`status = PENDING_CALLBACK` in Postgres.

## Scope

**In:** tool definitions, the slot filler, datetime resolution, readback and confirmation, `Booking`
persistence including partials, the full receptionist prompt.

**Out:** German (Phase 5), staff API (Phase 5), notifications (Phase 5).

## Detailed design

### Slots

| Slot | Source | Required |
| --- | --- | --- |
| `customerName` | asked | yes |
| `partySize` | asked | yes |
| `requestedAt` | asked, resolved to a timestamp | yes |
| `phone` | pre-filled from Twilio `From`, confirmed aloud | yes |
| `notes` | volunteered or lightly prompted | no |

Pre-filling `phone` from caller ID and merely confirming it — *"I have you on 0176 double-three…, is
that the best number?"* — removes the single most error-prone thing to collect over a noisy phone
line. Digit-by-digit readback of a misheard number is where these calls go to die.

### Tools

Extraction happens through tool calls in the same model turn as the spoken reply. No second
extraction pass, no added latency.

```ts
update_booking({
  customerName?: string,
  partySize?: number,
  requestedDateTime?: string,  // ISO 8601 local, e.g. "2026-08-22T19:30"
  requestedRaw?: string,       // the caller's exact words: "next Friday at half seven"
  phone?: string,              // E.164
  notes?: string,
})

finalize_booking({ confirmed: boolean })
```

`update_booking` accepts **partial** updates and is called whenever the model learns anything. Every
call upserts `Booking` by `callId` immediately, so a caller who hangs up after giving their name and
party size still leaves something a human can act on. Persisting only at the end would throw away
every abandoned call, and abandoned calls are common.

`requestedRaw` is not redundant with `requestedDateTime`. When resolution is ambiguous or wrong, the
staff member calling back sees what the caller actually said instead of a confidently incorrect
timestamp. Always populate both.

`finalize_booking` is called only after the readback and an explicit yes. It sets
`status = PENDING_CALLBACK` and emits the event Phase 5 turns into a staff notification.

### Datetime resolution

Inject the current date, time, and store timezone into the system prompt every turn so "next Friday"
and "tomorrow" have a reference point. The model returns a local ISO string; **we** validate it with
`luxon` in the store timezone:

- Reject times in the past → the agent re-asks rather than booking last Tuesday.
- Reject more than 90 days out → almost always a year-rollover mistake ("January" in August).
- Warn (do not reject) outside opening hours → staff can still make a judgement on callback.
- On any rejection, leave `requestedAt` null, keep `requestedRaw`, and let the agent clarify.

Do not let the model do timezone arithmetic. Give it local wall-clock time, resolve to UTC yourself.
DST transitions are exactly where hand-rolled date maths fails.

### Slot filler

`src/conversation/slot-filler.ts` is a small pure module over the accumulated slots:

- `missing(): SlotName[]` — drives what the agent asks next.
- `isComplete(): boolean` — gates the readback.
- `readback(locale): string` — builds the confirmation sentence from resolved values.

Building the readback in code rather than letting the model paraphrase means the caller confirms
*what was actually stored*. A model that says "table for four" while having stored `partySize: 40`
produces a confirmed-but-wrong booking, and the human callback will not catch it.

### Prompt additions

On top of the Phase 3 baseline:

- The slots to collect, and to ask for **at most two at a time** — phone callers cannot hold a
  five-part question.
- Call `update_booking` the moment any detail is learned, not at the end.
- Read everything back before `finalize_booking`, and only finalise on explicit agreement.
- **The availability guard, stated plainly:** the agent cannot see the reservation book, must never
  confirm or deny that a time is available, and must tell the caller a colleague will ring back
  shortly to confirm. This is the most important line in the prompt — an agent that says "yes, 8pm
  is free" creates real double bookings and real angry customers.
- If the caller asks about menu, prices, or opening hours: answer only from store data, otherwise say
  it will be covered on the callback. Never invent.

### Abandoned and partial bookings

A caller who hangs up mid-slot leaves a `Booking` row with some fields and no `finalize_booking`.

`BookingStatus` as designed has no value for this. Two options: add `ABANDONED_PARTIAL` to the enum
(one additive migration, explicit and queryable), or leave the row un-finalised and let the staff API
infer it from `Call.status = ABANDONED`.

**Recommendation: add the enum value.** Staff will want "incomplete calls worth chasing" as its own
queue, and inferring state from a join is the kind of thing that quietly rots. This changes the
schema from the parent plan — update the parent plan's schema section in the same commit.

## Implementation steps

1. [ ] `npm i luxon` and `npm i -D @types/luxon`.
2. [ ] `src/llm/tools/booking.tools.ts` — JSON schemas for both tools.
3. [ ] Extend `OpenAiLlmService` to pass tools and surface `toolCalls` alongside streamed sentences.
4. [ ] `src/conversation/slot-filler.ts` — missing / complete / readback.
5. [ ] `src/conversation/datetime-resolver.ts` — luxon validation in the store timezone.
6. [ ] `src/bookings/bookings.service.ts` — `upsertFromToolCall`, `finalize`.
7. [ ] Handle tool calls in `CallSession`: apply, persist, feed results back into the turn.
8. [ ] `src/llm/prompts/receptionist.en.ts` — full prompt with slots, readback, availability guard.
9. [ ] Wire readback → `finalize_booking` → `PENDING_CALLBACK` → domain event.
10. [ ] Add `ABANDONED_PARTIAL` (migration) and set it on `stop` without finalise.
11. [ ] Extend the harness with scripted multi-turn booking conversations.
12. [ ] Real call; confirm the demo criterion.

## Files created or changed

- `src/llm/tools/booking.tools.ts` — new.
- `src/conversation/slot-filler.ts`, `datetime-resolver.ts` — new.
- `src/bookings/bookings.service.ts`, `bookings.module.ts` — new.
- `src/llm/prompts/receptionist.en.ts` — expanded.
- `src/llm/openai-llm.service.ts` — tool calling.
- `src/conversation/call-session.ts` — tool-call handling and slot state.
- `prisma/schema.prisma` + migration — `ABANDONED_PARTIAL`.
- [../../2026-08-19-ai-receptionist-phone-booking-agent.md](../../2026-08-19-ai-receptionist-phone-booking-agent.md) — schema section updated to match.

## Testing

- **Unit — datetime resolver:** "next Friday" from a known Wednesday; "tomorrow at 8" across a DST
  boundary; a past time is rejected; a date 400 days out is rejected; a time outside opening hours
  resolves with a warning rather than a rejection.
- **Unit — slot filler:** `missing()` shrinks as slots arrive; `isComplete()` ignores `notes`;
  `readback()` renders party size, name, and a spoken-friendly date and time.
- **Unit — tool application:** partial updates merge rather than overwrite; a null field does not
  erase an existing value (a model that re-sends `{customerName: null}` must not wipe the name).
- **Integration (harness):** scripted conversations — everything in one sentence; details drip-fed
  over six turns; caller corrects the party size after giving it; caller hangs up mid-slot and the
  partial row survives with `ABANDONED_PARTIAL`.
- **Adversarial:** caller asks *"is 8pm free?"* — assert the transcript contains no confirmation and
  the agent offers a callback instead. Worth an automated assertion, not just a manual check.
- **E2E:** real call end to end, verifying every persisted field including `requestedRaw`.

## Risks & gotchas

- **The agent confirms availability anyway.** Prompt constraints are not guarantees. Back them with
  the adversarial test above, and rely on the human callback as the real backstop.
- **Numbers over the phone are unreliable.** "Four" / "for" / "fourteen" and "thirty" / "thirteen"
  are the classic confusions. The readback is what catches them — never skip it, even when the agent
  seems confident.
- **Model overwrites good data with nulls.** Merge semantics must ignore null and undefined.
- **Year rollover.** In August, "the third of January" is next year. The 90-day rule catches the
  common case; `requestedRaw` catches the rest.
- **Do not add availability "just to be helpful."** It is explicitly out of scope and it is what
  makes this system safe to ship.

## Exit checklist

- [ ] Demo criterion demonstrated on a real call.
- [ ] Partial bookings persist when the caller hangs up mid-conversation.
- [ ] The availability-guard adversarial test passes.
- [ ] Readback is generated from stored values, not model paraphrase.
- [ ] Parent plan schema section updated to match the migration.
- [ ] `npm run build` and `npm run lint` clean.
