import { Module } from '@nestjs/common';
import { SttModule } from '../stt/stt.module';
import { ConversationService } from './conversation.service';

/**
 * The conversation layer, imported by telephony.
 *
 * The dependency runs that way round on purpose: the gateway knows it hands
 * audio to a conversation, and the conversation knows nothing about Twilio.
 * Phase 3 inverts a little of this when the agent needs to write frames back,
 * and will do it with a narrow callback rather than a circular import.
 */
@Module({
  imports: [SttModule],
  providers: [ConversationService],
  exports: [ConversationService],
})
export class ConversationModule {}
