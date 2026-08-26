import { EVENT_INTERRUPT, EVENT_SESSION_INIT, type SessionInit } from "./protocol";

export type BridgeHandlers = {
  onOpen?: () => void;
  onPcm?: (bytes: ArrayBuffer) => void;
  onInterrupt?: () => void;
  onControl?: (payload: Record<string, unknown>) => void;
  onClose?: (code: number, reason: string) => void;
  onError?: (message: string) => void;
};

export function toWebSocketUrl(raw: string, token: string): string {
  const trimmed = raw.trim();
  let url: URL;
  try {
    if (trimmed.startsWith("ws://") || trimmed.startsWith("wss://")) {
      url = new URL(trimmed);
    } else if (trimmed.startsWith("http://") || trimmed.startsWith("https://")) {
      url = new URL(trimmed);
      url.protocol = url.protocol === "https:" ? "wss:" : "ws:";
    } else {
      url = new URL(trimmed || "/v1/bridge", window.location.href);
      url.protocol = url.protocol === "https:" ? "wss:" : "ws:";
    }
  } catch {
    throw new Error(`URL WebSocket không hợp lệ: ${raw}`);
  }
  if (token) {
    url.searchParams.set("token", token);
  }
  return url.toString();
}

export class BridgeClient {
  private ws: WebSocket | null = null;

  get readyState(): number {
    return this.ws?.readyState ?? WebSocket.CLOSED;
  }

  connect(url: string, token: string, handlers: BridgeHandlers): void {
    this.close();
    const wsUrl = toWebSocketUrl(url, token);
    const ws = new WebSocket(wsUrl);
    ws.binaryType = "arraybuffer";
    this.ws = ws;

    ws.addEventListener("open", () => handlers.onOpen?.());

    ws.addEventListener("message", (event) => {
      if (event.data instanceof ArrayBuffer) {
        handlers.onPcm?.(event.data);
        return;
      }
      if (typeof event.data === "string") {
        try {
          const payload = JSON.parse(event.data) as Record<string, unknown>;
          if (payload.event === EVENT_INTERRUPT) {
            handlers.onInterrupt?.();
          }
          handlers.onControl?.(payload);
        } catch {
          handlers.onError?.("Control JSON không parse được");
        }
      }
    });

    ws.addEventListener("close", (event) => {
      if (this.ws === ws) this.ws = null;
      handlers.onClose?.(event.code, event.reason || closeReason(event.code));
    });

    ws.addEventListener("error", () => {
      handlers.onError?.("Lỗi WebSocket — kiểm tra server AI còn chạy và token đúng chưa");
    });
  }

  sendInit(init: Omit<SessionInit, "event">): void {
    if (this.ws?.readyState !== WebSocket.OPEN) return;
    const payload: SessionInit = { event: EVENT_SESSION_INIT, ...init };
    this.ws.send(JSON.stringify(payload));
  }

  sendPcm(frame: ArrayBuffer): void {
    if (this.ws?.readyState !== WebSocket.OPEN) return;
    this.ws.send(frame);
  }

  close(code = 1000, reason = "client hangup"): void {
    if (!this.ws) return;
    const ws = this.ws;
    this.ws = null;
    try {
      if (ws.readyState === WebSocket.OPEN || ws.readyState === WebSocket.CONNECTING) {
        ws.close(code, reason);
      }
    } catch {
      /* already closing */
    }
  }
}

function closeReason(code: number): string {
  if (code === 1008) return "Unauthorized — sai hoặc thiếu token";
  if (code === 1011) return "Internal error phía AI Bridge";
  if (code === 1006) return "Socket đứt bất ngờ";
  if (code === 1000) return "Đóng bình thường";
  return `Mã đóng ${code}`;
}
