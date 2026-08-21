/**
 * Where a `CallSession` writes the agent's voice.
 *
 * The gateway builds one per call, closing over the socket and `streamSid`, and
 * hands it down at `create()`. The conversation layer therefore never calls back
 * into the transport: routing barge-in through `MediaStreamGateway`'s registry
 * instead would make a cycle (gateway → ConversationService → CallSession →
 * gateway) and leak the gateway's private session type across the seam.
 *
 * All three methods are the messages Twilio accepts from us, and nothing else.
 */
export interface OutboundAudioSink {
  /** One 20 ms, 160-byte mu-law frame, to be played to the caller. */
  playFrame(mulawFrame: Buffer): void;

  /**
   * Echoed back by Twilio once the audio queued ahead of it has finished
   * playing — the only reliable signal that the agent has genuinely stopped
   * talking, since sending the last frame is not the same as the caller hearing
   * it.
   */
  mark(name: string): void;

  /**
   * Drops audio Twilio has buffered but not yet played. The barge-in primitive.
   *
   * Without it, aborting our own streams achieves nothing about the seconds of
   * audio already handed over: the logs say the agent stopped while the caller
   * still hears it talking.
   */
  clear(): void;
}
