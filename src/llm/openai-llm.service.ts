import { Injectable, Logger } from '@nestjs/common';
import { ConfigService } from '@nestjs/config';
import OpenAI from 'openai';
import type { Env } from '../config/env.schema';
import type { LlmProvider } from './llm.provider';
import type { ChatMessage, ToolCall, ToolDefinition } from './llm.types';
import { SentenceChunker } from './sentence-chunker';

/**
 * The brain, over Chat Completions.
 *
 * `gpt-5.6-terra` streams from `POST /v1/chat/completions`; text deltas arrive
 * as `choices[0].delta.content`. Confirmed against the live API on 2026-08-21 —
 * see the phase plan. The SDK is used here (and not for TTS) because it owns SSE
 * framing now and streaming tool-call delta reassembly in Phase 4, which is the
 * genuinely error-prone part.
 */
@Injectable()
export class OpenAiLlmService implements LlmProvider {
  private readonly logger = new Logger(OpenAiLlmService.name);
  private readonly client: OpenAI;
  private readonly model: string;

  constructor(config: ConfigService<Env, true>) {
    this.client = new OpenAI({
      apiKey: config.get('OPENAI_API_KEY', { infer: true }),
    });
    this.model = config.get('LLM_MODEL', { infer: true });
  }

  respond(opts: {
    messages: ChatMessage[];
    tools: ToolDefinition[];
    signal: AbortSignal;
  }): {
    sentences: AsyncIterable<string>;
    toolCalls: Promise<ToolCall[]>;
  } {
    // The promise has to exist before anything is consumed: on barge-in the
    // caller abandons `sentences` while still holding `toolCalls`.
    let settle!: (calls: ToolCall[]) => void;
    const toolCalls = new Promise<ToolCall[]>((resolve) => {
      settle = resolve;
    });

    return { sentences: this.stream(opts, settle), toolCalls };
  }

  private async *stream(
    opts: {
      messages: ChatMessage[];
      tools: ToolDefinition[];
      signal: AbortSignal;
    },
    settle: (calls: ToolCall[]) => void,
  ): AsyncGenerator<string> {
    const chunker = new SentenceChunker();
    const requestedAt = Date.now();
    let firstTokenAt: number | undefined;

    try {
      const stream = await this.client.chat.completions.create(
        {
          model: this.model,
          messages: opts.messages.map(toOpenAiMessage),
          stream: true,
          ...(opts.tools.length > 0
            ? { tools: opts.tools.map(toOpenAiTool) }
            : {}),
        },
        { signal: opts.signal },
      );

      for await (const chunk of stream) {
        const delta = chunk.choices[0]?.delta;

        // The first chunk carries `delta.role` with empty content, and chunks
        // also carry an `obfuscation` field that is padding against compression
        // side-channels. Both are nothing to do with us.
        if (!delta?.content) continue;

        firstTokenAt ??= Date.now();

        for (const sentence of chunker.push(delta.content)) yield sentence;
      }

      const tail = chunker.flush();
      if (tail) yield tail;

      // Phase 4 accumulates real calls here. Empty until then.
      settle([]);
    } finally {
      /**
       * Also runs when the consumer breaks out of its `for await` on barge-in —
       * that calls `.return()` on this generator, which unwinds the block.
       *
       * Settling (rather than rejecting) is what keeps an abandoned turn safe:
       * a rejection nobody is awaiting is an unhandled rejection, and that ends
       * the process along with every other live call. Resolving twice is a
       * no-op, so the happy path above is unaffected.
       */
      settle([]);

      this.logger.debug(
        firstTokenAt === undefined
          ? `No tokens after ${Date.now() - requestedAt}ms`
          : `First token +${firstTokenAt - requestedAt}ms, completion ${Date.now() - requestedAt}ms`,
      );
    }
  }
}

function toOpenAiMessage(
  message: ChatMessage,
): OpenAI.Chat.ChatCompletionMessageParam {
  if (message.role === 'tool') {
    return {
      role: 'tool',
      content: message.content,
      // Phase 4 always sets this; the fallback keeps the mapping total rather
      // than throwing inside a live call over a malformed history entry.
      tool_call_id: message.toolCallId ?? '',
    };
  }

  return { role: message.role, content: message.content };
}

function toOpenAiTool(tool: ToolDefinition): OpenAI.Chat.ChatCompletionTool {
  return {
    type: 'function',
    function: {
      name: tool.name,
      description: tool.description,
      parameters: tool.parameters,
    },
  };
}
