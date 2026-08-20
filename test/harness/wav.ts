import { readFileSync, writeFileSync } from 'fs';

/**
 * Just enough RIFF/WAVE to get 16-bit PCM in and out of the replay harness.
 *
 * Not a general WAV library — it reads the two chunks it needs and refuses
 * anything else with a message that says what to convert the file to.
 */

export interface WavAudio {
  sampleRate: number;
  samples: Int16Array;
}

const PCM_FORMAT = 1;

export function readWav(path: string): WavAudio {
  const file = readFileSync(path);

  if (file.toString('ascii', 0, 4) !== 'RIFF') {
    throw new Error(`${path} is not a RIFF file`);
  }
  if (file.toString('ascii', 8, 12) !== 'WAVE') {
    throw new Error(`${path} is not a WAVE file`);
  }

  let sampleRate = 0;
  let channels = 0;
  let bitsPerSample = 0;
  let data: Buffer | undefined;

  // Walk the chunks rather than assuming fixed offsets: real files carry LIST
  // and fact chunks between `fmt ` and `data`.
  let offset = 12;
  while (offset + 8 <= file.length) {
    const id = file.toString('ascii', offset, offset + 4);
    const size = file.readUInt32LE(offset + 4);
    const body = offset + 8;

    if (id === 'fmt ') {
      const format = file.readUInt16LE(body);
      if (format !== PCM_FORMAT) {
        throw new Error(
          `${path} is compressed (format ${format}); convert it to 16-bit PCM first`,
        );
      }
      channels = file.readUInt16LE(body + 2);
      sampleRate = file.readUInt32LE(body + 4);
      bitsPerSample = file.readUInt16LE(body + 14);
    } else if (id === 'data') {
      data = file.subarray(body, body + size);
    }

    // Chunks are word-aligned; an odd size is followed by a pad byte.
    offset = body + size + (size % 2);
  }

  if (!data) throw new Error(`${path} has no data chunk`);
  if (bitsPerSample !== 16) {
    throw new Error(
      `${path} is ${bitsPerSample}-bit; convert it to 16-bit PCM first`,
    );
  }

  const interleaved = new Int16Array(
    data.buffer,
    data.byteOffset,
    Math.floor(data.length / 2),
  );

  return { sampleRate, samples: toMono(interleaved, channels) };
}

/** The phone network is mono; average the channels rather than dropping one. */
function toMono(interleaved: Int16Array, channels: number): Int16Array {
  if (channels <= 1) return interleaved;

  const mono = new Int16Array(Math.floor(interleaved.length / channels));

  for (let i = 0; i < mono.length; i++) {
    let sum = 0;
    for (let c = 0; c < channels; c++) sum += interleaved[i * channels + c];
    mono[i] = Math.round(sum / channels);
  }

  return mono;
}

export function writeWav(path: string, audio: WavAudio): void {
  const dataBytes = audio.samples.length * 2;
  const file = Buffer.alloc(44 + dataBytes);

  file.write('RIFF', 0, 'ascii');
  file.writeUInt32LE(36 + dataBytes, 4);
  file.write('WAVE', 8, 'ascii');

  file.write('fmt ', 12, 'ascii');
  file.writeUInt32LE(16, 16); // PCM fmt chunk size
  file.writeUInt16LE(PCM_FORMAT, 20);
  file.writeUInt16LE(1, 22); // mono
  file.writeUInt32LE(audio.sampleRate, 24);
  file.writeUInt32LE(audio.sampleRate * 2, 28); // byte rate
  file.writeUInt16LE(2, 32); // block align
  file.writeUInt16LE(16, 34); // bits per sample

  file.write('data', 36, 'ascii');
  file.writeUInt32LE(dataBytes, 40);

  for (let i = 0; i < audio.samples.length; i++) {
    file.writeInt16LE(audio.samples[i], 44 + i * 2);
  }

  writeFileSync(path, file);
}
