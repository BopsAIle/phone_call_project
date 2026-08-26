import { SAMPLE_RATE } from "./protocol";
import { pcm16ToFloat } from "./pcm";

const LEAD_SECONDS = 0.06;

export class PcmPlayer {
  private context: AudioContext | null = null;
  private gain: GainNode | null = null;
  private analyser: AnalyserNode | null = null;
  private nextTime = 0;
  private sources: AudioBufferSourceNode[] = [];
  private queuedSeconds = 0;

  getAnalyser(): AnalyserNode | null {
    return this.analyser;
  }

  get isPlaying(): boolean {
    return this.sources.length > 0 || this.queuedSeconds > 0.04;
  }

  async ensureStarted(): Promise<void> {
    if (this.context && this.context.state !== "closed") {
      if (this.context.state === "suspended") await this.context.resume();
      return;
    }
    const context = new AudioContext();
    this.context = context;
    const gain = context.createGain();
    gain.gain.value = 1;
    const analyser = context.createAnalyser();
    analyser.fftSize = 1024;
    analyser.smoothingTimeConstant = 0.7;
    gain.connect(analyser);
    analyser.connect(context.destination);
    this.gain = gain;
    this.analyser = analyser;
    this.nextTime = 0;
    if (context.state === "suspended") await context.resume();
  }

  setVolume(value: number): void {
    if (this.gain) this.gain.gain.value = Math.max(0, Math.min(1, value));
  }

  enqueue(pcmBytes: ArrayBuffer): void {
    if (!this.context || !this.gain || this.context.state === "closed") return;
    const samples = pcm16ToFloat(pcmBytes);
    if (samples.length === 0) return;

    const buffer = this.context.createBuffer(1, samples.length, SAMPLE_RATE);
    const channel = buffer.getChannelData(0);
    channel.set(samples);

    const source = this.context.createBufferSource();
    source.buffer = buffer;
    source.connect(this.gain);

    const now = this.context.currentTime;
    if (this.nextTime < now + LEAD_SECONDS) {
      this.nextTime = now + LEAD_SECONDS;
    }
    source.start(this.nextTime);
    this.nextTime += buffer.duration;
    this.queuedSeconds = Math.max(0, this.nextTime - now);
    this.sources.push(source);
    source.onended = () => {
      this.sources = this.sources.filter((s) => s !== source);
      if (this.context) {
        this.queuedSeconds = Math.max(0, this.nextTime - this.context.currentTime);
      }
    };
  }

  /** Hợp đồng barge-in: xóa audio agent đã xếp, để mic người dùng không bị nói đè. */
  interrupt(): void {
    for (const source of this.sources) {
      try {
        source.stop();
      } catch {
        /* already stopped */
      }
    }
    this.sources = [];
    this.queuedSeconds = 0;
    this.nextTime = 0;
  }

  async close(): Promise<void> {
    this.interrupt();
    this.gain?.disconnect();
    this.analyser?.disconnect();
    this.gain = null;
    this.analyser = null;
    if (this.context) {
      try {
        await this.context.close();
      } catch {
        /* already closed */
      }
      this.context = null;
    }
  }
}
