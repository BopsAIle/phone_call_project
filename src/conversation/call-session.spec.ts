import type { AiSession } from '../ai-bridge/ai-bridge.provider';
import { AI_SAMPLE_RATE } from '../ai-bridge/wire-format';
import {
  MULAW_FRAME_BYTES,
  decodeMulaw,
  encodeMulaw,
} from '../audio/mulaw.codec';
import { int16ToLe } from '../audio/pcm';
import { Upsampler } from '../audio/resampler';
import type { OutboundAudioSink } from './audio-sink';
import { CallSession } from './call-session';

/** One 20 ms Twilio frame: 160 mu-law bytes. */
function twilioFrame(): Buffer {
  return encodeMulaw(new Int16Array(160).fill(1000));
}

/**
 * `n` samples of agent audio at 16 kHz, as the AI service would send them.
 *
 * A tone rather than silence: the assertions below are about byte counts and
 * alignment, but a resampler bug that produced silence would still pass a
 * length check, and this makes the round-trip test in `mulaw.codec` meaningful.
 */
function agentAudio(samples: number, amplitude = 8000): Buffer {
  const pcm = new Int16Array(samples);

  for (let i = 0; i < samples; i++) {
    pcm[i] = Math.round(
      amplitude * Math.sin((2 * Math.PI * 440 * i) / AI_SAMPLE_RATE),
    );
  }

  return int16ToLe(pcm);
}

interface Built {
  session: CallSession;
  /** Fires whatever `CallSession` registered via `ai.onAudio`. */
  emitAudio: (pcm: Buffer) => void;
  emitInterrupt: () => void;
  pushAudio: jest.Mock;
  playFrame: jest.Mock;
  clear: jest.Mock;
  aiClose: jest.Mock;
}

function build(): Built {
  let onAudio: (pcm: Buffer) => void = () => undefined;
  let onInterrupt: () => void = () => undefined;

  const pushAudio = jest.fn();
  const aiClose = jest.fn().mockResolvedValue(undefined);

  const ai: AiSession = {
    pushAudio,
    onAudio: (cb) => {
      onAudio = cb;
    },
    onInterrupt: (cb) => {
      onInterrupt = cb;
    },
    close: aiClose,
  };

  const playFrame = jest.fn();
  const clear = jest.fn();
  const sink: OutboundAudioSink = { playFrame, clear, mark: jest.fn() };

  const session = new CallSession({
    callId: 'call_1',
    streamSid: 'MZ1',
    ai,
    sink,
  });

  return {
    session,
    emitAudio: (pcm) => onAudio(pcm),
    emitInterrupt: () => onInterrupt(),
    pushAudio,
    playFrame,
    clear,
    aiClose,
  };
}

function framesPlayed(playFrame: jest.Mock): Buffer[] {
  return playFrame.mock.calls.map(([frame]) => frame as Buffer);
}

describe('CallSession', () => {
  describe('caller audio', () => {
    it('hands Twilio frames straight to the AI session', () => {
      const built = build();
      const frame = twilioFrame();

      built.session.pushAudio(frame);

      expect(built.pushAudio).toHaveBeenCalledWith(frame);
    });

    it('stops forwarding once closed', async () => {
      const built = build();
      await built.session.close();

      built.session.pushAudio(twilioFrame());

      expect(built.pushAudio).not.toHaveBeenCalled();
    });
  });

  describe('agent audio', () => {
    /**
     * 16 kHz halves to 8 kHz, and mu-law is one byte per sample, so 1600 samples
     * of PCM16 (3200 bytes) becomes 800 mu-law bytes — exactly five 160-byte
     * Twilio frames.
     */
    it('converts 16 kHz PCM16 into whole 20 ms mu-law frames', () => {
      const built = build();

      built.emitAudio(agentAudio(1600));

      const frames = framesPlayed(built.playFrame);
      expect(frames).toHaveLength(5);
      for (const frame of frames) {
        expect(frame).toHaveLength(MULAW_FRAME_BYTES);
      }
    });

    it('holds back a partial frame rather than padding mid-stream', () => {
      const built = build();

      // 500 samples → 250 mu-law bytes → one whole frame, 90 bytes held.
      built.emitAudio(agentAudio(500));

      expect(built.playFrame).toHaveBeenCalledTimes(1);
    });

    it('joins audio across frames instead of restarting at each boundary', () => {
      const whole = build();
      whole.emitAudio(agentAudio(1600));

      const split = build();
      const source = agentAudio(1600);
      // A boundary that lands mid-frame, as a synthesiser's chunking would.
      split.emitAudio(source.subarray(0, 1000));
      split.emitAudio(source.subarray(1000));

      expect(framesPlayed(split.playFrame)).toEqual(
        framesPlayed(whole.playFrame),
      );
    });

    /**
     * The AI service guarantees whole samples, but `leToInt16` drops a trailing
     * odd byte by design — and one dropped byte shifts every sample after it,
     * which is not silence but loud static. This asserts the carry, by splitting
     * on an odd boundary and requiring the output to match the unsplit stream.
     */
    it('carries a sample split across two frames', () => {
      const whole = build();
      whole.emitAudio(agentAudio(1600));

      const split = build();
      const source = agentAudio(1600);
      split.emitAudio(source.subarray(0, 999));
      split.emitAudio(source.subarray(999));

      expect(framesPlayed(split.playFrame)).toEqual(
        framesPlayed(whole.playFrame),
      );
    });

    it('survives an empty frame', () => {
      const built = build();

      expect(() => built.emitAudio(Buffer.alloc(0))).not.toThrow();
      expect(built.playFrame).not.toHaveBeenCalled();
    });

    it('preserves the signal rather than emitting silence', () => {
      const built = build();

      built.emitAudio(agentAudio(1600));

      const peak = framesPlayed(built.playFrame)
        .flatMap((frame) => Array.from(decodeMulaw(frame)))
        .reduce((max, sample) => Math.max(max, Math.abs(sample)), 0);

      // Down 8 kHz and through mu-law, but nowhere near silent.
      expect(peak).toBeGreaterThan(4000);
    });

    it('plays nothing once closed', async () => {
      const built = build();
      await built.session.close();
      built.playFrame.mockClear();

      built.emitAudio(agentAudio(1600));

      expect(built.playFrame).not.toHaveBeenCalled();
    });
  });

  describe('barge-in', () => {
    it('clears the Twilio buffer when the AI service reports an interrupt', () => {
      const built = build();

      built.emitInterrupt();

      expect(built.clear).toHaveBeenCalledTimes(1);
    });

    /**
     * The partial frame belongs to the abandoned turn. Left in place it would be
     * prepended to the first frame of the next reply, splicing the tail of a
     * sentence the caller interrupted onto the start of the answer.
     */
    it('drops the partial frame held from the interrupted turn', () => {
      const built = build();

      // 90 mu-law bytes held back, not yet a whole frame.
      built.emitAudio(agentAudio(500));
      built.playFrame.mockClear();

      built.emitInterrupt();

      // 320 samples → 160 mu-law bytes → exactly one frame, if nothing was
      // carried over from before the interrupt.
      built.emitAudio(agentAudio(320));

      expect(built.playFrame).toHaveBeenCalledTimes(1);
    });

    /**
     * The AI service sends `interrupt` as soon as its VAD fires, which can be
     * before it has sent any audio for that turn. Clearing an empty buffer is a
     * no-op and must not be treated as a protocol violation.
     */
    it('tolerates an interrupt with nothing playing', () => {
      const built = build();

      expect(() => {
        built.emitInterrupt();
        built.emitInterrupt();
      }).not.toThrow();

      expect(built.clear).toHaveBeenCalledTimes(2);
    });

    it('is also reachable directly, for the dev client', () => {
      const built = build();

      built.session.interrupt();

      expect(built.clear).toHaveBeenCalledTimes(1);
    });
  });

  describe('close', () => {
    /**
     * The AI service sends no end-of-response signal, so the frame buffer holds
     * anything under 160 bytes until the next audio arrives. At the end of the
     * call there is no next audio — without this flush the last fragment of the
     * final utterance is dropped.
     */
    it('flushes the held tail so the last syllable is not lost', async () => {
      const built = build();

      built.emitAudio(agentAudio(500));
      const before = built.playFrame.mock.calls.length;

      await built.session.close();

      expect(built.playFrame.mock.calls.length).toBe(before + 1);
      expect(framesPlayed(built.playFrame).at(-1)).toHaveLength(
        MULAW_FRAME_BYTES,
      );
    });

    it('plays no tail when nothing is held', async () => {
      const built = build();

      built.emitAudio(agentAudio(1600));
      const before = built.playFrame.mock.calls.length;

      await built.session.close();

      expect(built.playFrame.mock.calls.length).toBe(before);
    });

    it('closes the AI session', async () => {
      const built = build();

      await built.session.close();

      expect(built.aiClose).toHaveBeenCalledTimes(1);
    });
  });

  /**
   * Not a unit of `CallSession` so much as the property the whole bridge exists
   * to preserve: audio that goes up at 16 kHz and comes back down still sounds
   * like the same tone. A ratio or gain error in either direction breaks this
   * while every length assertion above still passes.
   */
  it('round-trips a tone through both conversions at recognisable level', () => {
    const built = build();

    const caller = new Int16Array(1600);
    for (let i = 0; i < caller.length; i++) {
      caller[i] = Math.round(8000 * Math.sin((2 * Math.PI * 440 * i) / 8000));
    }

    // What the AI service would receive, then echo straight back.
    const upsampled = int16ToLe(new Upsampler(AI_SAMPLE_RATE).process(caller));
    built.emitAudio(upsampled);

    const peak = framesPlayed(built.playFrame)
      .flatMap((frame) => Array.from(decodeMulaw(frame)))
      .reduce((max, sample) => Math.max(max, Math.abs(sample)), 0);

    expect(peak).toBeGreaterThan(8000 * 0.8);
    expect(peak).toBeLessThan(8000 * 1.2);
  });
});
