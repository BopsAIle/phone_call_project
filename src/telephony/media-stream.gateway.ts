import { BeforeApplicationShutdown, Injectable, Logger } from '@nestjs/common';
import type { Server } from 'http';
import { WebSocket, WebSocketServer } from 'ws';
import type { OutboundAudioSink } from '../conversation/audio-sink';
import type { CallSession } from '../conversation/call-session';
import { ConversationService } from '../conversation/conversation.service';
import { PrismaService } from '../prisma/prisma.service';
import { CallStatus } from '../generated/prisma/enums';
import { MEDIA_STREAM_PATH } from './twiml.service';
import {
  EXPECTED_MEDIA_FORMAT,
  type StartFrame,
  clearMessage,
  markMessage,
  mediaMessage,
  parseInboundFrame,
} from './twilio-frames';

/**
 * One live call's socket state.
 *
 * Keyed by the socket rather than by `streamSid`, because a socket that closes
 * before the `start` frame arrives has no `streamSid` at all and would leak.
 */
interface MediaStreamSession {
  socket: WebSocket;
  streamSid?: string;
  callId?: string;
  /** From the `Call` row, so the `stop` path can compute a duration without a read. */
  startedAt?: Date;
  /**
   * Held directly rather than looked up per frame.
   *
   * A map lookup 50 times a second per call is the smaller reason; the real one
   * is that it makes the "no conversation yet" window explicit at the one place
   * that has to tolerate it.
   */
  conversation?: CallSession;
  framesIn: number;
  framesOut: number;
}

/**
 * The audio entry point: a raw `ws` server on `/media-stream`.
 *
 * Nest's WebSocket adapters do not fit. The socket.io adapter speaks a
 * different protocol entirely, and `@nestjs/platform-ws`'s `WsAdapter` expects
 * a `{ event, data }` envelope while Twilio sends `{ event, media: {...} }` —
 * the payload is a sibling of `event`, not nested under `data`.
 *
 * Inbound `media` frames go to the conversation layer for transcription.
 * Outbound audio is the agent's own voice, written through the
 * `OutboundAudioSink` handed to the conversation at `start`.
 *
 * Phase 1's echo is gone as of Phase 3: with real speech to play, echoing the
 * caller back would put them underneath the agent.
 */
@Injectable()
export class MediaStreamGateway implements BeforeApplicationShutdown {
  private readonly logger = new Logger(MediaStreamGateway.name);
  private readonly sessions = new Map<WebSocket, MediaStreamSession>();
  private readonly byStreamSid = new Map<string, MediaStreamSession>();
  private server?: WebSocketServer;

  constructor(
    private readonly prisma: PrismaService,
    private readonly conversations: ConversationService,
  ) {}

  /**
   * Called from `main.ts` once the HTTP server is listening.
   *
   * The `ws` server has to share Nest's HTTP server (Twilio connects to the
   * same host and port), but only `main.ts` holds it — hence a method rather
   * than construction in the constructor.
   */
  attach(server: Server): void {
    this.server = new WebSocketServer({ server, path: MEDIA_STREAM_PATH });

    this.server.on('connection', (socket: WebSocket) => {
      this.handleConnection(socket);
    });

    this.logger.log(`Media stream gateway listening on ${MEDIA_STREAM_PATH}`);
  }

  /**
   * Used only by the dev controller, to push a `mark` or `clear` into a live
   * stream on demand.
   *
   * Not the barge-in path: the conversation writes through the
   * `OutboundAudioSink` it was given, so nothing in production looks a session
   * up by `streamSid` to send audio.
   */
  findByStreamSid(streamSid: string): MediaStreamSession | undefined {
    return this.byStreamSid.get(streamSid);
  }

  /**
   * Closes every live socket, and it must be *this* hook.
   *
   * Nest's shutdown order is `onModuleDestroy` → `beforeApplicationShutdown` →
   * **close the HTTP server** → `onApplicationShutdown`. An open WebSocket
   * keeps that HTTP close pending forever, so doing this work in
   * `onApplicationShutdown` deadlocks: the hook that would close the sockets
   * sits behind a close that is waiting on those same sockets. The process then
   * hangs until the orchestrator SIGKILLs it, cutting any other live call.
   *
   * Verified by the shutdown case in test/media-stream.e2e-spec.ts, which fails
   * within seconds if this moves back to `onApplicationShutdown`.
   */
  async beforeApplicationShutdown(): Promise<void> {
    for (const session of [...this.sessions.values()]) {
      await this.teardown(session, 'error');
      session.socket.terminate();
    }

    await new Promise<void>((resolve) => {
      if (!this.server) return resolve();
      this.server.close(() => resolve());
    });
  }

  private handleConnection(socket: WebSocket): void {
    const session: MediaStreamSession = { socket, framesIn: 0, framesOut: 0 };
    this.sessions.set(socket, session);

    socket.on('message', (raw: Buffer) => {
      // Never let a rejection escape into the socket's event loop: an
      // unhandled one takes down the process, and with it every other call.
      void this.handleFrame(session, raw).catch((error: unknown) => {
        this.logger.error(
          `Frame handling failed for ${session.streamSid ?? 'unstarted stream'}`,
          error instanceof Error ? error.stack : String(error),
        );
      });
    });

    socket.on('close', () => {
      void this.teardown(session, 'caller_hangup');
    });

    socket.on('error', (error: Error) => {
      this.logger.error(`Socket error: ${error.message}`);
      void this.teardown(session, 'error');
    });
  }

  private async handleFrame(
    session: MediaStreamSession,
    raw: Buffer,
  ): Promise<void> {
    const frame = parseInboundFrame(raw);

    if (!frame) {
      // Twilio adds message types over time. Log and carry on — a throw here
      // would end a live phone call over an unrecognised notification.
      this.logger.warn('Ignoring unrecognised inbound frame');
      return;
    }

    switch (frame.event) {
      case 'connected':
        this.logger.debug('Twilio connected');
        break;

      case 'start':
        await this.handleStart(session, frame);
        break;

      case 'media':
        session.framesIn++;
        // Decode → upsample → STT happens inside the conversation's STT
        // session, which takes the frame exactly as Twilio sent it.
        session.conversation?.pushAudio(
          Buffer.from(frame.media.payload, 'base64'),
        );
        break;

      case 'mark':
        // Twilio echoes a mark once the audio queued ahead of it has finished
        // playing. That is the only reliable "the agent has stopped talking"
        // signal, so it has to reach the conversation, not just the log.
        session.conversation?.onMarkPlayed(frame.mark.name);
        this.logger.debug(`Mark ${frame.mark.name} played`);
        break;

      case 'dtmf':
        this.logger.log(`Caller pressed ${frame.dtmf.digit}`);
        break;

      case 'stop':
        await this.teardown(session, 'caller_hangup');
        break;
    }
  }

  private async handleStart(
    session: MediaStreamSession,
    frame: StartFrame,
  ): Promise<void> {
    const { streamSid, callSid, customParameters, mediaFormat } = frame.start;

    // The codec assumes this format everywhere. If Twilio ever announces
    // something else, say so loudly rather than decoding noise.
    if (
      mediaFormat.encoding !== EXPECTED_MEDIA_FORMAT.encoding ||
      mediaFormat.sampleRate !== EXPECTED_MEDIA_FORMAT.sampleRate ||
      mediaFormat.channels !== EXPECTED_MEDIA_FORMAT.channels
    ) {
      this.logger.error(
        `Unexpected media format ${JSON.stringify(mediaFormat)}; expected ${JSON.stringify(EXPECTED_MEDIA_FORMAT)}`,
      );
    }

    session.streamSid = streamSid;
    this.byStreamSid.set(streamSid, session);

    const callId = customParameters.callId;

    if (!callId) {
      // Audio beats bookkeeping: keep the call up and lose the association
      // rather than hanging up on someone over a missing parameter.
      this.logger.error(
        `Stream ${streamSid} (call ${callSid}) started with no callId parameter`,
      );
      return;
    }

    session.callId = callId;

    // The store comes back with the call because the greeting lives on it, and
    // the greeting is needed before the caller has said anything at all.
    let call: Awaited<ReturnType<typeof this.loadCall>>;

    try {
      call = await this.loadCall(callId, streamSid);
      session.startedAt = call.startedAt;
    } catch (error: unknown) {
      // Audio beats bookkeeping, but without the store there is no greeting and
      // no store name for the prompt, so this call cannot hold a conversation.
      this.logger.error(
        `Could not attach stream ${streamSid} to call ${callId}: ${
          error instanceof Error ? error.message : String(error)
        }`,
      );
      return;
    }

    const { store } = call;

    try {
      session.conversation = await this.conversations.create({
        callId,
        streamSid,
        greeting:
          store.defaultLocale === 'de' ? store.greetingDe : store.greetingEn,
        storeName: store.name,
        timezone: store.timezone,
        sink: this.sinkFor(session, streamSid),
      });
    } catch (error: unknown) {
      // Audio beats conversation: a call that cannot reach OpenAI is still
      // worth connecting, and Phase 6 turns this into a spoken apology.
      this.logger.error(
        `Could not open a conversation for call ${callId}: ${
          error instanceof Error ? error.message : String(error)
        }`,
      );
    }

    this.logger.log(`Stream ${streamSid} started for call ${callId}`);

    // After the session is registered, so a mark echoing back off the greeting
    // has somewhere to land.
    await session.conversation?.start();
  }

  private loadCall(callId: string, streamSid: string) {
    return this.prisma.call.update({
      where: { id: callId },
      data: { streamSid },
      include: { store: true },
    });
  }

  /**
   * The agent's voice, as the conversation layer sees it.
   *
   * Built here and passed down rather than looked up from the conversation,
   * which would make a cycle (gateway → ConversationService → CallSession →
   * gateway) and leak `MediaStreamSession` across the seam.
   */
  private sinkFor(
    session: MediaStreamSession,
    streamSid: string,
  ): OutboundAudioSink {
    return {
      playFrame: (frame: Buffer) => {
        this.send(session, mediaMessage(streamSid, frame.toString('base64')));
        session.framesOut++;
      },
      mark: (name: string) => {
        this.send(session, markMessage(streamSid, name));
      },
      clear: () => {
        this.send(session, clearMessage(streamSid));
      },
    };
  }

  /**
   * Idempotent: `stop`, `close`, and `error` can all fire for the same call,
   * and Twilio does not always send `stop` at all.
   *
   * The `endedAt: null` guard is what makes this safe to race against
   * `POST /twilio/status`, which owns the ending and writes unconditionally.
   */
  private async teardown(
    session: MediaStreamSession,
    endReason: string,
  ): Promise<void> {
    if (!this.sessions.delete(session.socket)) return;

    if (session.streamSid) {
      this.byStreamSid.delete(session.streamSid);

      // Closes the OpenAI socket and flushes the last partial batch of audio,
      // which is where the caller's final word usually is.
      await this.conversations.destroy(session.streamSid);
      session.conversation = undefined;
    }

    this.logger.log(
      `Stream ${session.streamSid ?? '(unstarted)'} ended after ${session.framesIn} frames in, ${session.framesOut} out`,
    );

    if (!session.callId) return;

    const endedAt = new Date();
    const durationSec = session.startedAt
      ? Math.round((endedAt.getTime() - session.startedAt.getTime()) / 1000)
      : undefined;

    try {
      await this.prisma.call.updateMany({
        where: { id: session.callId, endedAt: null },
        data: {
          endedAt,
          durationSec,
          status: CallStatus.COMPLETED,
          endReason,
        },
      });
    } catch (error: unknown) {
      this.logger.error(
        `Could not finalise call ${session.callId}: ${
          error instanceof Error ? error.message : String(error)
        }`,
      );
    }
  }

  /** Writes to a socket Twilio has already torn down surface asynchronously. */
  private send(session: MediaStreamSession, message: string): void {
    if (session.socket.readyState !== WebSocket.OPEN) return;

    session.socket.send(message);
  }
}
