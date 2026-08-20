import 'dotenv/config';
import { defineConfig } from 'prisma/config';

// Prisma 7 reads CLI configuration from this file. It replaces the `prisma`
// key in package.json, which no longer exists.
export default defineConfig({
  schema: 'prisma/schema.prisma',
  migrations: {
    path: 'prisma/migrations',
    // `tsx`, not `ts-node`: the generated client's imports carry `.js`
    // extensions that resolve back to `.ts` files, and ts-node does not remap
    // them at require time.
    seed: 'tsx prisma/seed.ts',
  },
  datasource: {
    url: process.env['DATABASE_URL'],
  },
});
