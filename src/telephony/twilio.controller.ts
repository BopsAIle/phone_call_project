import {
  Body,
  Controller,
  Header,
  HttpCode,
  HttpStatus,
  Logger,
  Post,
} from '@nestjs/common';
import { PrismaService } from '../prisma/prisma.service';
import { CallStatus } from '../generated/prisma/enums';
import { TwimlService } from './twiml.service';

/** Twilio posts these as `application/x-www-form-urlencoded`, so every value is a string. */
interface VoiceWebhookBody {
  CallSid?: string;
  From?: string;
  To?: string;
}

interface StatusWebhookBody {
  CallSid?: string;
  CallStatus?: string;
  CallDuration?: string;
}

/**
 * How a finished call is recorded. Twilio also posts non-terminal statuses
 * (`initiated`, `ringing`, `in-progress`) when the number is configured to send
 * them; those are absent from this table on purpose, and anything not listed is
 * ignored rather than being written as an ending.
 */
const TERMINAL_STATUSES: Record<
  string,
  { status: CallStatus; endReason: string }
> = {
  completed: { status: CallStatus.COMPLETED, endReason: 'completed' },
  busy: { status: CallStatus.ABANDONED, endReason: 'caller_hangup' },
  'no-answer': { status: CallStatus.ABANDONED, endReason: 'caller_hangup' },
  canceled: { status: CallStatus.ABANDONED, endReason: 'caller_hangup' },
  failed: { status: CallStatus.FAILED, endReason: 'error' },
};

const NO_STORE_MESSAGE =
  'Sorry, this number is not in service. Goodbye.' as const;

@Controller('twilio')
export class TwilioController {
  private readonly logger = new Logger(TwilioController.name);

  constructor(
    private readonly prisma: PrismaService,
    private readonly twiml: TwimlService,
  ) {}

  /**
   * The call's entry point. This is the only place that sees the caller's
   * number: Twilio's WebSocket `start` event carries `callSid` and
   * `streamSid` but neither `From` nor `To`, so the `Call` row has to be
   * created here and its id handed to the socket as a `<Parameter>`.
   *
   * Twilio times this request out at 15 s. The store lookup and the row write
   * are the only work that belongs on this path.
   */
  @Post('voice')
  @Header('Content-Type', 'text/xml')
  async voice(@Body() body: VoiceWebhookBody): Promise<string> {
    const { CallSid: callSid, From: from, To: to } = body;

    if (!callSid || !from || !to) {
      this.logger.error(
        `Voice webhook missing required fields (CallSid=${callSid ?? '-'}, From=${from ? 'set' : '-'}, To=${to ?? '-'})`,
      );
      return this.twiml.rejectCall(NO_STORE_MESSAGE);
    }

    const store = await this.prisma.store.findUnique({
      where: { phoneNumber: to },
    });

    if (!store) {
      this.logger.warn(`No store configured for ${to}; rejecting call`);
      return this.twiml.rejectCall(NO_STORE_MESSAGE);
    }

    // upsert, not create: Twilio retries webhooks, and `twilioCallSid` is
    // @unique — a retry against `create` is a 500 and a dropped call.
    const call = await this.prisma.call.upsert({
      where: { twilioCallSid: callSid },
      create: {
        storeId: store.id,
        twilioCallSid: callSid,
        fromNumber: from,
        toNumber: to,
      },
      update: {},
    });

    this.logger.log(`Call ${call.id} from ${from} to store ${store.name}`);

    return this.twiml.connectStream({ callId: call.id, storeId: store.id });
  }

  /**
   * Owns the ending of the call.
   *
   * The gateway also finalises on `stop`, but only when `endedAt` is still
   * null — the two arrive in either order, and Twilio does not always send
   * `stop` at all. This handler writes unconditionally so the authoritative
   * duration wins whichever got there first.
   *
   * Nothing calls this unless the number's status callback URL is configured.
   * When it is missing every `Call` stays `IN_PROGRESS` and nothing complains.
   */
  @Post('status')
  @HttpCode(HttpStatus.NO_CONTENT)
  async status(@Body() body: StatusWebhookBody): Promise<void> {
    const { CallSid: callSid, CallStatus: callStatus } = body;

    if (!callSid || !callStatus) return;

    const outcome = TERMINAL_STATUSES[callStatus];
    if (!outcome) return;

    const durationSec = Number.parseInt(body.CallDuration ?? '', 10);

    const { count } = await this.prisma.call.updateMany({
      where: { twilioCallSid: callSid },
      data: {
        endedAt: new Date(),
        durationSec: Number.isNaN(durationSec) ? undefined : durationSec,
        status: outcome.status,
        endReason: outcome.endReason,
      },
    });

    if (count === 0) {
      this.logger.warn(`Status callback for unknown call ${callSid}`);
    }
  }
}
