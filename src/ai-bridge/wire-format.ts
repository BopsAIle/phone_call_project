import { z } from 'zod';

/**
 * The AI-bridge wire protocol, in both directions.
 *
 * Everything that touches the shape of the socket lives here; the session class
 * owns only lifecycle, queueing, and reconnection. That split is deliberate and
 * mirrors the one between `realtime-events.types.ts` and the STT service — the
 * frame encoding is the part of this contract still marked `[CONFIRM]`, so it is
 * worth having it in one file with its own spec rather than threaded through a
 * class that also handles backoff.
 *
 * See docs/integrations/ai-bridge-contract.md.
 */

/**
 * Audio travels as **binary** WebSocket frames, control as **text**.
 *
 * The alternative on the table is base64 inside a JSON envelope, which costs
 * ~33% bandwidth and a decode step on a path carrying ~32 KB/s per call in each
 * direction. Every WebSocket library exposes the frame type directly, so telling
 * the two apart is a field check rather than parsing.
 *
 * If the AI team asks for base64 instead, this file is the only one that
 * changes.
 */

/** What the AI service needs in order to answer as this store. */
export interface SessionContext {
  callId: string;
  storeName: string;
  /** IANA zone, so "tonight" resolves against the store's clock, not the server's. */
  timezone: string;
  locale: 'en' | 'de';
  /**
   * Spoken verbatim as the first thing on the call. Carries a required
   * automated-assistant disclosure, so it is passed as text rather than left to
   * the model to compose.
   */
  greeting: string;
}

/**
 * The handshake, sent as a text frame the moment the socket opens.
 *
 * Sent again after a reconnect, because the AI service has no way to recover
 * the store context otherwise — but with `resumed: true`, which is what stops
 * the greeting being spoken a second time in the middle of a call. A dropped
 * socket mid-conversation is exactly when a caller would least understand being
 * greeted again.
 */
export function sessionInit(
  context: SessionContext,
  opts: { resumed: boolean },
): string {
  return JSON.stringify({
    event: 'session.init',
    ...context,
    resumed: opts.resumed,
  });
}

const interruptSchema = z.object({
  event: z.literal('interrupt'),
});

/**
 * Anything with an `event` string, so an unrecognised message can be logged by
 * name instead of as a blob.
 */
const envelopeSchema = z.object({
  event: z.string(),
});

/**
 * One message from the AI service, already classified.
 *
 * `unhandled` and `malformed` are distinct on purpose. The first is routine —
 * the contract says unknown events are ignored, so new message types are
 * additive and safe. The second means a message we *do* depend on arrived in a
 * shape we do not understand, which is the contract moving underneath us and is
 * worth a warning.
 */
export type InboundMessage =
  | { kind: 'audio'; pcm: Buffer }
  | { kind: 'interrupt' }
  | { kind: 'unhandled'; event: string }
  | { kind: 'malformed'; detail: string };

/**
 * Classifies one inbound frame. Never throws.
 *
 * An exception raised inside a socket's `message` handler takes down a live
 * phone call, so a message we cannot read has to be a log line rather than an
 * incident — the same rule `parseInboundFrame` follows for Twilio.
 */
export function parseInbound(raw: Buffer, isBinary: boolean): InboundMessage {
  if (isBinary) {
    /**
     * An odd length means a PCM16 sample was split across two frames, which the
     * contract forbids. Passed through rather than rejected: `leToInt16` drops a
     * trailing odd byte by design, so the damage is one sample, whereas dropping
     * the frame would lose ~100 ms of speech and desynchronise everything after
     * it.
     */
    return { kind: 'audio', pcm: raw };
  }

  let parsed: unknown;

  try {
    parsed = JSON.parse(raw.toString('utf8'));
  } catch {
    return { kind: 'malformed', detail: 'not JSON' };
  }

  const envelope = envelopeSchema.safeParse(parsed);

  if (!envelope.success) {
    return { kind: 'malformed', detail: 'no event field' };
  }

  if (envelope.data.event !== 'interrupt') {
    return { kind: 'unhandled', event: envelope.data.event };
  }

  const interrupt = interruptSchema.safeParse(parsed);

  return interrupt.success
    ? { kind: 'interrupt' }
    : { kind: 'malformed', detail: 'interrupt in an unexpected shape' };
}
