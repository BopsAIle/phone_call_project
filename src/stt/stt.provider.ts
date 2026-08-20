/**
 * Speech-to-text, as the conversation layer needs it. Implemented in Phase 2
 * by an OpenAI realtime-transcription adapter.
 *
 * Audio comes in exactly as Twilio delivers it — 8 kHz mu-law — so every
 * resampling concern stays inside the implementation.
 */
export interface SttSession {
  /** Straight from the Twilio `media` frame, already base64-decoded. */
  pushAudio(mulaw8k: Buffer): void;

  onPartial(cb: (text: string) => void): void;
  onFinal(
    cb: (text: string, meta: { startMs: number; endMs: number }) => void,
  ): void;

  /** The barge-in trigger: the caller started talking over the agent. */
  onSpeechStarted(cb: () => void): void;
  onSpeechStopped(cb: () => void): void;

  setLocale(locale: 'en' | 'de'): void;

  close(): Promise<void>;
}

export interface SttProvider {
  createSession(opts: { locale?: 'en' | 'de' }): Promise<SttSession>;
}
