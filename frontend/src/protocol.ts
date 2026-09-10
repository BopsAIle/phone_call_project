/** Wire constants — khớp documents/backend_contract/ai-bridge-contract.md */

// Wire runs at 24 kHz: mic 48 kHz → 24 kHz straight to STT (no 16 kHz hop),
// and the agent's 24 kHz TTS reaches us without a downsample.
export const SAMPLE_RATE = 24_000;
export const CHANNELS = 1;
export const SAMPLE_WIDTH = 2;
export const FRAME_MS = 100;
export const FRAME_SAMPLES = (SAMPLE_RATE * FRAME_MS) / 1000; // 2400
export const FRAME_BYTES = FRAME_SAMPLES * SAMPLE_WIDTH; // 4800

export const EVENT_SESSION_INIT = "session.init";
export const EVENT_INTERRUPT = "interrupt";
export const EVENT_ORDER_CREATED = "order.created";
export const EVENT_TRANSCRIPT = "transcript";
export const EVENT_AGENT_SPEECH = "agent.speech";
export const EVENT_DTMF = "dtmf";

export type SessionInit = {
  event: typeof EVENT_SESSION_INIT;
  callId: string;
  storeName: string;
  toNumber?: string;
  timezone: string;
  locale: string;
  greeting: string;
};

export type InterruptEvent = { event: typeof EVENT_INTERRUPT };

export type TranscriptEvent = {
  event: typeof EVENT_TRANSCRIPT;
  callId?: string;
  status?: "started" | "completed";
  text?: string;
};

export type AgentSpeechEvent = {
  event: typeof EVENT_AGENT_SPEECH;
  callId?: string;
  text?: string;
};

export type DtmfEvent = {
  event: typeof EVENT_DTMF;
  digit: string;
  callId?: string;
};

export type OrderCreatedItem = {
  name?: string;
  quantity?: number;
  unit?: string;
  note?: string;
  line_total?: number;
  lineTotal?: number;
  currency?: string;
};

export type OrderCreatedEvent = {
  event: typeof EVENT_ORDER_CREATED;
  callId?: string;
  fulfillment?: string;
  message?: string;
  orderId?: string;
  customerName?: string;
  phoneNumber?: string;
  branchName?: string;
  bookingDate?: string;
  bookingTime?: string;
  deliveryAddress?: string;
  deliveryPhone?: string;
  cart?: OrderCreatedItem[];
  total?: number;
  note?: string;
  payment?: string;
};

export function newCallId(): string {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) {
    return `web-${crypto.randomUUID()}`;
  }
  return `web-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`;
}
