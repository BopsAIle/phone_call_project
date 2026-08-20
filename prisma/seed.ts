import 'dotenv/config';
import { PrismaPg } from '@prisma/adapter-pg';
import { PrismaClient } from '../src/generated/prisma/client';
import { validateEnv } from '../src/config/env.schema';

// TODO(Phase 3): replace with the real wording supplied by the store owner.
// Phase 3 speaks this aloud, and German callers are covered by GDPR/TTDSG —
// the automated-assistant and transcription disclosure must be in the final
// text, before anything is collected from the caller.
const PLACEHOLDER_GREETING_EN =
  'Hello, and thank you for calling. You are speaking with an automated assistant ' +
  'and this call is transcribed. How can I help you today?';

const PLACEHOLDER_GREETING_DE =
  'Hallo und danke für Ihren Anruf. Sie sprechen mit einem automatischen Assistenten, ' +
  'und dieses Gespräch wird transkribiert. Wie kann ich Ihnen helfen?';

async function main(): Promise<void> {
  // Same validation the application uses, so a misconfigured seed fails with
  // the same readable message rather than a null-constraint violation.
  const env = validateEnv(process.env);

  const prisma = new PrismaClient({
    adapter: new PrismaPg({ connectionString: env.DATABASE_URL }),
  });

  try {
    // upsert, not create: Store.phoneNumber is @unique, so a plain create
    // throws on the second run and makes `migrate reset` + seed non-repeatable.
    const store = await prisma.store.upsert({
      where: { phoneNumber: env.TWILIO_PHONE_NUMBER },
      update: {
        name: env.STORE_NAME,
        timezone: env.STORE_TIMEZONE,
        defaultLocale: env.DEFAULT_LOCALE,
      },
      create: {
        name: env.STORE_NAME,
        phoneNumber: env.TWILIO_PHONE_NUMBER,
        timezone: env.STORE_TIMEZONE,
        defaultLocale: env.DEFAULT_LOCALE,
        greetingEn: PLACEHOLDER_GREETING_EN,
        greetingDe: PLACEHOLDER_GREETING_DE,
      },
    });

    // Greetings are intentionally left out of `update` so that wording edited
    // directly in the database survives a re-seed.
    console.log(`Seeded store ${store.id} (${store.name}, ${store.phoneNumber})`);
  } finally {
    await prisma.$disconnect();
  }
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
