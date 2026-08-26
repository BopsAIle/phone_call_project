const CAPTURE_WORKLET = `
class CaptureProcessor extends AudioWorkletProcessor {
  constructor() {
    super();
    this._chunks = [];
    this._samples = 0;
  }
  process(inputs) {
    const ch = inputs[0] && inputs[0][0];
    if (!ch || ch.length === 0) return true;
    this._chunks.push(new Float32Array(ch));
    this._samples += ch.length;
    if (this._samples >= 2048) {
      const merged = new Float32Array(this._samples);
      let offset = 0;
      for (const chunk of this._chunks) {
        merged.set(chunk, offset);
        offset += chunk.length;
      }
      this.port.postMessage(merged, [merged.buffer]);
      this._chunks = [];
      this._samples = 0;
    }
    return true;
  }
}
registerProcessor("capture-processor", CaptureProcessor);
`;

export type CaptureHandlers = {
  onAudio: (samples: Float32Array, sampleRate: number) => void;
};

export class MicCapture {
  private stream: MediaStream | null = null;
  private context: AudioContext | null = null;
  private source: MediaStreamAudioSourceNode | null = null;
  private worklet: AudioWorkletNode | null = null;
  private processor: ScriptProcessorNode | null = null;
  private silent: GainNode | null = null;
  private analyser: AnalyserNode | null = null;

  get sampleRate(): number {
    return this.context?.sampleRate ?? 48000;
  }

  getAnalyser(): AnalyserNode | null {
    return this.analyser;
  }

  async start(handlers: CaptureHandlers): Promise<void> {
    await this.stop();
    try {
      this.stream = await navigator.mediaDevices.getUserMedia({
        audio: {
          echoCancellation: true,
          noiseSuppression: true,
          autoGainControl: true,
          channelCount: 1,
        },
      });
    } catch {
      throw new Error("Không mở được micro. Hãy cho phép quyền micro rồi thử lại.");
    }

    const context = new AudioContext();
    this.context = context;
    if (context.state === "suspended") {
      await context.resume();
    }

    const source = context.createMediaStreamSource(this.stream);
    this.source = source;

    const analyser = context.createAnalyser();
    analyser.fftSize = 1024;
    analyser.smoothingTimeConstant = 0.65;
    this.analyser = analyser;
    source.connect(analyser);

    const silent = context.createGain();
    silent.gain.value = 0;
    this.silent = silent;

    try {
      const blob = new Blob([CAPTURE_WORKLET], { type: "application/javascript" });
      const url = URL.createObjectURL(blob);
      await context.audioWorklet.addModule(url);
      URL.revokeObjectURL(url);
      const node = new AudioWorkletNode(context, "capture-processor");
      this.worklet = node;
      node.port.onmessage = (event: MessageEvent<Float32Array>) => {
        handlers.onAudio(event.data, context.sampleRate);
      };
      analyser.connect(node);
      node.connect(silent);
      silent.connect(context.destination);
    } catch {
      const proc = context.createScriptProcessor(2048, 1, 1);
      this.processor = proc;
      proc.onaudioprocess = (event) => {
        const input = event.inputBuffer.getChannelData(0);
        handlers.onAudio(new Float32Array(input), context.sampleRate);
      };
      analyser.connect(proc);
      proc.connect(silent);
      silent.connect(context.destination);
    }
  }

  async stop(): Promise<void> {
    this.worklet?.port.postMessage("stop");
    this.worklet?.disconnect();
    this.processor?.disconnect();
    this.source?.disconnect();
    this.analyser?.disconnect();
    this.silent?.disconnect();
    this.worklet = null;
    this.processor = null;
    this.source = null;
    this.analyser = null;
    this.silent = null;
    if (this.stream) {
      for (const track of this.stream.getTracks()) track.stop();
      this.stream = null;
    }
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
