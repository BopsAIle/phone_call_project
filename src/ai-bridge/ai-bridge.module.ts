import { Module } from '@nestjs/common';
import { AiBridgeService } from './ai-bridge.service';

/**
 * The AI service seam.
 *
 * The concrete class is exported rather than an `AI_BRIDGE` token, matching
 * `SttModule`: there is exactly one implementation, and the seam that matters is
 * the `AiBridgeProvider` interface the conversation layer types against, not the
 * DI token it is registered under. A token can be introduced the day a second
 * implementation exists.
 *
 * Not yet imported by `ConversationModule` — that is the cutover commit.
 */
@Module({
  providers: [AiBridgeService],
  exports: [AiBridgeService],
})
export class AiBridgeModule {}
