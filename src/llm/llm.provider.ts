import type { ChatMessage, ToolCall, ToolDefinition } from './llm.types';

/**
 * The brain. Implemented in Phase 3.
 *
 * `sentences` is an async iterable rather than a single string so Phase 3 can
 * feed text into TTS at sentence boundaries instead of waiting for the whole
 * completion — that streaming is most of the latency budget.
 *
 * `signal` is not decoration: aborting it is how barge-in cancels an in-flight
 * response. Designing it in now avoids a refactor when Phase 3 needs it.
 */
export interface LlmProvider {
  respond(opts: {
    messages: ChatMessage[];
    tools: ToolDefinition[];
    signal: AbortSignal;
  }): {
    sentences: AsyncIterable<string>;
    toolCalls: Promise<ToolCall[]>;
  };
}
