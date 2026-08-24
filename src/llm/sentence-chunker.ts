/**
 * Cuts a stream of LLM token deltas into speakable sentences.
 *
 * This is the single biggest latency win in the phase. Waiting for the whole
 * completion before calling TTS costs ~2.5 s to first audio; flushing the first
 * sentence the moment it is complete costs ~0.8 s, because TTS synthesises it
 * while the model is still writing the second.
 *
 * Deliberately the same shape as `FrameBuffer`: `push()` returns whole units and
 * `flush()` returns the tail. The two stream chunkers in this codebase should
 * read alike.
 *
 * One instance per completion.
 */

/** Below this, a boundary is treated as punctuation inside a phrase, not an end. */
const MIN_CHUNK_CHARS = 12;

/**
 * Flush an over-long run-on even without punctuation.
 *
 * A model that writes a 300-character sentence would otherwise hold all of it
 * back and hand TTS one enormous request, which is exactly the wait this class
 * exists to avoid.
 */
const MAX_CHUNK_CHARS = 80;

const BOUNDARIES = new Set(['.', '?', '!', '\n']);

/**
 * Titles and abbreviations whose trailing dot is not a sentence end.
 *
 * Short and English-only on purpose — Phase 5 adds `Hr`, `Fr`, `Nr`, `bzw`,
 * `ca`, `usw` for German. A missed entry costs one extra TTS request and a small
 * pause in an odd place, never a wrong or broken reply, so this does not warrant
 * a tokeniser.
 */
const ABBREVIATIONS = new Set([
  'dr',
  'mr',
  'mrs',
  'ms',
  'prof',
  'st',
  'vs',
  'etc',
  'approx',
  'no',
]);

export class SentenceChunker {
  private buffer = '';

  /**
   * Set when the buffer ends on `.` and we cannot yet tell whether it is a
   * sentence end or a decimal point.
   *
   * `7.30` and `Dr. Smith` are only distinguishable by what comes *next*, and a
   * streamed delta often ends exactly on the dot. Holding one delta is the
   * whole trick; `?` and `!` are unambiguous and never wait.
   */
  private pendingDot = false;

  /** Characters held back because they do not yet make a whole sentence. */
  get pending(): number {
    return this.buffer.length;
  }

  /** Adds a token delta and returns every sentence that became complete. */
  push(delta: string): string[] {
    const chunks: string[] = [];
    if (delta.length === 0) return chunks;

    for (const char of delta) {
      // Resolve the previous delta's trailing dot now that its successor is
      // known: a digit means a decimal, anything else means a sentence end.
      if (this.pendingDot) {
        this.pendingDot = false;

        if (!/\d/.test(char) && !this.endsWithAbbreviation()) {
          const chunk = this.take();
          if (chunk) chunks.push(chunk);
        }
      }

      this.buffer += char;

      if (
        BOUNDARIES.has(char) &&
        this.buffer.trim().length >= MIN_CHUNK_CHARS
      ) {
        if (char === '.') {
          // Wait one character before deciding. If the stream ends here,
          // `flush()` emits it anyway, so nothing is ever stranded.
          this.pendingDot = true;
        } else {
          const chunk = this.take();
          if (chunk) chunks.push(chunk);
        }
        continue;
      }

      if (this.buffer.length >= MAX_CHUNK_CHARS) {
        const chunk = this.takeAtLastSpace();
        if (chunk) chunks.push(chunk);
      }
    }

    return chunks;
  }

  /**
   * Emits whatever is left, for the end of a completion.
   *
   * A reply very often ends without terminal punctuation, or on a dot still
   * waiting for its successor — both would otherwise be silently dropped, which
   * reads as the agent trailing off mid-thought.
   */
  flush(): string | null {
    this.pendingDot = false;
    return this.take();
  }

  reset(): void {
    this.buffer = '';
    this.pendingDot = false;
  }

  private take(): string | null {
    const chunk = this.buffer.trim();
    this.buffer = '';

    return chunk.length > 0 ? chunk : null;
  }

  /**
   * Splits a run-on at the last space so the cap never lands mid-word.
   *
   * TTS pronounces a fragment like "reserva" phonetically, which is far more
   * obviously broken than a slightly early sentence break.
   */
  private takeAtLastSpace(): string | null {
    const cut = this.buffer.lastIndexOf(' ');

    if (cut <= 0) {
      // One unbroken token longer than the cap. Rare, and splitting it mid-word
      // would sound worse than letting it grow.
      return null;
    }

    const chunk = this.buffer.slice(0, cut).trim();
    this.buffer = this.buffer.slice(cut + 1);

    return chunk.length > 0 ? chunk : null;
  }

  /** True when the buffer ends on something like "Dr." rather than a sentence. */
  private endsWithAbbreviation(): boolean {
    const match = /(\w+)\.$/.exec(this.buffer);

    return match ? ABBREVIATIONS.has(match[1].toLowerCase()) : false;
  }
}
