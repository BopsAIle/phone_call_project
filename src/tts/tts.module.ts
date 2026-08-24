import { Module } from '@nestjs/common';
import { GreetingCache } from './greeting-cache';
import { OpenAiTtsService } from './openai-tts.service';

/** Concrete class rather than a `TTS_PROVIDER` token, for the reason in SttModule. */
@Module({
  providers: [OpenAiTtsService, GreetingCache],
  exports: [OpenAiTtsService, GreetingCache],
})
export class TtsModule {}
