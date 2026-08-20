/**
 * Provider-neutral conversation types.
 *
 * Deliberately not the OpenAI SDK's types: the whole point of LlmProvider is
 * that the SDK stays behind it, so a different brain (or the speech-to-speech
 * adapter discussed in the parent plan) can be dropped in without touching the
 * conversation layer.
 */
export type ChatRole = 'system' | 'user' | 'assistant' | 'tool';

export interface ChatMessage {
  role: ChatRole;
  content: string;
  /** Set when `role === 'tool'`, linking the result back to its call. */
  toolCallId?: string;
}

export interface ToolDefinition {
  name: string;
  description: string;
  /** JSON Schema describing the arguments. */
  parameters: Record<string, unknown>;
}

export interface ToolCall {
  id: string;
  name: string;
  /** Parsed, not the raw JSON string the model emitted. */
  arguments: Record<string, unknown>;
}
