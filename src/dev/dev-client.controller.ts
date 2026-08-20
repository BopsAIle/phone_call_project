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
   * Phase 1's gateway only echoes `media`, so `mark` and `clear` never leave the
   * server on their own and both paths would stay dormant until Phase 3 wires
   * them up. These push one into a live stream on demand.
   *
   * Deliberately here rather than on the gateway: adding a method to
   * `src/telephony/` for the benefit of a dev page would break the swap-in
   * guarantee this client exists to prove. `findByStreamSid` is already public
   * for Phase 3's barge-in lookups, and `markMessage` / `clearMessage` are the
   * same encoders the production path will use.
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

  private push(streamSid: string, message: string): void {
    const session = this.gateway.findByStreamSid(streamSid);

    if (!session || session.socket.readyState !== WebSocket.OPEN) {
      throw new NotFoundException(`No live stream ${streamSid}`);
    }

    session.socket.send(message);
  }
}
