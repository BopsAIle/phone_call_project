import { Logger } from '@nestjs/common';
import type { AiSession } from '../ai-bridge/ai-bridge.provider';
import { AI_SAMPLE_RATE } from '../ai-bridge/wire-format';
import { FrameBuffer } from '../audio/frame-buffer';
import { encodeMulaw } from '../audio/mulaw.codec';
import { leToInt16 } from '../audio/pcm';
import { Downsampler } from '../audio/resampler';
import type { OutboundAudioSink } from './audio-sink';

export interface CallSessionOptions {
  callId: string;
  streamSid: string;
  ai: AiSession;
  sink: OutboundAudioSink;
}

/**
 * One call, as a pipe between Twilio and the AI service.
 *
 * ```
 * Twilio ──mu-law 8k──► AiSession ──16k PCM16──► AI service
 * Twilio ◄─mu-law 8k─── this ◄─────16k PCM16──── AI service
 * ```
 *
 * There is no turn state machine here any more. Deciding when the caller has
 * finished, when to reply, and when to stop is the AI service's job now — this
 * class converts audio and owns one thing the AI service cannot reach: Twilio's
 * playback buffer.
 *
 * Inbound conversion lives in `AiSession`; outbound lives here, because only
 * this side knows Twilio wants exactly 160-byte frames.
 */
export class CallSession {
  private readonly logger: Logger;
  private readonly options: CallSessionOptions;

  /**
   * One instance each for the whole call, not one per utterance.
   *
   * The AI service sends a continuous stream rather than a request per sentence,
   * so filter state and frame alignment have to run through it. A `Downsampler`
   * restarted mid-stream rings at the seam; a `FrameBuffer` restarted loses the
   * partial frame it was holding.
   */
  private readonly downsampler = new Downsampler(AI_SAMPLE_RATE);
  private readonly frames = new FrameBuffer();

  /**
   * A PCM16 sample split across two inbound frames.
   *
   * The AI service guarantees whole samples, so this should always be empty —
   * but `leToInt16` drops a trailing odd byte by design, and one dropped byte
   * shifts every sample after it by one, which is not silence but loud static.
   * Cheap insurance against a guarantee held by someone else's code.
   */
  private carry = Buffer.alloc(0);

  private closed = false;

  constructor(options: CallSessionOptions) {
    this.options = options;
    this.logger = new Logger(`CallSession[${options.callId}]`);

    this.wire();
  }

  get callId(): string {
    return this.options.callId;
  }

  get streamSid(): string {
    return this.options.streamSid;
  }

  /** Straight from the Twilio `media` frame, already base64-decoded. */
  pushAudio(mulaw8k: Buffer): void {
    if (this.closed) return;

    this.options.ai.pushAudio(mulaw8k);
  }

  /**
   * Stops the agent talking, as though the caller had interrupted.
   *
   * Exists for the dev client and the replay harness: driving barge-in from a
   * fixture's own speech would be timing-dependent and flaky, and this is the
   * behaviour that most needs a deterministic offline test. In production the
   * trigger is the AI service's `interrupt` event, which lands on the same path.
   */
  interrupt(): void {
    this.bargeIn();
  }

  async close(): Promise<void> {
    this.closed = true;

    /**
     * The tail, padded to a whole frame.
     *
     * The AI service sends no end-of-response signal, so `FrameBuffer` holds
     * anything under 160 bytes until the next audio arrives. Mid-call that is at
     * most 20 ms and inaudible; at the end of the call there is no "next audio",
     * so without this the last fragment of the final utterance is dropped.
     */
    const tail = this.frames.flush();
    if (tail) this.options.sink.playFrame(tail);

    await this.options.ai.close();
  }

  // --- inbound ----------------------------------------------------------

  private wire(): void {
    const { ai } = this.options;

    ai.onAudio((pcm) => {
      this.handleAudio(pcm);
    });

    ai.onInterrupt(() => {
      // Routine, and specifically *not* an error: the AI service sends this as
      // soon as its VAD fires, which can be before it has sent any audio for the
      // turn. Clearing an empty Twilio buffer is a no-op.
      this.logger.debug('Barge-in reported by the AI service');
      this.bargeIn();
    });
  }

  /**
   * Agent audio on its way to the caller: 16 kHz PCM16 → 20 ms mu-law frames.
   *
   * Frames arrive at whatever size the AI service's synthesiser produced, which
   * has no relationship to Twilio's 20 ms — hence the carry and the frame
   * buffer.
   */
  private handleAudio(pcm: Buffer): void {
    if (this.closed) return;

    const bytes =
      this.carry.length === 0 ? pcm : Buffer.concat([this.carry, pcm]);

    const usable = bytes.length - (bytes.length % 2);

    // Copied rather than kept as a view: `subarray` aliases the buffer, and the
    // next `concat` would then read bytes the socket may have reused.
    this.carry = Buffer.from(bytes.subarray(usable));

    if (usable === 0) return;

    const mulaw = encodeMulaw(
      this.downsampler.process(leToInt16(bytes.subarray(0, usable))),
    );

    for (const frame of this.frames.push(mulaw)) {
      this.options.sink.playFrame(frame);
    }
  }

  /**
   * Drop what Twilio has buffered but not yet played.
   *
   * The `clear` is the step that is easy to forget and produces the signature
   * bug: the AI service stopping does nothing about audio already handed over,
   * so the logs insist the agent stopped while the caller still hears it.
   *
   * The partial frame goes too. It belongs to the abandoned turn, and would
   * otherwise be prepended to the first frame of the next reply.
   *
   * The `Downsampler` is deliberately left alone. Resetting a 48-tap filter
   * mid-stream rings at the seam, and its decaying history is inaudible against
   * the hard discontinuity barge-in already creates.
   */
  private bargeIn(): void {
    this.options.sink.clear();
    this.frames.reset();
  }
}
