/** Wire constants — khớp documents/backend_contract/ai-bridge-contract.md */

export const SAMPLE_RATE = 16_000;
export const CHANNELS = 1;
export const SAMPLE_WIDTH = 2;
export const FRAME_MS = 100;
export const FRAME_SAMPLES = (SAMPLE_RATE * FRAME_MS) / 1000; // 1600
export const FRAME_BYTES = FRAME_SAMPLES * SAMPLE_WIDTH; // 3200

export const EVENT_SESSION_INIT = "session.init";
export const EVENT_INTERRUPT = "interrupt";

export type SessionInit = {
  event: typeof EVENT_SESSION_INIT;
  callId: string;
  storeName: string;
  timezone: string;
  locale: string;
  greeting: string;
};

export type InterruptEvent = { event: typeof EVENT_INTERRUPT };

export function newCallId(): string {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) {
    return `web-${crypto.randomUUID()}`;
  }
  return `web-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`;
}
