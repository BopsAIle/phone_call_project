import { z } from 'zod';

/**
 * The Twilio Media Streams wire protocol, in both directions.
 *
 * Twilio sends plain JSON text frames where the payload is a *sibling* of
 * `event`, not nested under a `data` key — which is why none of Nest's
 * WebSocket adapters fit and this file exists.
 */

/** Twilio always announces this; the codec is built on it. */
export const EXPECTED_MEDIA_FORMAT = {
  encoding: 'audio/x-mulaw',
  sampleRate: 8000,
  channels: 1,
} as const;

const mediaFormatSchema = z.object({
  encoding: z.string(),
  sampleRate: z.number(),
  channels: z.number(),
});

const connectedSchema = z.object({
  event: z.literal('connected'),
  protocol: z.string().optional(),
  version: z.string().optional(),
});

const startSchema = z.object({
  event: z.literal('start'),
  streamSid: z.string(),
  start: z.object({
    streamSid: z.string(),
    accountSid: z.string(),
    callSid: z.string(),
    tracks: z.array(z.string()).optional(),
    // Custom <Parameter> values always arrive as strings, whatever they were
    // in the TwiML.
    customParameters: z.record(z.string(), z.string()).default({}),
    mediaFormat: mediaFormatSchema,
  }),
});

const mediaSchema = z.object({
  event: z.literal('media'),
  streamSid: z.string(),
  media: z.object({
    track: z.string().optional(),
    chunk: z.string().optional(),
    timestamp: z.string().optional(),
    payload: z.string(),
  }),
});

const markSchema = z.object({
  event: z.literal('mark'),
  streamSid: z.string(),
  mark: z.object({ name: z.string() }),
});

const dtmfSchema = z.object({
  event: z.literal('dtmf'),
  streamSid: z.string(),
  dtmf: z.object({
    track: z.string().optional(),
    digit: z.string(),
  }),
});

const stopSchema = z.object({
  event: z.literal('stop'),
  streamSid: z.string(),
  stop: z
    .object({
      accountSid: z.string().optional(),
      callSid: z.string().optional(),
    })
    .optional(),
});

const inboundSchema = z.discriminatedUnion('event', [
  connectedSchema,
  startSchema,
  mediaSchema,
  markSchema,
  dtmfSchema,
  stopSchema,
]);

export type ConnectedFrame = z.infer<typeof connectedSchema>;
export type StartFrame = z.infer<typeof startSchema>;
export type MediaFrame = z.infer<typeof mediaSchema>;
export type MarkFrame = z.infer<typeof markSchema>;
export type DtmfFrame = z.infer<typeof dtmfSchema>;
export type StopFrame = z.infer<typeof stopSchema>;
export type InboundFrame = z.infer<typeof inboundSchema>;

/**
 * Parses one inbound text frame, returning `null` for anything unrecognised.
 *
 * Never throws. Twilio adds message types over time, and an exception raised
 * inside a socket's `message` handler takes down a live phone call — an unknown
 * event has to be a log line, not an incident.
 */
export function parseInboundFrame(raw: string | Buffer): InboundFrame | null {
  let parsed: unknown;

  try {
    parsed = JSON.parse(typeof raw === 'string' ? raw : raw.toString('utf8'));
  } catch {
    return null;
  }

  const result = inboundSchema.safeParse(parsed);
  return result.success ? result.data : null;
}

/**
 * The three messages Twilio accepts from us. Anything else — or any of these
 * with the payload one level too deep — is discarded silently, with no NACK and
 * nothing in the Twilio console, so these shapes are asserted in the unit tests
 * rather than trusted.
 */

/** One 20 ms frame of base64 mu-law, to be played to the caller. */
export function mediaMessage(streamSid: string, payload: string): string {
  return JSON.stringify({ event: 'media', streamSid, media: { payload } });
}

/** Echoed back by Twilio once the audio queued before it has finished playing. */
export function markMessage(streamSid: string, name: string): string {
  return JSON.stringify({ event: 'mark', streamSid, mark: { name } });
}

/** Drops audio Twilio has buffered but not yet played — the barge-in primitive. */
export function clearMessage(streamSid: string): string {
  return JSON.stringify({ event: 'clear', streamSid });
}
