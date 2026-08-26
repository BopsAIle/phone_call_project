import "./styles.css";
import { BridgeClient } from "./bridge";
import { MicCapture } from "./capture";
import { floatToPcm16, LinearResampler, PcmFramer, rms } from "./pcm";
import { PcmPlayer } from "./playback";
import { newCallId } from "./protocol";
import { PolarScope } from "./viz";

const STORAGE_KEY = "ai-bridge-voice-demo";

type Settings = {
  wsUrl: string;
  token: string;
  storeName: string;
  locale: string;
  timezone: string;
  greeting: string;
};

const DEFAULTS: Settings = {
  wsUrl: import.meta.env.VITE_AI_BRIDGE_URL || "ws://127.0.0.1:8080/v1/bridge",
  token: import.meta.env.VITE_AI_BRIDGE_TOKEN || "",
  storeName: "Bella Vista",
  locale: "vi",
  timezone: "Asia/Ho_Chi_Minh",
  greeting:
    "Xin chào, cảm ơn bạn đã gọi Bella Vista. Đây là trợ lý tự động — mình có thể giúp gì ạ?",
};

const els = {
  wsUrl: $("wsUrl", HTMLInputElement),
  token: $("token", HTMLInputElement),
  storeName: $("storeName", HTMLInputElement),
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
    return { ...DEFAULTS, ...(JSON.parse(raw) as Partial<Settings>) };
  } catch {
    return { ...DEFAULTS };
  }
}

function readForm(): Settings {
  return {
    wsUrl: els.wsUrl.value.trim() || DEFAULTS.wsUrl,
    token: els.token.value.trim(),
    storeName: els.storeName.value.trim() || DEFAULTS.storeName,
    locale: els.locale.value || "vi",
    timezone: els.timezone.value.trim() || DEFAULTS.timezone,
    greeting: els.greeting.value.trim() || DEFAULTS.greeting,
  };
}

function fillForm(s: Settings): void {
  els.wsUrl.value = s.wsUrl;
  els.token.value = s.token;
  els.storeName.value = s.storeName;
  els.locale.value = s.locale;
  els.timezone.value = s.timezone;
  els.greeting.value = s.greeting;
}

function persist(): void {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(readForm()));
}

function log(message: string, tone: "info" | "warn" | "ok" = "info"): void {
  const li = document.createElement("li");
  const time = document.createElement("time");
  time.textContent = new Date().toLocaleTimeString("vi-VN", { hour12: false });
  const body = document.createElement("strong");
  body.textContent = tone === "warn" ? "!" : tone === "ok" ? "●" : "·";
  li.append(time, body, document.createTextNode(message));
  els.log.prepend(li);
}

function setStatus(text: string): void {
  els.status.textContent = text;
}

function setLiveUi(live: boolean): void {
  els.callBtn.disabled = live;
  els.hangBtn.disabled = !live;
  els.muteBtn.disabled = !live;
  els.wsUrl.disabled = live;
  els.token.disabled = live;
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

let live = false;
let muted = false;
let canSend = false;
let agentSpeaking = false;
let heardAgent = false;
let levelTimer = 0;

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
        const peak = rms(samples);
        if (!muted && peak > 0.02 && agentSpeaking) {
          setStatus("Bạn đang nói — có thể barge-in");
        }
        if (muted || !canSend) return;
        const resampled = resampler.push(samples);
        if (resampled.length === 0) return;
        const pcm = floatToPcm16(resampled);
        for (const frame of framer.push(pcm)) {
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
      player.enqueue(bytes);
      setStatus("Agent đang nói");
    },
    onInterrupt: () => {
      agentSpeaking = false;
      player.interrupt();
      setStatus("Barge-in — agent dừng, đang nghe bạn.");
      log("interrupt từ AI", "ok");
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
    if (agentSpeaking && !player.isPlaying) {
      agentSpeaking = false;
    }
    if (!heardAgent || agentSpeaking) return;
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
  els.muteBtn.textContent = "Tắt mic";
  window.clearInterval(levelTimer);
  agentSpeaking = false;
  if (closeSocket) bridge.close();
  player.interrupt();
  await mic.stop();
  scope.setAnalysers(null, null);
  setLiveUi(false);
  setStatus("Đã cúp. Nhấn Gọi để bắt đầu lượt mới.");
  log("Cúp máy");
}

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
