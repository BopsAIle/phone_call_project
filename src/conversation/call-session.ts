import { Logger } from '@nestjs/common';
import { Role } from '../generated/prisma/enums';
import type { PrismaService } from '../prisma/prisma.service';
import type { SttSession } from '../stt/stt.provider';

/**
 * One call's conversation state.
 *
 * In this phase it is deliberately thin: it hears, it logs, it persists. Phase 3
 * grows the turn state machine (GREETING → LISTENING → THINKING → SPEAKING) and
 * the barge-in wiring into this same class, which is why it exists now rather
 * than living in the gateway — the gateway's job is the Twilio socket, and
 * conversation state does not belong to a transport.
 */
export class CallSession {
  private readonly logger: Logger;

  /**
   * When the caller last stopped talking, as `t0` for Phase 3's latency budget.
   *
   * Captured here so Phase 3 measures first-token and first-audio against a
   * value the conversation layer owns, instead of reaching back into the STT
   * implementation for it.
   */
  private speechStoppedAt?: number;

  constructor(
    readonly callId: string,
    readonly streamSid: string,
    private readonly stt: SttSession,
    private readonly prisma: PrismaService,
  ) {
    this.logger = new Logger(`CallSession[${callId}]`);
    this.wire();
  }

  /** Straight from the Twilio `media` frame, already base64-decoded. */
  pushAudio(mulaw8k: Buffer): void {
    this.stt.pushAudio(mulaw8k);
  }

  /** `t0` for Phase 3. Undefined until the caller has finished a first turn. */
  get lastSpeechStoppedAt(): number | undefined {
    return this.speechStoppedAt;
  }

  setLocale(locale: 'en' | 'de'): void {
    this.stt.setLocale(locale);
  }

  async close(): Promise<void> {
    await this.stt.close();
  }

  private wire(): void {
    this.stt.onPartial((text) => {
      // Partials revise themselves several times per sentence. Never persisted,
      // and never fed to the LLM in Phase 3.
      this.logger.debug(`… ${text}`);
    });

    this.stt.onFinal((text, meta) => {
      this.handleFinal(text, meta);
    });

    this.stt.onSpeechStarted(() => {
      // Phase 3 hangs barge-in off this: abort the in-flight LLM and TTS
      // streams, then send Twilio a `clear`. It fires reliably today so that
      // Phase 3 is wiring rather than debugging.
      this.logger.debug('Caller started speaking');
    });

    this.stt.onSpeechStopped(() => {
      this.speechStoppedAt = Date.now();
      this.logger.debug('Caller stopped speaking');
    });
  }

  private handleFinal(
    text: string,
    meta: { startMs: number; endMs: number },
  ): void {
    /**
     * Transcripts are personal data from this phase onward, so the shape of the
     * utterance goes to `log` and the words themselves only to `debug` — which
     * main.ts silences in production. Phase 6 owns the retention policy for the
     * rows themselves.
     */
    this.logger.log(
      `Caller utterance: ${text.length} chars over ${meta.endMs - meta.startMs}ms`,
    );
    this.logger.debug(`Transcript: ${text}`);

    // Fire and forget. A phone call must not end because Postgres hiccuped, and
    // awaiting here would put a database round trip inside the socket's event
    // handling. Same trade the gateway makes when finalising a Call row.
    void this.prisma.utterance
      .create({
        data: {
          callId: this.callId,
          role: Role.CALLER,
          text,
          startMs: meta.startMs,
          endMs: meta.endMs,
        },
      })
      .catch((error: unknown) => {
        this.logger.error(
          `Could not persist utterance: ${
            error instanceof Error ? error.message : String(error)
          }`,
        );
      });
  }
}
