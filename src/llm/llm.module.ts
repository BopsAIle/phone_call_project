import { Module } from '@nestjs/common';
import { OpenAiLlmService } from './openai-llm.service';

/** Concrete class rather than an `LLM_PROVIDER` token, for the reason in SttModule. */
@Module({
  providers: [OpenAiLlmService],
  exports: [OpenAiLlmService],
})
export class LlmModule {}
