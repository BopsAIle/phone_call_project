/**
 * A browser that pretends to be Twilio.
 *
 * It drives the real `/twilio/voice` webhook, then speaks the Media Streams
 * protocol at `/media-stream` byte for byte — same frames out, same frames in,
 * no special case anywhere on the server. When a real number is available you
 * point it at the webhook and nothing here matters any more.
 *
 * See docs/plan/phases/phase-1-audio-path/browser-dev-client.md.
 */
import {
  TELEPHONY_SAMPLE_RATE,
  decodeMulaw,
  pcm16ToMulaw,
} from '../src/audio/mulaw.codec';

/**
 * Int16 full scale. One constant for both directions on purpose: if capture and
 * playback disagreed, the loopback would still sound correct because the second
 * conversion undoes the first, and the error would only surface in Phase 2 as
 * bad STT.
 */
const FULL_SCALE = 32768;

/** Jitter margin before the first scheduled frame, ~3 frames. */
const PLAYBACK_CUSHION_S = 0.06;

const WORKLET_URL = '/dev/assets/capture-worklet.js';

/** Twilio's own format: a `CA`/`MZ`/`AC` prefix and 32 hex characters. */
function sid(prefix: string): string {
  const bytes = new Uint8Array(16);
  crypto.getRandomValues(bytes);

  return (
    prefix +
    Array.from(bytes, (byte) => byte.toString(16).padStart(2, '0')).join('')
  );
}

function toBase64(bytes: Uint8Array): string {
  let binary = '';
  for (let i = 0; i < bytes.length; i++) binary += String.fromCharCode(bytes[i]);

  return btoa(binary);
}

function fromBase64(payload: string): Uint8Array {
  const binary = atob(payload);
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i);

  return bytes;
}

/**
 * Float32 `[-1, 1]` to Int16.
 *
 * The clamp is not decoration. `Math.round(1.0 * 32768)` is 32768, which
 * overflows Int16 and wraps to -32768 — a full-scale positive sample becomes
 * full-scale negative, and it only crackles on the loudest peaks.
 */
function floatToPcm16(sample: number): number {
  return Math.max(
    -FULL_SCALE,
    Math.min(FULL_SCALE - 1, Math.round(sample * FULL_SCALE)),
  );
}

interface StreamTarget {
  url: string;
  parameters: Record<string, string>;
}

/**
 * Calls the voice webhook exactly as Twilio would and reads the stream target
 * back out of the TwiML, the same way test/harness/replay.ts does — so the
 * store lookup and the `Call` row are genuinely exercised rather than faked.
 */
async function openCall(callSid: string): Promise<StreamTarget> {
  const configResponse = await fetch('/dev/config');
  if (!configResponse.ok) {
    throw new Error(`GET /dev/config returned ${configResponse.status}`);
  }

  const { storeNumber } = (await configResponse.json()) as {
    storeNumber: string;
  };

  const response = await fetch('/twilio/voice', {
    method: 'POST',
    headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
    body: new URLSearchParams({
      CallSid: callSid,
      From: '+15550000001',
      To: storeNumber,
      CallStatus: 'ringing',
      Direction: 'inbound',
    }),
  });

  if (!response.ok) {
    throw new Error(`POST /twilio/voice returned ${response.status}`);
  }

  const twiml = new DOMParser().parseFromString(
    await response.text(),
    'text/xml',
  );
  const stream = twiml.querySelector('Stream');

  if (!stream) {
    throw new Error(
      `No <Stream> in the TwiML — is ${storeNumber} seeded as a store? ` +
        'Run `npm run db:seed`.',
    );
  }

  const parameters: Record<string, string> = {};
  for (const parameter of stream.querySelectorAll('Parameter')) {
    const name = parameter.getAttribute('name');
    const value = parameter.getAttribute('value');
    if (name !== null && value !== null) parameters[name] = value;
  }

  // Take the path from the TwiML but keep this page's origin. The advertised
  // host comes from PUBLIC_BASE_URL, which points at the tunnel Twilio would
  // use — the browser is already inside the network and has no tunnel to cross.
  const local = new URL(
    new URL(stream.getAttribute('url') ?? '').pathname,
    window.location.origin,
  );
  local.protocol = local.protocol === 'https:' ? 'wss:' : 'ws:';

  return { url: local.toString(), parameters };
}

interface InboundFrame {
  event: string;
  media?: { payload: string };
  mark?: { name: string };
}

/** One call: its socket, its audio graph, and its share of the protocol. */
class DevCall {
  private readonly callSid = sid('CA');
  private readonly streamSid = sid('MZ');
  private readonly accountSid = sid('AC');

  private socket!: WebSocket;
  private ctx!: AudioContext;
  private microphone!: MediaStream;

  private sequence = 1;
  private chunk = 0;

  /** Playback scheduling cursor, in `AudioContext` time. */
  private cursor = 0;
  private readonly live = new Set<AudioBufferSourceNode>();
  private readonly pendingMarks = new Map<AudioBufferSourceNode, string[]>();
  private lastScheduled: AudioBufferSourceNode | null = null;

  framesSent = 0;
  framesReceived = 0;

  constructor(private readonly onClosed: () => void) {}

  async start(): Promise<void> {
    const target = await openCall(this.callSid);

    this.microphone = await navigator.mediaDevices.getUserMedia({
      audio: {
        channelCount: 1,
        echoCancellation: true,
        noiseSuppression: true,
        autoGainControl: true,
      },
    });

    this.ctx = new AudioContext({ sampleRate: TELEPHONY_SAMPLE_RATE });

    // Fail loudly. Silently sending audio at the wrong rate sounds exactly like
    // a codec bug and costs an afternoon to trace back to here.
    if (this.ctx.sampleRate !== TELEPHONY_SAMPLE_RATE) {
      await this.ctx.close();
      throw new Error(
        `This browser opened the AudioContext at ${this.ctx.sampleRate} Hz ` +
          `instead of ${TELEPHONY_SAMPLE_RATE}. Try Chrome, Edge, or Firefox.`,
      );
    }

    await this.ctx.audioWorklet.addModule(WORKLET_URL);
    await this.connect(target.url);

    this.send({ event: 'connected', protocol: 'Call', version: '1.0.0' });
    this.send({
      event: 'start',
      sequenceNumber: String(this.sequence++),
      streamSid: this.streamSid,
      start: {
        streamSid: this.streamSid,
        accountSid: this.accountSid,
        callSid: this.callSid,
        tracks: ['inbound'],
        customParameters: target.parameters,
        mediaFormat: {
          encoding: 'audio/x-mulaw',
          sampleRate: TELEPHONY_SAMPLE_RATE,
          channels: 1,
        },
      },
    });

    this.startCapture();
  }

  private connect(url: string): Promise<void> {
    this.socket = new WebSocket(url);

    this.socket.addEventListener('message', (event: MessageEvent<string>) => {
      this.handleFrame(event.data);
    });
    this.socket.addEventListener('close', this.onClosed, { once: true });

    return new Promise((resolve, reject) => {
      this.socket.addEventListener('open', () => resolve(), { once: true });
      this.socket.addEventListener(
        'error',
        () => reject(new Error(`Could not connect to ${url}`)),
        { once: true },
      );
    });
  }

  private startCapture(): void {
    const source = this.ctx.createMediaStreamSource(this.microphone);
    const capture = new AudioWorkletNode(this.ctx, 'capture-processor');

    capture.port.onmessage = (event: MessageEvent<Float32Array>) => {
      this.sendMedia(event.data);
    };

    // The graph only pulls nodes that reach the destination, so the worklet
    // needs a path there or it never runs. It goes through a silent gain —
    // routing the microphone to the speakers directly would be a second echo,
    // on top of the one we are actually testing.
    const silence = this.ctx.createGain();
    silence.gain.value = 0;

    source.connect(capture);
    capture.connect(silence).connect(this.ctx.destination);
  }

  private sendMedia(frame: Float32Array): void {
    const mulaw = new Uint8Array(frame.length);
    for (let i = 0; i < frame.length; i++) {
      mulaw[i] = pcm16ToMulaw(floatToPcm16(frame[i]));
    }

    this.send({
      event: 'media',
      sequenceNumber: String(this.sequence++),
      streamSid: this.streamSid,
      media: {
        track: 'inbound',
        chunk: String(++this.chunk),
        timestamp: String(this.chunk * 20),
        payload: toBase64(mulaw),
      },
    });

    this.framesSent++;
  }

  private handleFrame(raw: string): void {
    let frame: InboundFrame;

    try {
      frame = JSON.parse(raw) as InboundFrame;
    } catch {
      return;
    }

    switch (frame.event) {
      case 'media':
        if (!frame.media) return;
        this.framesReceived++;
        this.schedule(decodeMulaw(fromBase64(frame.media.payload)));
        break;

      case 'mark':
        if (frame.mark) this.handleMark(frame.mark.name);
        break;

      case 'clear':
        this.handleClear();
        break;
    }
  }

  private schedule(pcm: Int16Array): void {
    const buffer = this.ctx.createBuffer(
      1,
      pcm.length,
      TELEPHONY_SAMPLE_RATE,
    );
    const channel = buffer.getChannelData(0);
    for (let i = 0; i < pcm.length; i++) channel[i] = pcm[i] / FULL_SCALE;

    const source = this.ctx.createBufferSource();
    source.buffer = buffer;
    source.connect(this.ctx.destination);

    const startAt = Math.max(
      this.cursor,
      this.ctx.currentTime + PLAYBACK_CUSHION_S,
    );
    source.start(startAt);
    this.cursor = startAt + buffer.duration;

    this.live.add(source);
    this.lastScheduled = source;
    source.onended = () => this.onSourceEnded(source);
  }

  /**
   * Twilio does not consume a `mark` — it sends it back once the audio queued
   * ahead of it has finished playing, which is how the server learns an
   * utterance actually reached the caller. Holding it against the last
   * scheduled buffer reproduces that; logging it would leave the gateway's
   * `mark` path untested until the first real phone call.
   */
  private handleMark(name: string): void {
    if (!this.lastScheduled) {
      this.sendMark(name);
      return;
    }

    const queued = this.pendingMarks.get(this.lastScheduled) ?? [];
    queued.push(name);
    this.pendingMarks.set(this.lastScheduled, queued);
  }

  private onSourceEnded(source: AudioBufferSourceNode): void {
    this.live.delete(source);
    if (this.lastScheduled === source) this.lastScheduled = null;

    const queued = this.pendingMarks.get(source);
    if (!queued) return;

    this.pendingMarks.delete(source);
    for (const name of queued) this.sendMark(name);
  }

  /** Drops buffered audio the way Twilio does — including the marks waiting on it. */
  private handleClear(): void {
    for (const source of this.live) {
      source.onended = null;
      try {
        source.stop();
      } catch {
        // Already finished; stop() on a stopped source throws.
      }
    }

    this.live.clear();
    this.pendingMarks.clear();
    this.lastScheduled = null;
    this.cursor = 0;
  }

  async hangUp(): Promise<void> {
    this.send({
      event: 'stop',
      sequenceNumber: String(this.sequence++),
      streamSid: this.streamSid,
      stop: { accountSid: this.accountSid, callSid: this.callSid },
    });

    this.socket.close();
    for (const track of this.microphone.getTracks()) track.stop();
    await this.ctx.close();
  }

  private sendMark(name: string): void {
    this.send({ event: 'mark', streamSid: this.streamSid, mark: { name } });
  }

  private send(message: unknown): void {
    if (this.socket.readyState !== WebSocket.OPEN) return;

    this.socket.send(JSON.stringify(message));
  }

  get sid(): string {
    return this.streamSid;
  }
}

const el = <T extends HTMLElement>(id: string): T =>
  document.getElementById(id) as T;

const callButton = el<HTMLButtonElement>('call');
const hangUpButton = el<HTMLButtonElement>('hangup');
const markButton = el<HTMLButtonElement>('mark');
const clearButton = el<HTMLButtonElement>('clear');
const bargeInButton = el<HTMLButtonElement>('barge-in');
const statusLine = el<HTMLParagraphElement>('status');
const framesLine = el<HTMLParagraphElement>('frames');

let call: DevCall | null = null;
let ticker: number | undefined;

function setStatus(text: string, tone: 'idle' | 'live' | 'error'): void {
  statusLine.textContent = text;
  statusLine.dataset.tone = tone;
}

function setLive(live: boolean): void {
  callButton.disabled = live;
  hangUpButton.disabled = !live;
  markButton.disabled = !live;
  clearButton.disabled = !live;
  bargeInButton.disabled = !live;
}

function onClosed(): void {
  window.clearInterval(ticker);
  setLive(false);
  setStatus('Call ended.', 'idle');
  call = null;
}

callButton.addEventListener('click', () => {
  const active = new DevCall(onClosed);

  setLive(true);
  setStatus('Connecting…', 'idle');

  active
    .start()
    .then(() => {
      call = active;
      setStatus(`Live on ${active.sid}. Use headphones.`, 'live');
      ticker = window.setInterval(() => {
        framesLine.textContent = `${active.framesSent} frames sent · ${active.framesReceived} received`;
      }, 250);
    })
    .catch((error: unknown) => {
      setLive(false);
      setStatus(error instanceof Error ? error.message : String(error), 'error');
    });
});

hangUpButton.addEventListener('click', () => {
  setLive(false);
  void call?.hangUp();
});

/**
 * Asks the *server* to act on the live stream.
 *
 * `mark` and `clear` push raw frames and prove the wire protocol on its own.
 * `barge-in` drives the agent's real interruption path — abort, clear, drop the
 * queue — from a deterministic trigger, which is the only way to test that
 * behaviour without talking over the agent at exactly the right moment.
 */
function trigger(path: string): void {
  if (!call) return;

  void fetch(`/dev/${path}/${call.sid}`, { method: 'POST' });
}

markButton.addEventListener('click', () => trigger('mark'));
clearButton.addEventListener('click', () => trigger('clear'));
bargeInButton.addEventListener('click', () => trigger('barge-in'));

setLive(false);
setStatus('Ready.', 'idle');
