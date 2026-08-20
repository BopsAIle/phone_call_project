import { Injectable } from '@nestjs/common';
import { ConfigService } from '@nestjs/config';
import { twiml } from 'twilio';
import type { Env } from '../config/env.schema';

/** Where the gateway listens; shared so the two cannot drift apart. */
export const MEDIA_STREAM_PATH = '/media-stream';

@Injectable()
export class TwimlService {
  constructor(private readonly config: ConfigService<Env, true>) {}

  /**
   * `wss://<host>/media-stream`, derived from `PUBLIC_BASE_URL`.
   *
   * The env schema validates that variable as an `https://` URL, but `<Stream>`
   * needs a WebSocket scheme — an `https://` value there fails at connect time
   * with an error that never mentions the scheme. Going through `URL` rather
   * than concatenating also absorbs a trailing slash, which is the other way
   * this produces a subtly wrong `wss://host//media-stream`.
   */
  mediaStreamUrl(): string {
    const url = new URL(
      MEDIA_STREAM_PATH,
      this.config.get('PUBLIC_BASE_URL', { infer: true }),
    );

    url.protocol = url.protocol === 'http:' ? 'ws:' : 'wss:';

    return url.toString();
  }

  /**
   * The answer TwiML: hand the call's audio to our WebSocket.
   *
   * `<Connect>` is blocking — the call lives exactly as long as the stream,
   * which is what a conversation needs. `<Start><Stream>` forks a copy of the
   * audio and continues to the next verb; it is unidirectional and cannot play
   * anything back.
   */
  connectStream(params: { callId: string; storeId: string }): string {
    const response = new twiml.VoiceResponse();

    const stream = response.connect().stream({ url: this.mediaStreamUrl() });
    stream.parameter({ name: 'callId', value: params.callId });
    stream.parameter({ name: 'storeId', value: params.storeId });

    return response.toString();
  }

  /**
   * Said aloud when the dialled number matches no store.
   *
   * Deliberately not a 500: an error status gets the caller Twilio's generic
   * failure tone with no explanation, and leaves nothing behind to diagnose.
   */
  rejectCall(message: string): string {
    const response = new twiml.VoiceResponse();

    response.say({ language: 'en-US' }, message);
    response.hangup();

    return response.toString();
  }
}
