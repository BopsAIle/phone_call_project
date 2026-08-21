import { Logger } from '@nestjs/common';
import { Role } from '../generated/prisma/enums';
import type { LlmProvider } from '../llm/llm.provider';
import type { ChatMessage } from '../llm/llm.types';
import { receptionistPrompt } from '../llm/prompts/receptionist.en';
import type { PrismaService } from '../prisma/prisma.service';
import type { SttSession } from '../stt/stt.provider';
import type { GreetingCache } from '../tts/greeting-cache';
import type { TtsProvider } from '../tts/tts.provider';
import type { OutboundAudioSink } from './audio-sink';

/**
 * ```
 * GREETING ──► LISTENING ──► THINKING ──► SPEAKING ──► LISTENING
 *                   ▲                         │
 *                   └──────── barge-in ───────┘
 * ```
 */
export type TurnState = 'GREETING' | 'LISTENING' | 'THINKING' | 'SPEAKING';

export interface CallSessionOptions {
  callId: string;
  streamSid: string;
  locale: 'en' | 'de';
  greeting: string;
  storeName: string;
  timezone: string;
  stt: SttSession;
  llm: LlmProvider;
  tts: TtsProvider;
  greetings: GreetingCache;
  sink: OutboundAudioSink;
  prisma: PrismaService;
}

/** 20 ms per Twilio frame — a monotonic clock in the medium being measured. */
const FRAME_MS = 20;

/**
 * One call's conversation.
 *
 * Owns the turn state machine explicitly, because the classic voice-agent
 * failure is two replies playing over each other after a late stream completes
 * for a turn the caller has already moved on from. Every transition here is
 * driven by an STT event, a mark echoing back from Twilio, or a stream ending.
 */
export class CallSession {
  private readonly logger: Logger;
  private readonly options: CallSessionOptions;

  private state: TurnState = 'GREETING';
  private history: ChatMessage[] = [];

  /**
   * Marks sent but not yet echoed back by Twilio.
   *
   * Empty means the agent has genuinely stopped talking. "I sent the last
   * frame" does not: Twilio may still be holding seconds of it.
   */
  private readonly pendingMarks = new Set<string>();
  private markSeq = 0;

  /**
   * The in-flight turn, or undefined between turns.
   *
   * Also the turn's identity: an aborted turn's async loop does not stop
   * synchronously, so every step re-checks that it is still the current one
   * before touching shared state.
   */
  private turn?: AbortController;

  /** `t0` for the latency budget: when the caller stopped talking. */
  private speechStoppedAt?: number;

  /** Offset into the call's audio, by frame count rather than wall clock. */
  private framesPushed = 0;

  private closed = false;

  constructor(options: CallSessionOptions) {
    this.options = options;
    this.logger = new Logger(`CallSession[${options.callId}]`);

    this.history.push({
      role: 'system',
      content: receptionistPrompt({
        storeName: options.storeName,
        timezone: options.timezone,
      }),
    });

    this.wire();
  }

  get callId(): string {
    return this.options.callId;
  }

  get streamSid(): string {
    return this.options.streamSid;
  }

  /** Exposed for the state-machine tests and for log correlation. */
  get turnState(): TurnState {
    return this.state;
  }

  /** Straight from the Twilio `media` frame, already base64-decoded. */
  pushAudio(mulaw8k: Buffer): void {
    this.framesPushed++;
    this.options.stt.pushAudio(mulaw8k);
  }

  /**
   * Greets the caller. Called by the gateway once the stream has started.
   *
   * Silence at pickup makes callers repeat "hello?" or hang up, so this runs
   * before anything else and does not wait for the caller to speak first.
   */
  async start(): Promise<void> {
    const controller = new AbortController();
    this.turn = controller;

    try {
      const frames = await this.options.greetings.frames({
        text: this.options.greeting,
        locale: this.options.locale,
        signal: controller.signal,
      });

      if (this.closed || this.turn !== controller) return;

      for (const frame of frames) this.options.sink.playFrame(frame);
      this.emitMark();

      this.history.push({
        role: 'assistant',
        content: this.options.greeting,
      });
      this.persistAgentUtterance(this.options.greeting, 0, undefined);
    } catch (error: unknown) {
      // Loud, and then carry on listening. A call with no greeting is far
      // better than a call that drops; Phase 6 turns this into a spoken
      // apology rather than an awkward silence.
      this.logger.error(
        `Could not play the greeting: ${
          error instanceof Error ? error.message : String(error)
        }`,
      );

      if (this.turn === controller) {
        this.turn = undefined;
        this.state = 'LISTENING';
      }
    }
  }

  /**
   * Interrupts the agent as though the caller had started talking.
   *
   * Exists for the dev client and the replay harness: driving barge-in from a
   * fixture's own speech would be timing-dependent and flaky, and this is the
   * one behaviour in the phase that most needs a deterministic offline test.
   * Returns whether there was anything to interrupt.
   */
  interrupt(): boolean {
    if (this.state !== 'SPEAKING' && this.state !== 'THINKING') return false;

    this.logger.log(`Interrupted during ${this.state}`);
    this.bargeIn();

    return true;
  }

  onMarkPlayed(name: string): void {
    // The dev controller injects `dev-*` marks that were never ours; they fall
    // out of the set lookup harmlessly.
    if (!this.pendingMarks.delete(name)) return;

    if (this.pendingMarks.size > 0) return;
    if (this.state !== 'SPEAKING' && this.state !== 'GREETING') return;

    this.turn = undefined;
    this.state = 'LISTENING';
    this.logger.debug('Finished speaking');
  }

  setLocale(locale: 'en' | 'de'): void {
    this.options.locale = locale;
    this.options.stt.setLocale(locale);
  }

  async close(): Promise<void> {
    this.closed = true;
    this.turn?.abort();
    this.turn = undefined;

    await this.options.stt.close();
  }

  // --- inbound events ---------------------------------------------------

  private wire(): void {
    const { stt } = this.options;

    stt.onPartial((text) => {
      // Partials revise themselves several times per sentence. Never persisted,
      // and never fed to the LLM.
      this.logger.debug(`… ${text}`);
    });

    stt.onFinal((text, meta) => {
      this.handleFinal(text, meta);
    });

    stt.onSpeechStarted(() => {
      this.handleSpeechStarted();
    });

    stt.onSpeechStopped(() => {
      this.speechStoppedAt = Date.now();
      this.logger.debug('Caller stopped speaking');
    });
  }

  /**
   * The caller has started talking. If the agent is mid-reply, stop it.
   *
   * Only while `SPEAKING`, deliberately. The signal behind this is a
   * transcript-activity gate, not a VAD edge, so during `THINKING` it almost
   * always means the caller's *own* sentence is continuing after a pause the
   * endpointer called early — and there is no audio playing to interrupt
   * anyway. Cancelling there would throw away a turn that the merge in
   * `handleFinal` is about to complete correctly.
   */
  private handleSpeechStarted(): void {
    if (this.state !== 'SPEAKING') return;

    this.logger.debug('Barge-in while speaking');
    this.bargeIn();
  }

  private handleFinal(
    text: string,
    meta: { startMs: number; endMs: number },
  ): void {
    /**
     * Transcripts are personal data from Phase 2 onward, so the shape of the
     * utterance goes to `log` and the words themselves only to `debug` — which
     * main.ts silences in production.
     */
    this.logger.log(
      `Caller utterance: ${text.length} chars over ${meta.endMs - meta.startMs}ms`,
    );
    this.logger.debug(`Transcript: ${text}`);

    this.persistUtterance({
      role: Role.CALLER,
      text,
      startMs: meta.startMs,
      endMs: meta.endMs,
    });

    if (this.closed) return;

    const trimmed = text.trim();
    if (trimmed.length === 0) return;

    /**
     * `gpt-live-transcribe` chunks audio itself, so one spoken turn can arrive
     * as several finals. Merging into the turn already in flight — rather than
     * debouncing every turn by a few hundred milliseconds — keeps the common
     * single-final case free, at the cost of one wasted partial completion in
     * the rare case there are two.
     */
    if (this.state === 'THINKING') {
      this.logger.debug('Second final while thinking; merging and restarting');
      this.mergeIntoLastUserMessage(trimmed);
      this.turn?.abort();
      void this.runTurn();
      return;
    }

    // Mostly unreachable: `speech_started` fires first and has already moved
    // us to LISTENING. Handled rather than asserted, because "mostly" is not
    // "never" on a live phone line.
    if (this.state === 'SPEAKING' || this.state === 'GREETING') {
      this.bargeIn();
    }

    this.history.push({ role: 'user', content: trimmed });
    void this.runTurn();
  }

  // --- the turn ---------------------------------------------------------

  private async runTurn(): Promise<void> {
    const controller = new AbortController();
    this.turn = controller;
    this.state = 'THINKING';

    const t0 = this.speechStoppedAt ?? Date.now();
    const spoken: string[] = [];
    let firstFrameAt: number | undefined;
    let startMs = this.audioMs;

    const { sentences, toolCalls } = this.options.llm.respond({
      messages: this.history,
      tools: [],
      signal: controller.signal,
    });

    // Phase 4 awaits this. Attach a handler now so an abandoned turn can never
    // surface as an unhandled rejection and take the process down with it.
    void toolCalls.catch(() => undefined);

    try {
      for await (const sentence of sentences) {
        if (this.isStale(controller)) return;

        spoken.push(sentence);

        for await (const frame of this.options.tts.synthesize({
          text: sentence,
          locale: this.options.locale,
          signal: controller.signal,
        })) {
          if (this.isStale(controller)) return;

          if (firstFrameAt === undefined) {
            firstFrameAt = Date.now();
            startMs = this.audioMs;
            this.state = 'SPEAKING';
            this.logger.log(`Reply started +${firstFrameAt - t0}ms after t0`);
          }

          this.options.sink.playFrame(frame);
        }

        // One mark per sentence, so a long reply reports progress rather than
        // going silent until the very end.
        this.emitMark();
      }
    } catch (error: unknown) {
      // An aborted turn is the normal barge-in path, not a failure.
      if (!controller.signal.aborted && !this.isStale(controller)) {
        this.logger.error(
          `Turn failed: ${error instanceof Error ? error.message : String(error)}`,
        );
        this.recover(controller);
      }

      return;
    }

    if (this.isStale(controller)) return;

    const reply = spoken.join(' ').trim();

    if (reply.length === 0) {
      // The model said nothing at all. Do not sit in THINKING waiting for a
      // mark that will never arrive.
      this.recover(controller);
      return;
    }

    this.history.push({ role: 'assistant', content: reply });
    this.persistAgentUtterance(
      reply,
      startMs,
      firstFrameAt === undefined ? undefined : firstFrameAt - t0,
    );
  }

  /**
   * Abort, flush Twilio's buffer, and listen.
   *
   * The `clear` is the step that is easy to forget and produces the signature
   * bug: aborting our own streams does nothing about audio already handed over,
   * so the logs insist the agent stopped while the caller still hears it.
   */
  private bargeIn(): void {
    this.turn?.abort();
    this.turn = undefined;

    this.options.sink.clear();
    this.pendingMarks.clear();
    this.state = 'LISTENING';
  }

  /** Back to LISTENING after a turn that produced nothing playable. */
  private recover(controller: AbortController): void {
    if (this.turn !== controller) return;

    this.turn = undefined;
    this.pendingMarks.clear();
    this.state = 'LISTENING';
  }

  /**
   * True once this turn has been superseded or aborted.
   *
   * An aborted turn's loops do not stop synchronously, so without this a
   * restarted turn would race the one it replaced — which is precisely the
   * overlapping-replies failure the state machine exists to prevent.
   */
  private isStale(controller: AbortController): boolean {
    return this.closed || this.turn !== controller || controller.signal.aborted;
  }

  private emitMark(): void {
    const name = `agent-${++this.markSeq}`;
    this.pendingMarks.add(name);
    this.options.sink.mark(name);
  }

  private get audioMs(): number {
    return this.framesPushed * FRAME_MS;
  }

  // --- persistence ------------------------------------------------------

  private persistAgentUtterance(
    text: string,
    startMs: number,
    latencyMs: number | undefined,
  ): void {
    this.persistUtterance({
      role: Role.AGENT,
      text,
      startMs,
      // An agent utterance has no measured end: we know when it started
      // playing, not when the caller finished hearing it.
      endMs: null,
      latencyMs,
    });
  }

  private persistUtterance(data: {
    role: Role;
    text: string;
    startMs: number;
    endMs: number | null;
    latencyMs?: number;
  }): void {
    // Fire and forget. A phone call must not end because Postgres hiccuped,
    // and awaiting here would put a database round trip inside a socket's
    // event handling.
    void this.options.prisma.utterance
      .create({ data: { callId: this.options.callId, ...data } })
      .catch((error: unknown) => {
        this.logger.error(
          `Could not persist utterance: ${
            error instanceof Error ? error.message : String(error)
          }`,
        );
      });
  }

  private mergeIntoLastUserMessage(text: string): void {
    const last = this.history[this.history.length - 1];

    if (last?.role === 'user') {
      last.content = `${last.content} ${text}`;
      return;
    }

    this.history.push({ role: 'user', content: text });
  }
}
