import { Module } from '@nestjs/common';
import { LlmModule } from '../llm/llm.module';
import { SttModule } from '../stt/stt.module';
import { TtsModule } from '../tts/tts.module';
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
  imports: [SttModule, LlmModule, TtsModule],
  providers: [ConversationService],
  exports: [ConversationService],
})
export class ConversationModule {}
