import { Injectable, Logger } from '@nestjs/common';
import { PrismaService } from '../prisma/prisma.service';
import { OpenAiRealtimeSttService } from '../stt/openai-realtime-stt.service';
import { CallSession } from './call-session';

/**
 * The live conversations, keyed by `streamSid`.
 *
 * `streamSid` rather than `callId` because every inbound and outbound Twilio
 * frame carries it, so it is the key the transport already has in hand — the
 * same reason `MediaStreamGateway.findByStreamSid` exists for Phase 3's
 * barge-in lookups.
 */
@Injectable()
export class ConversationService {
  private readonly logger = new Logger(ConversationService.name);
  private readonly sessions = new Map<string, CallSession>();

  constructor(
    private readonly stt: OpenAiRealtimeSttService,
    private readonly prisma: PrismaService,
  ) {}

  /**
   * Opens a transcription session for one call.
   *
   * Resolves in a microtask — the STT session buffers while its socket is still
   * connecting — so the caller can await this on Twilio's `start` without
   * putting a network round trip in front of the first audio frame.
   */
  async create(opts: {
    callId: string;
    streamSid: string;
    locale?: 'en' | 'de';
  }): Promise<CallSession> {
    const stt = await this.stt.createSession({
      locale: opts.locale,
      callId: opts.callId,
    });

    const session = new CallSession(
      opts.callId,
      opts.streamSid,
      stt,
      this.prisma,
    );

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
