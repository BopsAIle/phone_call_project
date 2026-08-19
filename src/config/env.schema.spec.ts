import { envSchema, validateEnv } from './env.schema';

const completeEnv = {
  NODE_ENV: 'development',
  PORT: '3000',
  DATABASE_URL:
    'postgresql://receptionist:receptionist@localhost:5432/ai_receptionist?schema=public',
  OPENAI_API_KEY: 'sk-test',
  TWILIO_ACCOUNT_SID: 'AC00000000000000000000000000000000',
  TWILIO_AUTH_TOKEN: 'token',
  TWILIO_PHONE_NUMBER: '+15551234567',
  PUBLIC_BASE_URL: 'https://example.ngrok.app',
  STORE_NAME: 'Test Restaurant',
};

/** `completeEnv` with one key removed. */
function without(key: keyof typeof completeEnv): Record<string, unknown> {
  const env: Record<string, unknown> = { ...completeEnv };
  delete env[key];
  return env;
}

describe('envSchema', () => {
  it('accepts a complete environment', () => {
    const result = envSchema.safeParse(completeEnv);

    expect(result.success).toBe(true);
  });

  it('coerces PORT to a number', () => {
    expect(validateEnv(completeEnv).PORT).toBe(3000);
  });

  it('applies defaults for the optional keys', () => {
    const env = validateEnv(completeEnv);

    expect(env.STORE_TIMEZONE).toBe('Europe/Berlin');
    expect(env.DEFAULT_LOCALE).toBe('en');
    expect(env.LLM_MODEL).toBe('gpt-5.6-terra');
    expect(env.TTS_VOICE).toBe('marin');
  });

  it('accepts the Docker-internal database host', () => {
    const env = validateEnv({
      ...completeEnv,
      DATABASE_URL:
        'postgresql://receptionist:receptionist@db:5432/ai_receptionist',
    });

    expect(env.DATABASE_URL).toContain('@db:5432');
  });

  it.each([
    ['a missing key', 'OPENAI_API_KEY', undefined],
    ['a non-E.164 phone number', 'TWILIO_PHONE_NUMBER', '555-1234'],
    [
      'a phone number without the leading +',
      'TWILIO_PHONE_NUMBER',
      '15551234567',
    ],
    ['a non-URL database URL', 'DATABASE_URL', 'not-a-url'],
    ['an account SID of the wrong length', 'TWILIO_ACCOUNT_SID', 'AC123'],
    [
      'an account SID with the wrong prefix',
      'TWILIO_ACCOUNT_SID',
      'XX00000000000000000000000000000000',
    ],
    ['an unsupported locale', 'DEFAULT_LOCALE', 'fr'],
  ])('rejects %s', (_label, key, value) => {
    const env: Record<string, unknown> = { ...completeEnv, [key]: value };
    if (value === undefined) delete env[key];

    expect(() => validateEnv(env)).toThrow();
  });

  it('names the offending key in the error message', () => {
    expect(() => validateEnv(without('OPENAI_API_KEY'))).toThrow(
      /OPENAI_API_KEY/,
    );
  });

  it('reports every problem at once, not just the first', () => {
    const broken = {
      ...without('OPENAI_API_KEY'),
      TWILIO_PHONE_NUMBER: 'nope',
    };

    expect(() => validateEnv(broken)).toThrow(
      /OPENAI_API_KEY[\s\S]*TWILIO_PHONE_NUMBER/,
    );
  });
});
