import { Injectable, Logger } from '@nestjs/common';
import { ConfigService } from '@nestjs/config';
import { AiBridgeService } from '../ai-bridge/ai-bridge.service';
import type { Env } from '../config/env.schema';
import type { OutboundAudioSink } from './audio-sink';
import { CallSession } from './call-session';

/**
 * The live conversations, keyed by `streamSid`.
 *
 * `streamSid` rather than `callId` because every inbound and outbound Twilio
 * frame carries it, so it is the key the transport already has in hand.
 */
@Injectable()
export class ConversationService {
  private readonly logger = new Logger(ConversationService.name);
  private readonly sessions = new Map<string, CallSession>();
  private readonly defaultLocale: 'en' | 'de';

  constructor(
    private readonly ai: AiBridgeService,
    config: ConfigService<Env, true>,
  ) {
    this.defaultLocale = config.get('DEFAULT_LOCALE', { infer: true }) ?? 'en';
  }

  /**
   * Opens a conversation for one call.
   *
   * The AI session resolves in a microtask — it buffers while its socket
   * connects — so the caller can await this on Twilio's `start` without putting
   * a network round trip in front of the first audio frame.
   *
   * The greeting is not played here, or anywhere in this repo: the AI service
   * speaks it on receiving `session.init`, which happens the moment its socket
   * opens. Audio can therefore start flowing back before this method returns,
   * which is safe because the sink is a closure over the Twilio socket rather
   * than a lookup in a registry this session is not yet in.
   */
  async create(opts: {
    callId: string;
    streamSid: string;
    greeting: string;
    storeName: string;
    timezone: string;
    sink: OutboundAudioSink;
    locale?: 'en' | 'de';
  }): Promise<CallSession> {
    const ai = await this.ai.createSession({
      callId: opts.callId,
      storeName: opts.storeName,
      timezone: opts.timezone,
      locale: opts.locale ?? this.defaultLocale,
      greeting: opts.greeting,
    });

    const session = new CallSession({
      callId: opts.callId,
      streamSid: opts.streamSid,
      ai,
      sink: opts.sink,
    });

    this.sessions.set(opts.streamSid, session);
    this.logger.log(`Conversation open for call ${opts.callId}`);

    return session;
  }

  get(streamSid: string): CallSession | undefined {
    return this.sessions.get(streamSid);
  }

  /**
   * Idempotent, because the gateway's teardown is: `stop`, `close`, and `error`
   * can all fire for the same call.
   */
  async destroy(streamSid: string): Promise<void> {
    const session = this.sessions.get(streamSid);
    if (!session) return;

    this.sessions.delete(streamSid);

    try {
      await session.close();
    } catch (error: unknown) {
      this.logger.error(
        `Could not close conversation for ${streamSid}: ${
          error instanceof Error ? error.message : String(error)
        }`,
      );
    }
  }
}
