import { Module } from '@nestjs/common';
import { ConversationModule } from '../conversation/conversation.module';
import { TelephonyModule } from '../telephony/telephony.module';
import { DevClientController } from './dev-client.controller';

/**
 * The browser dev client, which stands in for a real phone call until a Twilio
 * number is configurable.
 *
 * `app.module.ts` imports this only when `isDevClientEnabled()`, so in
 * production the routes do not exist rather than being guarded.
 */
@Module({
  imports: [TelephonyModule, ConversationModule],
  controllers: [DevClientController],
})
export class DevModule {}
