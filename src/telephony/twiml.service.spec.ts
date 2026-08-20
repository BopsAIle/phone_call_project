import type { ConfigService } from '@nestjs/config';
import type { Env } from '../config/env.schema';
import { TwimlService } from './twiml.service';

function serviceFor(publicBaseUrl: string): TwimlService {
  return new TwimlService({
    get: () => publicBaseUrl,
  } as unknown as ConfigService<Env, true>);
}

describe('TwimlService', () => {
  describe('mediaStreamUrl', () => {
    it('swaps https for wss', () => {
      expect(serviceFor('https://abc.ngrok.app').mediaStreamUrl()).toBe(
        'wss://abc.ngrok.app/media-stream',
      );
    });

    // Concatenating would give wss://abc.ngrok.app//media-stream, which
    // connects to nothing and reports only a 502.
    it('absorbs a trailing slash on the base URL', () => {
      expect(serviceFor('https://abc.ngrok.app/').mediaStreamUrl()).toBe(
        'wss://abc.ngrok.app/media-stream',
      );
    });

    it('keeps a port', () => {
      expect(serviceFor('https://abc.ngrok.app:8443').mediaStreamUrl()).toBe(
        'wss://abc.ngrok.app:8443/media-stream',
      );
    });

    it('uses ws for a plain-http base, so the replay harness can connect', () => {
      expect(serviceFor('http://localhost:3000').mediaStreamUrl()).toBe(
        'ws://localhost:3000/media-stream',
      );
    });
  });

  describe('connectStream', () => {
    const xml = serviceFor('https://abc.ngrok.app').connectStream({
      callId: 'call-1',
      storeId: 'store-1',
    });

    // <Start><Stream> forks a copy of the audio and continues; it is
    // unidirectional and cannot play anything back to the caller.
    it('uses the blocking Connect verb, not Start', () => {
      expect(xml).toContain('<Connect>');
      expect(xml).not.toContain('<Start>');
    });

    it('points the stream at the wss endpoint', () => {
      expect(xml).toContain('<Stream url="wss://abc.ngrok.app/media-stream">');
    });

    // The socket learns which call and store it is serving from these alone —
    // Twilio's start event carries neither From nor To.
    it('carries the call and store ids as custom parameters', () => {
      expect(xml).toContain('<Parameter name="callId" value="call-1"/>');
      expect(xml).toContain('<Parameter name="storeId" value="store-1"/>');
    });
  });

  describe('rejectCall', () => {
    const xml = serviceFor('https://abc.ngrok.app').rejectCall(
      'Not in service.',
    );

    it('speaks the message and hangs up', () => {
      expect(xml).toContain('Not in service.');
      expect(xml).toContain('<Hangup/>');
    });

    it('opens no stream', () => {
      expect(xml).not.toContain('<Stream');
    });
  });
});
