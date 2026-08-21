import { SentenceChunker } from './sentence-chunker';

/** Feeds text one character at a time, the worst case a real stream produces. */
function streamCharwise(text: string): {
  chunks: string[];
  tail: string | null;
} {
  const chunker = new SentenceChunker();
  const chunks: string[] = [];

  for (const char of text) chunks.push(...chunker.push(char));

  return { chunks, tail: chunker.flush() };
}

/** Feeds text in word-sized deltas, closer to what the API actually sends. */
function streamWordwise(text: string): {
  chunks: string[];
  tail: string | null;
} {
  const chunker = new SentenceChunker();
  const chunks: string[] = [];

  for (const word of text.split(/(?<= )/)) chunks.push(...chunker.push(word));

  return { chunks, tail: chunker.flush() };
}

describe('SentenceChunker', () => {
  it('holds a partial sentence back', () => {
    const chunker = new SentenceChunker();

    expect(chunker.push('Of course, I can take')).toEqual([]);
    expect(chunker.pending).toBeGreaterThan(0);
  });

  it('flushes on a sentence boundary once the delta after the dot arrives', () => {
    const chunker = new SentenceChunker();

    // The dot alone is not enough: it could still be a decimal.
    expect(chunker.push('Of course, I can take a booking for two.')).toEqual(
      [],
    );
    expect(chunker.push(' What')).toEqual([
      'Of course, I can take a booking for two.',
    ]);
  });

  it('flushes immediately on ? and !, which are never ambiguous', () => {
    expect(new SentenceChunker().push('What time would you like?')).toEqual([
      'What time would you like?',
    ]);

    expect(new SentenceChunker().push('Thanks for calling!')).toEqual([
      'Thanks for calling!',
    ]);
  });

  it('treats a newline as a boundary', () => {
    expect(new SentenceChunker().push('Let me take your name\n')).toEqual([
      'Let me take your name',
    ]);
  });

  it('ignores empty deltas', () => {
    const chunker = new SentenceChunker();

    expect(chunker.push('')).toEqual([]);
    expect(chunker.pending).toBe(0);
  });

  describe('boundaries that are not sentence ends', () => {
    it('does not split a decimal time', () => {
      const { chunks, tail } = streamCharwise(
        'Your table is booked for 7.30 this evening.',
      );

      expect(chunks).toEqual([]);
      expect(tail).toBe('Your table is booked for 7.30 this evening.');
    });

    it('does not split after an abbreviation', () => {
      const { chunks, tail } = streamCharwise(
        'I will let Dr. Weber know you called.',
      );

      expect(chunks).toEqual([]);
      expect(tail).toBe('I will let Dr. Weber know you called.');
    });

    it('does not split on punctuation inside a very short opener', () => {
      // "Sure." is under the minimum, so it rides along with what follows
      // rather than becoming a TTS request of its own.
      const { chunks } = streamWordwise('Sure. What day were you thinking of?');

      expect(chunks).toEqual(['Sure. What day were you thinking of?']);
    });
  });

  describe('the character cap', () => {
    it('breaks a run-on at a space, never mid-word', () => {
      const runOn =
        'we can certainly note that down for you and someone will call you back ' +
        'later today to confirm everything';

      const { chunks, tail } = streamCharwise(runOn);

      expect(chunks.length).toBeGreaterThan(0);
      for (const chunk of chunks) {
        expect(chunk.length).toBeLessThanOrEqual(80);
        expect(chunk).not.toMatch(/\s$/);
      }

      expect([...chunks, tail].join(' ')).toBe(runOn);
    });

    it('lets a single unbroken token exceed the cap rather than splitting it', () => {
      const token = 'a'.repeat(120);

      const { chunks, tail } = streamCharwise(token);

      expect(chunks).toEqual([]);
      expect(tail).toBe(token);
    });
  });

  describe('flush', () => {
    it('emits a reply that ends without punctuation', () => {
      const chunker = new SentenceChunker();
      chunker.push('and someone will call you back');

      expect(chunker.flush()).toBe('and someone will call you back');
    });

    it('emits a reply whose last character is a dot still awaiting its successor', () => {
      const chunker = new SentenceChunker();

      expect(chunker.push('I can take those details for you.')).toEqual([]);
      expect(chunker.flush()).toBe('I can take those details for you.');
    });

    it('returns null when nothing is pending', () => {
      expect(new SentenceChunker().flush()).toBeNull();
    });

    it('empties the buffer', () => {
      const chunker = new SentenceChunker();
      chunker.push('anything');
      chunker.flush();

      expect(chunker.pending).toBe(0);
      expect(chunker.flush()).toBeNull();
    });
  });

  /**
   * The property that matters: delta boundaries must not be visible in the
   * output. The API splits tokens wherever it likes, and a chunker that behaved
   * differently per split would be untestable against a real stream.
   */
  it('produces the same sentences regardless of how the stream is split', () => {
    const reply =
      'Of course, I can take a booking request for two. ' +
      'What day and time were you hoping for?';

    const charwise = streamCharwise(reply);
    const wordwise = streamWordwise(reply);
    const atOnce = (() => {
      const chunker = new SentenceChunker();
      const chunks = chunker.push(reply);
      return { chunks, tail: chunker.flush() };
    })();

    expect(wordwise).toEqual(charwise);
    expect(atOnce).toEqual(charwise);
    expect(charwise.chunks).toEqual([
      'Of course, I can take a booking request for two.',
      'What day and time were you hoping for?',
    ]);
    expect(charwise.tail).toBeNull();
  });

  it('never loses or reorders text across a whole reply', () => {
    const reply =
      'I cannot check availability from here. ' +
      'I will take your details and a colleague will call you back to confirm. ' +
      'Could I start with your name?';

    const { chunks, tail } = streamCharwise(reply);

    expect([...chunks, tail].filter(Boolean).join(' ')).toBe(reply.trim());
  });
});
