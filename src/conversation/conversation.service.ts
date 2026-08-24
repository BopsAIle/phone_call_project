import { Injectable, Logger } from '@nestjs/common';
import { ConfigService } from '@nestjs/config';
import type { Env } from '../config/env.schema';
import { OpenAiLlmService } from '../llm/openai-llm.service';
import { PrismaService } from '../prisma/prisma.service';
import { OpenAiRealtimeSttService } from '../stt/openai-realtime-stt.service';
import { GreetingCache } from '../tts/greeting-cache';
import { OpenAiTtsService } from '../tts/openai-tts.service';
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
    private readonly stt: OpenAiRealtimeSttService,
    private readonly llm: OpenAiLlmService,
    private readonly tts: OpenAiTtsService,
    private readonly greetings: GreetingCache,
    private readonly prisma: PrismaService,
    config: ConfigService<Env, true>,
  ) {
    this.defaultLocale = config.get('DEFAULT_LOCALE', { infer: true }) ?? 'en';
  }

  /**
   * Opens a conversation for one call.
   *
   * The STT session resolves in a microtask — it buffers while its socket
   * connects — so the caller can await this on Twilio's `start` without putting
   * a network round trip in front of the first audio frame.
   *
   * The greeting is *not* played here. The gateway calls `start()` once the
   * session is registered, so a mark echoing back cannot arrive before there is
   * anything to route it to.
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
    const locale = opts.locale ?? this.defaultLocale;

    const stt = await this.stt.createSession({
      locale,
      callId: opts.callId,
    });

    const session = new CallSession({
      callId: opts.callId,
      streamSid: opts.streamSid,
      locale,
      greeting: opts.greeting,
      storeName: opts.storeName,
      timezone: opts.timezone,
      stt,
      llm: this.llm,
      tts: this.tts,
      greetings: this.greetings,
      sink: opts.sink,
      prisma: this.prisma,
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
