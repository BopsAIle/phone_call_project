import 'dotenv/config';
import { randomBytes } from 'crypto';
import { WebSocket } from 'ws';
import {
  MULAW_FRAME_BYTES,
  OPENAI_SAMPLE_RATE,
  TELEPHONY_SAMPLE_RATE,
  decodeMulaw,
  encodeMulaw,
} from '../../src/audio/mulaw.codec';
import { Downsampler } from '../../src/audio/resampler';
import { parseInboundFrame } from '../../src/telephony/twilio-frames';
import { readWav, writeWav } from './wav';

/**
 * Replays a WAV file through the whole pipeline with no phone call, no tunnel,
 * and no Twilio charges.
 *
 *   npm run replay -- [input.wav] [output.wav]
 *
 * It drives the real `/twilio/voice` webhook rather than inventing its own
 * `Call` row, so the store lookup, the TwiML, and the custom parameters are all
 * exercised too. That means the server must be running (`npm run start:dev`)
 * with a seeded store whose `phoneNumber` matches `TWILIO_PHONE_NUMBER`.
 *
 * By default frames are paced at 20 ms, the rate real Twilio sends them. From
 * Phase 2 that matters — server-side VAD endpointing and barge-in are timing
 * behaviour, and a stream delivered all at once does not test either. Pass
 * `--fast` to skip the pacing when only the audio path is in question.
 */

const FRAME_INTERVAL_MS = 20;

/** How long to keep listening after the last frame, for audio still in flight. */
const DRAIN_MS = 500;

interface StreamTarget {
  url: string;
  parameters: Record<string, string>;
}

function sid(prefix: string): string {
  return prefix + randomBytes(16).toString('hex');
}

function requireEnv(key: string): string {
  const value = process.env[key];
  if (!value) throw new Error(`${key} is not set; is .env present?`);
  return value;
}

/**
 * Calls the voice webhook exactly as Twilio would and reads the stream target
 * back out of the TwiML it returns.
 */
async function openCall(
  baseUrl: string,
  callSid: string,
): Promise<StreamTarget> {
  const response = await fetch(`${baseUrl}/twilio/voice`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
    body: new URLSearchParams({
      CallSid: callSid,
      From: '+15550000001',
      To: requireEnv('TWILIO_PHONE_NUMBER'),
      CallStatus: 'ringing',
      Direction: 'inbound',
    }),
  });

  if (!response.ok) {
    throw new Error(`/twilio/voice returned ${response.status}`);
  }

  const xml = await response.text();
  const advertised = /<Stream url="([^"]+)"/.exec(xml)?.[1];

  if (!advertised) {
    throw new Error(
      `No <Stream> in the TwiML — is TWILIO_PHONE_NUMBER seeded as a store?\n${xml}`,
    );
  }

  const parameters: Record<string, string> = {};
  for (const [, name, value] of xml.matchAll(
    /<Parameter name="([^"]+)" value="([^"]*)"\/>/g,
  )) {
    parameters[name] = value;
  }

  // Take the *path* from the TwiML but keep our own origin. The advertised host
  // comes from PUBLIC_BASE_URL, which points at the tunnel Twilio would use —
  // the harness is already inside the network and has no tunnel to go through.
  const local = new URL(new URL(advertised).pathname, baseUrl);
  local.protocol = local.protocol === 'https:' ? 'wss:' : 'ws:';

  return { url: local.toString(), parameters };
}

/** Sleeps until `deadline`, correcting for the drift a bare setTimeout accumulates. */
function sleepUntil(deadline: number): Promise<void> {
  return new Promise((resolve) =>
    setTimeout(resolve, Math.max(0, deadline - Date.now())),
  );
}

async function main(): Promise<void> {
  const inputPath = process.argv[2] ?? 'test/fixtures/tone-sweep.wav';
  const outputPath = process.argv[3] ?? 'test/fixtures/replay-output.wav';
  const realtime = !process.argv.includes('--fast');
  const baseUrl = process.env.REPLAY_BASE_URL ?? 'http://localhost:3000';

  const input = readWav(inputPath);
  console.log(
    `Read ${inputPath}: ${input.samples.length} samples @ ${input.sampleRate} Hz`,
  );

  let pcm8k: Int16Array;
  if (input.sampleRate === TELEPHONY_SAMPLE_RATE) {
    pcm8k = input.samples;
  } else if (input.sampleRate === OPENAI_SAMPLE_RATE) {
    pcm8k = new Downsampler().process(input.samples);
  } else {
    throw new Error(
      `Unsupported sample rate ${input.sampleRate}; use ${TELEPHONY_SAMPLE_RATE} or ${OPENAI_SAMPLE_RATE} Hz`,
    );
  }

  const mulaw = encodeMulaw(pcm8k);
  const frameCount = Math.floor(mulaw.length / MULAW_FRAME_BYTES);

  const callSid = sid('CA');
  const streamSid = sid('MZ');
  const target = await openCall(baseUrl, callSid);
  console.log(
    `Webhook returned ${target.url} (callId=${target.parameters.callId})`,
  );

  const socket = new WebSocket(target.url);
  const received: Buffer[] = [];

  socket.on('message', (raw: Buffer) => {
    const frame = parseInboundFrame(raw);
    if (frame?.event === 'media') {
      received.push(Buffer.from(frame.media.payload, 'base64'));
    }
  });

  await new Promise<void>((resolve, reject) => {
    socket.once('open', resolve);
    socket.once('error', reject);
  });

  socket.send(
    JSON.stringify({
      event: 'connected',
      protocol: 'Call',
      version: '1.0.0',
    }),
  );

  socket.send(
    JSON.stringify({
      event: 'start',
      sequenceNumber: '1',
      streamSid,
      start: {
        streamSid,
        accountSid: sid('AC'),
        callSid,
        tracks: ['inbound'],
        customParameters: target.parameters,
        mediaFormat: {
          encoding: 'audio/x-mulaw',
          sampleRate: TELEPHONY_SAMPLE_RATE,
          channels: 1,
        },
      },
    }),
  );

  const startedAt = Date.now();

  for (let i = 0; i < frameCount; i++) {
    socket.send(
      JSON.stringify({
        event: 'media',
        sequenceNumber: String(i + 2),
        streamSid,
        media: {
          track: 'inbound',
          chunk: String(i + 1),
          timestamp: String(i * FRAME_INTERVAL_MS),
          payload: mulaw
            .subarray(i * MULAW_FRAME_BYTES, (i + 1) * MULAW_FRAME_BYTES)
            .toString('base64'),
        },
      }),
    );

    if (realtime) {
      await sleepUntil(startedAt + (i + 1) * FRAME_INTERVAL_MS);
    }
  }

  await sleepUntil(Date.now() + DRAIN_MS);

  socket.send(
    JSON.stringify({
      event: 'stop',
      sequenceNumber: String(frameCount + 2),
      streamSid,
      stop: { accountSid: sid('AC'), callSid },
    }),
  );

  socket.close();

  const returned = Buffer.concat(received);
  writeWav(outputPath, {
    sampleRate: TELEPHONY_SAMPLE_RATE,
    samples: decodeMulaw(returned),
  });

  console.log(`Sent     ${frameCount} frames (${mulaw.length} bytes)`);
  console.log(
    `Received ${Math.round(returned.length / MULAW_FRAME_BYTES)} frames (${returned.length} bytes)`,
  );
  console.log(`Wrote    ${outputPath} — listen to it`);
}

main().catch((error: unknown) => {
  console.error(error);
  process.exit(1);
});
