import { Module } from '@nestjs/common';
import { AiBridgeModule } from '../ai-bridge/ai-bridge.module';
import { ConversationService } from './conversation.service';

/**
 * The conversation layer, imported by telephony.
 *
 * The dependency runs that way round on purpose: the gateway knows it hands
 * audio to a conversation, and the conversation knows nothing about Twilio.
 * Outbound audio does not invert it — the gateway passes an `OutboundAudioSink`
 * down at `create()`, so frames flow back through an interface this layer owns
 * rather than through a circular import.
 */
@Module({
  imports: [AiBridgeModule],
  providers: [ConversationService],
  exports: [ConversationService],
})
export class ConversationModule {}
