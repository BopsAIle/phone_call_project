export class PolarScope {
  private readonly canvas: HTMLCanvasElement;
  private readonly ctx: CanvasRenderingContext2D;
  private mic: AnalyserNode | null = null;
  private agent: AnalyserNode | null = null;
  private raf = 0;
  private micBuf: Uint8Array<ArrayBuffer> | null = null;
  private agentBuf: Uint8Array<ArrayBuffer> | null = null;
  private pulse = 0;

  constructor(canvas: HTMLCanvasElement) {
    this.canvas = canvas;
    const ctx = canvas.getContext("2d");
    if (!ctx) throw new Error("Canvas 2D không khả dụng");
    this.ctx = ctx;
    this.resize();
  }

  setAnalysers(mic: AnalyserNode | null, agent: AnalyserNode | null): void {
    this.mic = mic;
    this.agent = agent;
    this.micBuf = mic ? new Uint8Array(new ArrayBuffer(mic.fftSize)) : null;
    this.agentBuf = agent ? new Uint8Array(new ArrayBuffer(agent.fftSize)) : null;
  }

  start(): void {
    cancelAnimationFrame(this.raf);
    const tick = () => {
      this.draw();
      this.raf = requestAnimationFrame(tick);
    };
    this.raf = requestAnimationFrame(tick);
  }

  stop(): void {
    cancelAnimationFrame(this.raf);
    this.raf = 0;
    this.drawIdle();
  }

  resize(): void {
    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    const rect = this.canvas.getBoundingClientRect();
    const w = Math.max(1, Math.floor(rect.width * dpr));
    const h = Math.max(1, Math.floor(rect.height * dpr));
    if (this.canvas.width !== w || this.canvas.height !== h) {
      this.canvas.width = w;
      this.canvas.height = h;
    }
  }

  private draw(): void {
    this.resize();
    const { ctx, canvas } = this;
    const w = canvas.width;
    const h = canvas.height;
    ctx.clearRect(0, 0, w, h);

    const cx = w / 2;
    const cy = h / 2;
    const radius = Math.min(w, h) * 0.32;
    this.pulse += 0.03;

    this.ring(cx, cy, radius * 1.35, "rgba(232, 165, 75, 0.12)");
    this.ring(cx, cy, radius * 1.15, "rgba(61, 214, 140, 0.1)");

    if (this.mic && this.micBuf) {
      this.mic.getByteTimeDomainData(this.micBuf);
      this.drawPolar(this.micBuf, cx, cy, radius, "#3dd68c", 0.9);
    }
    if (this.agent && this.agentBuf) {
      this.agent.getByteTimeDomainData(this.agentBuf);
      this.drawPolar(this.agentBuf, cx, cy, radius * 0.72, "#e8a54b", 0.85);
    }
    if (!this.mic && !this.agent) {
      this.drawIdleWave(cx, cy, radius);
    }

    ctx.beginPath();
    ctx.arc(cx, cy, 10 + Math.sin(this.pulse) * 2, 0, Math.PI * 2);
    ctx.fillStyle = "#f3efe6";
    ctx.fill();
  }

  private drawIdle(): void {
    this.resize();
    const { ctx, canvas } = this;
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    this.drawIdleWave(canvas.width / 2, canvas.height / 2, Math.min(canvas.width, canvas.height) * 0.32);
  }

  private drawIdleWave(cx: number, cy: number, radius: number): void {
    const t = performance.now() / 700;
    const fake = new Uint8Array(180);
    for (let i = 0; i < fake.length; i++) {
      fake[i] = 128 + Math.sin(i / 12 + t) * 10;
    }
    this.drawPolar(fake, cx, cy, radius, "rgba(243, 239, 230, 0.35)", 0.35);
    this.ring(cx, cy, radius * 1.2, "rgba(243, 239, 230, 0.08)");
  }

  private ring(cx: number, cy: number, r: number, color: string): void {
    const { ctx } = this;
    ctx.beginPath();
    ctx.arc(cx, cy, r, 0, Math.PI * 2);
    ctx.strokeStyle = color;
    ctx.lineWidth = 2;
    ctx.stroke();
  }

  private drawPolar(
    data: Uint8Array,
    cx: number,
    cy: number,
    radius: number,
    color: string,
    amp: number,
  ): void {
    const { ctx } = this;
    const n = data.length;
    ctx.beginPath();
    for (let i = 0; i <= n; i++) {
      const idx = i % n;
      const v = ((data[idx] ?? 128) - 128) / 128;
      const r = radius + v * radius * amp;
      const angle = (idx / n) * Math.PI * 2 - Math.PI / 2;
      const x = cx + Math.cos(angle) * r;
      const y = cy + Math.sin(angle) * r;
      if (i === 0) ctx.moveTo(x, y);
      else ctx.lineTo(x, y);
    }
    ctx.closePath();
    ctx.strokeStyle = color;
    ctx.lineWidth = 2.2;
    ctx.stroke();
  }
}
