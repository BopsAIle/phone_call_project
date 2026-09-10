import "./styles.css";
import { BridgeClient } from "./bridge";
import { MicCapture } from "./capture";
import { floatToPcm16, LinearResampler, PcmFramer, rms } from "./pcm";
import { PcmPlayer } from "./playback";
import { newCallId, type OrderCreatedEvent, type OrderCreatedItem } from "./protocol";
import { PolarScope } from "./viz";

const STORAGE_KEY = "ai-bridge-voice-demo";

type Settings = {
  wsUrl: string;
  token: string;
  storeName: string;
  toNumber: string;
  locale: string;
  timezone: string;
  greeting: string;
};

const DEFAULTS: Settings = {
  wsUrl: import.meta.env.VITE_AI_BRIDGE_URL || "ws://127.0.0.1:8080/v1/bridge",
  token: import.meta.env.VITE_AI_BRIDGE_TOKEN || "",
  storeName: "Bella Vista",
  toNumber: "1900636886",
  locale: "vi",
  timezone: "Asia/Ho_Chi_Minh",
  greeting:
    "Hello, I am the AI for Bella Vista. I will listen to your request and record this call. We will call you back if needed.",
};

const LEGACY_GREETINGS = new Set([
  "Xin chào, cảm ơn bạn đã gọi Bella Vista. Đây là trợ lý tự động — mình có thể giúp gì ạ?",
  "Xin chào, cảm ơn bạn đã gọi Bella Vista. Đây là trợ lý tự động. Bạn muốn đặt bàn hay mang về ạ?",
  "Xin chào khách hàng, tôi là AI của nhà hàng Bella Vista. Tôi sẽ lắng nghe mong muốn của bạn và ghi âm lại, sau đó chúng tôi sẽ gọi lại cho bạn khi cần thiết.",
]);

const els = {
  wsUrl: $("wsUrl", HTMLInputElement),
  token: $("token", HTMLInputElement),
  storeName: $("storeName", HTMLInputElement),
  toNumber: $("toNumber", HTMLInputElement),
  locale: $("locale", HTMLSelectElement),
  timezone: $("timezone", HTMLInputElement),
  greeting: $("greeting", HTMLTextAreaElement),
  callBtn: $("callBtn", HTMLButtonElement),
  hangBtn: $("hangBtn", HTMLButtonElement),
  muteBtn: $("muteBtn", HTMLButtonElement),
  pingBtn: $("pingBtn", HTMLButtonElement),
  clearLogBtn: $("clearLogBtn", HTMLButtonElement),
  volume: $("volume", HTMLInputElement),
  status: $("statusLabel", HTMLElement),
  health: $("healthBadge", HTMLElement),
  healthLabel: $("healthLabel", HTMLElement),
  log: $("log", HTMLOListElement),
  scope: $("scope", HTMLCanvasElement),
  orderBanner: $("orderBanner", HTMLElement),
  orderBannerTitle: $("orderBannerTitle", HTMLElement),
  orderBannerMeta: $("orderBannerMeta", HTMLElement),
  orderBannerItems: $("orderBannerItems", HTMLUListElement),
  dtmf1: $("dtmf1", HTMLButtonElement),
  dtmf2: $("dtmf2", HTMLButtonElement),
  dtmf3: $("dtmf3", HTMLButtonElement),
};

const keypadButtons = [els.dtmf1, els.dtmf2, els.dtmf3];
const DTMF_LABELS: Record<string, string> = {
  "1": "Đặt bàn",
  "2": "Đến lấy",
  "3": "Giao hàng",
};

function $<T extends HTMLElement>(id: string, ctor: { new (): T }): T {
  const node = document.getElementById(id);
  if (!node || !(node instanceof ctor)) {
    throw new Error(`Missing #${id}`);
  }
  return node;
}

function loadSettings(): Settings {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return { ...DEFAULTS };
    const merged = { ...DEFAULTS, ...(JSON.parse(raw) as Partial<Settings>) };
    if (LEGACY_GREETINGS.has(merged.greeting)) {
      merged.greeting = DEFAULTS.greeting;
    }
    // Token luôn lấy theo VITE_AI_BRIDGE_TOKEN hiện tại (.env), không dùng giá trị
    // cũ còn sót trong localStorage — tránh lệch token mỗi khi .env đổi.
    if (DEFAULTS.token) {
      merged.token = DEFAULTS.token;
    }
    return merged;
  } catch {
    return { ...DEFAULTS };
  }
}

function readForm(): Settings {
  return {
    wsUrl: els.wsUrl.value.trim() || DEFAULTS.wsUrl,
    token: els.token.value.trim(),
    storeName: els.storeName.value.trim() || DEFAULTS.storeName,
    toNumber: els.toNumber.value.trim() || DEFAULTS.toNumber,
    locale: els.locale.value || "vi",
    timezone: els.timezone.value.trim() || DEFAULTS.timezone,
    greeting: els.greeting.value.trim() || DEFAULTS.greeting,
  };
}

function fillForm(s: Settings): void {
  els.wsUrl.value = s.wsUrl;
  els.token.value = s.token;
  els.storeName.value = s.storeName;
  els.toNumber.value = s.toNumber;
  els.locale.value = s.locale;
  els.timezone.value = s.timezone;
  els.greeting.value = s.greeting;
}

function persist(): void {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(readForm()));
}

function log(message: string, tone: "info" | "warn" | "ok" | "agent" = "info"): void {
  const li = document.createElement("li");
  li.dataset.tone = tone;
  const time = document.createElement("time");
  time.textContent = new Date().toLocaleTimeString("vi-VN", { hour12: false });
  const body = document.createElement("strong");
  body.textContent = tone === "warn" ? "!" : tone === "ok" ? "●" : tone === "agent" ? "AI" : "·";
  li.append(time, body, document.createTextNode(message));
  els.log.prepend(li);
}

function hideOrderBanner(): void {
  els.orderBanner.hidden = true;
  els.orderBannerTitle.textContent = "Đã đặt hàng thành công";
  els.orderBannerMeta.textContent = "";
  els.orderBannerItems.replaceChildren();
}

function formatMoney(amount: number, currency = "VND"): string {
  const formatted = Number(amount).toLocaleString("vi-VN");
  return `${formatted} ${currency}`;
}

function formatWhen(date?: string, time?: string): string {
  if (!date && !time) return "";
  if (!date) return time || "";
  const parts = date.split("-");
  const pretty = parts.length === 3 ? `${parts[2]}/${parts[1]}/${parts[0]}` : date;
  return time ? `${pretty} · ${time}` : pretty;
}

function lineLabel(item: OrderCreatedItem): string {
  const qty = item.quantity ?? 1;
  const unit = item.unit ? ` ${item.unit}` : "";
  const name = item.name || "món";
  let text = `${qty}${unit} ${name}`;
  if (item.note) text += ` (${item.note})`;
  const total = item.lineTotal ?? item.line_total;
  if (typeof total === "number") {
    text += ` — ${formatMoney(total, item.currency || "VND")}`;
  }
  return text;
}

function showOrderSuccess(payload: OrderCreatedEvent): void {
  const title = (payload.message || "Đã đặt hàng thành công").trim();
  els.orderBannerTitle.textContent = title;
  const bits: string[] = [];
  if (payload.orderId) bits.push(`Mã ${payload.orderId}`);
  if (payload.branchName) bits.push(payload.branchName);
  if (payload.fulfillment === "delivery") {
    bits.push("Giao hàng");
  } else if (payload.fulfillment === "pickup") {
    bits.push("Mang về");
  }
  const when = formatWhen(payload.bookingDate, payload.bookingTime);
  if (when) bits.push(when);
  if (payload.customerName) bits.push(payload.customerName);
  if (payload.phoneNumber) bits.push(payload.phoneNumber);
  if (payload.deliveryAddress) bits.push(payload.deliveryAddress);
  if (typeof payload.total === "number") {
    bits.push(formatMoney(payload.total));
  }
  if (payload.payment === "cod") bits.push("Thanh toán khi nhận");
  els.orderBannerMeta.textContent = bits.join(" · ");
  els.orderBannerItems.replaceChildren();
  for (const item of payload.cart || []) {
    const li = document.createElement("li");
    li.textContent = lineLabel(item);
    els.orderBannerItems.append(li);
  }
  els.orderBanner.hidden = false;
  setStatus(title);
  log(title, "ok");
}

function setStatus(text: string): void {
  els.status.textContent = text;
}

function setLiveUi(live: boolean): void {
  els.callBtn.disabled = live;
  els.hangBtn.disabled = !live;
  els.muteBtn.disabled = !live;
  for (const btn of keypadButtons) {
    btn.disabled = !live;
  }
  els.wsUrl.disabled = live;
  els.token.disabled = live;
  els.toNumber.disabled = live;
}

function resetKeypad(): void {
  for (const btn of keypadButtons) {
    btn.setAttribute("aria-pressed", "false");
  }
}

function healthUrlFromBridge(wsUrl: string): string {
  const trimmed = wsUrl.trim();
  if (trimmed.startsWith("ws://") || trimmed.startsWith("wss://")) {
    const url = new URL(trimmed);
    url.protocol = url.protocol === "wss:" ? "https:" : "http:";
    url.pathname = "/health";
    url.search = "";
    return url.toString();
  }
  if (trimmed.startsWith("http://") || trimmed.startsWith("https://")) {
    const url = new URL(trimmed);
    url.pathname = "/health";
    url.search = "";
    return url.toString();
  }
  return "/health";
}

async function pingHealth(): Promise<boolean> {
  const url = healthUrlFromBridge(readForm().wsUrl);
  try {
    const response = await fetch(url, { cache: "no-store" });
    const ok = response.ok;
    els.health.dataset.state = ok ? "ok" : "bad";
    els.healthLabel.textContent = ok ? `Server OK (${url})` : `Health lỗi ${response.status}`;
    return ok;
  } catch {
    els.health.dataset.state = "bad";
    els.healthLabel.textContent = "Không tới được /health — server AI đã chạy chưa?";
    return false;
  }
}

fillForm(loadSettings());
document.getElementById("settingsForm")?.addEventListener("change", persist);
document.getElementById("settingsForm")?.addEventListener("input", persist);

const scope = new PolarScope(els.scope);
scope.start();
window.addEventListener("resize", () => scope.resize());

const bridge = new BridgeClient();
const mic = new MicCapture();
const player = new PcmPlayer();
const resampler = new LinearResampler(48000);
const framer = new PcmFramer();

/** Hold the uplink after speaker playback so room echo is not treated as the caller. */
const ECHO_TAIL_MS = 450;

let live = false;
let muted = false;
let canSend = false;
let agentSpeaking = false;
let heardAgent = false;
let lastAgentLine = "";
let orderPlaced = false;
let levelTimer = 0;
let lastSpeechLog = 0;
let sentFirstPcm = false;
let suppressMicUntil = 0;

function noteAgentPlayback(): void {
  suppressMicUntil = Math.max(suppressMicUntil, performance.now() + ECHO_TAIL_MS);
}

function holdingMicForEcho(now: number): boolean {
  if (player.isPlaying) {
    noteAgentPlayback();
    return true;
  }
  return now < suppressMicUntil;
}

async function startCall(): Promise<void> {
  if (live) return;
  persist();
  const settings = readForm();
  if (!settings.token) {
    setStatus("Điền token (cùng AI_BRIDGE_TOKEN trên server) rồi gọi lại.");
    log("Thiếu token", "warn");
    return;
  }

  setLiveUi(true);
  muted = false;
  orderPlaced = false;
  hideOrderBanner();
  resetKeypad();
  els.muteBtn.textContent = "Tắt mic";
  setStatus("Đang xin quyền micro…");
  log("Xin micro");

  try {
    await player.ensureStarted();
    player.setVolume(Number(els.volume.value));
    await mic.start({
      onAudio: (samples, sampleRate) => {
        if (!live) return;
        resampler.setInputRate(sampleRate);
        const now = performance.now();
        const holdEcho = holdingMicForEcho(now);
        const peak = rms(samples);
        if (!muted && !holdEcho && peak > 0.02) {
          if (now - lastSpeechLog > 2500) {
            lastSpeechLog = now;
            log(`Mic có tiếng (rms ${peak.toFixed(2)})`);
          }
        }
        if (muted || !canSend) return;
        // Send silence while speakers are live so laptop echo never hits STT/VAD.
        const uplink = holdEcho ? new Float32Array(samples.length) : samples;
        const resampled = resampler.push(uplink);
        if (resampled.length === 0) return;
        const pcm = floatToPcm16(resampled);
        for (const frame of framer.push(pcm)) {
          if (!sentFirstPcm) {
            sentFirstPcm = true;
            log("Đã gửi PCM lên bridge", "ok");
          }
          bridge.sendPcm(frame);
        }
      },
    });
  } catch (err) {
    const message = err instanceof Error ? err.message : "Không mở được micro";
    setStatus(message);
    log(message, "warn");
    setLiveUi(false);
    await mic.stop();
    return;
  }

  setStatus("Đang kết nối AI Bridge…");
  live = true;
  canSend = false;
  heardAgent = false;
  lastAgentLine = "";
  sentFirstPcm = false;
  lastSpeechLog = 0;
  suppressMicUntil = 0;
  resampler.reset();
  framer.reset();
  player.interrupt();
  scope.setAnalysers(mic.getAnalyser(), player.getAnalyser());

  bridge.connect(settings.wsUrl, settings.token, {
    onOpen: () => {
      const callId = newCallId();
      bridge.sendInit({
        callId,
        storeName: settings.storeName,
        toNumber: settings.toNumber,
        timezone: settings.timezone,
        locale: settings.locale,
        greeting: settings.greeting,
      });
      canSend = true;
      setStatus("Đã nối — đợi câu chào, rồi nói khi sẵn sàng.");
      log(`session.init ${callId}`, "ok");
    },
    onPcm: (bytes) => {
      heardAgent = true;
      agentSpeaking = true;
      noteAgentPlayback();
      player.enqueue(bytes);
      setStatus(lastAgentLine ? `AI nói: ${lastAgentLine}` : "Agent đang nói");
    },
    onInterrupt: () => {
      agentSpeaking = false;
      player.interrupt();
      noteAgentPlayback();
      setStatus("Barge-in — agent dừng, đang nghe bạn.");
      log("interrupt từ AI", "ok");
    },
    onTranscript: (payload) => {
      if (payload.status === "started") {
        setStatus("AI đang nhận diện giọng nói…");
        log("AI đang nghe bạn nói");
        console.log("[STT] speech started");
        return;
      }
      const spoken = (payload.text || "").trim();
      if (spoken) {
        setStatus(`Bạn nói: ${spoken}`);
        log(`Bạn nói: ${spoken}`, "ok");
        console.log("[STT] transcript:", spoken);
      } else {
        log("AI không nhận ra câu nói", "warn");
        console.warn("[STT] transcript empty");
      }
    },
    onAgentSpeech: (payload) => {
      const spoken = (payload.text || "").trim();
      if (!spoken) return;
      lastAgentLine = spoken;
      setStatus(`AI nói: ${spoken}`);
      log(`AI nói: ${spoken}`, "agent");
      console.log("[TTS] agent:", spoken);
    },
    onOrderCreated: (payload) => {
      orderPlaced = true;
      showOrderSuccess(payload);
    },
    onClose: (code, reason) => {
      log(`Socket đóng: ${reason} (${code})`, code === 1000 ? "info" : "warn");
      void endCall(false);
    },
    onError: (message) => {
      log(message, "warn");
      setStatus(message);
    },
  });

  window.clearInterval(levelTimer);
  levelTimer = window.setInterval(() => {
    if (!live) return;
    const now = performance.now();
    if (agentSpeaking && !player.isPlaying && now >= suppressMicUntil) {
      agentSpeaking = false;
    }
    if (!heardAgent || agentSpeaking || holdingMicForEcho(now)) return;
    if (orderPlaced) {
      setStatus("Đã đặt hàng thành công");
      return;
    }
    setStatus(muted ? "Mic đang tắt" : "Đang nghe bạn nói");
  }, 800);
}

async function endCall(closeSocket: boolean): Promise<void> {
  if (!live && closeSocket === false) {
    setLiveUi(false);
    return;
  }
  live = false;
  canSend = false;
  muted = false;
  heardAgent = false;
  lastAgentLine = "";
  els.muteBtn.textContent = "Tắt mic";
  window.clearInterval(levelTimer);
  agentSpeaking = false;
  suppressMicUntil = 0;
  if (closeSocket) bridge.close();
  player.interrupt();
  await mic.stop();
  scope.setAnalysers(null, null);
  setLiveUi(false);
  resetKeypad();
  setStatus("Đã cúp. Nhấn Gọi để bắt đầu lượt mới.");
  log("Cúp máy");
}

function sendDtmf(digit: string): void {
  if (!live) return;
  // Im ngay tại client, không chờ server trả `interrupt` (§7.1.10).
  player.interrupt();
  agentSpeaking = false;
  noteAgentPlayback();
  bridge.sendDtmf(digit);
  for (const btn of keypadButtons) {
    btn.setAttribute("aria-pressed", String(btn.dataset.digit === digit));
  }
  const label = DTMF_LABELS[digit] || digit;
  log(`Đã ấn phím ${digit} — ${label}`, "ok");
  setStatus(`Đã chọn: ${label}`);
}

for (const btn of keypadButtons) {
  btn.addEventListener("click", () => {
    const digit = btn.dataset.digit || "";
    if (digit) sendDtmf(digit);
  });
}

window.addEventListener("keydown", (event) => {
  if (!live || event.repeat) return;
  if (event.key !== "1" && event.key !== "2" && event.key !== "3") return;
  const target = event.target;
  if (target instanceof HTMLElement) {
    const tag = target.tagName;
    if (tag === "INPUT" || tag === "TEXTAREA" || target.isContentEditable) return;
  }
  event.preventDefault();
  sendDtmf(event.key);
});

els.callBtn.addEventListener("click", () => {
  void startCall();
});
els.hangBtn.addEventListener("click", () => {
  void endCall(true);
});
els.muteBtn.addEventListener("click", () => {
  muted = !muted;
  els.muteBtn.textContent = muted ? "Bật mic" : "Tắt mic";
  setStatus(muted ? "Mic đang tắt" : "Đang nghe bạn nói");
  log(muted ? "Tắt mic" : "Bật mic");
});
els.volume.addEventListener("input", () => {
  player.setVolume(Number(els.volume.value));
});
els.pingBtn.addEventListener("click", () => {
  void pingHealth().then((ok) => log(ok ? "Health OK" : "Health thất bại", ok ? "ok" : "warn"));
});
els.clearLogBtn.addEventListener("click", () => {
  els.log.replaceChildren();
});

window.addEventListener("beforeunload", () => {
  if (live) bridge.close();
});

void pingHealth();
