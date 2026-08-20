import type { Server } from 'http';
import type { AddressInfo } from 'net';
import { INestApplication } from '@nestjs/common';
import { Test, TestingModule } from '@nestjs/testing';
import { WebSocket } from 'ws';
import { AppModule } from './../src/app.module';
import { MediaStreamGateway } from './../src/telephony/media-stream.gateway';
import { parseInboundFrame } from './../src/telephony/twilio-frames';

/**
 * Boots the full AppModule, so it needs a valid .env and a reachable Postgres
 * (`docker compose up -d`).
 *
 * This covers the two things the replay harness cannot: the gateway running
 * under a real Nest lifecycle, and shutdown with a socket still open.
 */
describe('MediaStreamGateway (e2e)', () => {
  let app: INestApplication;
  let port: number;

  const STREAM_SID = 'MZ0000000000000000000000000000e2e';

  /** Twilio's start frame, minus the callId — the echo must not depend on it. */
  const startFrame = JSON.stringify({
    event: 'start',
    streamSid: STREAM_SID,
    start: {
      streamSid: STREAM_SID,
      accountSid: 'AC00000000000000000000000000000000',
      callSid: 'CA00000000000000000000000000000000',
      tracks: ['inbound'],
      customParameters: {},
      mediaFormat: { encoding: 'audio/x-mulaw', sampleRate: 8000, channels: 1 },
    },
  });

  function mediaFrame(payload: string): string {
    return JSON.stringify({
      event: 'media',
      streamSid: STREAM_SID,
      media: { track: 'inbound', chunk: '1', timestamp: '0', payload },
    });
  }

  let sockets: WebSocket[];

  async function connect(): Promise<WebSocket> {
    const socket = new WebSocket(`ws://127.0.0.1:${port}/media-stream`);
    sockets.push(socket);

    await new Promise<void>((resolve, reject) => {
      socket.once('open', resolve);
      socket.once('error', reject);
    });

    return socket;
  }

  /** Left open, these keep the jest worker alive and hide real leaks. */
  async function closeClientSockets(): Promise<void> {
    await Promise.all(
      sockets.map(
        (socket) =>
          new Promise<void>((resolve) => {
            if (socket.readyState === WebSocket.CLOSED) return resolve();
            socket.once('close', () => resolve());
            socket.terminate();
          }),
      ),
    );

    sockets = [];
  }

  beforeEach(async () => {
    sockets = [];

    const moduleFixture: TestingModule = await Test.createTestingModule({
      imports: [AppModule],
    }).compile();

    app = moduleFixture.createNestApplication();
    app.enableShutdownHooks();
    await app.listen(0);

    const server = app.getHttpServer() as Server;
    app.get(MediaStreamGateway).attach(server);
    port = (server.address() as AddressInfo).port;
  });

  afterEach(async () => {
    await closeClientSockets();
    await app.close();
  });

  it('echoes a media frame back on the same streamSid', async () => {
    const socket = await connect();
    const echoed = new Promise<string>((resolve) => {
      socket.on('message', (raw: Buffer) => {
        const frame = parseInboundFrame(raw);
        if (frame?.event === 'media') resolve(frame.media.payload);
      });
    });

    socket.send(startFrame);
    socket.send(mediaFrame('dGVzdC1wYXlsb2Fk'));

    await expect(echoed).resolves.toBe('dGVzdC1wYXlsb2Fk');

    socket.close();
  });

  it('ignores an unrecognised event instead of dropping the call', async () => {
    const socket = await connect();
    const echoed = new Promise<string>((resolve) => {
      socket.on('message', (raw: Buffer) => {
        const frame = parseInboundFrame(raw);
        if (frame?.event === 'media') resolve(frame.media.payload);
      });
    });

    socket.send(startFrame);
    socket.send(JSON.stringify({ event: 'somethingTwilioAddedLater' }));
    socket.send('{ not even json');
    socket.send(mediaFrame('c3RpbGwtaGVyZQ=='));

    // The echo still arrives, so the socket survived both bad frames.
    await expect(echoed).resolves.toBe('c3RpbGwtaGVyZQ==');

    socket.close();
  });

  /**
   * The SIGTERM hang, minus the signal. An open WebSocket keeps the HTTP
   * server's close() pending, so without the gateway's onApplicationShutdown
   * this never resolves — which on a real host means a deploy that times out
   * and gets SIGKILLed.
   *
   * Windows has no real SIGTERM, so `app.close()` is the portable way to prove
   * the teardown itself is sound.
   */
  it('shuts down while a socket is still open', async () => {
    const socket = await connect();
    socket.send(startFrame);

    // Let the start frame land, so the session is fully registered.
    await new Promise((resolve) => setTimeout(resolve, 50));

    await expect(app.close()).resolves.toBeUndefined();
  });
});
