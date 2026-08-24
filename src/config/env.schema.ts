import { z } from 'zod';

/**
 * Every environment variable the process needs, validated once at boot.
 *
 * The point of validating here rather than at the point of use is that a
 * missing OPENAI_API_KEY becomes a startup crash instead of a 500 in the
 * middle of a phone call.
 *
 * zod 4: string formats are top-level functions (`z.url()`), not methods on
 * `z.string()`.
 */
export const envSchema = z.object({
  NODE_ENV: z
    .enum(['development', 'test', 'production'])
    .default('development'),
  PORT: z.coerce.number().default(3000),

  DATABASE_URL: z.url(),

  OPENAI_API_KEY: z.string().min(1),

  TWILIO_ACCOUNT_SID: z.string().startsWith('AC').length(34),
  TWILIO_AUTH_TOKEN: z.string().min(1),
  TWILIO_PHONE_NUMBER: z
    .string()
    .regex(/^\+[1-9]\d{6,14}$/, 'must be E.164, e.g. +15551234567'),

  /** Tunnel or deployed host; the wss:// media-stream URL is built from it. */
  PUBLIC_BASE_URL: z.url(),

  /**
   * Seed values only. After `prisma db seed` the Store row is the source of
   * truth for name, timezone, locale, and greetings.
   */
  STORE_NAME: z.string().min(1),
  STORE_TIMEZONE: z.string().default('Europe/Berlin'),
  DEFAULT_LOCALE: z.enum(['en', 'de']).default('en'),

  LLM_MODEL: z.string().default('gpt-5.6-terra'),
  /**
   * Must be a model that supports `turn_detection`, or the session falls back to
   * transcript-activity endpointing and every reply is ~2.5 s slower.
   * `gpt-live-transcribe` and `gpt-realtime-whisper` do not; see
   * src/stt/realtime-events.types.ts for the probed table.
   */
  STT_MODEL: z.string().default('gpt-4o-transcribe'),
  TTS_MODEL: z.string().default('gpt-4o-mini-tts'),
  TTS_VOICE: z.string().default('marin'),
});

export type Env = z.infer<typeof envSchema>;

/**
 * Passed to `ConfigModule.forRoot({ validate })`.
 *
 * A raw ZodError prints as a wall of JSON, which makes a misconfigured
 * deployment needlessly hard to diagnose. Flatten it to one line per problem,
 * each naming the offending key.
 */
export function validateEnv(config: Record<string, unknown>): Env {
  const parsed = envSchema.safeParse(config);

  if (!parsed.success) {
    const detail = parsed.error.issues
      .map((issue) => `${issue.path.join('.') || '(root)'}: ${issue.message}`)
      .join('\n  ');

    throw new Error(`Invalid environment configuration:\n  ${detail}`);
  }

  return parsed.data;
}
