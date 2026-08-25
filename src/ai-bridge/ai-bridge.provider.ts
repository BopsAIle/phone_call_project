import type { SessionContext } from './wire-format';

/**
 * The AI service, as the conversation layer needs it.
 *
 * Deliberately the same shape as the `SttSession` it replaces: audio in exactly
 * as Twilio delivers it, results out through callbacks. Keeping mu-law at the
 * boundary is what lets the resampling, batching, and wire format stay entirely
 * inside the implementation — the conversation layer never learns what rate the
 * AI team wanted.
 */
export interface AiSession {
  /** Straight from the Twilio `media` frame, already base64-decoded. */
  pushAudio(mulaw8k: Buffer): void;

  /**
   * Agent audio, as raw wideband PCM16 bytes exactly as they arrived.
   *
   * Not framed and not converted — chunk boundaries are wherever the AI service
   * and the network put them. Turning this into 20 ms mu-law frames is the
   * caller's job, because only the caller knows when an utterance has ended and
   * the tail needs padding.
   */
  onAudio(cb: (pcm: Buffer) => void): void;

  /**
   * The barge-in trigger: the caller started talking over the agent.
   *
   * This can only come from the AI service, because voice activity detection
   * lives there — and it can only be *acted* on here, because the audio already
   * playing sits in Twilio's buffer and nothing but a `clear` on the Twilio
   * socket will empty it. Knowledge on one side, actuator on the other.
   */
  onInterrupt(cb: () => void): void;

  close(): Promise<void>;
}

export interface AiBridgeProvider {
  /**
   * Opens one session per call. Never pooled: a session carries one
   * conversation's audio and context, so crossing two callers would be both
   * wrong and a privacy breach.
   */
  createSession(context: SessionContext): Promise<AiSession>;
}
