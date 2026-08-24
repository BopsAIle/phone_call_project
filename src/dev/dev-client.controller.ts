import {
  Controller,
  Get,
  HttpCode,
  HttpStatus,
  NotFoundException,
  Param,
  Post,
  Res,
} from '@nestjs/common';
import { ConfigService } from '@nestjs/config';
import type { Response } from 'express';
import { join } from 'path';
import { WebSocket } from 'ws';
import type { Env } from '../config/env.schema';
import { ConversationService } from '../conversation/conversation.service';
import { MediaStreamGateway } from '../telephony/media-stream.gateway';
import { clearMessage, markMessage } from '../telephony/twilio-frames';

/**
 * Serves the browser dev client and the two nudges it needs.
 *
 * Registered only when `isDevClientEnabled()` — see dev.module.ts.
 */
@Controller('dev')
export class DevClientController {
  constructor(
    private readonly config: ConfigService<Env, true>,
    private readonly gateway: MediaStreamGateway,
    private readonly conversations: ConversationService,
  ) {}

  @Get()
  page(@Res() res: Response): void {
    res.sendFile(join(process.cwd(), 'public', 'dev-client.html'));
  }

  /**
   * The number to dial. The page posts it to `/twilio/voice` as `To`, which is
   * what resolves the `Store` — so it has to match the seeded row.
   */
  @Get('config')
  clientConfig(): { storeNumber: string } {
    return {
      storeNumber: this.config.get('TWILIO_PHONE_NUMBER', { infer: true }),
    };
  }

  /**
   * Pushes a raw `mark` or `clear` into a live stream on demand.
   *
   * Deliberately here rather than on the gateway: adding a method to
   * `src/telephony/` for the benefit of a dev page would break the swap-in
   * guarantee this client exists to prove. `markMessage` / `clearMessage` are
   * the same encoders the production path uses.
   *
   * These bypass the conversation entirely — they prove the wire protocol, not
   * the agent. `barge-in` below is the one that exercises the real path.
   */
  @Post('mark/:streamSid')
  @HttpCode(HttpStatus.NO_CONTENT)
  sendMark(@Param('streamSid') streamSid: string): void {
    this.push(streamSid, markMessage(streamSid, `dev-${Date.now()}`));
  }

  @Post('clear/:streamSid')
  @HttpCode(HttpStatus.NO_CONTENT)
  sendClear(@Param('streamSid') streamSid: string): void {
    this.push(streamSid, clearMessage(streamSid));
  }

  /**
   * Interrupts the agent exactly as `speech_started` would.
   *
   * Barge-in is the hardest behaviour in the phase to test offline: driving it
   * from a fixture's own speech means depending on when a real VAD fires, which
   * is neither repeatable nor cheap. This drives the production path — abort,
   * `clear`, drop the queue — from a deterministic trigger, so the replay
   * harness can assert on it and the dev page has a button for it.
   */
  @Post('barge-in/:streamSid')
  @HttpCode(HttpStatus.NO_CONTENT)
  bargeIn(@Param('streamSid') streamSid: string): void {
    const conversation = this.conversations.get(streamSid);

    if (!conversation) {
      throw new NotFoundException(`No conversation for stream ${streamSid}`);
    }

    conversation.interrupt();
  }

  private push(streamSid: string, message: string): void {
    const session = this.gateway.findByStreamSid(streamSid);

    if (!session || session.socket.readyState !== WebSocket.OPEN) {
      throw new NotFoundException(`No live stream ${streamSid}`);
    }

    session.socket.send(message);
  }
}
