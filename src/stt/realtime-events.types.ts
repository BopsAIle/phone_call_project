import { z } from 'zod';

/**
 * The OpenAI realtime transcription wire protocol, in both directions.
 *
 * The sibling of src/telephony/twilio-frames.ts, and deliberately the same
 * shape: zod schemas for what we receive, plain builders for what we send, and
 * a parser that never throws. An exception raised inside a socket's `message`
 * handler ends a live phone call, and that is as true of OpenAI's socket as it
 * is of Twilio's.
 *
 * The API shape here was confirmed against the current reference on 2026-08-21;
 * see docs/plan/phases/phase-2-speech-to-text/plan.md for the citation and for
 * the two claims still marked for verification against a live session.
 */

/**
 * Transcription sessions connect with `intent=transcription` rather than the
 * `model=` parameter a speech-to-speech session uses — the model is named in
 * `session.update` instead.
 */
export const REALTIME_URL =
  'wss://api.openai.com/v1/realtime?intent=transcription';

/**
 * `OpenAI-Beta: realtime=v1` is deliberately absent. It was required during the
 * beta and is not sent on GA; most tutorials online still include it.
 */
export function realtimeHeaders(apiKey: string): Record<string, string> {
  return { Authorization: `Bearer ${apiKey}` };
}

/** What the model reports when it thinks the caller started or stopped talking. */
const speechStartedSchema = z.object({
  type: z.literal('input_audio_buffer.speech_started'),
  event_id: z.string().optional(),
  item_id: z.string().optional(),
  // Optional on purpose. The documented field is the accurate boundary, but it
  // is one of the two things this phase verifies against a live session — an
  // absent value has to fall back to the local audio clock, not be rejected as
  // a malformed event.
  audio_start_ms: z.number().optional(),
});

const speechStoppedSchema = z.object({
  type: z.literal('input_audio_buffer.speech_stopped'),
  event_id: z.string().optional(),
  item_id: z.string().optional(),
  audio_end_ms: z.number().optional(),
});

/** Partial text. Revises itself several times per sentence; never persisted. */
const transcriptDeltaSchema = z.object({
  type: z.literal('conversation.item.input_audio_transcription.delta'),
  event_id: z.string().optional(),
  item_id: z.string().optional(),
  delta: z.string(),
});

/** Final text for one utterance. This is what becomes an `Utterance` row. */
const transcriptCompletedSchema = z.object({
  type: z.literal('conversation.item.input_audio_transcription.completed'),
  event_id: z.string().optional(),
  item_id: z.string().optional(),
  transcript: z.string(),
});

/** Echoed back after connect and after each `session.update`. */
const sessionCreatedSchema = z.object({
  type: z.literal('session.created'),
  session: z.unknown().optional(),
});

const sessionUpdatedSchema = z.object({
  type: z.literal('session.updated'),
  session: z.unknown().optional(),
});

const errorSchema = z.object({
  type: z.literal('error'),
  error: z.object({
    type: z.string().optional(),
    code: z.string().nullish(),
    message: z.string(),
    param: z.string().nullish(),
  }),
});

const serverEventSchema = z.discriminatedUnion('type', [
  speechStartedSchema,
  speechStoppedSchema,
  transcriptDeltaSchema,
  transcriptCompletedSchema,
  sessionCreatedSchema,
  sessionUpdatedSchema,
  errorSchema,
]);

export type SpeechStartedEvent = z.infer<typeof speechStartedSchema>;
export type SpeechStoppedEvent = z.infer<typeof speechStoppedSchema>;
export type TranscriptDeltaEvent = z.infer<typeof transcriptDeltaSchema>;
export type TranscriptCompletedEvent = z.infer<
  typeof transcriptCompletedSchema
>;
export type RealtimeErrorEvent = z.infer<typeof errorSchema>;
export type ServerEvent = z.infer<typeof serverEventSchema>;

/**
 * The event types above, as a set, for telling "not ours" from "wrong shape".
 *
 * Derived from the schemas rather than written out again, so adding an event to
 * the union cannot leave it classified as unhandled. Widened to `Set<string>`
 * because it is queried with the arbitrary `type` off the wire.
 */
const HANDLED_TYPES: Set<string> = new Set(
  serverEventSchema.options.map((option) => option.shape.type.value),
);

/**
 * The outcome of reading one inbound frame.
 *
 * Three cases rather than the `event | null` that twilio-frames.ts uses, and
 * the difference is not gold-plating. Twilio sends six message types and an
 * unrecognised one is genuinely unusual, so `null` deserves a warning. OpenAI
 * emits a much larger vocabulary — `input_audio_buffer.committed`,
 * `conversation.item.added`, `rate_limits.updated` and more — several times per
 * turn. Warning on each would bury the transcripts in the log, and ignoring all
 * of them silently would hide a shape change to `.completed`, which we depend
 * on. So: an event type we do not handle is quiet, and one we *do* handle
 * arriving in the wrong shape is loud.
 */
export type ParsedFrame =
  | { kind: 'event'; event: ServerEvent }
  | { kind: 'unhandled'; type: string }
  | { kind: 'malformed'; type?: string; detail: string };

/** Reads one inbound frame. Never throws. */
export function parseServerEvent(raw: string | Buffer): ParsedFrame {
  let parsed: unknown;

  try {
    parsed = JSON.parse(typeof raw === 'string' ? raw : raw.toString('utf8'));
  } catch {
    return { kind: 'malformed', detail: 'not JSON' };
  }

  const envelope = z.object({ type: z.string() }).safeParse(parsed);

  if (!envelope.success) {
    return { kind: 'malformed', detail: 'no string `type` field' };
  }

  const { type } = envelope.data;

  if (!HANDLED_TYPES.has(type)) return { kind: 'unhandled', type };

  const result = serverEventSchema.safeParse(parsed);

  if (!result.success) {
    return {
      kind: 'malformed',
      type,
      detail: result.error.issues
        .map((issue) => `${issue.path.join('.') || '(root)'}: ${issue.message}`)
        .join('; '),
    };
  }

  return { kind: 'event', event: result.data };
}

/**
 * The two messages we send.
 *
 * As with Twilio, a malformed one produces no useful complaint from the far
 * end — here it comes back as a generic `error` event with no indication of
 * which key was wrong — so the shapes are asserted in unit tests rather than
 * trusted.
 */

export interface TurnDetectionConfig {
  threshold: number;
  prefixPaddingMs: number;
  silenceDurationMs: number;
}

/**
 * `null` means "let the model chunk the audio itself".
 *
 * Turn-detection support depends on the transcription model, and
 * `gpt-live-transcribe` does **not** accept it — a `server_vad` block comes
 * back as `Turn detection is not supported for this transcription model.
 * (invalid_value)`, verified against a live session on 2026-08-21. The
 * documented example for this model sends `null` explicitly, so we do too
 * rather than omitting the key.
 *
 * The shape is kept because other transcription models do support it, and
 * because this is the knob Phase 6 would reach for if endpointing ever needs
 * tuning against real phone noise.
 */
export type TurnDetection = TurnDetectionConfig | null;

export interface SessionConfig {
  model: string;
  /**
   * ISO 639-1 codes. `gpt-live-transcribe` takes an **array**; the singular
   * `language` belongs to older models and is rejected at connect time — on a
   * live call, not in a test.
   */
  languages: string[];
  /**
   * Latency against word error rate. Typed as a string rather than a union
   * because the full set of accepted values is not enumerated in the reference;
   * `"low"` is the documented example and our default.
   */
  delay: string;
  turnDetection: TurnDetection;
}

/**
 * The GA API requires this **nested** `session.audio.input` object. The flat
 * `input_audio_format` / `input_audio_transcription` keys of the beta are
 * rejected outright, and they are what almost every blog post still shows.
 *
 * `create_response` and `interrupt_response` are conversation-mode only and are
 * deliberately absent: in a transcription session VAD only decides how audio is
 * chunked, it does not trigger a reply.
 */
export function sessionUpdate(config: SessionConfig): string {
  return JSON.stringify({
    type: 'session.update',
    session: {
      type: 'transcription',
      audio: {
        input: {
          format: { type: 'audio/pcm', rate: 24000 },
          transcription: {
            model: config.model,
            languages: config.languages,
            delay: config.delay,
          },
          turn_detection: config.turnDetection && {
            type: 'server_vad',
            threshold: config.turnDetection.threshold,
            prefix_padding_ms: config.turnDetection.prefixPaddingMs,
            silence_duration_ms: config.turnDetection.silenceDurationMs,
          },
        },
      },
    },
  });
}

/** One batch of base64-encoded 24 kHz little-endian PCM16. */
export function appendAudio(base64Pcm16: string): string {
  return JSON.stringify({
    type: 'input_audio_buffer.append',
    audio: base64Pcm16,
  });
}
