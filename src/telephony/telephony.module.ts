import { Module } from '@nestjs/common';
import { ConversationModule } from '../conversation/conversation.module';
import { MediaStreamGateway } from './media-stream.gateway';
import { TwilioController } from './twilio.controller';
import { TwimlService } from './twiml.service';

@Module({
  imports: [ConversationModule],
  controllers: [TwilioController],
  providers: [TwimlService, MediaStreamGateway],
  // main.ts resolves the gateway to hand it the HTTP server once it is listening.
  exports: [MediaStreamGateway],
})
export class TelephonyModule {}
