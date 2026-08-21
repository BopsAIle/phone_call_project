import { Module } from '@nestjs/common';
import { OpenAiRealtimeSttService } from './openai-realtime-stt.service';

/**
 * The concrete class is exported rather than an `STT_PROVIDER` token.
 *
 * There is exactly one implementation, and the seam that matters — the one a
 * speech-to-speech adapter would replace — is the `SttProvider` interface the
 * conversation layer types against, not the DI token it is registered under. A
 * token can be introduced the day a second implementation exists.
 */
@Module({
  providers: [OpenAiRealtimeSttService],
  exports: [OpenAiRealtimeSttService],
})
export class SttModule {}
